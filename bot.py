#!/usr/bin/env python3
"""Telegram front-end for Marc: send a photo, get a draft caption back,
tap Post to actually publish it to X. Run as a long-lived process (systemd)."""

from __future__ import annotations

import asyncio
import logging
import os
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

from trash_agent import generate_post_draft
from twitter_poster import post_image_with_caption
from giselle_agent import generate_reaction as giselle_react
from yousuf_agent import generate_comments as yousuf_comment
from x_accounts import post_reply

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_IDS = {
    int(x) for x in os.getenv("ALLOWED_TELEGRAM_CHAT_IDS", "").split(",") if x.strip()
}

PENDING_TTL_SECONDS = 3600
PENDING: dict[str, dict] = {}


def _authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return False
    return update.effective_chat.id in ALLOWED_CHAT_IDS


def _cleanup_expired():
    now = time.time()
    for token in [t for t, e in PENDING.items() if now - e["ts"] > PENDING_TTL_SECONDS]:
        entry = PENDING.pop(token)
        Path(entry["image_path"]).unlink(missing_ok=True)


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 I'm Marc. Your chat_id is {update.effective_chat.id}.\n"
        "Once that's in ALLOWED_TELEGRAM_CHAT_IDS, send me a trash photo (as a photo, "
        "not compressed-away — attach as a File if you want GPS-based hashtags to work)."
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

    user_note = update.message.caption

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
    await status.edit_text(f"📝 Draft:\n\n{caption}\n\n({len(caption)} chars)", reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not _authorized(update):
        return

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
    except Exception as e:
        logger.exception("Failed to post to X")
        await query.edit_message_text(f"❌ Failed to post: {e}")
        return
    finally:
        Path(entry["image_path"]).unlink(missing_ok=True)

    await _chain_giselle_and_yousuf(
        context, update.effective_chat.id, result["post_id"], entry["caption"]
    )


async def _chain_giselle_and_yousuf(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, marc_tweet_id: str, marc_text: str
):
    """Fire Giselle's reaction, then Yousuf's comments, right after Marc posts.
    Fully autonomous — no Telegram approval — but errors are reported back to chat."""
    try:
        giselle_text = await asyncio.to_thread(giselle_react, marc_text)
        giselle_result = await asyncio.to_thread(post_reply, "GISELLE", marc_tweet_id, giselle_text)
        await context.bot.send_message(chat_id, f"🗯️ Giselle: {giselle_result['post_url']}")
    except Exception as e:
        logger.exception("Giselle failed to react")
        await context.bot.send_message(chat_id, f"⚠️ Giselle failed to react: {e}")
        return

    try:
        comment_on_marc, comment_on_giselle = await asyncio.to_thread(
            yousuf_comment, marc_text, giselle_text
        )
        r1 = await asyncio.to_thread(post_reply, "YOUSUF", marc_tweet_id, comment_on_marc)
        r2 = await asyncio.to_thread(
            post_reply, "YOUSUF", giselle_result["post_id"], comment_on_giselle
        )
        await context.bot.send_message(
            chat_id, f"🙃 Yousuf: {r1['post_url']}\n🙃 Yousuf: {r2['post_url']}"
        )
    except Exception as e:
        logger.exception("Yousuf failed to comment")
        await context.bot.send_message(chat_id, f"⚠️ Yousuf failed to comment: {e}")


def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN not set in .env")
    if not ALLOWED_CHAT_IDS:
        logger.warning(
            "ALLOWED_TELEGRAM_CHAT_IDS is not set — every incoming chat will be refused. "
            "Message the bot once, check the logs for its chat_id, then set the env var."
        )

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("Marc TrashBot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
