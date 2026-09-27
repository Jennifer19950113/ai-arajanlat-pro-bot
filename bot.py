import os
import sqlite3
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "arajanlat.db"

# ============================================================
# TELEGRAM STARS ÁRAK
# ============================================================

PRO_STARS = 1000
PRO_PLUS_STARS = 3000

PRO_DAYS = 7
PRO_PLUS_DAYS = 30

SUBSCRIPTION_PERIOD = 2592000


# ============================================================
# RENDER WEB SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()
        self.wfile.write(
            b"AI Arjanlat Pro is running!"
        )

    def log_message(self, format, *args):
        pass


def run_web_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# ============================================================
# DATABASE
# ============================================================

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
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan TEXT,
            stars INTEGER,
            expires_at TEXT,
            is_recurring INTEGER DEFAULT 0,
            charge_id TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# AKTÍV ELŐFIZETÉS ELLENŐRZÉSE
# ============================================================

def get_active_subscription(user_id):

    now = datetime.now().isoformat()

    conn = sqlite3.connect(DB_FILE)

    row = conn.execute(
        """
        SELECT plan, stars, expires_at, is_recurring
        FROM subscriptions
        WHERE user_id = ?
        AND expires_at > ?
        ORDER BY expires_at DESC
        LIMIT 1
        """,
        (user_id, now)
    ).fetchone()

    conn.close()

    return row


async def require_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    subscription = get_active_subscription(user_id)

    if subscription:
        return True

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "💳 Előfizetések",
                callback_data="subscription"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Főmenü",
                callback_data="back_menu"
            )
        ],
    ])

    message = update.callback_query.message

    await message.edit_text(

        "🔒 Ez a funkció aktív előfizetéshez kötött.\n\n"

        "Az AI Árajánlat Pro használatához "
        "válassz egy előfizetést.\n\n"

        "🔵 PRO – 6 500 Ft / 7 nap\n"
        "🟣 PRO+ – 20 000 Ft / hó",

        reply_markup=keyboard
    )

    return False


# ============================================================
# FŐMENÜ
# ============================================================

def main_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📝 Új árajánlat",
                callback_data="new_quote"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 Ügyfeleim",
                callback_data="clients"
            )
        ],

        [
            InlineKeyboardButton(
                "📋 Ajánlataim",
                callback_data="quotes"
            )
        ],

        [
            InlineKeyboardButton(
                "🤖 AI Segítő",
                callback_data="ai"
            )
        ],

        [
            InlineKeyboardButton(
                "⚙️ Cégadatok",
                callback_data="company"
            )
        ],

        [
            InlineKeyboardButton(
                "💳 Előfizetésem",
                callback_data="subscription"
            )
        ],

        [
            InlineKeyboardButton(
                "🆘 Segítség",
                callback_data="help"
            )
        ],
    ])


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(

        "🤖 AI Árajánlat Pro\n\n"

        "Készíts professzionális árajánlatokat "
        "gyorsan és egyszerűen.\n\n"

        "Válassz az alábbi menüből:",

        reply_markup=main_keyboard()
    )


async def menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(
        "🤖 Főmenü",
        reply_markup=main_keyboard()
    )


async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(

        "❌ Az aktuális folyamat megszakítva.",

        reply_markup=main_keyboard()
    )


# ============================================================
# ÚJ ÁRAJÁNLAT
# ============================================================

async def new_quote(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if not await require_subscription(
        update,
        context
    ):
        return

    context.user_data.clear()

    context.user_data["quote_step"] = 1

    await query.edit_message_text(

        "📝 Új árajánlat\n\n"

        "1/8\n"
        "👤 Írd be az ügyfél nevét:"
    )


# ============================================================
# ÁRAJÁNLAT ADATBEVITEL
# ============================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    step = context.user_data.get("quote_step")

    if not step:
        return

    text = update.message.text.strip()


    # 1. NÉV
    if step == 1:

        context.user_data["name"] = text
        context.user_data["quote_step"] = 2

        await update.message.reply_text(

            "2/8\n"
            "📞 Írd be az ügyfél telefonszámát:"
        )

        return


    # 2. TELEFON
    if step == 2:

        context.user_data["phone"] = text
        context.user_data["quote_step"] = 3

        await update.message.reply_text(

            "3/8\n"
            "🏠 Írd be a munkavégzés címét:"
        )

        return


    # 3. CÍM
    if step == 3:

        context.user_data["address"] = text
        context.user_data["quote_step"] = 4

        await update.message.reply_text(

            "4/8\n"
            "🔨 Milyen munkát szeretne az ügyfél?"
        )

        return


    # 4. MUNKA
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


    # 5. MENNYISÉG
    if step == 5:

        context.user_data["quantity"] = text
        context.user_data["quote_step"] = 6

        await update.message.reply_text(

            "6/8\n"
            "💰 Add meg a munkadíjat forintban:"
        )

        return


    # 6. MUNKADÍJ
    if step == 6:

        context.user_data["price"] = text
        context.user_data["quote_step"] = 7

        await update.message.reply_text(

            "7/8\n"
            "🧱 Add meg az anyagköltséget forintban.\n\n"

            "Ha nincs anyagköltség, írd: 0"
        )

        return


    # 7. ANYAG
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


    # 8. HATÁRIDŐ
    if step == 8:

        context.user_data["deadline"] = text

        user_id = update.effective_user.id

        data = context.user_data

        # Biztonsági ellenőrzés még mentés előtt
        if not get_active_subscription(user_id):

            context.user_data.clear()

            await update.message.reply_text(

                "🔒 Az előfizetésed lejárt vagy nem aktív.\n\n"

                "Az árajánlat mentéséhez aktív "
                "előfizetés szükséges.",

                reply_markup=main_keyboard()
            )

            return

        conn = sqlite3.connect(DB_FILE)

        # ÜGYFÉL MENTÉSE
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

        # AJÁNLAT MENTÉSE
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

            "✅ Az árajánlat elkészült!\n\n"

            + quote,

            reply_markup=main_keyboard()
        )


# ============================================================
# ÜGYFELEIM
# ============================================================

async def clients(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if not await require_subscription(
        update,
        context
    ):
        return

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


# ============================================================
# AJÁNLATAIM
# ============================================================

async def quotes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if not await require_subscription(
        update,
        context
    ):
        return

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


# ============================================================
# AI SEGÍTŐ
# ============================================================

async def ai_helper(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if not await require_subscription(
        update,
        context
    ):
        return

    await query.edit_message_text(

        "🤖 AI Segítő\n\n"

        "Hamarosan itt kérhetsz segítséget az ajánlatok "
        "megfogalmazásához.\n\n"

        "Például:\n"

        "„Írj egy professzionális ajánlatot "
        "egy lakás festésére.”",

        reply_markup=main_keyboard()
    )


# ============================================================
# CÉGADATOK
# ============================================================

async def company(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if not await require_subscription(
        update,
        context
    ):
        return

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


# ============================================================
# ELŐFIZETÉS MENÜ
# ============================================================

async def subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🔵 PRO – 6 500 Ft / 7 nap",
                callback_data="buy_pro"
            )
        ],

        [
            InlineKeyboardButton(
                "🟣 PRO+ – 20 000 Ft / hó",
                callback_data="buy_pro_plus"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 Saját előfizetésem",
                callback_data="subscription_status"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Vissza",
                callback_data="back_menu"
            )
        ],
    ])

    await query.edit_message_text(

        "💳 AI Árajánlat Pro előfizetés\n\n"

        "🔵 PRO\n"
        "6 500 Ft / 7 nap\n"
        "⭐ 1 000 Stars\n\n"

        "🟣 PRO+\n"
        "20 000 Ft / hó\n"
        "⭐ 3 000 Stars\n\n"

        "Válaszd ki a csomagot:",

        reply_markup=keyboard
    )


# ============================================================
# PRO VÁSÁRLÁS
# ============================================================

async def buy_pro(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await context.bot.send_invoice(

        chat_id=update.effective_chat.id,

        title="AI Árajánlat Pro",

        description=(
            "PRO hozzáférés 7 napra. "
            "Árajánlatkészítés, ügyfél- és ajánlatkezelés."
        ),

        payload="PRO_7_DAYS",

        provider_token="",

        currency="XTR",

        prices=[
            LabeledPrice(
                "PRO – 7 nap",
                PRO_STARS
            )
        ],
    )


# ============================================================
# PRO+ VÁSÁRLÁS
# ============================================================

async def buy_pro_plus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await context.bot.send_invoice(

        chat_id=update.effective_chat.id,

        title="AI Árajánlat Pro+",

        description=(
            "PRO+ havi hozzáférés. "
            "Árajánlatkészítés, ügyfél- és ajánlatkezelés."
        ),

        payload="PRO_PLUS_MONTHLY",

        provider_token="",

        currency="XTR",

        prices=[
            LabeledPrice(
                "PRO+ – 30 nap",
                PRO_PLUS_STARS
            )
        ],

        subscription_period=SUBSCRIPTION_PERIOD
    )


# ============================================================
# ELŐFIZETÉS ÁLLAPOTA
# ============================================================

async def subscription_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    row = get_active_subscription(user_id)

    if not row:

        text = (
            "💳 Előfizetésem\n\n"
            "❌ Nincs aktív előfizetésed.\n\n"
            "Válassz egy csomagot a használathoz."
        )

    else:

        plan, stars, expires_at, recurring = row

        try:
            expires = datetime.fromisoformat(expires_at)
            formatted_date = expires.strftime(
                "%Y.%m.%d %H:%M"
            )
        except Exception:
            formatted_date = expires_at

        text = (

            "💳 Előfizetésem\n\n"

            f"📦 Csomag: {plan}\n"
            f"⭐ Fizetett Stars: {stars}\n"
            f"📅 Érvényes eddig: {formatted_date}\n"
        )

        if recurring:
            text += (
                "\n🔄 Automatikusan megújuló "
                "előfizetés."
            )

        else:
            text += (
                "\n📌 Egyszeri 7 napos "
                "hozzáférés."
            )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🛒 Csomagok",
                callback_data="subscription"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Vissza",
                callback_data="back_menu"
            )
        ],
    ])

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )


# ============================================================
# PRE-CHECKOUT
# ============================================================

async def precheckout_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.pre_checkout_query

    await query.answer(ok=True)


# ============================================================
# SIKERES FIZETÉS
# ============================================================

async def successful_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    payment = update.message.successful_payment

    user_id = update.effective_user.id

    payload = payment.invoice_payload

    stars = payment.total_amount

    charge_id = payment.telegram_payment_charge_id

    now = datetime.now()


    if payload == "PRO_7_DAYS":

        plan = "PRO"

        expires = now + timedelta(
            days=PRO_DAYS
        )

        recurring = 0


    elif payload == "PRO_PLUS_MONTHLY":

        plan = "PRO+"

        if payment.subscription_expiration_date:

            expires = payment.subscription_expiration_date

        else:

            expires = now + timedelta(
                days=PRO_PLUS_DAYS
            )

        recurring = 1


    else:

        await update.message.reply_text(
            "⚠️ Ismeretlen fizetési csomag."
        )

        return


    conn = sqlite3.connect(DB_FILE)

    conn.execute(

        """
        INSERT INTO subscriptions
        (
            user_id,
            plan,
            stars,
            expires_at,
            is_recurring,
            charge_id,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,

        (
            user_id,
            plan,
            stars,
            expires.isoformat(),
            recurring,
            charge_id,
            now.isoformat()
        )
    )

    conn.commit()
    conn.close()


    if recurring:

        renewal_text = (
            "🔄 Az előfizetés automatikusan megújul."
        )

    else:

        renewal_text = (
            "📅 A hozzáférés 7 napig aktív."
        )


    await update.message.reply_text(

        "🎉 Sikeres fizetés!\n\n"

        f"📦 Csomag: {plan}\n"
        f"⭐ Fizetett: {stars} Stars\n"
        f"📅 Érvényes eddig: "
        f"{expires.strftime('%Y.%m.%d %H:%M')}\n\n"

        f"{renewal_text}\n\n"

        "✅ Az előfizetésed aktiválva lett.",

        reply_markup=main_keyboard()
    )


# ============================================================
# TERMS
# ============================================================

async def terms(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "📄 Általános feltételek\n\n"

        "Az AI Árajánlat Pro digitális szolgáltatás.\n\n"

        "A szolgáltatás Telegramon keresztül érhető el.\n"

        "A vásárlás Telegram Stars használatával történik.\n\n"

        "PRO: 7 napos hozzáférés.\n"

        "PRO+: 30 napos, automatikusan megújuló "
        "előfizetés.\n\n"

        "A vásárlás előtt mindig ellenőrizd az "
        "aktuális csomagot és az árat."
    )


# ============================================================
# PAYMENT SUPPORT
# ============================================================

async def paysupport(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "🆘 Fizetési segítség\n\n"

        "Ha problémád van a fizetéssel vagy "
        "az előfizetéseddel, írj az "
        "AI Árajánlat Pro ügyfélszolgálatának."
    )


# ============================================================
# SEGÍTSÉG
# ============================================================

async def help_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(

        "🆘 Segítség\n\n"

        "📝 Új árajánlat – új ajánlat készítése.\n"
        "👥 Ügyfeleim – mentett ügyfelek.\n"
        "📋 Ajánlataim – korábbi ajánlatok.\n"
        "🤖 AI Segítő – AI segítség.\n"
        "⚙️ Cégadatok – vállalkozási adatok.\n"
        "💳 Előfizetés – PRO és PRO+.\n\n"

        "/terms – feltételek\n"
        "/paysupport – fizetési segítség",

        reply_markup=main_keyboard()
    )


# ============================================================
# VISSZA A FŐMENÜBE
# ============================================================

async def back_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(

        "🤖 Főmenü",

        reply_markup=main_keyboard()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN nincs beállítva."
        )

    init_db()

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )


    # ========================================================
    # PARANCSOK
    # ========================================================

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "menu",
            menu
        )
    )

    app.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    app.add_handler(
        CommandHandler(
            "terms",
            terms
        )
    )

    app.add_handler(
        CommandHandler(
            "paysupport",
            paysupport
        )
    )


    # ========================================================
    # ÁRAJÁNLAT
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            new_quote,
            pattern="^new_quote$"
        )
    )


    # ========================================================
    # ÜGYFELEK
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            clients,
            pattern="^clients$"
        )
    )


    # ========================================================
    # AJÁNLATOK
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            quotes,
            pattern="^quotes$"
        )
    )


    # ========================================================
    # AI
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            ai_helper,
            pattern="^ai$"
        )
    )


    # ========================================================
    # CÉGADATOK
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            company,
            pattern="^company$"
        )
    )


    # ========================================================
    # ELŐFIZETÉS
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            subscription,
            pattern="^subscription$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buy_pro,
            pattern="^buy_pro$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buy_pro_plus,
            pattern="^buy_pro_plus$"
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            subscription_status,
            pattern="^subscription_status$"
        )
    )


    # ========================================================
    # VISSZA
    # ========================================================

    app.add_handler(
        CallbackQueryHandler(
            back_menu,
            pattern="^back_menu$"
        )
    )


    # ========================================================
    # FIZETÉS
    # ========================================================

    app.add_handler(
        PreCheckoutQueryHandler(
            precheckout_callback
        )
    )

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )


    # ========================================================
    # SZÖVEGES ÜZENETEK
    # ========================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )


    # ========================================================
    # INDÍTÁS
    # ========================================================

    app.run_polling()


if __name__ == "__main__":
    main()
