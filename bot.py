import logging
import os
import json
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

# ── All config from environment variables ONLY — no hardcoded secrets ──────────
TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
SLACK_WEBHOOK   = os.environ["SLACK_WEBHOOK"]
CALENDAR_ID     = os.environ["CALENDAR_ID"]
FIXED_ATTENDEES = ["sherry.wang@tron.network", "nadia.song@wbtc.network"]
SGT             = pytz.timezone("Asia/Singapore")
BOOKING_START   = 10
BOOKING_END     = 20

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

ASK_TYPE, ASK_AMOUNT, ASK_WALLET, ASK_EMAIL, ASK_MERCHANT, ASK_DATE, ASK_TIME, ASK_CONFIRM = range(8)


def get_calendar_service():
    # Railway/cloud: paste full JSON contents into GOOGLE_CREDENTIALS env var
    # Local dev: set GOOGLE_CREDS_FILE to path of credentials.json
    raw = os.environ.get("GOOGLE_CREDENTIALS")
    if raw:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=["https://www.googleapis.com/auth/calendar"]
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            os.environ.get("GOOGLE_CREDS_FILE", "credentials.json"),
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
    return build("calendar", "v3", credentials=creds)


def create_calendar_event(data):
    service  = get_calendar_service()
    dt_start = data["datetime"]
    dt_end   = dt_start + timedelta(hours=1)
    attendees = [{"email": e} for e in FIXED_ATTENDEES]
    if data["email"].lower() not in [a["email"].lower() for a in attendees]:
        attendees.append({"email": data["email"]})
    event = {
        "summary": f"WBTC {data['type'].upper()} — {data['merchant']}",
        "description": (
            f"Request Type: {data['type'].upper()}\n"
            f"Merchant: {data['merchant']}\n"
            f"Amount: {data['amount']} BTC\n"
            f"Wallet: {data['wallet']}\n"
            f"Email: {data['email']}\n"
            f"Submitted via WBTC Support Bot"
        ),
        "start": {"dateTime": dt_start.isoformat(), "timeZone": "Asia/Singapore"},
        "end":   {"dateTime": dt_end.isoformat(),   "timeZone": "Asia/Singapore"},
        "attendees": attendees,
        "reminders": {"useDefault": False, "overrides": [
            {"method": "email", "minutes": 60},
            {"method": "popup", "minutes": 15},
        ]},
    }
    created = service.events().insert(
        calendarId=CALENDAR_ID, body=event, sendUpdates="all"
    ).execute()
    return created.get("htmlLink", "")


def send_slack(data, cal_link):
    emoji  = "🟢" if data["type"] == "mint" else "🔴"
    dt_str = data["datetime"].strftime("%d %b %Y, %I:%M %p SGT")
    requests.post(SLACK_WEBHOOK, json={"blocks": [
        {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} New WBTC {data['type'].upper()} Request", "emoji": True}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Merchant:*\n{data['merchant']}"},
            {"type": "mrkdwn", "text": f"*Type:*\n{data['type'].upper()}"},
            {"type": "mrkdwn", "text": f"*Amount:*\n{data['amount']} BTC"},
            {"type": "mrkdwn", "text": f"*Scheduled:*\n{dt_str}"},
            {"type": "mrkdwn", "text": f"*Wallet:*\n`{data['wallet']}`"},
            {"type": "mrkdwn", "text": f"*Email:*\n{data['email']}"},
        ]},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "View Calendar Event"},
             "url": cal_link, "style": "primary"}
        ]},
    ]}, timeout=10)


def date_keyboard():
    now, rows, row = datetime.now(SGT), [], []
    for i in range(1, 8):
        day = now + timedelta(days=i)
        row.append(InlineKeyboardButton(
            day.strftime("%a %d %b"), callback_data=f"date_{day.strftime('%Y-%m-%d')}"
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Cancel", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


def time_keyboard(date_str):
    rows, row = [], []
    for hour in range(BOOKING_START, BOOKING_END):
        row.append(InlineKeyboardButton(
            f"{hour:02d}:00", callback_data=f"time_{date_str}_{hour:02d}00"
        ))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("Back", callback_data="back_date"),
        InlineKeyboardButton("Cancel", callback_data="cancel"),
    ])
    return InlineKeyboardMarkup(rows)


async def entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").lower()
    for w in text.split():
        if w.startswith("@"):
            text = text.replace(w, "").strip()
    if "mint" in text:
        context.user_data["type"] = "mint"
        await update.message.reply_text("*WBTC MINT Request*\n\nPlease enter the *amount* (BTC):", parse_mode="Markdown")
        return ASK_AMOUNT
    if "burn" in text:
        context.user_data["type"] = "burn"
        await update.message.reply_text("*WBTC BURN Request*\n\nPlease enter the *amount* (BTC):", parse_mode="Markdown")
        return ASK_AMOUNT
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Mint", callback_data="type_mint"),
         InlineKeyboardButton("Burn", callback_data="type_burn")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ])
    await update.message.reply_text("*WBTC Support Bot*\n\nWhat would you like to do?", parse_mode="Markdown", reply_markup=kb)
    return ASK_TYPE


async def cb_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("Cancelled."); context.user_data.clear(); return ConversationHandler.END
    context.user_data["type"] = q.data.replace("type_", "")
    await q.edit_message_text(f"*WBTC {context.user_data['type'].upper()} Request*\n\nPlease enter the *amount* (BTC):", parse_mode="Markdown")
    return ASK_AMOUNT


async def got_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["amount"] = update.message.text.strip()
    await update.message.reply_text("Please enter your *wallet address*:", parse_mode="Markdown")
    return ASK_WALLET


async def got_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["wallet"] = update.message.text.strip()
    await update.message.reply_text("Please enter your *email address*:", parse_mode="Markdown")
    return ASK_EMAIL


async def got_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["email"] = update.message.text.strip()
    await update.message.reply_text("Please enter your *company / merchant name*:", parse_mode="Markdown")
    return ASK_MERCHANT


async def got_merchant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["merchant"] = update.message.text.strip()
    await update.message.reply_text("Select your *preferred date*:", parse_mode="Markdown", reply_markup=date_keyboard())
    return ASK_DATE


async def cb_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("Cancelled."); context.user_data.clear(); return ConversationHandler.END
    date_str = q.data.replace("date_", "")
    context.user_data["date"] = date_str
    await q.edit_message_text(f"Select a *time slot* for {date_str} (SGT):", parse_mode="Markdown", reply_markup=time_keyboard(date_str))
    return ASK_TIME


async def cb_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("Cancelled."); context.user_data.clear(); return ConversationHandler.END
    if q.data == "back_date":
        await q.edit_message_text("Select your *preferred date*:", parse_mode="Markdown", reply_markup=date_keyboard())
        return ASK_DATE
    _, date_str, time_str = q.data.split("_")
    hour = int(time_str[:2]); minute = int(time_str[2:])
    y, m, d = map(int, date_str.split("-"))
    context.user_data["datetime"] = SGT.localize(datetime(y, m, d, hour, minute))
    data   = context.user_data
    dt_str = data["datetime"].strftime("%d %b %Y, %I:%M %p SGT")
    summary = (
        f"*Confirm your request:*\n\n"
        f"*Type:*      {data['type'].upper()}\n"
        f"*Merchant:*  {data['merchant']}\n"
        f"*Amount:*    {data['amount']} BTC\n"
        f"*Wallet:*    `{data['wallet']}`\n"
        f"*Email:*     {data['email']}\n"
        f"*Date/Time:* {dt_str}\n"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Confirm", callback_data="confirm"),
        InlineKeyboardButton("Cancel",  callback_data="cancel"),
    ]])
    await q.edit_message_text(summary, parse_mode="Markdown", reply_markup=kb)
    return ASK_CONFIRM


async def cb_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("Cancelled."); context.user_data.clear(); return ConversationHandler.END
    await q.edit_message_text("Creating your calendar invite...")
    try:
        data = context.user_data
        link = create_calendar_event(data)
        send_slack(data, link)
        dt_str = data["datetime"].strftime("%d %b %Y, %I:%M %p SGT")
        await q.edit_message_text(
            f"*{data['type'].upper()} request booked!*\n\n"
            f"*{dt_str}*\n\n"
            f"Calendar invites sent to all attendees.\n"
            f"Our team will be in touch shortly.\n\n"
            f"[View Calendar Event]({link})",
            parse_mode="Markdown"
        )
    except Exception as e:
        import traceback
        logger.error(f"Event creation failed: {e}")
        logger.error(traceback.format_exc())
        await q.edit_message_text(f"Error: {str(e)[:300]}")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, entry)],
        states={
            ASK_TYPE:     [CallbackQueryHandler(cb_type)],
            ASK_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_amount)],
            ASK_WALLET:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_wallet)],
            ASK_EMAIL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_email)],
            ASK_MERCHANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_merchant)],
            ASK_DATE:     [CallbackQueryHandler(cb_date)],
            ASK_TIME:     [CallbackQueryHandler(cb_time)],
            ASK_CONFIRM:  [CallbackQueryHandler(cb_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
        per_chat=False,
        per_user=True,
        per_message=False,
    )
    app.add_handler(conv)
    logger.info("WBTC Bot running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
