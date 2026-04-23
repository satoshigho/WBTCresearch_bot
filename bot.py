"""
WBTC Community Telegram Admin Bot
Full-featured moderation, info, and utility bot for the WBTC community.
"""

import logging
import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberUpdated,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8633516655:AAEyh_6S3qaCfHJL7DEtkePSlfcNBCYep_8")

# Admins (Telegram user IDs) who can use admin commands
ADMIN_IDS: set[int] = {
    6171782909,  # Owner
}

# Spam / moderation settings
SPAM_KEYWORDS = [
    "airdrop", "giveaway", "free btc", "free wbtc", "click here",
    "earn 10x", "guaranteed profit", "investment opportunity",
    "dm me", "message me for", "telegram.me/", "t.me/joinchat",
    "crypto pump", "presale", "rug", "honeypot",
]

MAX_WARNINGS = 3          # Warnings before auto-ban
MUTE_DURATION_MIN = 10    # Minutes for mute on warning 2
NEW_MEMBER_MUTE_MIN = 5   # Minutes new members are muted after join

# In-memory warning store  {user_id: warning_count}
warnings: dict[int, int] = {}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def get_chat_admin_ids(update: Update, context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    admins = await context.bot.get_chat_administrators(update.effective_chat.id)
    return [a.user.id for a in admins]


async def is_chat_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    admin_ids = await get_chat_admin_ids(update, context)
    return update.effective_user.id in admin_ids or is_admin(update.effective_user.id)


async def safe_delete(update: Update) -> None:
    try:
        await update.message.delete()
    except Exception:
        pass


# ─── Welcome Message ─────────────────────────────────────────────────────────

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome new members and mute them briefly to reduce spam."""
    result: ChatMemberUpdated = update.chat_member
    if result.new_chat_member.status not in ("member", "restricted"):
        return

    user = result.new_chat_member.user
    chat = update.effective_chat

    # Temporarily mute new member
    mute_until = datetime.utcnow() + timedelta(minutes=NEW_MEMBER_MUTE_MIN)
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=mute_until,
        )
    except Exception as e:
        logger.warning(f"Could not mute new member: {e}")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 What is WBTC?", callback_data="info_wbtc"),
         InlineKeyboardButton("📜 Rules", callback_data="info_rules")],
        [InlineKeyboardButton("💰 WBTC Price", callback_data="info_price")],
    ])

    await context.bot.send_message(
        chat_id=chat.id,
        text=(
            f"👋 Welcome, [{user.first_name}](tg://user?id={user.id})!\n\n"
            f"You've joined the *WBTC Community*. You'll be able to chat in {NEW_MEMBER_MUTE_MIN} minutes.\n\n"
            "Please read the rules and enjoy your stay! 🧡"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


# ─── Spam / Moderation ────────────────────────────────────────────────────────

async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check messages for spam keywords and take action."""
    if not update.message or not update.effective_user:
        return

    user = update.effective_user
    text = (update.message.text or update.message.caption or "").lower()

    # Skip admins
    if await is_chat_admin(update, context):
        return

    # Check for spam keywords
    triggered = [kw for kw in SPAM_KEYWORDS if kw in text]

    # Check for excessive links
    link_count = len(re.findall(r"https?://", text))

    if triggered or link_count > 2:
        await safe_delete(update)
        await add_warning(update, context, user.id, user.first_name, reason=f"spam/links ({', '.join(triggered)})")
        return

    # Check for all-caps abuse (>15 chars, >80% caps)
    if len(text) > 15 and sum(1 for c in text if c.isupper()) / max(len(text), 1) > 0.8:
        await safe_delete(update)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"⚠️ {user.first_name}, please don't shout (ALL CAPS). Message removed.",
        )


async def add_warning(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    user_name: str,
    reason: str = "rule violation",
) -> None:
    warnings[user_id] = warnings.get(user_id, 0) + 1
    count = warnings[user_id]
    chat_id = update.effective_chat.id

    if count >= MAX_WARNINGS:
        # Ban
        await context.bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🚫 *{user_name}* has been *banned* after {MAX_WARNINGS} warnings. Reason: {reason}.",
            parse_mode=ParseMode.MARKDOWN,
        )
        warnings.pop(user_id, None)
    elif count == 2:
        # Mute
        mute_until = datetime.utcnow() + timedelta(minutes=MUTE_DURATION_MIN)
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=mute_until,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ *{user_name}* — Warning {count}/{MAX_WARNINGS}.\n"
                f"Muted for {MUTE_DURATION_MIN} minutes. Reason: {reason}."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ *{user_name}* — Warning {count}/{MAX_WARNINGS}.\n"
                f"Reason: {reason}. One more and you'll be muted."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )


# ─── Admin Commands ───────────────────────────────────────────────────────────

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Reply to a user's message to ban them.")
        return
    target = update.message.reply_to_message.from_user
    await context.bot.ban_chat_member(update.effective_chat.id, target.id)
    await update.message.reply_text(f"🚫 {target.first_name} has been banned.")


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    user_id = int(context.args[0])
    await context.bot.unban_chat_member(update.effective_chat.id, user_id)
    await update.message.reply_text(f"✅ User {user_id} has been unbanned.")


async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Reply to a user's message to mute them.")
        return
    target = update.message.reply_to_message.from_user
    minutes = int(context.args[0]) if context.args else 60
    mute_until = datetime.utcnow() + timedelta(minutes=minutes)
    await context.bot.restrict_chat_member(
        chat_id=update.effective_chat.id,
        user_id=target.id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=mute_until,
    )
    await update.message.reply_text(f"🔇 {target.first_name} muted for {minutes} minutes.")


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Reply to a user's message to unmute them.")
        return
    target = update.message.reply_to_message.from_user
    await context.bot.restrict_chat_member(
        chat_id=update.effective_chat.id,
        user_id=target.id,
        permissions=ChatPermissions(
            can_send_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        ),
    )
    await update.message.reply_text(f"🔊 {target.first_name} has been unmuted.")


async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Reply to a user's message to warn them.")
        return
    target = update.message.reply_to_message.from_user
    reason = " ".join(context.args) if context.args else "no reason given"
    await add_warning(update, context, target.id, target.first_name, reason)


async def cmd_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("↩️ Reply to a user's message to check their warnings.")
        return
    target = update.message.reply_to_message.from_user
    count = warnings.get(target.id, 0)
    await update.message.reply_text(f"⚠️ {target.first_name} has {count}/{MAX_WARNINGS} warnings.")


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if update.message.reply_to_message:
        await update.message.reply_to_message.delete()
    await update.message.delete()


async def cmd_announce(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_chat_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: /announce <message>")
        return
    text = "📢 *ANNOUNCEMENT*\n\n" + " ".join(context.args)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.delete()


# ─── Info Commands ────────────────────────────────────────────────────────────

WBTC_INFO = """
🟠 *What is WBTC (Wrapped Bitcoin)?*

WBTC is an ERC-20 token on Ethereum that is backed 1:1 with Bitcoin.

• 1 WBTC = 1 BTC (always)
• Enables Bitcoin liquidity on Ethereum DeFi
• Fully audited & transparent reserves
• Managed by the WBTC DAO

🔗 *Official Links:*
• Website: [wbtc.network](https://wbtc.network)
• CoinGecko: [wbtc on CoinGecko](https://www.coingecko.com/en/coins/wrapped-bitcoin)
• Contract: `0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599`
"""

RULES_TEXT = """
📜 *WBTC Community Rules*

1️⃣ No spam, scams, or phishing links
2️⃣ No unsolicited DMs — report them to admins
3️⃣ No price manipulation / pump talk
4️⃣ Be respectful to all members
5️⃣ English only in main chat
6️⃣ No posting of competitor token promotions
7️⃣ No sharing of unverified contract addresses
8️⃣ Admins have final say — follow instructions

⚠️ Violations result in warnings → mute → ban.
"""

FAQ_TEXT = """
❓ *WBTC FAQ*

*Q: Is WBTC safe?*
A: WBTC is audited and reserves are verifiable on-chain.

*Q: How do I mint/redeem WBTC?*
A: Through authorized merchants listed at wbtc.network

*Q: Is WBTC the same as BTC?*
A: It tracks BTC 1:1 but lives on Ethereum.

*Q: What wallets support WBTC?*
A: Any ERC-20 compatible wallet (MetaMask, Ledger, etc.)

*Q: Where can I trade WBTC?*
A: Major DEXes (Uniswap, Curve) and CEXes (Binance, Coinbase).
"""

LINKS_TEXT = """
🔗 *Official WBTC Links*

🌐 Website: [wbtc.network](https://wbtc.network)
📊 CoinGecko: [WBTC](https://www.coingecko.com/en/coins/wrapped-bitcoin)
🦊 Contract: `0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599`
📁 GitHub: [github.com/WrappedBTC](https://github.com/WrappedBTC)
🐦 Twitter: [@WrappedBTC](https://twitter.com/WrappedBTC)
"""


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 About WBTC", callback_data="info_wbtc"),
         InlineKeyboardButton("📜 Rules", callback_data="info_rules")],
        [InlineKeyboardButton("❓ FAQ", callback_data="info_faq"),
         InlineKeyboardButton("🔗 Links", callback_data="info_links")],
        [InlineKeyboardButton("💰 Live Price", callback_data="info_price")],
    ])
    await update.message.reply_text(
        "ℹ️ *WBTC Bot Info Menu* — choose a topic:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_price(update.message.chat_id, context)


async def send_price(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": "wrapped-bitcoin,bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            }
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

        wbtc = data.get("wrapped-bitcoin", {})
        btc = data.get("bitcoin", {})

        wbtc_price = wbtc.get("usd", 0)
        wbtc_change = wbtc.get("usd_24h_change", 0)
        wbtc_mcap = wbtc.get("usd_market_cap", 0)
        btc_price = btc.get("usd", 0)

        arrow = "🟢 ▲" if wbtc_change >= 0 else "🔴 ▼"
        peg_diff = ((wbtc_price - btc_price) / btc_price * 100) if btc_price else 0

        msg = (
            f"💰 *WBTC Price*\n\n"
            f"Price: *${wbtc_price:,.2f}*\n"
            f"24h: {arrow} {abs(wbtc_change):.2f}%\n"
            f"Market Cap: ${wbtc_mcap:,.0f}\n"
            f"BTC Price: ${btc_price:,.2f}\n"
            f"Peg Diff: {peg_diff:+.4f}%\n\n"
            f"_Source: CoinGecko_"
        )
    except Exception as e:
        logger.error(f"Price fetch error: {e}")
        msg = "⚠️ Could not fetch price. Try again later."

    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_rules(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(RULES_TEXT, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def cmd_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(FAQ_TEXT, parse_mode=ParseMode.MARKDOWN)


async def cmd_links(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(LINKS_TEXT, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_info(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_adm = await is_chat_admin(update, context)
    text = (
        "🤖 *WBTC Admin Bot — Commands*\n\n"
        "📊 *Info Commands:*\n"
        "/price — Live WBTC price\n"
        "/info — Info menu\n"
        "/rules — Community rules\n"
        "/faq — Frequently asked questions\n"
        "/links — Official links\n"
    )
    if is_adm:
        text += (
            "\n🛡 *Admin Commands:*\n"
            "/ban — Ban a user (reply to their message)\n"
            "/unban <user_id> — Unban a user\n"
            "/mute [minutes] — Mute a user\n"
            "/unmute — Unmute a user\n"
            "/warn [reason] — Warn a user\n"
            "/warnings — Check user's warning count\n"
            "/del — Delete a message\n"
            "/announce <text> — Post an announcement\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ─── Callback Query Handler ───────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    handlers = {
        "info_wbtc": (WBTC_INFO, True),
        "info_rules": (RULES_TEXT, False),
        "info_faq": (FAQ_TEXT, False),
        "info_links": (LINKS_TEXT, False),
    }

    if query.data in handlers:
        text, preview = handlers[query.data]
        await query.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=not preview,
        )
    elif query.data == "info_price":
        await send_price(query.message.chat_id, context)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    # Info commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("info", cmd_info))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("rules", cmd_rules))
    app.add_handler(CommandHandler("faq", cmd_faq))
    app.add_handler(CommandHandler("links", cmd_links))

    # Admin commands
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("warnings", cmd_warnings))
    app.add_handler(CommandHandler("del", cmd_delete))
    app.add_handler(CommandHandler("announce", cmd_announce))

    # Inline buttons
    app.add_handler(CallbackQueryHandler(button_callback))

    # Welcome new members
    app.add_handler(ChatMemberHandler(welcome_new_member, ChatMemberHandler.CHAT_MEMBER))

    # Spam moderation (all text messages)
    app.add_handler(MessageHandler(filters.TEXT | filters.CAPTION, moderate_message))

    logger.info("🤖 WBTC Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
