#!/data/data/com.termux/files/usr/bin/bash
# X Engine — Termux bootstrap
# Run once after cloning: bash scripts/termux_setup.sh
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║         X Engine — Setup             ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. System packages ──────────────────────────────────────────────────────
echo "📦 Installing system packages…"
pkg update -y -q && pkg upgrade -y -q
pkg install -y -q python git

# ── 2. Python dependencies ──────────────────────────────────────────────────
echo "🐍 Installing Python dependencies…"
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ── 3. Telegram bot token ───────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "You need a Telegram bot token to continue."
echo ""
echo "If you don't have one:"
echo "  1. Open Telegram and search for @BotFather"
echo "  2. Send /newbot and follow the prompts"
echo "  3. Copy the token it gives you"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -r -p "Paste your Telegram bot token: " BOT_TOKEN

if [ -z "$BOT_TOKEN" ]; then
  echo "❌ No token entered. Run this script again when you have one."
  exit 1
fi

# ── 4. Write .env ───────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
fi

# Replace or add TELEGRAM_BOT_TOKEN in .env
if grep -q "^TELEGRAM_BOT_TOKEN=" .env; then
  sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${BOT_TOKEN}|" .env
else
  echo "TELEGRAM_BOT_TOKEN=${BOT_TOKEN}" >> .env
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Next step: start the bot"
echo ""
echo "  python main.py"
echo ""
echo "Then open your bot in Telegram and send /setup"
echo "The wizard will ask for your Claude API key"
echo "and walk you through connecting your X account."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
