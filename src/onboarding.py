"""
Telegram onboarding wizard.

Steps:
  1. Claude API key  (format check)
  2. Claude model    (inline keyboard)
  3. X username or email
  4. X password      (deleted from chat immediately)
  5. Email verification code — only if X triggers it (rare)

On completion saves to .env + cookies.json and restarts the process.
"""
import asyncio
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

from config.settings import MODEL_CHOICES, save_config
from src.x_auth import LoginSession, provide_code, start_login, wait_for_login

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────────
AWAITING_CLAUDE_KEY  = 1
AWAITING_MODEL       = 2
AWAITING_X_USERNAME  = 3
AWAITING_X_PASSWORD  = 4
AWAITING_X_CODE      = 5   # only if X asks for email verification


# ── Entry point ───────────────────────────────────────────────────────────────

async def start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "👋 Welcome to X Engine!\n\n"
        "Let's get you configured. I'll need:\n"
        "  1. Your Claude API key\n"
        "  2. Your preferred Claude model\n"
        "  3. Your X username and password\n\n"
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
            "❌ That doesn't look like a valid Claude API key.\n\n"
            "It should start with `sk-ant-` and be ~100 characters.\n"
            "Get yours at console.anthropic.com",
            parse_mode="Markdown",
        )
        return AWAITING_CLAUDE_KEY

    context.user_data["claude_api_key"] = key

    keyboard = [
        [InlineKeyboardButton(f"⚡ {label}", callback_data=choice)]
        for choice, (_, label) in MODEL_CHOICES.items()
    ]
    await update.message.reply_text(
        "✅ API key saved!\n\nChoose your Claude model:",
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

    await query.edit_message_text(f"✅ Model: {model_label}")
    await query.message.reply_text(
        "🐦 Now let's connect your X account.\n\n"
        "Send me your X username or email address:"
    )
    return AWAITING_X_USERNAME


# ── Step 3: X username ────────────────────────────────────────────────────────

async def receive_x_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username = update.message.text.strip().lstrip("@")

    if len(username) < 2:
        await update.message.reply_text("Please send a valid username or email:")
        return AWAITING_X_USERNAME

    context.user_data["x_username"] = username
    await update.message.reply_text(
        "Now send your X password.\n"
        "_(It will be deleted from chat immediately)_",
        parse_mode="Markdown",
    )
    return AWAITING_X_PASSWORD


# ── Step 4: X password ────────────────────────────────────────────────────────

async def receive_x_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    if len(password) < 4:
        await update.message.reply_text("Password seems too short. Try again:")
        return AWAITING_X_PASSWORD

    status = await update.message.reply_text("🔐 Logging into X…")

    # Start login in background thread
    session = start_login(
        username=context.user_data["x_username"],
        password=password,
    )
    context.user_data["login_session"] = session

    result = await wait_for_login(session, timeout=40.0)

    if result == "needs_code":
        await status.edit_text(
            "📧 X sent a verification code to your email.\n\n"
            "Check your inbox and send the code here:"
        )
        return AWAITING_X_CODE

    if result == "timeout":
        await status.edit_text(
            "⏱ Login timed out. Please check your credentials and try again.\n"
            "Send /setup to start over."
        )
        return ConversationHandler.END

    # result == "done"
    return await _finish_login(update, context, session, status)


# ── Step 5: Email verification code (only if triggered) ──────────────────────

async def receive_x_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    session: LoginSession = context.user_data.get("login_session")
    if session is None:
        await update.message.reply_text("Session expired. Send /setup to start over.")
        return ConversationHandler.END

    status = await update.message.reply_text("🔐 Verifying code…")

    provide_code(session, code)
    result = await wait_for_login(session, timeout=30.0)

    if result == "timeout":
        await status.edit_text("⏱ Timed out. Send /setup to try again.")
        return ConversationHandler.END

    return await _finish_login(update, context, session, status)


# ── Shared finish ─────────────────────────────────────────────────────────────

async def _finish_login(update, context, session: LoginSession, status_msg) -> int:
    if session.error:
        logger.error(f"X login error: {session.error}")
        short_error = str(session.error)[:200]
        await status_msg.edit_text(
            f"❌ X login failed:\n{short_error}\n\nSend /setup to try again."
        )
        return ConversationHandler.END

    # Save Claude settings (.env) — cookies already saved by twikit
    save_config(
        claude_api_key=context.user_data["claude_api_key"],
        model_id=context.user_data["model_id"],
    )

    await status_msg.edit_text(
        "✅ All done! X Engine is configured and ready.\n\n"
        "Just type any question and I'll search X for you.\n\n"
        "Example: *what's new in AI agents this week?*\n\n"
        "_Restarting to apply settings…_",
        parse_mode="Markdown",
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
            AWAITING_X_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_x_username)
            ],
            AWAITING_X_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_x_password)
            ],
            AWAITING_X_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_x_code)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="onboarding",
        persistent=False,
    )


# ── Internal ──────────────────────────────────────────────────────────────────

def _restart() -> None:
    os.execv(sys.executable, [sys.executable] + sys.argv)
