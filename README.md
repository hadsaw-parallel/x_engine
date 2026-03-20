# X Engine

A Telegram bot that searches X/Twitter for recent posts on any topic and summarizes them using Claude AI. Ask a question, get a digest — no scheduled jobs, just on-demand search.

## How It Works

1. You send a topic to the bot (e.g., "AI agents")
2. Bot searches X/Twitter for recent posts
3. Claude AI summarizes each post in 3-4 lines
4. You get a clean, formatted digest with links

## Setup

### Prerequisites

- Python 3.10+
- A [Telegram Bot Token](https://core.telegram.org/bots#botfather)
- A [Claude API Key](https://console.anthropic.com/)
- An X/Twitter account

### Installation

```bash
git clone https://github.com/yourusername/x_engine.git
cd x_engine
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

- `TELEGRAM_BOT_TOKEN` — from BotFather
- `CLAUDE_API_KEY` — from Anthropic Console
- `X_USERNAME` — your X username
- `X_EMAIL` — your X email
- `X_PASSWORD` — your X password

### Run

```bash
python main.py
```

### Run on Termux (Android)

```bash
git clone https://github.com/yourusername/x_engine.git
cd x_engine
bash scripts/termux_setup.sh
cp .env.example .env
nano .env  # fill in credentials
python main.py
```

## Usage

Open your bot in Telegram and:

- Send any text — bot treats it as a search query
- `/search RAG` — explicit search command
- `/start` — see welcome message

## License

MIT
