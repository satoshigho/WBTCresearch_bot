# 🟠 WBTC Community Telegram Admin Bot

A full-featured Telegram admin bot for the WBTC community group.

---

## ✨ Features

### 🛡 Auto-Moderation
- **Spam detection** — blocks known spam keywords (airdrops, giveaways, scam phrases)
- **Link flooding** — removes messages with 3+ links
- **ALL CAPS** — warns users abusing caps lock
- **Warning system** — 3 strikes → auto-ban (warn → mute → ban)
- **New member muting** — new members are muted for 5 min to prevent bot spam

### 👋 Welcome
- Greets new members with a friendly message and inline buttons
- Shows rules, FAQ, and price links immediately

### 💰 Live Price
- Fetches live WBTC & BTC prices from CoinGecko
- Shows 24h change, market cap, and BTC peg deviation

### 📖 Info Menu
- `/info` — interactive menu with inline buttons
- `/rules` — community rules
- `/faq` — common questions answered
- `/links` — official WBTC links

### 🔧 Admin Commands
| Command | Description |
|---|---|
| `/ban` | Ban user (reply to their message) |
| `/unban <id>` | Unban by user ID |
| `/mute [mins]` | Mute user (default 60 min) |
| `/unmute` | Remove mute |
| `/warn [reason]` | Issue a warning |
| `/warnings` | Check warning count |
| `/del` | Delete replied message |
| `/announce <text>` | Post a pinned-style announcement |

---

## 🚀 Setup

### 1. Prerequisites
- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure the Bot

Open `bot.py` and set:

```python
BOT_TOKEN = "your_token_here"          # Or use env var BOT_TOKEN

ADMIN_IDS = {123456789, 987654321}     # Your Telegram user IDs
```

Or use environment variable:
```bash
export BOT_TOKEN="your_token_here"
```

### 4. Add Bot to Your Group
1. Add the bot to your WBTC Telegram group
2. Promote it to **Admin** with these permissions:
   - ✅ Delete messages
   - ✅ Ban users
   - ✅ Restrict members
   - ✅ Pin messages (optional)

### 5. Enable Chat Member Updates in BotFather
Run `/setprivacy` → Disable (so bot can see all messages)

### 6. Run
```bash
python bot.py
```

---

## 🔧 Customization

### Add/Remove Spam Keywords
Edit `SPAM_KEYWORDS` list in `bot.py`:
```python
SPAM_KEYWORDS = [
    "airdrop", "giveaway", ...
]
```

### Adjust Warning Thresholds
```python
MAX_WARNINGS = 3        # Warnings before ban
MUTE_DURATION_MIN = 10  # Mute length on 2nd warning
NEW_MEMBER_MUTE_MIN = 5 # New member mute duration
```

### Customize Welcome Message
Edit the `welcome_new_member()` function in `bot.py`.

---

## 🐳 Running with Docker (Optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY bot.py .
CMD ["python", "bot.py"]
```

```bash
docker build -t wbtc-bot .
docker run -e BOT_TOKEN=your_token wbtc-bot
```

---

## ⚠️ Notes
- Warnings are stored **in memory** and reset on bot restart. For persistence, add a database (SQLite/PostgreSQL).
- The bot must be an admin in the group to ban/mute/delete.
- Price data is sourced from CoinGecko (free tier, rate limited).
