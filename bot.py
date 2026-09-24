import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📝 Új árajánlat", callback_data="new_quote")],
        [InlineKeyboardButton("👥 Ügyfeleim", callback_data="clients")],
        [InlineKeyboardButton("📋 Ajánlataim", callback_data="quotes")],
        [InlineKeyboardButton("🤖 AI Segítő", callback_data="ai")],
        [InlineKeyboardButton("⚙️ Cégadatok", callback_data="company")],
        [InlineKeyboardButton("💳 Előfizetésem", callback_data="subscription")],
        [InlineKeyboardButton("🆘 Segítség", callback_data="help")],
    ]

    await update.message.reply_text(
        "🤖 AI Árajánlat Pro\n\n"
        "Készíts professzionális árajánlatokat gyorsan és egyszerűen.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    messages = {
        "new_quote": "📝 Új árajánlat\n\nHamarosan itt készíthetsz új árajánlatot.",
        "clients": "👥 Ügyfeleim\n\nItt kezelheted majd az ügyfeleidet.",
        "quotes": "📋 Ajánlataim\n\nItt találod majd a korábbi ajánlataidat.",
        "ai": "🤖 AI Segítő\n\nAz AI segít majd az ajánlatok elkészítésében.",
        "company": "⚙️ Cégadatok\n\nItt állíthatod be a vállalkozásod adatait.",
        "subscription": "💳 Előfizetés\n\nPRO – 5 000 Ft/hó\nPRO+ – 12 000 Ft/hó",
        "help": "🆘 Segítség\n\nVálaszd ki a menüből, amiben segítségre van szükséged.",
    }

    await query.edit_message_text(
        messages.get(query.data, "Ismeretlen menüpont.")
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN nincs beállítva.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
