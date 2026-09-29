#!/usr/bin/env python3
"""Telegram front-end for Marc: send a photo, get a draft caption back,
tap Post to actually publish it to X. Run as a long-lived process (systemd)."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import shutil
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import chain_state
import feed_publisher
import local_llm
import feed_poller
import fixmystreet
import fms_profiles
from exif_extractor import extract_gps_coordinates
from trash_agent import generate_post_draft
from twitter_poster import post_image_with_caption
from giselle_agent import generate_reaction as giselle_react, generate_followup as giselle_followup
from yousuf_agent import generate_comments as yousuf_comment, generate_followup as yousuf_followup
from x_accounts import post_reply

logging.basicConfig(level=logging.INFO)
# httpx logs full request URLs, and Telegram's include the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS = {
    int(x) for x in os.getenv("ALLOWED_TELEGRAM_CHAT_IDS", "").split(",") if x.strip()
}
# Telegram user_ids (not chat_ids) allowed to approve/discard drafts and to
# have their photo caption passed to the agent as a location hint. Anyone
# else in an allowed chat can still submit photos, but their caption text is
# dropped before it reaches the LLM (untrusted free text next to a prompt is
# exactly what prompt injection needs), and their Post/Discard taps are
# rejected — only an owner can actually publish anything.
OWNER_USER_IDS = {
    int(x) for x in os.getenv("OWNER_TELEGRAM_USER_IDS", "").split(",") if x.strip()
}

PENDING_TTL_SECONDS = 3600
PENDING: dict[str, dict] = {}
# Chat members' own FixMyStreet reports, keyed like PENDING but with their own
# copy of the photo, so the owner posting/discarding the draft doesn't affect it.
FMS_PENDING: dict[str, dict] = {}

# How often to read public replies + engagement counts from X for the public
# site. 0 (default) = never — reads cost X API credits, the bots' own posts
# reach the site without any (see feed_publisher.py / feed_poller.py).
FEED_POLL_HOURS = float(os.getenv("FEED_POLL_HOURS", "0") or 0)

# FixMyStreet Brussels reports. The owner's own (in their name, from .env) are
# only offered for photos sent to the bot in a private chat, with GPS. Other
# chat members who send a photo as a File (so it keeps its GPS) are offered a
# report under their OWN details (/fms_profile, see fms_profiles.py), with a
# preview they confirm themselves — independent of whether the owner posts it.
# FMS_DRY_RUN=1 does everything except the final "send", for a first test.
FMS_ENABLED = os.getenv("FMS_ENABLED", "1") != "0"
FMS_DRY_RUN = os.getenv("FMS_DRY_RUN", "0") == "1"
FMS_STATUS_POLL_HOURS = float(os.getenv("FMS_STATUS_POLL_HOURS", "12") or 0)

# Reactions land at a random point within the hour, not instantly — real
# people don't reply to a tweet within milliseconds.
MIN_REACTION_DELAY = 180  # 3 min
MAX_REACTION_DELAY = 3600  # 60 min

# After Giselle's initial reaction and Yousuf's two comments, they may keep
# bickering with each other a bit more — never guaranteed, capped so it can't
# run forever.
MAX_EXTRA_ROUNDS = 2
EXTRA_ROUND_CONTINUE_CHANCE = 0.5


async def _wait_a_bit():
    await asyncio.sleep(random.randint(MIN_REACTION_DELAY, MAX_REACTION_DELAY))


async def _to_feed(chain_id: str, **post):
    """Record a bot post on the public site and ship it. The site is a
    by-product: if it fails, the X chain must carry on regardless."""
    try:
        await asyncio.to_thread(feed_publisher.record_post, chain_id, **post)
        await asyncio.to_thread(feed_publisher.publish)
    except Exception:
        logger.exception("Public feed update failed for chain %s", chain_id)


def _authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return False
    return update.effective_chat.id in ALLOWED_CHAT_IDS


def _is_owner(update: Update) -> bool:
    # If OWNER_TELEGRAM_USER_IDS isn't configured, fall back to "anyone in an
    # allowed chat can approve" (today's behavior) rather than locking
    # everyone out — but this means the submitter-restriction isn't in
    # effect until it's set.
    if not OWNER_USER_IDS:
        return True
    return update.effective_user.id in OWNER_USER_IDS


def _cleanup_expired():
    now = time.time()
    for token in [t for t, e in PENDING.items() if now - e["ts"] > PENDING_TTL_SECONDS]:
        entry = PENDING.pop(token)
        Path(entry["image_path"]).unlink(missing_ok=True)
    for token in [t for t, e in FMS_PENDING.items()
                  if now - e["ts"] > PENDING_TTL_SECONDS and e["stage"] in ("offered", "previewed")]:
        Path(FMS_PENDING.pop(token)["image_path"]).unlink(missing_ok=True)


async def _is_member_of_allowed_chat(bot, user_id: int) -> bool:
    """For commands in a private chat: is this person in one of the bot's chats?"""
    for chat_id in ALLOWED_CHAT_IDS:
        if chat_id == user_id:
            return True
        if chat_id > 0:
            continue
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            continue
        if member.status in ("creator", "administrator", "member", "restricted"):
            return True
    return False


def _fms_setup_link(bot) -> str:
    return f"https://t.me/{bot.username}?start=fms"


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0] == "fms" and update.effective_chat.type == "private":
        await _fms_profile_help(update, context)
        return
    await update.message.reply_text(
        f"👋 I'm Marc.\n"
        f"chat_id: {update.effective_chat.id} (goes in ALLOWED_TELEGRAM_CHAT_IDS)\n"
        f"your user_id: {update.effective_user.id} (the project owner's user_id goes "
        "in OWNER_TELEGRAM_USER_IDS — only owners can approve/discard drafts)\n\n"
        "Once set up, send a trash photo (as a photo, not compressed-away — attach as "
        "a File if you want GPS-based hashtags to work)."
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        logger.warning("Rejected photo from unauthorized chat_id=%s", update.effective_chat.id)
        await update.message.reply_text(
            f"⛔ This bot isn't set up for this chat (chat_id={update.effective_chat.id})."
        )
        return

    _cleanup_expired()

    photo = update.message.photo[-1] if update.message.photo else None
    document = update.message.document
    is_image_doc = document and document.mime_type and document.mime_type.startswith("image/")
    if not photo and not is_image_doc:
        return

    tg_file = await (photo.get_file() if photo else document.get_file())
    suffix = ".jpg" if photo else (Path(document.file_name or "photo.jpg").suffix or ".jpg")
    tmp_dir = Path(tempfile.gettempdir()) / "trashbot"
    tmp_dir.mkdir(exist_ok=True)
    image_path = tmp_dir / f"{tg_file.file_unique_id}{suffix}"
    await tg_file.download_to_drive(str(image_path))

    local = local_llm.use_local()
    status = await update.message.reply_text(
        "🗑️ Looking at it... (local model, usually 1–3 min)" if local else "🗑️ Looking at it..."
    )

    submitter_is_owner = _is_owner(update)
    # Only an owner's caption reaches the LLM as a location hint. A
    # non-owner's caption is free text next to a prompt — exactly what
    # prompt injection needs — so it's dropped here rather than trusted.
    user_note = update.message.caption if submitter_is_owner else None

    gps = extract_gps_coordinates(str(image_path))
    report_ok = (
        FMS_ENABLED
        and submitter_is_owner
        and update.effective_chat.type == "private"
        and gps is not None
    )
    sender_name = update.effective_user.first_name or "someone"
    notes = "" if submitter_is_owner else f"\n(from {sender_name} — only an owner can approve)"
    if FMS_ENABLED and submitter_is_owner and update.effective_chat.type == "private" and gps is None:
        notes += "\n(no GPS in this photo — send it as a File to be able to report it to FixMyStreet)"

    token = tg_file.file_unique_id
    if FMS_ENABLED and not submitter_is_owner:
        await _offer_member_report(update, context, token, image_path, gps)
    PENDING[token] = {
        "image_path": str(image_path), "caption": None, "ts": time.time(), "gps": gps, "report_ok": report_ok,
        "user_note": user_note, "notes": notes,
    }
    # In the background: drafting takes minutes on the local models, and updates are
    # handled one at a time — button taps (e.g. a member's FixMyStreet report) mustn't wait.
    context.application.create_task(_draft_and_show(status, token, None), update=update)


def _claude_available() -> bool:
    return bool(os.getenv("CLAUDE_API_KEY"))


async def _draft_and_show(message, token: str, backend: str | None):
    """Generate a draft for PENDING[token] and put it (or the failure) on `message`."""
    entry = PENDING[token]
    retry_row = [InlineKeyboardButton("🔁 Retry with Claude", callback_data=f"claude:{token}")]
    try:
        draft = await asyncio.to_thread(generate_post_draft, entry["image_path"], entry["user_note"], backend)
    except Exception as e:
        logger.exception("Failed to generate a draft")
        if backend != "anthropic" and local_llm.use_local() and _claude_available():
            # Local failures never fall through to a paid model on their own — the owner decides.
            rows = [retry_row, [InlineKeyboardButton("❌ Discard", callback_data=f"discard:{token}")]]
            await message.edit_text(f"❌ Local model failed: {e}", reply_markup=InlineKeyboardMarkup(rows))
            return
        PENDING.pop(token, None)
        await message.edit_text(f"❌ Couldn't generate a caption: {e}")
        Path(entry["image_path"]).unlink(missing_ok=True)
        return

    entry["caption"] = draft.caption
    if entry["report_ok"]:
        rows = [
            [InlineKeyboardButton("✅ Post + report to FixMyStreet", callback_data=f"postreport:{token}")],
            [
                InlineKeyboardButton("🐦 Post only", callback_data=f"post:{token}"),
                InlineKeyboardButton("❌ Discard", callback_data=f"discard:{token}"),
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("✅ Post to X", callback_data=f"post:{token}"),
                InlineKeyboardButton("❌ Discard", callback_data=f"discard:{token}"),
            ]
        ]
    if draft.backend == "local" and _claude_available():
        rows.append(retry_row)
    warning = ""
    if draft.belongings_warning:
        warning = (f"⚠️ This may be someone's belongings (a person sleeping or living here?): "
                   f"{draft.belongings_warning}\n\n")
    source = (f"local model, seen by {draft.seen_by}" if draft.seen_by else "local model") \
        if draft.backend == "local" else "Claude"
    await message.edit_text(
        f"{warning}📝 Draft ({source}):\n\n{draft.caption}\n\n({len(draft.caption)} chars){entry['notes']}",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not _authorized(update):
        await query.answer()
        return

    if query.data.startswith("fmsu:"):
        await _handle_member_report_callback(update, context)
        return

    if not _is_owner(update):
        await query.answer("⛔ Only the project owner can approve or discard posts.", show_alert=True)
        return

    await query.answer()

    action, token = query.data.split(":", 1)
    if action == "claude":
        if token not in PENDING:
            await query.edit_message_text("⌛ This draft expired or was already handled.")
            return
        await query.edit_message_text("🗑️ Asking Claude...")
        await _draft_and_show(query.message, token, "anthropic")
        return

    entry = PENDING.pop(token, None)
    if not entry:
        await query.edit_message_text("⌛ This draft expired or was already handled.")
        return
    if action != "discard" and not entry.get("caption"):
        PENDING[token] = entry  # stale Post button on a failed draft: nothing to post
        return

    if action == "discard":
        await query.edit_message_text("🗑️ Discarded.")
        Path(entry["image_path"]).unlink(missing_ok=True)
        return

    report_copy = None
    if action == "postreport" and entry.get("report_ok"):
        # The photo is deleted right after posting; the report needs it a bit longer.
        report_copy = Path(entry["image_path"]).with_name(Path(entry["image_path"]).stem + "-fms" + Path(entry["image_path"]).suffix)
        shutil.copy2(entry["image_path"], report_copy)

    try:
        result = await asyncio.to_thread(
            post_image_with_caption, entry["image_path"], entry["caption"]
        )
        await query.edit_message_text(f"✅ Posted: {result['post_url']}")
        await _to_feed(
            result["post_id"],
            post_id=result["post_id"],
            author="marc",
            text=entry["caption"],
            image_path=entry["image_path"],
            url=result["post_url"],
        )
    except Exception as e:
        logger.exception("Failed to post to X")
        await query.edit_message_text(f"❌ Failed to post: {e}")
        if report_copy:
            report_copy.unlink(missing_ok=True)
        return
    finally:
        Path(entry["image_path"]).unlink(missing_ok=True)

    if report_copy:
        context.application.create_task(
            _report_to_fixmystreet(
                context.application, update.effective_chat.id, str(report_copy), entry["gps"], result["post_id"]
            ),
            update=update,
        )

    # Fire-and-forget: the chain unfolds over up to ~an hour with random
    # delays, so it must not block this callback. State is saved to disk
    # first so a bot restart mid-wait resumes instead of silently dropping
    # the rest of the chain (see chain_state.py).
    initial_state = {
        "stage": "pending_giselle",
        "chat_id": update.effective_chat.id,
        "marc_tweet_id": result["post_id"],
        "marc_text": entry["caption"],
    }
    chain_state.save_chain(result["post_id"], initial_state)
    context.application.create_task(
        _chain_giselle_and_yousuf(context.application, initial_state),
        update=update,
    )


async def _chain_giselle_and_yousuf(application: Application, state: dict):
    """Giselle reacts, then Yousuf comments on both, each after a random delay.
    Then Giselle and Yousuf may keep bickering at each other for up to
    MAX_EXTRA_ROUNDS more replies. Fully autonomous — errors are reported to
    chat. Progress is persisted after every stage (see chain_state.py) so a
    bot restart resumes from the last completed stage instead of losing the
    rest of the chain."""
    bot = application.bot
    chat_id = state["chat_id"]
    marc_tweet_id = state["marc_tweet_id"]
    marc_text = state["marc_text"]

    if state["stage"] == "pending_giselle":
        await _wait_a_bit()
        try:
            giselle_text = await asyncio.to_thread(giselle_react, marc_text)
            giselle_result = await asyncio.to_thread(post_reply, "GISELLE", marc_tweet_id, giselle_text)
            await bot.send_message(chat_id, f"🗯️ Giselle: {giselle_result['post_url']}")
            await _to_feed(
                marc_tweet_id,
                post_id=giselle_result["post_id"],
                author="giselle",
                text=giselle_text,
                reply_to=marc_tweet_id,
                url=giselle_result["post_url"],
            )
        except Exception as e:
            logger.exception("Giselle failed to react")
            await bot.send_message(chat_id, f"⚠️ Giselle failed to react: {e}")
            chain_state.clear_chain(marc_tweet_id)
            return

        state = {
            "stage": "pending_yousuf",
            "chat_id": chat_id,
            "marc_tweet_id": marc_tweet_id,
            "marc_text": marc_text,
            "giselle_text": giselle_text,
            "giselle_post_id": giselle_result["post_id"],
        }
        chain_state.save_chain(marc_tweet_id, state)

    if state["stage"] == "pending_yousuf":
        giselle_text = state["giselle_text"]
        giselle_post_id = state["giselle_post_id"]
        await _wait_a_bit()
        try:
            comment_on_marc, comment_on_giselle = await asyncio.to_thread(
                yousuf_comment, marc_text, giselle_text
            )
            r1 = await asyncio.to_thread(post_reply, "YOUSUF", marc_tweet_id, comment_on_marc)
            r2 = await asyncio.to_thread(post_reply, "YOUSUF", giselle_post_id, comment_on_giselle)
            await bot.send_message(
                chat_id, f"🙃 Yousuf: {r1['post_url']}\n🙃 Yousuf: {r2['post_url']}"
            )
            await _to_feed(
                marc_tweet_id, post_id=r1["post_id"], author="yousuf", text=comment_on_marc,
                reply_to=marc_tweet_id, url=r1["post_url"],
            )
            await _to_feed(
                marc_tweet_id, post_id=r2["post_id"], author="yousuf", text=comment_on_giselle,
                reply_to=giselle_post_id, url=r2["post_url"],
            )
        except Exception as e:
            logger.exception("Yousuf failed to comment")
            await bot.send_message(chat_id, f"⚠️ Yousuf failed to comment: {e}")
            chain_state.clear_chain(marc_tweet_id)
            return

        state = {
            "stage": "pending_extra",
            "chat_id": chat_id,
            "marc_tweet_id": marc_tweet_id,
            "marc_text": marc_text,
            "last_speaker": "YOUSUF",
            "last_text": comment_on_giselle,
            "last_reply_id": r2["post_id"],
            "extra_round": 0,
        }
        chain_state.save_chain(marc_tweet_id, state)

    # pending_extra: alternates Giselle/Yousuf, each replying to the other's
    # last message, for up to MAX_EXTRA_ROUNDS more (randomly continued).
    last_speaker = state["last_speaker"]
    last_text = state["last_text"]
    last_reply_id = state["last_reply_id"]
    extra_round = state["extra_round"]

    while extra_round < MAX_EXTRA_ROUNDS:
        if random.random() > EXTRA_ROUND_CONTINUE_CHANCE:
            break
        await _wait_a_bit()
        try:
            if last_speaker == "YOUSUF":
                text = await asyncio.to_thread(giselle_followup, last_text)
                account, emoji = "GISELLE", "🗯️"
            else:
                text = await asyncio.to_thread(yousuf_followup, last_text)
                account, emoji = "YOUSUF", "🙃"
            result = await asyncio.to_thread(post_reply, account, last_reply_id, text)
            await bot.send_message(chat_id, f"{emoji} {account.title()}: {result['post_url']}")
            await _to_feed(
                marc_tweet_id, post_id=result["post_id"], author=account.lower(), text=text,
                reply_to=last_reply_id, url=result["post_url"],
            )
            last_speaker, last_text, last_reply_id = account, text, result["post_id"]
            extra_round += 1
            chain_state.save_chain(
                marc_tweet_id,
                {
                    "stage": "pending_extra",
                    "chat_id": chat_id,
                    "marc_tweet_id": marc_tweet_id,
                    "marc_text": marc_text,
                    "last_speaker": last_speaker,
                    "last_text": last_text,
                    "last_reply_id": last_reply_id,
                    "extra_round": extra_round,
                },
            )
        except Exception as e:
            logger.exception("Extra back-and-forth round failed")
            await bot.send_message(chat_id, f"⚠️ Back-and-forth stopped early: {e}")
            break

    chain_state.clear_chain(marc_tweet_id)


async def _report_to_fixmystreet(application: Application, chat_id: int, image_path: str, gps, marc_tweet_id: str):
    """File the FixMyStreet report for an approved photo. Fail-soft: any
    problem is reported to the owner and never touches the X chain."""
    bot = application.bot
    lat, lon = gps
    try:
        r = await asyncio.to_thread(fixmystreet.report_trash, image_path, lat, lon, dry_run=FMS_DRY_RUN)
        if r.get("dry_run"):
            await bot.send_message(
                chat_id,
                f"🏛️ DRY RUN — would report to FixMyStreet (nothing sent):\n{r['category']}\n{r['address']}\n« {r['description']} »\nSet FMS_DRY_RUN=0 to file for real.",
            )
            return
        if not r["filed"]:
            await bot.send_message(chat_id, f"🏛️ Not reported to FixMyStreet: {r['reason']}")
            return
        await bot.send_message(
            chat_id, f"🏛️ Reported to FixMyStreet\n{r['category']}\n{r['address']}\n« {r['description']} »\n{r['url']}"
        )
        report = {"id": r["id"], "url": r["url"], "category": r["category"], "status": "PROCESSING"}
        await asyncio.to_thread(feed_publisher.set_report, marc_tweet_id, marc_tweet_id, report)
        await asyncio.to_thread(feed_publisher.publish)
    except fixmystreet.FixMyStreetError as e:
        await bot.send_message(chat_id, f"⚠️ FixMyStreet report failed: {e}")
    except Exception as e:
        logger.exception("FixMyStreet report failed")
        await bot.send_message(chat_id, f"⚠️ FixMyStreet report failed: {e}")
    finally:
        Path(image_path).unlink(missing_ok=True)


# ------------------------------------------------ chat members' own reports

async def _offer_member_report(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str,
                               image_path: Path, gps):
    """A non-owner sent a photo: offer them a FixMyStreet report in their own name
    (with GPS), or tell them how to make that possible (without)."""
    user = update.effective_user
    profile = fms_profiles.get(user.id)
    if gps is None:
        if profile and update.message.document:
            await update.message.reply_text("🏛️ No GPS in this file, so it can't be reported to FixMyStreet.")
        elif profile:
            await update.message.reply_text(
                "🏛️ To report this to FixMyStreet, send it again as a File (📎 → File): "
                "Telegram strips the location from photos.")
        return
    copy = image_path.with_name(image_path.stem + "-fmsu" + image_path.suffix)
    shutil.copy2(image_path, copy)
    rows = [[InlineKeyboardButton("📋 Prepare my report", callback_data=f"fmsu:prep:{token}"),
             InlineKeyboardButton("No thanks", callback_data=f"fmsu:no:{token}")]]
    if not profile:
        rows.append([InlineKeyboardButton("🔐 Set up my details (private chat)", url=_fms_setup_link(context.bot))])
    who = f"your saved details ({fms_profiles.masked(profile)})" if profile else \
        "your own name and email (set them up once in a private chat with me)"
    offer = await update.message.reply_text(
        f"🏛️ {user.first_name}, want to report this spot to FixMyStreet Brussels yourself? "
        f"It's filed under {who}. You'll see exactly what would be sent before anything goes out.",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    FMS_PENDING[token] = {
        "image_path": str(copy), "gps": gps, "user_id": user.id, "first_name": user.first_name,
        "chat_id": offer.chat_id, "message_id": offer.message_id, "ts": time.time(), "stage": "offered",
    }


async def _handle_member_report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, action, token = query.data.split(":", 2)
    entry = FMS_PENDING.get(token)
    if not entry:
        await query.answer("⌛ This expired or was already handled.", show_alert=True)
        return
    if query.from_user.id != entry["user_id"]:
        await query.answer("Only the person who sent this photo can report it — under their own name.",
                           show_alert=True)
        return

    if action == "no":
        if entry["stage"] in ("preparing", "sending"):
            await query.answer("Already in progress.")
            return
        FMS_PENDING.pop(token, None)
        Path(entry["image_path"]).unlink(missing_ok=True)
        await query.answer()
        await query.edit_message_text("🏛️ OK — not reported to FixMyStreet.")
        return

    profile = fms_profiles.get(entry["user_id"])
    if not profile:
        await query.answer("First give me your name and email in a private chat — "
                           "tap « Set up my details », then come back here.", show_alert=True)
        return

    if action == "prep" and entry["stage"] == "offered":
        if fms_profiles.reports_today(entry["user_id"]) >= fms_profiles.daily_max():
            await query.answer(f"You've reached today's limit of {fms_profiles.daily_max()} reports.",
                               show_alert=True)
            return
        entry["stage"] = "preparing"
        await query.answer()
        await query.edit_message_text("🏛️ Preparing the report (looking at the photo, finding the address)…")
        context.application.create_task(_prepare_member_report(context.application, token), update=update)
    elif action == "send" and entry["stage"] == "previewed":
        entry["stage"] = "sending"
        await query.answer()
        await query.edit_message_text("🏛️ Sending to FixMyStreet…")
        context.application.create_task(_send_member_report(context.application, token, profile), update=update)
    else:
        await query.answer()


async def _edit_member_report(application: Application, entry: dict, text: str, rows=None):
    await application.bot.edit_message_text(
        text, chat_id=entry["chat_id"], message_id=entry["message_id"],
        reply_markup=InlineKeyboardMarkup(rows) if rows else None,
    )


def _drop_member_report(token: str):
    entry = FMS_PENDING.pop(token, None)
    if entry:
        Path(entry["image_path"]).unlink(missing_ok=True)


async def _prepare_member_report(application: Application, token: str):
    entry = FMS_PENDING[token]
    lat, lon = entry["gps"]
    try:
        details = await asyncio.to_thread(fixmystreet.prepare, entry["image_path"], lat, lon)
    except Exception as e:
        if not isinstance(e, fixmystreet.FixMyStreetError):
            logger.exception("FixMyStreet member report: prepare failed")
        _drop_member_report(token)
        await _edit_member_report(application, entry, f"⚠️ Couldn't prepare the FixMyStreet report: {e}")
        return
    if not details["reportable"]:
        _drop_member_report(token)
        await _edit_member_report(application, entry,
                                  f"🏛️ Doesn't look like something to report: {details['reason']}")
        return
    profile = fms_profiles.get(entry["user_id"]) or {}
    entry.update(details=details, stage="previewed", ts=time.time())
    test = "\n\n(test mode: nothing will actually be sent)" if FMS_DRY_RUN else ""
    await _edit_member_report(
        application, entry,
        f"🏛️ Report for {entry['first_name']} — check it:\n{details['category']}\n{details['address']}\n"
        f"« {details['description']} »\nFiled as: {fms_profiles.masked(profile)}{test}",
        [[InlineKeyboardButton("✅ Send to FixMyStreet", callback_data=f"fmsu:send:{token}"),
          InlineKeyboardButton("❌ Cancel", callback_data=f"fmsu:no:{token}")]],
    )


async def _send_member_report(application: Application, token: str, profile: dict):
    entry = FMS_PENDING[token]
    d = entry["details"]
    try:
        if FMS_DRY_RUN:
            await _edit_member_report(application, entry,
                                      f"🏛️ DRY RUN — would have reported for {entry['first_name']} (nothing sent):\n"
                                      f"{d['category']}\n{d['address']}")
            return
        r = await asyncio.to_thread(fixmystreet.submit, d["location"], d["category_id"], d["description"],
                                    entry["image_path"], profile)
        fms_profiles.record_report(entry["user_id"])
        await _edit_member_report(application, entry,
                                  f"🏛️ Reported to FixMyStreet by {entry['first_name']}\n{d['category']}\n"
                                  f"{d['address']}\n{r['url']}")
    except Exception as e:
        if not isinstance(e, fixmystreet.FixMyStreetError):
            logger.exception("FixMyStreet member report: submit failed")
        await _edit_member_report(application, entry, f"⚠️ FixMyStreet report failed: {e}")
    finally:
        _drop_member_report(token)


async def _fms_profile_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    profile = fms_profiles.get(update.effective_user.id)
    current = f"Saved now: {fms_profiles.masked(profile)}\n\n" if profile else ""
    await update.message.reply_text(
        "🏛️ FixMyStreet Brussels reports are filed in a real person's name. To report photos you send "
        "(as a File, so the location is kept), give me your details once — they're only used for "
        "reports you confirm yourself, and the Region/commune may email you about them.\n\n"
        f"{current}{fms_profiles.USAGE}\n\n/fms_forget deletes them."
    )


async def handle_fms_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message, user = update.message, update.effective_user
    if update.effective_chat.type != "private":
        if context.args:
            try:  # personal details typed into the group: take them down again
                await message.delete()
            except Exception:
                pass
        await context.bot.send_message(
            update.effective_chat.id,
            f"🔐 {user.first_name}, send your FixMyStreet details to me privately, not here: "
            f"{_fms_setup_link(context.bot)}",
        )
        return
    if not await _is_member_of_allowed_chat(context.bot, user.id):
        await message.reply_text("⛔ This is only for members of the TrashBot chat.")
        return
    args = message.text.partition(" ")[2].strip()
    if not args:
        await _fms_profile_help(update, context)
        return
    try:
        profile = fms_profiles.parse(args)
    except fms_profiles.ProfileError as e:
        await message.reply_text(f"⚠️ {e}")
        return
    fms_profiles.save(user.id, profile)
    await message.reply_text(
        f"✅ Saved: {fms_profiles.masked(profile)}\nNext time you send a photo as a File in the group, "
        "you'll get a « Prepare my report » button. /fms_forget deletes your details."
    )


async def handle_fms_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gone = fms_profiles.forget(update.effective_user.id)
    await update.message.reply_text("🗑️ Your FixMyStreet details are deleted." if gone
                                    else "Nothing saved for you.")


async def _refresh_report_statuses_forever():
    while True:
        try:
            if await asyncio.to_thread(feed_publisher.refresh_report_statuses, fixmystreet.status):
                await asyncio.to_thread(feed_publisher.publish)
        except Exception:
            logger.exception("FixMyStreet status refresh failed")
        await asyncio.sleep(FMS_STATUS_POLL_HOURS * 3600)


async def _poll_public_feed_forever():
    while True:
        try:
            await asyncio.to_thread(feed_poller.poll_and_publish)
        except Exception:
            logger.exception("Public feed poll failed")
        await asyncio.sleep(FEED_POLL_HOURS * 3600)


async def _resume_pending_chains(application: Application):
    # Plain asyncio.create_task, not application.create_task: post_init runs
    # before the Application is marked "running", so its own task-tracking
    # would just warn. Our own chain_state.json persistence is what actually
    # makes this resilient to interruption, not PTB's task supervision.
    pending = chain_state.load_pending_chains()
    for state in pending:
        logger.info(
            "Resuming interrupted reaction chain for tweet %s (stage=%s)",
            state["marc_tweet_id"],
            state["stage"],
        )
        asyncio.create_task(_chain_giselle_and_yousuf(application, state))
    if FEED_POLL_HOURS > 0:
        logger.info("Public feed: polling X for replies/metrics every %.1f h", FEED_POLL_HOURS)
        asyncio.create_task(_poll_public_feed_forever())
    if FMS_ENABLED and FMS_STATUS_POLL_HOURS > 0:
        asyncio.create_task(_refresh_report_statuses_forever())


async def _handle_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    # PTB's own polling loop already retries transient network errors (its
    # log line just says "No error handlers are registered" otherwise,
    # which reads like something is broken when it isn't) — log those at
    # warning without a traceback, and anything else at error with one.
    from telegram.error import NetworkError

    if isinstance(context.error, NetworkError):
        logger.warning("Transient network error (self-recovering): %s", context.error)
    else:
        logger.error("Unhandled exception in update handling", exc_info=context.error)


def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set in .env")
    if not ALLOWED_CHAT_IDS:
        logger.warning(
            "ALLOWED_TELEGRAM_CHAT_IDS is not set — every incoming chat will be refused. "
            "Message the bot once, check the logs for its chat_id, then set the env var."
        )
    if not OWNER_USER_IDS:
        logger.warning(
            "OWNER_TELEGRAM_USER_IDS is not set — anyone in an allowed chat can approve/"
            "discard drafts and have their photo captions passed to the agent. Set it to "
            "restrict that to specific Telegram user_ids."
        )

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(_resume_pending_chains).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("fms_profile", handle_fms_profile))
    app.add_handler(CommandHandler("fms_forget", handle_fms_forget))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_error_handler(_handle_error)
    logger.info("Marc TrashBot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
