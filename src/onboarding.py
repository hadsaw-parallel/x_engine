"""
Telegram onboarding wizard.

Steps:
  1. Claude API key  (format check)
  2. Claude model    (inline keyboard)
  3. X auth_token    (from browser cookies)
  4. X ct0 token     (from browser cookies)

On completion saves to .env + cookies.json and restarts the process.
"""
import asyncio
import json
import logging
import os
import sys

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config.settings import COOKIES_FILE, MODEL_CHOICES, save_config

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
AWAITING_CLAUDE_KEY  = 1
AWAITING_MODEL       = 2
AWAITING_AUTH_TOKEN   = 3
AWAITING_CT0          = 4


# ── Entry point ───────────────────────────────────────────────────────────────

async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Welcome to X Engine!\n\n"
        "Let's get you configured. I'll need:\n"
        "  1. Your Claude API key\n"
        "  2. Your preferred Claude model\n"
        "  3. Your X auth_token and ct0 cookies\n\n"
        "First, send your Claude API key.\n"
        "Get one at console.anthropic.com\n\n"
        "Send /cancel at any time to stop."
    )
    return AWAITING_CLAUDE_KEY


# ── Step 1: Claude API key ────────────────────────────────────────────────────

async def receive_claude_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    key = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if not key.startswith("sk-ant-") or len(key) < 40:
        await update.message.reply_text(
            "That doesn't look like a valid Claude API key.\n\n"
            "It should start with sk-ant- and be ~100 characters.\n"
            "Get yours at console.anthropic.com",
        )
        return AWAITING_CLAUDE_KEY

    context.user_data["claude_api_key"] = key

    keyboard = [
        [InlineKeyboardButton(f"{label}", callback_data=choice)]
        for choice, (_, label) in MODEL_CHOICES.items()
    ]
    await update.message.reply_text(
        "API key saved!\n\nChoose your Claude model:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return AWAITING_MODEL


# ── Step 2: Model selection ───────────────────────────────────────────────────

async def receive_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data
    if choice not in MODEL_CHOICES:
        return AWAITING_MODEL

    model_id, model_label = MODEL_CHOICES[choice]
    context.user_data["model_id"] = model_id

    await query.edit_message_text(f"Model: {model_label}")
    await query.message.reply_text(
        "Now let's connect your X account.\n\n"
        "I need your browser cookies from x.com.\n\n"
        "How to get them:\n"
        "1. Open x.com in your browser and log in\n"
        "2. Open DevTools (F12) > Application > Cookies > x.com\n"
        "3. Find the cookie named auth_token and copy its value\n\n"
        "Send me your auth_token now:\n"
        "(It will be deleted from chat immediately)"
    )
    return AWAITING_AUTH_TOKEN


# ── Step 3: X auth_token ─────────────────────────────────────────────────────

async def receive_auth_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if len(token) < 20:
        await update.message.reply_text(
            "That doesn't look like a valid auth_token.\n"
            "It should be a ~40 character hex string.\n"
            "Please try again:"
        )
        return AWAITING_AUTH_TOKEN

    context.user_data["auth_token"] = token
    await update.message.reply_text(
        "Got it!\n\n"
        "Now send me the ct0 cookie value.\n"
        "It's in the same cookies list in DevTools.\n"
        "(It will be deleted from chat immediately)"
    )
    return AWAITING_CT0


# ── Step 4: X ct0 ────────────────────────────────────────────────────────────

async def receive_ct0(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ct0 = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if len(ct0) < 10:
        await update.message.reply_text(
            "That doesn't look like a valid ct0 token.\n"
            "Please check DevTools and try again:"
        )
        return AWAITING_CT0

    # Build and save cookies.json for Twikit
    cookies = {
        "ct0": ct0,
        "auth_token": context.user_data["auth_token"],
    }

    try:
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save cookies: {e}")
        await update.message.reply_text(
            f"Failed to save cookies: {e}\nSend /setup to try again."
        )
        return ConversationHandler.END

    # Save Claude settings to .env
    save_config(
        claude_api_key=context.user_data["claude_api_key"],
        model_id=context.user_data["model_id"],
    )

    await update.message.reply_text(
        "All done! X Engine is configured and ready.\n\n"
        "Just type any question and I'll search X for you.\n\n"
        "Example: what's new in AI agents this week?\n\n"
        "Restarting to apply settings...",
    )

    asyncio.get_event_loop().call_later(1.5, _restart)
    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Setup cancelled. Send /setup whenever you're ready."
    )
    return ConversationHandler.END


# ── Factory ───────────────────────────────────────────────────────────────────

def create_onboarding_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("setup", start_setup)],
        states={
            AWAITING_CLAUDE_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_claude_key)
            ],
            AWAITING_MODEL: [
                CallbackQueryHandler(receive_model)
            ],
            AWAITING_AUTH_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_auth_token)
            ],
            AWAITING_CT0: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ct0)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="onboarding",
        persistent=False,
    )


# ── Internal ──────────────────────────────────────────────────────────────────

def _restart() -> None:
    os.execv(sys.executable, [sys.executable] + sys.argv)
