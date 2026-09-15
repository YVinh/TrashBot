#!/usr/bin/env python3
"""Telegram front-end for Marc: send a photo, get a draft caption back,
tap Post to actually publish it to X. Run as a long-lived process (systemd)."""

from __future__ import annotations

import asyncio
import logging
import os
import random
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
import feed_poller
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

# How often to read public replies + engagement counts from X for the public
# site. 0 (default) = never — reads cost X API credits, the bots' own posts
# reach the site without any (see feed_publisher.py / feed_poller.py).
FEED_POLL_HOURS = float(os.getenv("FEED_POLL_HOURS", "0") or 0)

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


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    status = await update.message.reply_text("🗑️ Looking at it...")

    submitter_is_owner = _is_owner(update)
    # Only an owner's caption reaches the LLM as a location hint. A
    # non-owner's caption is free text next to a prompt — exactly what
    # prompt injection needs — so it's dropped here rather than trusted.
    user_note = update.message.caption if submitter_is_owner else None

    try:
        caption = await asyncio.to_thread(generate_post_draft, str(image_path), user_note)
    except Exception as e:
        logger.exception("Agent failed to generate a draft")
        await status.edit_text(f"❌ Couldn't generate a caption: {e}")
        image_path.unlink(missing_ok=True)
        return

    token = tg_file.file_unique_id
    PENDING[token] = {"image_path": str(image_path), "caption": caption, "ts": time.time()}

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Post to X", callback_data=f"post:{token}"),
                InlineKeyboardButton("❌ Discard", callback_data=f"discard:{token}"),
            ]
        ]
    )
    sender_name = update.effective_user.first_name or "someone"
    owner_note = "" if submitter_is_owner else f"\n(from {sender_name} — only an owner can approve)"
    await status.edit_text(
        f"📝 Draft:\n\n{caption}\n\n({len(caption)} chars){owner_note}", reply_markup=keyboard
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not _authorized(update):
        await query.answer()
        return

    if not _is_owner(update):
        await query.answer("⛔ Only the project owner can approve or discard posts.", show_alert=True)
        return

    await query.answer()

    action, token = query.data.split(":", 1)
    entry = PENDING.pop(token, None)
    if not entry:
        await query.edit_message_text("⌛ This draft expired or was already handled.")
        return

    if action == "discard":
        await query.edit_message_text("🗑️ Discarded.")
        Path(entry["image_path"]).unlink(missing_ok=True)
        return

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
        return
    finally:
        Path(entry["image_path"]).unlink(missing_ok=True)

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
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Marc TrashBot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
