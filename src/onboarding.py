"""
Telegram onboarding wizard.

Guides a new user through:
  1. Claude API key  (validated with a live test call)
  2. Claude model    (inline keyboard)
  3. X auth_token   (browser cookie)
  4. X ct0          (browser cookie)

On completion everything is saved to .env + cookies.json and the
process restarts so the new settings are loaded cleanly.
"""
import asyncio
import logging
import os
import sys

import anthropic
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config.settings import MODEL_CHOICES, save_config

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
AWAITING_CLAUDE_KEY  = 1
AWAITING_MODEL       = 2
AWAITING_AUTH_TOKEN  = 3
AWAITING_CT0         = 4


# ── Entry point ───────────────────────────────────────────────────────────────

async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "👋 Welcome to X Engine!\n\n"
        "Let's get you configured. I'll need:\n"
        "  1. Your Claude API key\n"
        "  2. Your preferred Claude model\n"
        "  3. Two cookies from your X/Twitter browser session\n\n"
        "First, send your Claude API key.\n"
        "You can get one at console.anthropic.com\n\n"
        "Send /cancel at any time to stop."
    )
    return AWAITING_CLAUDE_KEY


# ── Step 1: Claude API key ────────────────────────────────────────────────────

async def receive_claude_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    key = update.message.text.strip()

    # Delete the message so the key isn't sitting in chat history
    try:
        await update.message.delete()
    except Exception:
        pass

    status = await update.message.reply_text("🔑 Validating API key…")

    try:
        test_client = anthropic.Anthropic(api_key=key)
        test_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            messages=[{"role": "user", "content": "hi"}],
        )
    except anthropic.AuthenticationError:
        await status.edit_text(
            "❌ Invalid API key. Please check and try again.\n\n"
            "Get your key at console.anthropic.com"
        )
        return AWAITING_CLAUDE_KEY
    except Exception as e:
        await status.edit_text(
            f"❌ Could not validate key: {str(e)[:120]}\n\nPlease try again:"
        )
        return AWAITING_CLAUDE_KEY

    context.user_data["claude_api_key"] = key
    await status.delete()

    keyboard = [
        [InlineKeyboardButton(f"⚡ {label}", callback_data=choice)]
        for choice, (_, label) in MODEL_CHOICES.items()
    ]
    await update.message.reply_text(
        "✅ API key valid!\n\nChoose your Claude model:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return AWAITING_MODEL


# ── Step 2: Model selection ───────────────────────────────────────────────────

async def receive_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data  # "haiku" | "sonnet" | "opus"
    if choice not in MODEL_CHOICES:
        return AWAITING_MODEL

    model_id, model_label = MODEL_CHOICES[choice]
    context.user_data["model_id"] = model_id

    await query.edit_message_text(f"✅ Model: {model_label}")

    await query.message.reply_text(
        "🐦 Now let's connect your X account.\n\n"
        "I need two cookies from your X browser session.\n\n"
        "*How to get them (takes ~1 minute):*\n"
        "1. Open x.com in Chrome or Firefox on any device\n"
        "2. Make sure you're logged in\n"
        "3. Open DevTools with F12 (or right-click → Inspect)\n"
        "4. Click the *Application* tab → *Cookies* → `https://x.com`\n"
        "5. Find the row named `auth_token` and copy its Value\n\n"
        "Send me the `auth_token` value now:",
        parse_mode="Markdown",
    )
    return AWAITING_AUTH_TOKEN


# ── Step 3: auth_token ────────────────────────────────────────────────────────

async def receive_auth_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if len(token) < 20:
        await update.message.reply_text(
            "❌ That doesn't look right (too short).\n"
            "Please copy the full `auth_token` value from the cookie table:",
            parse_mode="Markdown",
        )
        return AWAITING_AUTH_TOKEN

    context.user_data["auth_token"] = token

    await update.message.reply_text(
        "✅ Got `auth_token`.\n\n"
        "Now go back to the same cookie list and copy the `ct0` value.\n"
        "Send it here:",
        parse_mode="Markdown",
    )
    return AWAITING_CT0


# ── Step 4: ct0 ───────────────────────────────────────────────────────────────

async def receive_ct0(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ct0 = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if len(ct0) < 20:
        await update.message.reply_text(
            "❌ That doesn't look right (too short).\n"
            "Please copy the full `ct0` value:",
            parse_mode="Markdown",
        )
        return AWAITING_CT0

    status = await update.message.reply_text("🔐 Verifying X cookies…")

    # Validate the cookies with a real search call
    from twikit import Client
    from twikit.errors import Unauthorized

    client = Client("en-US")
    client.set_cookies({
        "auth_token": context.user_data["auth_token"],
        "ct0": ct0,
    })

    try:
        await client.search_tweet("test", product="Latest", count=1)
    except (Unauthorized, Exception) as e:
        err = str(e).lower()
        if "unauthorized" in err or "401" in err or "forbidden" in err or "403" in err:
            await status.edit_text(
                "❌ X cookies appear to be invalid or expired.\n\n"
                "Please go back to x.com, make sure you're still logged in,\n"
                "and copy fresh cookie values.\n\n"
                "Send the `auth_token` value again:",
                parse_mode="Markdown",
            )
            context.user_data.pop("auth_token", None)
            return AWAITING_AUTH_TOKEN
        # Network / unknown error — don't block setup
        logger.warning(f"Cookie validation soft error (saving anyway): {e}")

    # Everything checks out — save to disk
    save_config(
        claude_api_key=context.user_data["claude_api_key"],
        model_id=context.user_data["model_id"],
        auth_token=context.user_data["auth_token"],
        ct0=ct0,
    )

    await status.edit_text(
        "✅ All done! X Engine is configured and ready.\n\n"
        "Just type any question and I'll search X for you.\n\n"
        "Example: *what's new in AI agents this week?*\n\n"
        "_Restarting to apply settings…_",
        parse_mode="Markdown",
    )

    # Restart the process cleanly so the new .env values are loaded
    asyncio.get_event_loop().call_later(1.5, _restart)
    return ConversationHandler.END


# ── Cancel ────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Setup cancelled. Send /setup whenever you're ready to try again."
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
    """Replace the current process with a fresh one (loads new .env)."""
    os.execv(sys.executable, [sys.executable] + sys.argv)
