# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv

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
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# BEÁLLÍTÁSOK
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

APP_TITLE = "🤖 AI Árajánlat Pro"
APP_SUBTITLE = (
    "Készíts professzionális árajánlatokat "
    "gyorsan és egyszerűen."
)

DB_PATH = "ai_arajanlat_pro.db"

PRO_DAYS = 7
PRO_PLUS_DAYS = 30

PRO_STARS = 1000
PRO_PLUS_STARS = 3000

SUBSCRIPTION_PERIOD = 2592000


# ============================================================
# WEB / HEALTH CHECK
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()

        self.wfile.write(
            b"AI Arjanlat Pro OK"
        )

    def log_message(self, format, *args):
        return


def run_web_server():

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    server = HTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(
        f"Health server started on port {port}"
    )

    server.serve_forever()


# ============================================================
# ADATBÁZIS
# ============================================================

def db():

    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clients(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quotes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            client_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            work TEXT NOT NULL,
            quantity TEXT NOT NULL,
            price REAL NOT NULL,
            material REAL NOT NULL,
            total REAL NOT NULL,
            deadline TEXT NOT NULL,
            quote_number TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan TEXT NOT NULL,
            stars INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            is_recurring INTEGER DEFAULT 0,
            charge_id TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS company_data(
            user_id INTEGER PRIMARY KEY,
            company_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            address TEXT NOT NULL,
            tax_number TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.commit()

    # Régi adatbázisokhoz szükséges oszlopok
    quote_columns = conn.execute(
        "PRAGMA table_info(quotes)"
    ).fetchall()

    quote_column_names = [
        row["name"]
        for row in quote_columns
    ]

    if "total" not in quote_column_names:
        conn.execute(
            "ALTER TABLE quotes ADD COLUMN total REAL DEFAULT 0"
        )

    if "quote_number" not in quote_column_names:
        conn.execute(
            "ALTER TABLE quotes ADD COLUMN quote_number TEXT DEFAULT ''"
        )

    conn.commit()
    conn.close()


def now_str():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# SEGÉDFÜGGVÉNYEK
# ============================================================

def parse_number(value):

    value = str(value).strip()

    value = value.replace("Ft", "")
    value = value.replace("ft", "")
    value = value.replace(" ", "")
    value = value.replace(".", "")
    value = value.replace(",", ".")

    return float(value)


def money(value):

    try:
        number = float(value)
    except Exception:
        number = 0

    if number.is_integer():

        return (
            f"{int(number):,}"
            .replace(",", " ")
            + " Ft"
        )

    return (
        f"{number:,.2f}"
        .replace(",", " ")
        + " Ft"
    )


def safe_html(text):

    text = str(text)

    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def next_quote_number(user_id):

    conn = db()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM quotes
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()[0]

    conn.close()

    return (
        "AJ-"
        + datetime.now().strftime("%Y")
        + "-"
        + f"{count + 1:04d}"
    )


# ============================================================
# ELŐFIZETÉS
# ============================================================

def get_active_subscription(user_id):

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM subscriptions
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    if not row:
        return None

    try:
        expires = datetime.fromisoformat(
            row["expires_at"]
        )
    except Exception:
        return None

    if expires <= datetime.now():
        return None

    return row


def subscription_text(user_id):

    subscription = get_active_subscription(
        user_id
    )

    if not subscription:
        return (
            "❌ Nincs aktív előfizetésed."
        )

    try:
        expires = datetime.fromisoformat(
            subscription["expires_at"]
        )

        expires_text = expires.strftime(
            "%Y.%m.%d. %H:%M"
        )

    except Exception:

        expires_text = subscription[
            "expires_at"
        ]

    return (
        "✅ Aktív előfizetés\n\n"
        f"📦 Csomag: {subscription['plan']}\n"
        f"📅 Érvényes eddig: {expires_text}"
    )


async def require_subscription(
    update,
    context
):

    user_id = update.effective_user.id

    if get_active_subscription(user_id):
        return True

    text = (
        "🔒 Ez a funkció aktív előfizetéshez kötött.\n\n"
        "Az AI Árajánlat Pro használatához "
        "válassz egy előfizetést."
    )

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
                callback_data="buy_plus"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Főmenü",
                callback_data="menu"
            )
        ]
    ])

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )

    elif update.message:

        await update.message.reply_text(
            text,
            reply_markup=keyboard
        )

    return False


# ============================================================
# CÉGADATOK
# ============================================================

def parse_company_data(text):

    data = {
        "company_name": "",
        "phone": "",
        "email": "",
        "address": "",
        "tax_number": "",
    }

    for line in text.splitlines():

        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip().lower()
        value = value.strip()

        if "cégnév" in key or "cegnev" in key:
            data["company_name"] = value

        elif (
            "telefonszám" in key
            or "telefonszam" in key
            or "telefon" in key
        ):
            data["phone"] = value

        elif "e-mail" in key or "email" in key:
            data["email"] = value

        elif "cím" in key or "cim" in key:
            data["address"] = value

        elif "adószám" in key or "adoszam" in key:
            data["tax_number"] = value

    return data


def get_company_data(user_id):

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM company_data
        WHERE user_id=?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    return dict(row) if row else None


def save_company_data(user_id, data):

    conn = db()

    conn.execute(
        """
        INSERT INTO company_data(
            user_id,
            company_name,
            phone,
            email,
            address,
            tax_number,
            updated_at
        )
        VALUES(?,?,?,?,?,?,?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            company_name=excluded.company_name,
            phone=excluded.phone,
            email=excluded.email,
            address=excluded.address,
            tax_number=excluded.tax_number,
            updated_at=excluded.updated_at
        """,
        (
            user_id,
            data["company_name"],
            data["phone"],
            data["email"],
            data["address"],
            data["tax_number"],
            now_str()
        )
    )

    conn.commit()
    conn.close()


def company_display(data):

    return (
        f"🏢 Cégnév: {safe_html(data['company_name'])}\n"
        f"📞 Telefon: {safe_html(data['phone'])}\n"
        f"📧 E-mail: {safe_html(data['email'])}\n"
        f"🏠 Cím: {safe_html(data['address'])}\n"
        f"🧾 Adószám: {safe_html(data['tax_number'])}"
    )


# ============================================================
# ÜGYFELEK
# ============================================================

def save_or_update_client(
    user_id,
    name,
    phone,
    address
):

    conn = db()

    existing = conn.execute(
        """
        SELECT id
        FROM clients
        WHERE user_id=?
        AND phone=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            user_id,
            phone
        )
    ).fetchone()

    if existing:

        conn.execute(
            """
            UPDATE clients
            SET name=?,
                phone=?,
                address=?,
                created_at=?
            WHERE id=?
            """,
            (
                name,
                phone,
                address,
                now_str(),
                existing["id"]
            )
        )

        client_id = existing["id"]

    else:

        cursor = conn.execute(
            """
            INSERT INTO clients(
                user_id,
                name,
                phone,
                address,
                created_at
            )
            VALUES(?,?,?,?,?)
            """,
            (
                user_id,
                name,
                phone,
                address,
                now_str()
            )
        )

        client_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return client_id


def get_client(
    user_id,
    client_id
):

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM clients
        WHERE id=?
        AND user_id=?
        """,
        (
            client_id,
            user_id
        )
    ).fetchone()

    conn.close()

    return row


async def clients_menu(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM clients
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 30
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await query.edit_message_text(
            "👥 Még nincs mentett ügyfeled.\n\n"
            "Amikor elkészítesz egy új ajánlatot, "
            "az ügyfél automatikusan elmentésre kerül.",
            reply_markup=back_keyboard()
        )

        return

    buttons = []

    for row in rows:

        buttons.append([
            InlineKeyboardButton(
                f"👤 {row['name']}",
                callback_data=f"client:{row['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ Főmenü",
            callback_data="menu"
        )
    ])

    await query.edit_message_text(
        "👥 <b>Ügyfeleim</b>\n\n"
        "Válassz egy ügyfelet:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def client_detail(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query
    await query.answer()

    client_id = int(
        query.data.split(":")[1]
    )

    user_id = update.effective_user.id

    row = get_client(
        user_id,
        client_id
    )

    if not row:

        await query.edit_message_text(
            "❌ Az ügyfél nem található.",
            reply_markup=back_keyboard()
        )

        return

    text = (
        "👤 <b>Ügyfél adatai</b>\n\n"
        f"👤 Név: {safe_html(row['name'])}\n"
        f"📞 Telefon: {safe_html(row['phone'])}\n"
        f"🏠 Cím: {safe_html(row['address'])}"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📝 Új ajánlat ezzel az ügyféllel",
                callback_data=f"client_quote:{client_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "✏️ Ügyfél adatainak módosítása",
                callback_data=f"client_edit:{client_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Ügyfeleim",
                callback_data="clients"
            )
        ]

    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def client_quote(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query
    await query.answer()

    client_id = int(
        query.data.split(":")[1]
    )

    user_id = update.effective_user.id

    row = get_client(
        user_id,
        client_id
    )

    if not row:

        await query.edit_message_text(
            "❌ Az ügyfél nem található.",
            reply_markup=back_keyboard()
        )

        return

    context.user_data.clear()

    context.user_data["state"] = "quote:work"
    context.user_data["name"] = row["name"]
    context.user_data["phone"] = row["phone"]
    context.user_data["address"] = row["address"]
    context.user_data["client_id"] = client_id

    await query.edit_message_text(
        "📝 <b>Új ajánlat</b>\n\n"
        "Az ügyfél adatai automatikusan betöltődtek.\n\n"
        f"👤 {safe_html(row['name'])}\n"
        f"📞 {safe_html(row['phone'])}\n"
        f"🏠 {safe_html(row['address'])}\n\n"
        "4/8 🛠️ Milyen munkára készül az ajánlat?",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


async def client_edit(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query
    await query.answer()

    client_id = int(
        query.data.split(":")[1]
    )

    user_id = update.effective_user.id

    row = get_client(
        user_id,
        client_id
    )

    if not row:

        await query.edit_message_text(
            "❌ Az ügyfél nem található.",
            reply_markup=back_keyboard()
        )

        return

    context.user_data.clear()

    context.user_data["state"] = "client_edit:name"
    context.user_data["edit_client_id"] = client_id
    context.user_data["edit_client_name"] = row["name"]
    context.user_data["edit_client_phone"] = row["phone"]
    context.user_data["edit_client_address"] = row["address"]

    await query.edit_message_text(
        "✏️ <b>Ügyfél módosítása</b>\n\n"
        f"Jelenlegi név: <b>{safe_html(row['name'])}</b>\n\n"
        "Írd be az új nevet.\n"
        "Ha nem akarod módosítani, írd be: <b>-</b>",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


async def handle_client_edit(
    update,
    context,
    state
):

    text = update.message.text.strip()

    field = state.split(":", 1)[1]

    if field == "name":

        if text != "-":
            context.user_data["edit_client_name"] = text

        context.user_data["state"] = "client_edit:phone"

        await update.message.reply_text(
            "📞 <b>Telefonszám</b>\n\n"
            f"Jelenlegi: {safe_html(context.user_data['edit_client_phone'])}\n\n"
            "Írd be az új telefonszámot, vagy <b>-</b>.",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

        return

    if field == "phone":

        if text != "-":
            context.user_data["edit_client_phone"] = text

        context.user_data["state"] = "client_edit:address"

        await update.message.reply_text(
            "🏠 <b>Cím</b>\n\n"
            f"Jelenlegi: {safe_html(context.user_data['edit_client_address'])}\n\n"
            "Írd be az új címet, vagy <b>-</b>.",
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

        return

    if field == "address":

        if text != "-":
            context.user_data["edit_client_address"] = text

        client_id = context.user_data[
            "edit_client_id"
        ]

        conn = db()

        conn.execute(
            """
            UPDATE clients
            SET name=?,
                phone=?,
                address=?
            WHERE id=?
            AND user_id=?
            """,
            (
                context.user_data["edit_client_name"],
                context.user_data["edit_client_phone"],
                context.user_data["edit_client_address"],
                client_id,
                update.effective_user.id
            )
        )

        conn.commit()
        conn.close()

        name = context.user_data["edit_client_name"]

        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>Ügyfél adatai frissítve!</b>\n\n"
            f"👤 {safe_html(name)}",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )


# ============================================================
# PDF
# ============================================================

def create_pdf(quote, company, path):

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import (
        getSampleStyleSheet,
        ParagraphStyle,
    )
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.units import mm

    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font = "Helvetica"

    font_paths = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "DejaVuSans"
        ),
        (
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "LiberationSans"
        ),
    ]

    for font_path, font_name in font_paths:

        if os.path.exists(font_path):

            try:

                pdfmetrics.registerFont(
                    TTFont(
                        font_name,
                        font_path
                    )
                )

                font = font_name

                break

            except Exception:
                pass

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontName=font,
        fontSize=20,
        alignment=TA_CENTER,
        spaceAfter=8,
    )

    normal = ParagraphStyle(
        "normal",
        parent=styles["Normal"],
        fontName=font,
        fontSize=9,
        leading=13,
    )

    right = ParagraphStyle(
        "right",
        parent=normal,
        alignment=TA_RIGHT,
    )

    total_style = ParagraphStyle(
        "total",
        parent=right,
        fontName=font,
        fontSize=13,
    )

    story = [
        Paragraph(
            "ÁRAJÁNLAT",
            title_style
        )
    ]

    company_block = (
        f"<b>{safe_html(company['company_name'])}</b><br/>"
        f"{safe_html(company['address'])}<br/>"
        f"Tel.: {safe_html(company['phone'])}<br/>"
        f"E-mail: {safe_html(company['email'])}<br/>"
        f"Adószám: {safe_html(company['tax_number'])}"
    )

    customer_block = (
        "<b>Ügyfél</b><br/>"
        f"{safe_html(quote['client_name'])}<br/>"
        f"Tel.: {safe_html(quote['phone'])}<br/>"
        f"Cím: {safe_html(quote['address'])}"
    )

    info = Table(
        [[
            Paragraph(
                company_block,
                normal
            ),
            Paragraph(
                customer_block,
                normal
            )
        ]],
        colWidths=[
            90 * mm,
            75 * mm
        ]
    )

    info.setStyle(
        TableStyle([
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "BOX",
                (0, 0),
                (-1, -1),
                .5,
                colors.grey
            ),
            (
                "INNERGRID",
                (0, 0),
                (-1, -1),
                .25,
                colors.lightgrey
            ),
            (
                "PADDING",
                (0, 0),
                (-1, -1),
                7
            ),
        ])
    )

    story.append(info)
    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            f"Ajánlatszám: "
            f"<b>{safe_html(quote['quote_number'])}</b>"
            f"&nbsp;&nbsp;"
            f"Dátum: {safe_html(quote['created_at'])}",
            normal
        )
    )

    story.append(Spacer(1, 8))

    rows = [
        [
            Paragraph("Munka", normal),
            Paragraph("Mennyiség", normal),
            Paragraph("Munkadíj", normal),
            Paragraph("Anyag", normal),
            Paragraph("Összesen", normal),
        ],
        [
            Paragraph(
                safe_html(quote["work"]),
                normal
            ),
            Paragraph(
                safe_html(quote["quantity"]),
                normal
            ),
            Paragraph(
                money(quote["price"]),
                right
            ),
            Paragraph(
                money(quote["material"]),
                right
            ),
            Paragraph(
                money(quote["total"]),
                right
            ),
        ],
    ]

    table = Table(
        rows,
        colWidths=[
            60 * mm,
            25 * mm,
            27 * mm,
            27 * mm,
            27 * mm,
        ],
        repeatRows=1
    )

    table.setStyle(
        TableStyle([
            (
                "BACKGROUND",
                (0, 0),
                (-1, 0),
                colors.HexColor("#eeeeee")
            ),
            (
                "GRID",
                (0, 0),
                (-1, -1),
                .5,
                colors.grey
            ),
            (
                "VALIGN",
                (0, 0),
                (-1, -1),
                "TOP"
            ),
            (
                "PADDING",
                (0, 0),
                (-1, -1),
                6
            ),
        ])
    )

    story.append(table)
    story.append(Spacer(1, 10))

    story.append(
        Paragraph(
            f"<b>Végösszeg: "
            f"{money(quote['total'])}</b>",
            total_style
        )
    )

    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            f"Tervezett határidő: "
            f"<b>{safe_html(quote['deadline'])}</b>",
            normal
        )
    )

    story.append(Spacer(1, 18))

    story.append(
        Paragraph(
            "Az ajánlat a megadott adatok alapján készült. "
            "A végleges munkadíj a helyszíni felmérés "
            "és az esetleges változtatások "
            "függvényében módosulhat.",
            normal
        )
    )

    doc.build(story)


# ============================================================
# BILLENTYŰZETEK
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
            ),
            InlineKeyboardButton(
                "📋 Ajánlataim",
                callback_data="quotes"
            ),
        ],
        [
            InlineKeyboardButton(
                "🤖 AI Segítő",
                callback_data="ai_help"
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


def back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬅️ Főmenü",
                callback_data="menu"
            )
        ]
    ])


def cancel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "❌ Megszakítás",
                callback_data="cancel"
            )
        ]
    ])


# ============================================================
# START / MENU
# ============================================================

async def start(update, context):

    context.user_data.clear()

    await update.message.reply_text(
        f"{APP_TITLE}\n\n"
        f"{APP_SUBTITLE}",
        reply_markup=main_keyboard()
    )


async def menu_callback(update, context):

    query = update.callback_query

    await query.answer()

    context.user_data.clear()

    await query.edit_message_text(
        f"{APP_TITLE}\n\n"
        "Válassz egy funkciót:",
        reply_markup=main_keyboard()
    )


async def cancel(update, context):

    context.user_data.clear()

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            "❌ Megszakítva.",
            reply_markup=main_keyboard()
        )

    else:

        await update.message.reply_text(
            "❌ Megszakítva.",
            reply_markup=main_keyboard()
        )


# ============================================================
# CÉGADATOK
# ============================================================

async def company_menu(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    data = get_company_data(
        update.effective_user.id
    )

    if data:

        text = (
            "⚙️ <b>Cégadatok</b>\n\n"
            + company_display(data)
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "✏️ Módosítás",
                    callback_data="company_edit"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔄 Újra megadás",
                    callback_data="company_edit"
                )
            ],

            [
                InlineKeyboardButton(
                    "⬅️ Főmenü",
                    callback_data="menu"
                )
            ]

        ])

    else:

        text = (
            "⚙️ <b>Cégadatok</b>\n\n"
            "Még nincsenek elmentett cégadataid.\n\n"
            "Nyomd meg a beállítás gombot, majd küldd el "
            "az adatokat egy üzenetben."
        )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "➕ Cégadatok beállítása",
                    callback_data="company_edit"
                )
            ],

            [
                InlineKeyboardButton(
                    "⬅️ Főmenü",
                    callback_data="menu"
                )
            ]

        ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


async def company_edit(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    context.user_data.clear()

    context.user_data["state"] = "company"

    await query.edit_message_text(
        "⚙️ <b>Cégadatok beállítása</b>\n\n"
        "Küldd el az adatokat <b>egyetlen üzenetben</b>:\n\n"
        "Cégnév: ...\n"
        "Telefonszám: ...\n"
        "E-mail: ...\n"
        "Cím: ...\n"
        "Adószám: ...\n\n"
        "Ezek az adatok jelennek meg a PDF ajánlatokon.",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


# ============================================================
# ÚJ AJÁNLAT
# ============================================================

QUOTE_STEPS = [
    "name",
    "phone",
    "address",
    "work",
    "quantity",
    "price",
    "material",
    "deadline",
]

PROMPTS = {

    "name":
        "1/8 👤 Ügyfél neve:",

    "phone":
        "2/8 📞 Telefonszám:",

    "address":
        "3/8 🏠 Ügyfél címe:",

    "work":
        "4/8 🛠️ Milyen munkára készül az ajánlat?",

    "quantity":
        "5/8 📐 Mennyiség (pl. 80 m²):",

    "price":
        "6/8 💰 Munkadíj (Ft):",

    "material":
        "7/8 🧱 Anyagköltség (Ft):",

    "deadline":
        "8/8 📅 Határidő (pl. 2026. október 15.):",
}


async def new_quote(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    context.user_data.clear()

    context.user_data["state"] = "quote:name"

    await query.edit_message_text(
        PROMPTS["name"],
        reply_markup=cancel_keyboard()
    )


async def handle_quote_text(
    update,
    context,
    state
):

    text = update.message.text.strip()

    field = state.split(":", 1)[1]

    if field in ("price", "material"):

        try:

            value = parse_number(text)

        except Exception:

            await update.message.reply_text(
                "⚠️ Írj be érvényes összeget, "
                "például: 250000",
                reply_markup=cancel_keyboard()
            )

            return

        context.user_data[field] = value

    else:

        context.user_data[field] = text

    index = QUOTE_STEPS.index(field)

    if index < len(QUOTE_STEPS) - 1:

        next_field = QUOTE_STEPS[
            index + 1
        ]

        context.user_data["state"] = (
            "quote:" + next_field
        )

        await update.message.reply_text(
            PROMPTS[next_field],
            reply_markup=cancel_keyboard()
        )

        return

    await finish_quote(
        update,
        context
    )


async def finish_quote(update, context):

    user_id = update.effective_user.id

    if not get_active_subscription(user_id):

        context.user_data.clear()

        await update.message.reply_text(
            "🔒 Az előfizetésed lejárt.",
            reply_markup=main_keyboard()
        )

        return

    data = context.user_data

    quote_number = next_quote_number(
        user_id
    )

    total = (
        float(data["price"])
        +
        float(data["material"])
    )

    created = datetime.now().strftime(
        "%Y.%m.%d."
    )

    # Ügyfél mentése / frissítése
    client_id = save_or_update_client(
        user_id,
        data["name"],
        data["phone"],
        data["address"]
    )

    conn = db()

    conn.execute(
        """
        INSERT INTO quotes(
            user_id,
            client_name,
            phone,
            address,
            work,
            quantity,
            price,
            material,
            total,
            deadline,
            quote_number,
            created_at
        )
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
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
            total,
            data["deadline"],
            quote_number,
            created
        )
    )

    quote_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    saved_data = dict(data)

    context.user_data.clear()

    text = (
        "✅ <b>Árajánlat elkészült</b>\n\n"
        f"🔢 {safe_html(quote_number)}\n"
        f"👤 {safe_html(saved_data['name'])}\n"
        f"📞 {safe_html(saved_data['phone'])}\n"
        f"🏠 {safe_html(saved_data['address'])}\n\n"
        f"🛠️ {safe_html(saved_data['work'])}\n"
        f"📐 {safe_html(saved_data['quantity'])}\n"
        f"💰 Munkadíj: {money(saved_data['price'])}\n"
        f"🧱 Anyag: {money(saved_data['material'])}\n"
        f"💵 <b>Végösszeg: {money(total)}</b>\n"
        f"📅 Határidő: {safe_html(saved_data['deadline'])}"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📄 PDF elküldése",
                callback_data=f"pdf:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "✏️ Szerkesztés",
                callback_data=f"edit_quote:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "📋 Ajánlataim",
                callback_data="quotes"
            ),

            InlineKeyboardButton(
                "⬅️ Főmenü",
                callback_data="menu"
            )
        ]

    ])

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============================================================
# AJÁNLATAIM
# ============================================================

async def quotes_menu(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM quotes
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 30
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await query.edit_message_text(
            "📋 Még nincs mentett ajánlatod.",
            reply_markup=back_keyboard()
        )

        return

    buttons = []

    for row in rows:

        buttons.append([

            InlineKeyboardButton(
                f"{row['quote_number']} – "
                f"{row['client_name']}",
                callback_data=f"quote:{row['id']}"
            )

        ])

    buttons.append([

        InlineKeyboardButton(
            "⬅️ Főmenü",
            callback_data="menu"
        )

    ])

    await query.edit_message_text(
        "📋 <b>Ajánlataim</b>\n\n"
        "Válassz egy ajánlatot:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def quote_detail(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    quote_id = int(
        query.data.split(":")[1]
    )

    user_id = update.effective_user.id

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM quotes
        WHERE id=?
        AND user_id=?
        """,
        (
            quote_id,
            user_id
        )
    ).fetchone()

    conn.close()

    if not row:

        await query.edit_message_text(
            "❌ Az ajánlat nem található.",
            reply_markup=back_keyboard()
        )

        return

    text = (
        f"📋 <b>{safe_html(row['quote_number'])}</b>\n\n"
        f"👤 {safe_html(row['client_name'])}\n"
        f"📞 {safe_html(row['phone'])}\n"
        f"🏠 {safe_html(row['address'])}\n\n"
        f"🛠️ {safe_html(row['work'])}\n"
        f"📐 {safe_html(row['quantity'])}\n"
        f"💰 Munkadíj: {money(row['price'])}\n"
        f"🧱 Anyag: {money(row['material'])}\n"
        f"💵 <b>Összesen: {money(row['total'])}</b>\n"
        f"📅 Határidő: {safe_html(row['deadline'])}\n"
        f"📅 Készült: {safe_html(row['created_at'])}"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "📄 PDF elküldése",
                callback_data=f"pdf:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 PDF újragenerálása",
                callback_data=f"pdf:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "✏️ Ajánlat szerkesztése",
                callback_data=f"edit_quote:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Ajánlataim",
                callback_data="quotes"
            )
        ]

    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============================================================
# AJÁNLAT SZERKESZTÉSE
# ============================================================

EDIT_STEPS = [
    "name",
    "phone",
    "address",
    "work",
    "quantity",
    "price",
    "material",
    "deadline",
]


def edit_prompt(
    field,
    current
):

    labels = {

        "name":
            "👤 Ügyfél neve",

        "phone":
            "📞 Telefonszám",

        "address":
            "🏠 Cím",

        "work":
            "🛠️ Munka",

        "quantity":
            "📐 Mennyiség",

        "price":
            "💰 Munkadíj",

        "material":
            "🧱 Anyagköltség",

        "deadline":
            "📅 Határidő",
    }

    return (
        f"✏️ <b>{labels[field]}</b>\n\n"
        f"Jelenlegi érték:\n"
        f"<b>{safe_html(current)}</b>\n\n"
        "Írd be az új értéket.\n"
        "Ha nem szeretnéd módosítani, írd be: <b>-</b>"
    )


async def edit_quote_start(
    update,
    context
):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    quote_id = int(
        query.data.split(":")[1]
    )

    user_id = update.effective_user.id

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM quotes
        WHERE id=?
        AND user_id=?
        """,
        (
            quote_id,
            user_id
        )
    ).fetchone()

    conn.close()

    if not row:

        await query.edit_message_text(
            "❌ Az ajánlat nem található.",
            reply_markup=back_keyboard()
        )

        return

    context.user_data.clear()

    context.user_data["state"] = "edit_quote:name"
    context.user_data["edit_quote_id"] = quote_id

    for field in EDIT_STEPS:
        context.user_data[
            "edit_" + field
        ] = str(row[field])

    await query.edit_message_text(
        "✏️ <b>Ajánlat szerkesztése</b>\n\n"
        f"Ajánlatszám: <b>{safe_html(row['quote_number'])}</b>\n\n"
        + edit_prompt(
            "name",
            row["client_name"]
        ),
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


async def handle_edit_quote_text(
    update,
    context,
    state
):

    text = update.message.text.strip()

    field = state.split(":", 1)[1]

    current = context.user_data[
        "edit_" + field
    ]

    if text != "-":

        if field in ("price", "material"):

            try:
                value = parse_number(text)

            except Exception:

                await update.message.reply_text(
                    "⚠️ Érvénytelen összeg.\n\n"
                    "Például: 250000",
                    reply_markup=cancel_keyboard()
                )

                return

            context.user_data[
                "edit_" + field
            ] = value

        else:

            context.user_data[
                "edit_" + field
            ] = text

    index = EDIT_STEPS.index(field)

    if index < len(EDIT_STEPS) - 1:

        next_field = EDIT_STEPS[
            index + 1
        ]

        context.user_data["state"] = (
            "edit_quote:" + next_field
        )

        if next_field == "name":
            display_value = context.user_data["edit_name"]
        elif next_field == "phone":
            display_value = context.user_data["edit_phone"]
        elif next_field == "address":
            display_value = context.user_data["edit_address"]
        elif next_field == "work":
            display_value = context.user_data["edit_work"]
        elif next_field == "quantity":
            display_value = context.user_data["edit_quantity"]
        elif next_field == "price":
            display_value = money(context.user_data["edit_price"])
        elif next_field == "material":
            display_value = money(context.user_data["edit_material"])
        else:
            display_value = context.user_data["edit_deadline"]

        await update.message.reply_text(
            edit_prompt(
                next_field,
                display_value
            ),
            parse_mode="HTML",
            reply_markup=cancel_keyboard()
        )

        return

    quote_id = context.user_data[
        "edit_quote_id"
    ]

    price = float(
        context.user_data["edit_price"]
    )

    material = float(
        context.user_data["edit_material"]
    )

    total = price + material

    conn = db()

    conn.execute(
        """
        UPDATE quotes
        SET client_name=?,
            phone=?,
            address=?,
            work=?,
            quantity=?,
            price=?,
            material=?,
            total=?,
            deadline=?
        WHERE id=?
        AND user_id=?
        """,
        (
            context.user_data["edit_name"],
            context.user_data["edit_phone"],
            context.user_data["edit_address"],
            context.user_data["edit_work"],
            context.user_data["edit_quantity"],
            price,
            material,
            total,
            context.user_data["edit_deadline"],
            quote_id,
            update.effective_user.id
        )
    )

    # Az ügyféladatokat is frissítjük
    save_or_update_client(
        update.effective_user.id,
        context.user_data["edit_name"],
        context.user_data["edit_phone"],
        context.user_data["edit_address"]
    )

    conn.commit()
    conn.close()

    context.user_data.clear()

    await update.message.reply_text(
        "✅ <b>Az ajánlat sikeresen módosítva!</b>\n\n"
        f"💵 Új végösszeg: <b>{money(total)}</b>\n\n"
        "A PDF-et most már az új adatokkal "
        "tudod újragenerálni.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "📄 PDF újragenerálása",
                    callback_data=f"pdf:{quote_id}"
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
                    "⬅️ Főmenü",
                    callback_data="menu"
                )
            ]

        ])
    )


# ============================================================
# PDF KÜLDÉSE / ÚJRAGENERÁLÁSA
# ============================================================

async def send_pdf(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer(
        "PDF készül..."
    )

    quote_id = int(
        query.data.split(":")[1]
    )

    user_id = update.effective_user.id

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM quotes
        WHERE id=?
        AND user_id=?
        """,
        (
            quote_id,
            user_id
        )
    ).fetchone()

    conn.close()

    if not row:

        await query.message.reply_text(
            "❌ Az ajánlat nem található."
        )

        return

    company = get_company_data(
        user_id
    )

    if not company:

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "⚙️ Cégadatok beállítása",
                    callback_data="company"
                )
            ]

        ])

        await query.message.reply_text(
            "⚠️ Előbb töltsd ki a Cégadatokat, "
            "hogy a PDF fejlécében megjelenhessenek.",
            reply_markup=keyboard
        )

        return

    path = (
        "/tmp/"
        + str(row["quote_number"])
        + ".pdf"
    )

    try:

        create_pdf(
            dict(row),
            company,
            path
        )

        with open(
            path,
            "rb"
        ) as pdf_file:

            await query.message.reply_document(
                document=pdf_file,
                filename=(
                    str(row["quote_number"])
                    + ".pdf"
                ),
                caption=(
                    "📄 Árajánlat: "
                    + str(row["quote_number"])
                    + "\n"
                    "🔄 A PDF az aktuális adatokból "
                    "lett újragenerálva."
                )
            )

    except Exception as error:

        print(
            "PDF ERROR:",
            repr(error)
        )

        await query.message.reply_text(
            "❌ A PDF elkészítése nem sikerült:\n"
            + str(error)
        )

    finally:

        try:
            os.remove(path)
        except OSError:
            pass


# ============================================================
# AI SEGÍTŐ
# ============================================================

async def ai_help(update, context):

    if not await require_subscription(update, context):
        return

    query = update.callback_query

    await query.answer()

    context.user_data["state"] = "ai"

    await query.edit_message_text(
        "🤖 <b>AI Segítő</b>\n\n"
        "Írd le, miben segítsek az ajánlatoddal kapcsolatban.\n\n"
        "Például:\n"
        "„Mennyit kérjek 80 m² tisztasági festésért?”\n\n"
        "vagy:\n"
        "„Írj rövid munkaleírást festéshez.”",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


async def ai_answer(update, context):

    text = update.message.text.strip()

    low = text.lower()

    if any(
        word in low
        for word in [
            "ár",
            "mennyi",
            "mennyit",
            "ft"
        ]
    ):

        answer = (
            "🤖 <b>Árajánlati tipp</b>\n\n"
            "A pontos munkadíjat a terület, "
            "a felület állapota, a javítások, "
            "az anyagminőség és a helyszín alapján "
            "érdemes meghatározni.\n\n"
            "Ha megadod a m²-t, a munka típusát "
            "és az anyagköltséget, segítek "
            "kiszámolni az ajánlatot."
        )

    elif (
        "leírás" in low
        or "munkaleírás" in low
    ):

        answer = (
            "🤖 <b>Munkaleírás minta</b>\n\n"
            "A munkaterület előkészítése, "
            "a szükséges javítások elvégzése, "
            "alapozás és a megadott felületek "
            "szakszerű festése, majd a munkaterület "
            "tiszta átadása."
        )

    else:

        answer = (
            "🤖 Írd le konkrétan, mit szeretnél "
            "kiszámolni vagy megfogalmazni, "
            "és segítek az ajánlat elkészítésében."
        )

    context.user_data.pop(
        "state",
        None
    )

    await update.message.reply_text(
        answer,
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# ============================================================
# SEGÍTSÉG
# ============================================================

async def help_menu(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "🆘 <b>Segítség</b>\n\n"
        "1. Töltsd ki a Cégadatokat.\n"
        "2. Aktív előfizetéssel készíts új ajánlatot.\n"
        "3. Az elkészült ajánlat automatikusan mentésre kerül.\n"
        "4. Az ügyfél automatikusan bekerül az Ügyfeleim közé.\n"
        "5. Meglévő ügyfelet új ajánlathoz újra felhasználhatsz.\n"
        "6. A korábbi ajánlatokat az Ajánlataim menüben találod.\n"
        "7. A korábbi ajánlatokat szerkesztheted.\n"
        "8. A PDF-et bármikor újragenerálhatod.\n\n"
        "A PDF mindig az aktuális cégadatokkal készül.",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


# ============================================================
# ELŐFIZETÉS
# ============================================================

async def subscription_menu(update, context):

    query = update.callback_query

    await query.answer()

    text = (
        "💳 <b>Előfizetés</b>\n\n"
        + subscription_text(
            update.effective_user.id
        )
        + "\n\nVálassz csomagot:"
    )

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
                callback_data="buy_plus"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 Saját előfizetésem",
                callback_data="status"
            )
        ],

        [
            InlineKeyboardButton(
                "⬅️ Főmenü",
                callback_data="menu"
            )
        ]

    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# ============================================================
# PRO FIZETÉS
# ============================================================

async def buy_pro(update, context):

    query = update.callback_query

    try:

        await query.answer()

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,

            title=(
                "🤖 AI Árajánlat Pro – PRO"
            ),

            description=(
                "7 napos hozzáférés az "
                "AI Árajánlat Pro szolgáltatáshoz."
            ),

            payload=(
                "ai_arajanlat_pro_7_nap"
            ),

            provider_token="",

            currency="XTR",

            prices=[
                LabeledPrice(
                    label="PRO – 7 nap",
                    amount=PRO_STARS
                )
            ]
        )

    except Exception as error:

        print(
            "PRO PAYMENT ERROR:",
            repr(error)
        )

        try:

            await query.answer(
                "A fizetés indítása nem sikerült.",
                show_alert=True
            )

        except Exception:
            pass


# ============================================================
# PRO+ FIZETÉS
# ============================================================

async def buy_plus(update, context):

    query = update.callback_query

    try:

        await query.answer()

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,

            title=(
                "🤖 AI Árajánlat Pro – PRO+"
            ),

            description=(
                "30 napos hozzáférés az "
                "AI Árajánlat Pro+ szolgáltatáshoz."
            ),

            payload=(
                "ai_arajanlat_pro_plus_30_nap"
            ),

            provider_token="",

            currency="XTR",

            prices=[
                LabeledPrice(
                    label="PRO+ – 30 nap",
                    amount=PRO_PLUS_STARS
                )
            ],

            subscription_period=SUBSCRIPTION_PERIOD
        )

    except Exception as error:

        print(
            "PRO PLUS PAYMENT ERROR:",
            repr(error)
        )

        try:

            await query.answer(
                "A fizetés indítása nem sikerült.",
                show_alert=True
            )

        except Exception:
            pass


# ============================================================
# PRECHECKOUT
# ============================================================

async def precheckout(update, context):

    try:

        await update.pre_checkout_query.answer(
            ok=True
        )

    except Exception as error:

        print(
            "PRECHECKOUT ERROR:",
            repr(error)
        )

        try:

            await update.pre_checkout_query.answer(
                ok=False,
                error_message=(
                    "A fizetést nem sikerült ellenőrizni. "
                    "Próbáld újra."
                )
            )

        except Exception:
            pass


# ============================================================
# SIKERES FIZETÉS
# ============================================================

async def successful_payment(
    update,
    context
):

    payment = update.message.successful_payment

    user_id = update.effective_user.id

    if payment.total_amount == PRO_PLUS_STARS:

        plan = "PRO+"
        days = PRO_PLUS_DAYS

    else:

        plan = "PRO"
        days = PRO_DAYS

    expiration = getattr(
        payment,
        "subscription_expiration_date",
        None
    )

    if expiration:

        try:

            expires_at = datetime.fromtimestamp(
                expiration
            )

        except Exception:

            expires_at = (
                datetime.now()
                +
                timedelta(days=days)
            )

    else:

        expires_at = (
            datetime.now()
            +
            timedelta(days=days)
        )

    recurring = (
        1
        if plan == "PRO+"
        else 0
    )

    charge_id = getattr(
        payment,
        "telegram_payment_charge_id",
        ""
    )

    conn = db()

    conn.execute(
        """
        INSERT INTO subscriptions(
            user_id,
            plan,
            stars,
            expires_at,
            is_recurring,
            charge_id,
            created_at
        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            user_id,
            plan,
            payment.total_amount,
            expires_at.isoformat(),
            recurring,
            charge_id,
            now_str()
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ <b>Sikeres fizetés!</b>\n\n"
        f"📦 {plan}\n"
        f"📅 Érvényes eddig: "
        f"{expires_at.strftime('%Y.%m.%d. %H:%M')}\n\n"
        "Most már használhatod az "
        "AI Árajánlat Pro funkcióit.",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )


# ============================================================
# ELŐFIZETÉS STÁTUSZ
# ============================================================

async def status(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "📊 <b>Saját előfizetésem</b>\n\n"
        + subscription_text(
            update.effective_user.id
        ),
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


# ============================================================
# FELHASZNÁLÁSI FELTÉTELEK
# ============================================================

async def terms(update, context):

    await update.message.reply_text(
        "📄 <b>Felhasználási feltételek</b>\n\n"
        "Az AI Árajánlat Pro digitális szolgáltatás. "
        "A vásárlás Telegram Stars használatával történik.",
        parse_mode="HTML"
    )


async def paysupport(update, context):

    await update.message.reply_text(
        "💳 <b>Fizetési segítség</b>\n\n"
        "Ha fizetési problémád van, írd le pontosan, "
        "mi történt, és segítünk a hiba azonosításában.",
        parse_mode="HTML"
    )


# ============================================================
# SZÖVEGES ÜZENETEK
# ============================================================

async def text_handler(update, context):

    if (
        not update.message
        or not update.message.text
    ):
        return

    state = context.user_data.get(
        "state",
        ""
    )

    # ----------------------------------------
    # ÚJ AJÁNLAT
    # ----------------------------------------

    if state.startswith("quote:"):

        if await require_subscription(
            update,
            context
        ):

            await handle_quote_text(
                update,
                context,
                state
            )

        return

    # ----------------------------------------
    # AJÁNLAT SZERKESZTÉSE
    # ----------------------------------------

    if state.startswith(
        "edit_quote:"
    ):

        if await require_subscription(
            update,
            context
        ):

            await handle_edit_quote_text(
                update,
                context,
                state
            )

        return

    # ----------------------------------------
    # ÜGYFÉL SZERKESZTÉSE
    # ----------------------------------------

    if state.startswith(
        "client_edit:"
    ):

        if await require_subscription(
            update,
            context
        ):

            await handle_client_edit(
                update,
                context,
                state
            )

        return

    # ----------------------------------------
    # CÉGADATOK
    # ----------------------------------------

    if state == "company":

        if not await require_subscription(
            update,
            context
        ):
            return

        data = parse_company_data(
            update.message.text
        )

        required = [
            "company_name",
            "phone",
            "email",
            "address",
            "tax_number",
        ]

        if any(
            not data.get(field)
            for field in required
        ):

            await update.message.reply_text(
                "⚠️ Minden mező kötelező.\n\n"
                "Kérlek, így küldd el:\n\n"
                "Cégnév: ...\n"
                "Telefonszám: ...\n"
                "E-mail: ...\n"
                "Cím: ...\n"
                "Adószám: ...",
                reply_markup=cancel_keyboard()
            )

            return

        save_company_data(
            update.effective_user.id,
            data
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ <b>Cégadatok elmentve!</b>\n\n"
            + company_display(data),
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )

        return

    # ----------------------------------------
    # AI
    # ----------------------------------------

    if state == "ai":

        if await require_subscription(
            update,
            context
        ):

            await ai_answer(
                update,
                context
            )

        return

    await update.message.reply_text(
        "Válassz egy funkciót a menüből.",
        reply_markup=main_keyboard()
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(
    update,
    context
):

    data = update.callback_query.data

    if data == "menu":

        await menu_callback(
            update,
            context
        )

    elif data == "cancel":

        await cancel(
            update,
            context
        )

    elif data == "new_quote":

        await new_quote(
            update,
            context
        )

    elif data == "clients":

        await clients_menu(
            update,
            context
        )

    elif data.startswith("client_quote:"):

        await client_quote(
            update,
            context
        )

    elif data.startswith("client_edit:"):

        await client_edit(
            update,
            context
        )

    elif data.startswith("client:"):

        await client_detail(
            update,
            context
        )

    elif data == "quotes":

        await quotes_menu(
            update,
            context
        )

    elif data.startswith("edit_quote:"):

        await edit_quote_start(
            update,
            context
        )

    elif data.startswith("quote:"):

        await quote_detail(
            update,
            context
        )

    elif data.startswith("pdf:"):

        await send_pdf(
            update,
            context
        )

    elif data == "ai_help":

        await ai_help(
            update,
            context
        )

    elif data == "company":

        await company_menu(
            update,
            context
        )

    elif data == "company_edit":

        await company_edit(
            update,
            context
        )

    elif data == "help":

        await help_menu(
            update,
            context
        )

    elif data == "subscription":

        await subscription_menu(
            update,
            context
        )

    elif data == "buy_pro":

        await buy_pro(
            update,
            context
        )

    elif data == "buy_plus":

        await buy_plus(
            update,
            context
        )

    elif data == "status":

        await status(
            update,
            context
        )


# ============================================================
# HIBA NAPLÓ
# ============================================================

async def error_handler(
    update,
    context
):

    print(
        "BOT ERROR:",
        repr(context.error)
    )


# ============================================================
# INDÍTÁS
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing"
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

    # ----------------------------------------
    # PARANCSOK
    # ----------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
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

    # ----------------------------------------
    # FIZETÉS
    # ----------------------------------------

    app.add_handler(
        PreCheckoutQueryHandler(
            precheckout
        )
    )

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment
        )
    )

    # ----------------------------------------
    # GOMBOK
    # ----------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # ----------------------------------------
    # SZÖVEGES ÜZENETEK
    # ----------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    app.add_error_handler(
        error_handler
    )

    print(
        "AI Arjanlat Pro started"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# FONTOS: MAIN MEGHÍVÁSA
# ============================================================

if __name__ == "__main__":
    main()
