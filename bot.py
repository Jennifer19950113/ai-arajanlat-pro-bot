import os
import threading
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "arajanlat.db"

NAME, PHONE, ADDRESS, WORK, QUANTITY, PRICE, MATERIAL, DEADLINE = range(8)


# =========================
# WEB SERVER – RENDER
# =========================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"AI Arjanlat Pro is running!")

    def log_message(self, format, *args):
        return


def run_web_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# =========================
# DATABASE
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            phone TEXT,
            address TEXT,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            client_name TEXT,
            phone TEXT,
            address TEXT,
            work TEXT,
            quantity TEXT,
            price TEXT,
            material TEXT,
            deadline TEXT,
            created_at TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS company (
            user_id INTEGER PRIMARY KEY,
            company_name TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            tax_number TEXT
        )
    """)

    conn.commit()
    conn.close()


# =========================
# MAIN MENU
# =========================

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Új ajánlat", callback_data="new_quote")],
        [InlineKeyboardButton("👥 Ügyfeleim", callback_data="clients")],
        [InlineKeyboardButton("📋 Ajánlataim", callback_data="quotes")],
        [InlineKeyboardButton("🤖 AI Segítő", callback_data="ai")],
        [InlineKeyboardButton("⚙️ Cégadatok", callback_data="company")],
        [InlineKeyboardButton("💳 Előfizetésem", callback_data="subscription")],
        [InlineKeyboardButton("🆘 Segítség", callback_data="help")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 AI Árajánlat Pro\n\n"
        "Készíts professzionális árajánlatokat gyorsan és egyszerűen.\n\n"
        "Válassz az alábbi menüből:",
        reply_markup=main_keyboard(),
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Főmenü",
        reply_markup=main_keyboard(),
    )


# =========================
# NEW QUOTE
# =========================

async def new_quote_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        "📝 Új árajánlat\n\n"
        "1/8\n"
        "Írd be az ügyfél nevét:"
    )

    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text

    await update.message.reply_text(
        "2/8\n"
        "📞 Írd be az ügyfél telefonszámát:"
    )

    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text

    await update.message.reply_text(
        "3/8\n"
        "🏠 Írd be a munkavégzés címét:"
    )

    return ADDRESS


async def get_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["address"] = update.message.text

    await update.message.reply_text(
        "4/8\n"
        "🔨 Milyen munkát szeretne az ügyfél?"
    )

    return WORK


async def get_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["work"] = update.message.text

    await update.message.reply_text(
        "5/8\n"
        "📐 Add meg a mennyiséget.\n\n"
        "Például: 80 m², 5 db, 120 folyóméter.\n"
        "Ha nincs mennyiség, írd azt: nincs."
    )

    return QUANTITY


async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quantity"] = update.message.text

    await update.message.reply_text(
        "6/8\n"
        "💰 Add meg a munkadíjat forintban:"
    )

    return PRICE


async def get_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["price"] = update.message.text

    await update.message.reply_text(
        "7/8\n"
        "🧱 Add meg az anyagköltséget forintban.\n"
        "Ha nincs anyagköltség, írd: 0"
    )

    return MATERIAL


async def get_material(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["material"] = update.message.text

    await update.message.reply_text(
        "8/8\n"
        "📅 Mikorra vállalható a munka?\n\n"
        "Például: 2026. október 10."
    )

    return DEADLINE


async def get_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deadline"] = update.message.text

    data = context.user_data
    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        INSERT INTO clients
        (user_id, name, phone, address, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        data["name"],
        data["phone"],
        data["address"],
        datetime.now().isoformat()
    ))

    conn.execute("""
        INSERT INTO quotes
        (user_id, client_name, phone, address, work,
         quantity, price, material, deadline, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        data["name"],
        data["phone"],
        data["address"],
        data["work"],
        data["quantity"],
        data["price"],
        data["material"],
        data["deadline"],
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()

    quote_text = (
        "📋 **ÁRAJÁNLAT**\n\n"
        f"👤 Ügyfél: {data['name']}\n"
        f"📞 Telefon: {data['phone']}\n"
        f"🏠 Helyszín: {data['address']}\n\n"
        f"🔨 Munka: {data['work']}\n"
        f"📐 Mennyiség: {data['quantity']}\n"
        f"💰 Munkadíj: {data['price']} Ft\n"
        f"🧱 Anyagköltség: {data['material']} Ft\n"
        f"📅 Határidő: {data['deadline']}\n\n"
        "━━━━━━━━━━━━━━\n"
        "🤖 Készült az AI Árajánlat Pro segítségével."
    )

    await update.message.reply_text(
        quote_text,
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )

    context.user_data.clear()

    return ConversationHandler.END


async def cancel_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Az árajánlat készítése megszakítva.",
        reply_markup=main_keyboard(),
    )

    return ConversationHandler.END


# =========================
# CLIENTS
# =========================

async def show_clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT name, phone, address
        FROM clients
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (user_id,)).fetchall()
    conn.close()

    if not rows:
        text = (
            "👥 Ügyfeleim\n\n"
            "Még nincs mentett ügyfeled.\n\n"
            "Az első ügyfelet az 📝 Új ajánlat menüponttal tudod hozzáadni."
        )
    else:
        text = "👥 Ügyfeleim\n\n"

        for i, row in enumerate(rows, 1):
            text += (
                f"{i}. {row[0]}\n"
                f"📞 {row[1]}\n"
                f"🏠 {row[2]}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(),
    )


# =========================
# QUOTES
# =========================

async def show_quotes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute("""
        SELECT client_name, work, price, material, created_at
        FROM quotes
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
    """, (user_id,)).fetchall()
    conn.close()

    if not rows:
        text = (
            "📋 Ajánlataim\n\n"
            "Még nincs elkészített ajánlatod."
        )
    else:
        text = "📋 Ajánlataim\n\n"

        for i, row in enumerate(rows, 1):
            text += (
                f"{i}. {row[0]}\n"
                f"🔨 {row[1]}\n"
                f"💰 Munkadíj: {row[2]} Ft\n"
                f"🧱 Anyag: {row[3]} Ft\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(),
    )


# =========================
# COMPANY DATA
# =========================

async def show_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("""
        SELECT company_name, phone, email, address, tax_number
        FROM company
        WHERE user_id = ?
    """, (user_id,)).fetchone()
    conn.close()

    if row:
        text = (
            "⚙️ Cégadatok\n\n"
            f"🏢 Cégnév: {row[0]}\n"
            f"📞 Telefon: {row[1]}\n"
            f"📧 E-mail: {row[2]}\n"
            f"🏠 Cím: {row[3]}\n"
            f"🧾 Adószám: {row[4]}"
        )
    else:
        text = (
            "⚙️ Cégadatok\n\n"
            "Még nincsenek beállítva cégadataid.\n\n"
            "Ezt a funkciót a következő fejlesztésben tesszük teljesen szerkeszthetővé."
        )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard(),
    )


# =========================
# OTHER MENU ITEMS
# =========================

async def show_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🤖 AI Segítő\n\n"
        "Az AI Segítő segítségével később automatikusan "
        "megfogalmazhatod és javíthatod az ajánlataidat.\n\n"
        "Például:\n"
        "„Írj egy professzionális ajánlatot egy 80 m²-es lakás festésére.”",
        reply_markup=main_keyboard(),
    )


async def show_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💳 Előfizetés\n\n"
        "🔵 PRO – 5 000 Ft / hó\n"
        "Árajánlatok és ügyfélkezelés.\n\n"
        "🟣 PRO+ – 12 000 Ft / hó\n"
        "Haladó AI funkciók és extra lehetőségek.\n\n"
        "A fizetési rendszer hamarosan elérhető.",
        reply_markup=main_keyboard(),
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🆘 Segítség\n\n"
        "📝 Új ajánlat – készíts új árajánlatot.\n"
        "👥 Ügyfeleim – megtekintheted a mentett ügyfeleket.\n"
        "📋 Ajánlataim – megtekintheted a korábbi ajánlatokat.\n"
        "🤖 AI Segítő – AI-alapú segítség.\n"
        "⚙️ Cégadatok – vállalkozási adatok.\n"
        "💳 Előfizetés – PRO és PRO+ csomagok.",
        reply_markup=main_keyboard(),
    )


# =========================
# MAIN
# =========================

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN nincs beállítva.")

    init_db()

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    app = Application.builder().token(BOT_TOKEN).build()

    quote_conversation = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                new_quote_start,
                pattern="^new_quote$"
            )
        ],
        states={
            NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)
            ],
            PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)
            ],
            ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_address)
            ],
            WORK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_work)
            ],
            QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)
            ],
            PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_price)
            ],
            MATERIAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_material)
            ],
            DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_deadline)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_quote)
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(quote_conversation)

    app.add_handler(
        CallbackQueryHandler(show_clients, pattern="^clients$")
    )
    app.add_handler(
        CallbackQueryHandler(show_quotes, pattern="^quotes$")
    )
    app.add_handler(
        CallbackQueryHandler(show_ai, pattern="^ai$")
    )
    app.add_handler(
        CallbackQueryHandler(show_company, pattern="^company$")
    )
    app.add_handler(
        CallbackQueryHandler(show_subscription, pattern="^subscription$")
    )
    app.add_handler(
        CallbackQueryHandler(show_help, pattern="^help$")
    )

    app.run_polling()


if __name__ == "__main__":
    main()
