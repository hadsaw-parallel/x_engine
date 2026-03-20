import logging
from src.bot import create_bot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting X Engine bot...")
    bot = create_bot()
    bot.run_polling()


if __name__ == "__main__":
    main()
