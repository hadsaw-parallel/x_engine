import logging

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from config.settings import TELEGRAM_BOT_TOKEN, is_configured
from src.agent import research
from src.formatter import format_research
from src.onboarding import create_onboarding_handler

logger = logging.getLogger(__name__)

_NOT_CONFIGURED_MSG = (
    "⚙️ X Engine isn't set up yet.\n\n"
    "Run /setup to configure your Claude API key and X account.\n"
    "It only takes a minute."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_configured():
        await update.message.reply_text(
            "👋 Welcome to X Engine!\n\n"
            "Run /setup to get started — I'll walk you through everything."
        )
        return

    await update.message.reply_text(
        "🧠 Hey! I'm your X research agent.\n\n"
        "Ask me anything — I'll search X/Twitter with multiple smart queries, "
        "unroll threads, filter out noise, and find posts where people share "
        "real builds, insights, and demos.\n\n"
        "Just type your question:\n"
        "• what's new in claude skills\n"
        "• latest RAG techniques people are building\n"
        "• any new open source AI agents this week\n\n"
        "Or use /search <query>\n\n"
        "Use /reconfigure to change your API key, model, or X account."
    )


async def reconfigure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start the setup wizard even if already configured."""
    from src.onboarding import start_setup
    await start_setup(update, context)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_configured():
        await update.message.reply_text(_NOT_CONFIGURED_MSG)
        return

    if not context.args:
        await update.message.reply_text("Usage: /search <topic>\nExample: /search claude skills")
        return

    query = " ".join(context.args)
    await _handle_research(update, query)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_configured():
        await update.message.reply_text(_NOT_CONFIGURED_MSG)
        return

    query = update.message.text.strip()
    if not query:
        return

    await _handle_research(update, query)


async def _handle_research(update: Update, query: str) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)

    status_msg = await update.message.reply_text(f'🧠 Starting research: "{query}"')

    async def update_status(text: str):
        try:
            await update.message.chat.send_action(ChatAction.TYPING)
            await status_msg.edit_text(text)
        except Exception:
            pass

    try:
        result = await research(query, status_callback=update_status)

        post_count = len(result.get("posts", []))
        if post_count == 0:
            await status_msg.edit_text(
                f'Couldn\'t find high-quality posts about "{query}".\n'
                "Try rephrasing or a more specific topic."
            )
            return

        formatted = format_research(result, query)
        await status_msg.delete()

        if len(formatted) <= 4096:
            await update.message.reply_text(
                formatted,
                parse_mode=ParseMode.MARKDOWN_V2,
                disable_web_page_preview=True,
            )
        else:
            for i in range(0, len(formatted), 4096):
                await update.message.reply_text(
                    formatted[i : i + 4096],
                    parse_mode=ParseMode.MARKDOWN_V2,
                    disable_web_page_preview=True,
                )

    except Exception as e:
        logger.exception("Research failed")
        await status_msg.edit_text(f"❌ Something went wrong: {str(e)[:200]}")


def create_bot() -> Application:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Onboarding wizard — must be registered before general handlers
    app.add_handler(create_onboarding_handler())

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("reconfigure", reconfigure))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    return app
