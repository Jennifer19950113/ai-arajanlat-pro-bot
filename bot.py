import os
import sqlite3
import threading
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
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "arajanlat.db"


# =========================
# RENDER WEB SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"AI Arjanlat Pro is running!")

    def log_message(self, format, *args):
        pass


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

    conn.commit()
    conn.close()


# =========================
# MAIN MENU
# =========================

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Új árajánlat", callback_data="new_quote")],
        [InlineKeyboardButton("👥 Ügyfeleim", callback_data="clients")],
        [InlineKeyboardButton("📋 Ajánlataim", callback_data="quotes")],
        [InlineKeyboardButton("🤖 AI Segítő", callback_data="ai")],
        [InlineKeyboardButton("⚙️ Cégadatok", callback_data="company")],
        [InlineKeyboardButton("💳 Előfizetésem", callback_data="subscription")],
        [InlineKeyboardButton("🆘 Segítség", callback_data="help")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🤖 AI Árajánlat Pro\n\n"
        "Készíts professzionális árajánlatokat gyorsan és egyszerűen.\n\n"
        "Válassz az alábbi menüből:",
        reply_markup=main_keyboard()
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "🤖 Főmenü",
        reply_markup=main_keyboard()
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    await update.message.reply_text(
        "❌ Az aktuális folyamat megszakítva.",
        reply_markup=main_keyboard()
    )


# =========================
# ÚJ ÁRAJÁNLAT INDÍTÁSA
# =========================

async def new_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data.clear()
    context.user_data["quote_step"] = 1

    await query.edit_message_text(
        "📝 Új árajánlat\n\n"
        "1/8\n"
        "👤 Írd be az ügyfél nevét:"
    )


# =========================
# ÁRAJÁNLAT ADATBEVITEL
# =========================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    step = context.user_data.get("quote_step")

    if not step:
        return

    text = update.message.text.strip()

    # 1. Ügyfél neve
    if step == 1:
        context.user_data["name"] = text
        context.user_data["quote_step"] = 2

        await update.message.reply_text(
            "2/8\n"
            "📞 Írd be az ügyfél telefonszámát:"
        )
        return

    # 2. Telefonszám
    if step == 2:
        context.user_data["phone"] = text
        context.user_data["quote_step"] = 3

        await update.message.reply_text(
            "3/8\n"
            "🏠 Írd be a munkavégzés címét:"
        )
        return

    # 3. Cím
    if step == 3:
        context.user_data["address"] = text
        context.user_data["quote_step"] = 4

        await update.message.reply_text(
            "4/8\n"
            "🔨 Milyen munkát szeretne az ügyfél?"
        )
        return

    # 4. Munka
    if step == 4:
        context.user_data["work"] = text
        context.user_data["quote_step"] = 5

        await update.message.reply_text(
            "5/8\n"
            "📐 Add meg a mennyiséget.\n\n"
            "Például:\n"
            "80 m²\n"
            "5 db\n"
            "120 folyóméter\n\n"
            "Ha nincs mennyiség, írd: nincs"
        )
        return

    # 5. Mennyiség
    if step == 5:
        context.user_data["quantity"] = text
        context.user_data["quote_step"] = 6

        await update.message.reply_text(
            "6/8\n"
            "💰 Add meg a munkadíjat forintban:"
        )
        return

    # 6. Munkadíj
    if step == 6:
        context.user_data["price"] = text
        context.user_data["quote_step"] = 7

        await update.message.reply_text(
            "7/8\n"
            "🧱 Add meg az anyagköltséget forintban.\n\n"
            "Ha nincs anyagköltség, írd: 0"
        )
        return

    # 7. Anyagköltség
    if step == 7:
        context.user_data["material"] = text
        context.user_data["quote_step"] = 8

        await update.message.reply_text(
            "8/8\n"
            "📅 Mikorra vállalható a munka?\n\n"
            "Például:\n"
            "2026. október 10."
        )
        return

    # 8. Határidő
    if step == 8:

        context.user_data["deadline"] = text

        user_id = update.effective_user.id
        data = context.user_data

        # Mentés adatbázisba
        conn = sqlite3.connect(DB_FILE)

        conn.execute(
            """
            INSERT INTO clients
            (user_id, name, phone, address, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                data["name"],
                data["phone"],
                data["address"],
                datetime.now().isoformat()
            )
        )

        conn.execute(
            """
            INSERT INTO quotes
            (
                user_id,
                client_name,
                phone,
                address,
                work,
                quantity,
                price,
                material,
                deadline,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
            )
        )

        conn.commit()
        conn.close()

        quote = (
            "📋 ÁRAJÁNLAT\n\n"
            f"👤 Ügyfél: {data['name']}\n"
            f"📞 Telefon: {data['phone']}\n"
            f"🏠 Munkavégzés helye: {data['address']}\n\n"
            f"🔨 Munka: {data['work']}\n"
            f"📐 Mennyiség: {data['quantity']}\n"
            f"💰 Munkadíj: {data['price']} Ft\n"
            f"🧱 Anyagköltség: {data['material']} Ft\n"
            f"📅 Határidő: {data['deadline']}\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "AI Árajánlat Pro"
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Az árajánlat elkészült!\n\n" + quote,
            reply_markup=main_keyboard()
        )


# =========================
# ÜGYFELEIM
# =========================

async def clients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)

    rows = conn.execute(
        """
        SELECT name, phone, address
        FROM clients
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:
        text = (
            "👥 Ügyfeleim\n\n"
            "Még nincs mentett ügyfeled."
        )
    else:
        text = "👥 Ügyfeleim\n\n"

        for number, row in enumerate(rows, 1):
            text += (
                f"{number}. {row[0]}\n"
                f"📞 {row[1]}\n"
                f"🏠 {row[2]}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard()
    )


# =========================
# AJÁNLATAIM
# =========================

async def quotes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = sqlite3.connect(DB_FILE)

    rows = conn.execute(
        """
        SELECT client_name, work, price, material
        FROM quotes
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 20
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:
        text = (
            "📋 Ajánlataim\n\n"
            "Még nincs elkészített ajánlatod."
        )
    else:
        text = "📋 Ajánlataim\n\n"

        for number, row in enumerate(rows, 1):
            text += (
                f"{number}. {row[0]}\n"
                f"🔨 {row[1]}\n"
                f"💰 Munkadíj: {row[2]} Ft\n"
                f"🧱 Anyag: {row[3]} Ft\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_keyboard()
    )


# =========================
# AI SEGÍTŐ
# =========================

async def ai_helper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🤖 AI Segítő\n\n"
        "Hamarosan itt kérhetsz segítséget az ajánlatok "
        "megfogalmazásához.\n\n"
        "Például:\n"
        "„Írj egy professzionális ajánlatot egy lakás festésére.”",
        reply_markup=main_keyboard()
    )


# =========================
# CÉGADATOK
# =========================

async def company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "⚙️ Cégadatok\n\n"
        "Itt lesznek megadhatók a vállalkozásod adatai:\n\n"
        "🏢 Cégnév\n"
        "📞 Telefonszám\n"
        "📧 E-mail\n"
        "🏠 Cím\n"
        "🧾 Adószám\n\n"
        "A szerkesztést a következő fejlesztésben adjuk hozzá.",
        reply_markup=main_keyboard()
    )


# =========================
# ELŐFIZETÉS
# =========================

async def subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💳 Előfizetés\n\n"
        "🔵 PRO – 5 000 Ft / hó\n\n"
        "🟣 PRO+ – 12 000 Ft / hó\n\n"
        "A fizetési rendszer hamarosan elérhető.",
        reply_markup=main_keyboard()
    )


# =========================
# SEGÍTSÉG
# =========================

async def help_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🆘 Segítség\n\n"
        "📝 Új árajánlat – új ajánlat készítése.\n"
        "👥 Ügyfeleim – mentett ügyfelek.\n"
        "📋 Ajánlataim – korábbi ajánlatok.\n"
        "🤖 AI Segítő – AI segítség.\n"
        "⚙️ Cégadatok – vállalkozási adatok.\n"
        "💳 Előfizetés – PRO és PRO+.",
        reply_markup=main_keyboard()
    )


# =========================
# MAIN
# =========================

def main():

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN nincs beállítva.")

    init_db()

    # Render port
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # Parancsok
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("cancel", cancel))

    # Gombok
    app.add_handler(
        CallbackQueryHandler(new_quote, pattern="^new_quote$")
    )

    app.add_handler(
        CallbackQueryHandler(clients, pattern="^clients$")
    )

    app.add_handler(
        CallbackQueryHandler(quotes, pattern="^quotes$")
    )

    app.add_handler(
        CallbackQueryHandler(ai_helper, pattern="^ai$")
    )

    app.add_handler(
        CallbackQueryHandler(company, pattern="^company$")
    )

    app.add_handler(
        CallbackQueryHandler(subscription, pattern="^subscription$")
    )

    app.add_handler(
        CallbackQueryHandler(help_menu, pattern="^help$")
    )

    # Minden szöveges válasz kezelése
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
