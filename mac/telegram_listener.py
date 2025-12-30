#!/usr/bin/env python3
"""
WVOID-FM Telegram Bot

Listens for messages in a Telegram channel/group and adds them to the message queue.
Messages can then be read on air as dedications.

Usage:
    Set TELEGRAM_BOT_TOKEN environment variable and run the script.
    Add the bot to your channel/group.
"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Check for required package
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    print("Error: python-telegram-bot not installed")
    print("Install with: pip install python-telegram-bot")
    sys.exit(1)


# Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
MESSAGES_FILE = Path.home() / ".wvoid" / "messages.json"
ALLOWED_CHAT_IDS: set[int] = set()  # Empty = allow all, or specify chat IDs

# Load allowed chat IDs from environment
env_chat_ids = os.environ.get("TELEGRAM_ALLOWED_CHATS", "")
if env_chat_ids:
    ALLOWED_CHAT_IDS = {int(x.strip()) for x in env_chat_ids.split(",") if x.strip()}


def log(msg: str):
    """Log with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def save_message(message: str, username: str, source: str = "telegram"):
    """Save a message to the shared queue."""
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load existing messages
    messages = []
    if MESSAGES_FILE.exists():
        try:
            with open(MESSAGES_FILE) as f:
                messages = json.load(f)
        except:
            messages = []

    # Add new message
    messages.append({
        "message": message,
        "source": source,
        "username": username,
        "timestamp": datetime.now().isoformat(),
        "read": False,
    })

    # Keep only last 100 messages
    messages = messages[-100:]

    # Save
    with open(MESSAGES_FILE, "w") as f:
        json.dump(messages, f, indent=2)

    log(f"Saved message from @{username}: {message[:50]}...")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "WVOID-FM Message Bot\n\n"
        "Send me a message and it might be read on air.\n"
        "Keep it under 280 characters.\n\n"
        "/nowplaying - See what's currently playing"
    )


async def now_playing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /nowplaying command."""
    try:
        import urllib.request
        url = "https://api.khaledeltokhy.com/now-playing"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())

        track = data.get("track", "Unknown")
        vibe = data.get("vibe", "")
        listeners = data.get("listeners", 0)
        time_period = data.get("time_period", "")

        response_text = f"Now playing: {track}"
        if vibe and vibe != "unknown":
            response_text += f"\nVibe: {vibe}"
        if listeners > 0:
            response_text += f"\nListeners: {listeners}"
        if time_period:
            response_text += f"\nTime: {time_period.replace('_', ' ')}"

        await update.message.reply_text(response_text)
    except Exception as e:
        await update.message.reply_text(f"Couldn't fetch now playing info: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    # Check if chat is allowed
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        log(f"Ignored message from unauthorized chat {update.effective_chat.id}")
        return

    message = update.message.text
    if not message:
        return

    # Validate length
    if len(message) > 280:
        await update.message.reply_text(
            "Message too long! Keep it under 280 characters."
        )
        return

    # Get username
    user = update.effective_user
    username = user.username or user.first_name or "anonymous"

    # Save message
    save_message(message, username)

    # Confirm
    await update.message.reply_text(
        "Message received. It might be read on air."
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors."""
    log(f"Error: {context.error}")


def main():
    """Run the bot."""
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable not set")
        print("Get a token from @BotFather on Telegram")
        sys.exit(1)

    log("Starting WVOID-FM Telegram Bot...")

    # Create application
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("nowplaying", now_playing_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    # Run
    log("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
