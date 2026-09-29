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

APP_TITLE = "\U0001F916 AI \u00C1raj\u00E1nlat Pro"
APP_SUBTITLE = (
    "K\u00E9sz\u00EDts professzion\u00E1lis \u00E1raj\u00E1nlatokat "
    "gyorsan \u00E9s egyszer\u0171en."
)

DB_PATH = "ai_arajanlat_pro.db"

# Előfizetési idő
PRO_DAYS = 7
PRO_PLUS_DAYS = 30

# Telegram Stars
PRO_STARS = 1000
PRO_PLUS_STARS = 3000

# Telegram Stars havi előfizetés:
# 30 nap = 2592000 másodperc
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
    columns = conn.execute(
        "PRAGMA table_info(quotes)"
    ).fetchall()

    column_names = [
        row["name"]
        for row in columns
    ]

    if "total" not in column_names:

        conn.execute(
            "ALTER TABLE quotes ADD COLUMN total REAL DEFAULT 0"
        )

    if "quote_number" not in column_names:

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

    value = value.replace(
        "Ft",
        ""
    )

    value = value.replace(
        "ft",
        ""
    )

    value = value.replace(
        " ",
        ""
    )

    value = value.replace(
        ".",
        ""
    )

    value = value.replace(
        ",",
        "."
    )

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
            "\u274C Nincs akt\u00EDv el\u0151fizet\u00E9sed."
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
        "\u2705 Akt\u00EDv el\u0151fizet\u00E9s\n\n"
        f"\U0001F4E6 Csomag: {subscription['plan']}\n"
        f"\U0001F4C5 \u00C9rv\u00E9nyes eddig: {expires_text}"
    )


async def require_subscription(
    update,
    context
):

    user_id = update.effective_user.id

    if get_active_subscription(user_id):

        return True

    text = (
        "\U0001F512 Ez a funkci\u00F3 akt\u00EDv "
        "el\u0151fizet\u00E9shez k\u00F6t\u00F6tt.\n\n"
        "Az AI \u00C1raj\u00E1nlat Pro haszn\u00E1lat\u00E1hoz "
        "v\u00E1lassz egy el\u0151fizet\u00E9st."
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "\U0001F535 PRO \u2013 6 500 Ft / 7 nap",
                callback_data="buy_pro"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F7E3 PRO+ \u2013 20 000 Ft / h\u00F3",
                callback_data="buy_plus"
            )
        ],

        [
            InlineKeyboardButton(
                "\u2B05\uFE0F F\u0151men\u00FC",
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

    lines = text.splitlines()

    for line in lines:

        if ":" not in line:
            continue

        key, value = line.split(
            ":",
            1
        )

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
        f"\U0001F3E2 C\u00E9gn\u00E9v: {data['company_name']}\n"
        f"\U0001F4DE Telefon: {data['phone']}\n"
        f"\U0001F4E7 E-mail: {data['email']}\n"
        f"\U0001F3E0 C\u00EDm: {data['address']}\n"
        f"\U0001F9FE Ad\u00F3sz\u00E1m: {data['tax_number']}"
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
    from reportlab.lib.enums import (
        TA_CENTER,
        TA_RIGHT,
    )
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
            "\u00C1RAJ\u00C1NLAT",
            title_style
        )
    ]

    company_block = (
        f"<b>{company['company_name']}</b><br/>"
        f"{company['address']}<br/>"
        f"Tel.: {company['phone']}<br/>"
        f"E-mail: {company['email']}<br/>"
        f"Ad\u00F3sz\u00E1m: {company['tax_number']}"
    )

    customer_block = (
        "<b>\u00DCgyf\u00E9l</b><br/>"
        f"{quote['client_name']}<br/>"
        f"Tel.: {quote['phone']}<br/>"
        f"C\u00EDm: {quote['address']}"
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
            f"Aj\u00E1nlatsz\u00E1m: "
            f"<b>{quote['quote_number']}</b>"
            f"&nbsp;&nbsp;"
            f"D\u00E1tum: {quote['created_at']}",
            normal
        )
    )

    story.append(Spacer(1, 8))

    rows = [

        [
            Paragraph(
                "Munka",
                normal
            ),
            Paragraph(
                "Mennyis\u00E9g",
                normal
            ),
            Paragraph(
                "Munkad\u00EDj",
                normal
            ),
            Paragraph(
                "Anyag",
                normal
            ),
            Paragraph(
                "\u00D6sszesen",
                normal
            ),
        ],

        [
            Paragraph(
                quote["work"],
                normal
            ),
            Paragraph(
                str(quote["quantity"]),
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
            f"<b>V\u00E9g\u00F6sszeg: "
            f"{money(quote['total'])}</b>",
            total_style
        )
    )

    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            f"Tervezett hat\u00E1rid\u0151: "
            f"<b>{quote['deadline']}</b>",
            normal
        )
    )

    story.append(Spacer(1, 18))

    story.append(
        Paragraph(
            "Az aj\u00E1nlat a megadott adatok alapj\u00E1n k\u00E9sz\u00FClt. "
            "A v\u00E9gleges munkad\u00EDj a helysz\u00EDni felm\u00E9r\u00E9s "
            "\u00E9s az esetleges v\u00E1ltoztat\u00E1sok "
            "f\u00FCggv\u00E9ny\u00E9ben m\u00F3dosulhat.",
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
                "\U0001F4DD \u00DAj \u00E1raj\u00E1nlat",
                callback_data="new_quote"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F465 \u00DCgyfeleim",
                callback_data="clients"
            ),
            InlineKeyboardButton(
                "\U0001F4CB Aj\u00E1nlataim",
                callback_data="quotes"
            ),
        ],

        [
            InlineKeyboardButton(
                "\U0001F916 AI Seg\u00EDt\u0151",
                callback_data="ai_help"
            )
        ],

        [
            InlineKeyboardButton(
                "\u2699\uFE0F C\u00E9gadatok",
                callback_data="company"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F4B3 El\u0151fizet\u00E9sem",
                callback_data="subscription"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F198 Seg\u00EDts\u00E9g",
                callback_data="help"
            )
        ],
    ])


def back_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "\u2B05\uFE0F F\u0151men\u00FC",
                callback_data="menu"
            )
        ]
    ])


def cancel_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "\u274C Megszak\u00EDt\u00E1s",
                callback_data="cancel"
            )
        ]
    ])


# ============================================================
# START
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
        "V\u00E1lassz egy funkci\u00F3t:",
        reply_markup=main_keyboard()
    )


async def cancel(update, context):

    context.user_data.clear()

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            "\u274C Megszak\u00EDtva.",
            reply_markup=main_keyboard()
        )

    else:

        await update.message.reply_text(
            "\u274C Megszak\u00EDtva.",
            reply_markup=main_keyboard()
        )


# ============================================================
# CÉGADATOK
# ============================================================

async def company_menu(update, context):

    if not await require_subscription(
        update,
        context
    ):
        return

    query = update.callback_query

    await query.answer()

    data = get_company_data(
        update.effective_user.id
    )

    if data:

        text = (
            "\u2699\uFE0F <b>C\u00E9gadatok</b>\n\n"
            + company_display(data)
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "\u270F\uFE0F M\u00F3dos\u00EDt\u00E1s",
                    callback_data="company_edit"
                )
            ],
            [
                InlineKeyboardButton(
                    "\u2B05\uFE0F F\u0151men\u00FC",
                    callback_data="menu"
                )
            ]
        ])

    else:

        text = (
            "\u2699\uFE0F <b>C\u00E9gadatok</b>\n\n"
            "M\u00E9g nincsenek elmentett c\u00E9gadataid.\n\n"
            "K\u00FCldd el egy \u00FCzenetben az al\u00E1bbi form\u00E1ban:\n\n"
            "C\u00E9gn\u00E9v: ...\n"
            "Telefonsz\u00E1m: ...\n"
            "E-mail: ...\n"
            "C\u00EDm: ...\n"
            "Ad\u00F3sz\u00E1m: ..."
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "\u2B05\uFE0F F\u0151men\u00FC",
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

    query = update.callback_query

    await query.answer()

    context.user_data["state"] = "company"

    await query.edit_message_text(
        "\u2699\uFE0F K\u00FCldd el a c\u00E9gadataidat "
        "egyetlen \u00FCzenetben:\n\n"
        "C\u00E9gn\u00E9v: ...\n"
        "Telefonsz\u00E1m: ...\n"
        "E-mail: ...\n"
        "C\u00EDm: ...\n"
        "Ad\u00F3sz\u00E1m: ...",
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
        "1/8 \U0001F464 \u00DCgyf\u00E9l neve:",

    "phone":
        "2/8 \U0001F4DE Telefonsz\u00E1m:",

    "address":
        "3/8 \U0001F3E0 \u00DCgyf\u00E9l c\u00EDme:",

    "work":
        "4/8 \U0001F6E0\uFE0F Milyen munk\u00E1ra k\u00E9sz\u00FCl az aj\u00E1nlat?",

    "quantity":
        "5/8 \U0001F4CF Mennyis\u00E9g (pl. 80 m\u00B2):",

    "price":
        "6/8 \U0001F4B0 Munkad\u00EDj (Ft):",

    "material":
        "7/8 \U0001F9F1 Anyagk\u00F6lts\u00E9g (Ft):",

    "deadline":
        "8/8 \U0001F4C5 Hat\u00E1rid\u0151 "
        "(pl. 2026. okt\u00F3ber 15.):",
}


async def new_quote(update, context):

    if not await require_subscription(
        update,
        context
    ):
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

    field = state.split(
        ":",
        1
    )[1]

    if field in (
        "price",
        "material"
    ):

        try:

            value = parse_number(text)

        except Exception:

            await update.message.reply_text(
                "\u26A0\uFE0F \u00CDrj be \u00E9rv\u00E9nyes "
                "\u00F6sszeget, p\u00E9ld\u00E1ul: 250000",
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

    if not get_active_subscription(
        user_id
    ):

        context.user_data.clear()

        await update.message.reply_text(
            "\U0001F512 Az el\u0151fizet\u00E9sed lej\u00E1rt.",
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

    conn = db()

    conn.execute(
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
            data["name"],
            data["phone"],
            data["address"],
            now_str()
        )
    )

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

    # Az adatokat a PDF után is használjuk
    saved_data = dict(data)

    context.user_data.clear()

    text = (
        "\u2705 <b>\u00C1raj\u00E1nlat elk\u00E9sz\u00FClt</b>\n\n"
        f"\U0001F522 {quote_number}\n"
        f"\U0001F464 {saved_data['name']}\n"
        f"\U0001F4DE {saved_data['phone']}\n"
        f"\U0001F3E0 {saved_data['address']}\n\n"
        f"\U0001F6E0\uFE0F {saved_data['work']}\n"
        f"\U0001F4CF {saved_data['quantity']}\n"
        f"\U0001F4B0 Munkad\u00EDj: "
        f"{money(saved_data['price'])}\n"
        f"\U0001F9F1 Anyag: "
        f"{money(saved_data['material'])}\n"
        f"\U0001F4B5 <b>V\u00E9g\u00F6sszeg: "
        f"{money(total)}</b>\n"
        f"\U0001F4C5 Hat\u00E1rid\u0151: "
        f"{saved_data['deadline']}"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "\U0001F4C4 PDF elk\u00FCld\u00E9se",
                callback_data=f"pdf:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F4CB Aj\u00E1nlataim",
                callback_data="quotes"
            ),
            InlineKeyboardButton(
                "\u2B05\uFE0F F\u0151men\u00FC",
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
# ÜGYFELEIM
# ============================================================

async def clients_menu(update, context):

    if not await require_subscription(
        update,
        context
    ):
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
        LIMIT 20
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await query.edit_message_text(
            "\U0001F465 M\u00E9g nincs mentett \u00FCgyfeled.",
            reply_markup=back_keyboard()
        )

        return

    text = (
        "\U0001F465 <b>\u00DCgyfeleim</b>\n\n"
    )

    for row in rows:

        text += (
            f"<b>{row['name']}</b>\n"
            f"\U0001F4DE {row['phone']}\n"
            f"\U0001F3E0 {row['address']}\n\n"
        )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


# ============================================================
# AJÁNLATAIM
# ============================================================

async def quotes_menu(update, context):

    if not await require_subscription(
        update,
        context
    ):
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
        LIMIT 20
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await query.edit_message_text(
            "\U0001F4CB M\u00E9g nincs mentett aj\u00E1nlatod.",
            reply_markup=back_keyboard()
        )

        return

    buttons = []

    for row in rows:

        buttons.append([
            InlineKeyboardButton(
                f"{row['quote_number']} \u2013 "
                f"{row['client_name']}",
                callback_data=f"quote:{row['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "\u2B05\uFE0F F\u0151men\u00FC",
            callback_data="menu"
        )
    ])

    await query.edit_message_text(
        "\U0001F4CB <b>Aj\u00E1nlataim</b>\n\n"
        "V\u00E1lassz egy aj\u00E1nlatot:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


async def quote_detail(update, context):

    if not await require_subscription(
        update,
        context
    ):
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
            "\u274C Az aj\u00E1nlat nem tal\u00E1lhat\u00F3.",
            reply_markup=back_keyboard()
        )

        return

    text = (
        f"\U0001F4CB <b>{row['quote_number']}</b>\n\n"
        f"\U0001F464 {row['client_name']}\n"
        f"\U0001F4DE {row['phone']}\n"
        f"\U0001F3E0 {row['address']}\n\n"
        f"\U0001F6E0\uFE0F {row['work']}\n"
        f"\U0001F4CF {row['quantity']}\n"
        f"\U0001F4B0 Munkad\u00EDj: "
        f"{money(row['price'])}\n"
        f"\U0001F9F1 Anyag: "
        f"{money(row['material'])}\n"
        f"\U0001F4B5 <b>\u00D6sszesen: "
        f"{money(row['total'])}</b>\n"
        f"\U0001F4C5 Hat\u00E1rid\u0151: "
        f"{row['deadline']}\n"
        f"\U0001F4C5 K\u00E9sz\u00FClt: "
        f"{row['created_at']}"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "\U0001F4C4 PDF elk\u00FCld\u00E9se",
                callback_data=f"pdf:{quote_id}"
            )
        ],

        [
            InlineKeyboardButton(
                "\u2B05\uFE0F Aj\u00E1nlataim",
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
# PDF KÜLDÉSE
# ============================================================

async def send_pdf(update, context):

    if not await require_subscription(
        update,
        context
    ):
        return

    query = update.callback_query

    await query.answer(
        "PDF k\u00E9sz\u00FCl..."
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
            "\u274C Az aj\u00E1nlat nem tal\u00E1lhat\u00F3."
        )

        return

    company = get_company_data(
        user_id
    )

    if not company:

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "\u2699\uFE0F C\u00E9gadatok",
                    callback_data="company"
                )
            ]
        ])

        await query.message.reply_text(
            "\u26A0\uFE0F El\u0151bb t\u00F6ltsd ki a "
            "C\u00E9gadatokat, hogy a PDF fejl\u00E9c\u00E9ben "
            "megjelenhessenek.",
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
                    "\U0001F4C4 \u00C1raj\u00E1nlat: "
                    + str(row["quote_number"])
                )
            )

    except Exception as error:

        await query.message.reply_text(
            "\u274C A PDF elk\u00E9sz\u00EDt\u00E9se nem siker\u00FClt:\n"
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

    if not await require_subscription(
        update,
        context
    ):
        return

    query = update.callback_query

    await query.answer()

    context.user_data["state"] = "ai"

    await query.edit_message_text(
        "\U0001F916 <b>AI Seg\u00EDt\u0151</b>\n\n"
        "\u00CDrd le, miben seg\u00EDtsek az "
        "\u00E1raj\u00E1nlatoddal kapcsolatban.\n\n"
        "P\u00E9ld\u00E1ul:\n"
        "\u201EMennyit k\u00E9rjek 80 m\u00B2 tisztas\u00E1gi "
        "fest\u00E9s\u00E9rt?\u201D\n\n"
        "vagy:\n"
        "\u201E\u00CDrj r\u00F6vid munkale\u00EDr\u00E1st fest\u00E9shez.\u201D",
        parse_mode="HTML",
        reply_markup=cancel_keyboard()
    )


async def ai_answer(update, context):

    text = update.message.text.strip()

    low = text.lower()

    if any(
        word in low
        for word in [
            "\u00E1r",
            "mennyi",
            "mennyit",
            "ft"
        ]
    ):

        answer = (
            "\U0001F916 \u00C1raj\u00E1nlati tipp:\n\n"
            "A pontos munkad\u00EDjat a ter\u00FClet, "
            "a fel\u00FClet \u00E1llapota, a jav\u00EDt\u00E1sok, "
            "az anyagmin\u0151s\u00E9g \u00E9s a helysz\u00EDn "
            "alapj\u00E1n \u00E9rdemes meghat\u00E1rozni.\n\n"
            "Ha megadod a m\u00B2-t, a munka t\u00EDpus\u00E1t "
            "\u00E9s az anyagk\u00F6lts\u00E9get, seg\u00EDtek "
            "kisz\u00E1molni az aj\u00E1nlatot."
        )

    elif (
        "le\u00EDr\u00E1s" in low
        or "munkale\u00EDr\u00E1s" in low
    ):

        answer = (
            "\U0001F916 Munkale\u00EDr\u00E1s minta:\n\n"
            "A munkater\u00FClet el\u0151k\u00E9sz\u00EDt\u00E9se, "
            "a sz\u00FCks\u00E9ges jav\u00EDt\u00E1sok elv\u00E9gz\u00E9se, "
            "alapoz\u00E1s \u00E9s a megadott fel\u00FCletek "
            "szakszer\u0171 fest\u00E9se, majd a munkater\u00FClet "
            "tiszta \u00E1tad\u00E1sa."
        )

    else:

        answer = (
            "\U0001F916 \u00CDrd le konkr\u00E9tan, mit szeretn\u00E9l "
            "kisz\u00E1molni vagy megfogalmazni, "
            "\u00E9s seg\u00EDtek az aj\u00E1nlat elk\u00E9sz\u00EDt\u00E9s\u00E9ben."
        )

    context.user_data.pop(
        "state",
        None
    )

    await update.message.reply_text(
        answer,
        reply_markup=main_keyboard()
    )


# ============================================================
# SEGÍTSÉG
# ============================================================

async def help_menu(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "\U0001F198 <b>Seg\u00EDts\u00E9g</b>\n\n"
        "1. T\u00F6ltsd ki a C\u00E9gadatokat.\n"
        "2. Akt\u00EDv el\u0151fizet\u00E9ssel k\u00E9sz\u00EDts "
        "\u00FAj aj\u00E1nlatot.\n"
        "3. Az elk\u00E9sz\u00FClt aj\u00E1nlat automatikusan "
        "ment\u00E9sre ker\u00FCl.\n"
        "4. A PDF-et k\u00F6zvetlen\u00FCl Telegramon "
        "k\u00E9rheted.\n"
        "5. A kor\u00E1bbi aj\u00E1nlatokat az Aj\u00E1nlataim "
        "men\u00FCben tal\u00E1lod.\n\n"
        "Az adatokat a bot SQLite adatb\u00E1zisban t\u00E1rolja.",
        parse_mode="HTML",
        reply_markup=back_keyboard()
    )


# ============================================================
# ELŐFIZETÉS / FIZETÉS
# ============================================================

async def subscription_menu(update, context):

    query = update.callback_query

    await query.answer()

    text = (
        "\U0001F4B3 <b>El\u0151fizet\u00E9s</b>\n\n"
        + subscription_text(
            update.effective_user.id
        )
        + "\n\nV\u00E1lassz csomagot:"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "\U0001F535 PRO \u2013 6 500 Ft / 7 nap",
                callback_data="buy_pro"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F7E3 PRO+ \u2013 20 000 Ft / h\u00F3",
                callback_data="buy_plus"
            )
        ],

        [
            InlineKeyboardButton(
                "\U0001F4CA Saj\u00E1t el\u0151fizet\u00E9sem",
                callback_data="status"
            )
        ],

        [
            InlineKeyboardButton(
                "\u2B05\uFE0F F\u0151men\u00FC",
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
# JAVÍTOTT PRO FIZETÉS
# ============================================================

async def buy_pro(update, context):

    query = update.callback_query

    try:

        await query.answer()

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=(
                "\U0001F916 AI \u00C1raj\u00E1nlat Pro \u2013 PRO"
            ),
            description=(
                "7 napos hozz\u00E1f\u00E9r\u00E9s az "
                "AI \u00C1raj\u00E1nlat Pro szolg\u00E1ltat\u00E1shoz."
            ),
            payload="ai_arajanlat_pro_7_nap",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="PRO \u2013 7 nap",
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
                "A fizet\u00E9s ind\u00EDt\u00E1sa nem siker\u00FClt.",
                show_alert=True
            )

        except Exception:
            pass


# ============================================================
# JAVÍTOTT PRO+ FIZETÉS
# ============================================================

async def buy_plus(update, context):

    query = update.callback_query

    try:

        await query.answer()

        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=(
                "\U0001F916 AI \u00C1raj\u00E1nlat Pro \u2013 PRO+"
            ),
            description=(
                "30 napos hozz\u00E1f\u00E9r\u00E9s az "
                "AI \u00C1raj\u00E1nlat Pro+ szolg\u00E1ltat\u00E1shoz."
            ),
            payload="ai_arajanlat_pro_plus_30_nap",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="PRO+ \u2013 30 nap",
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
                "A fizet\u00E9s ind\u00EDt\u00E1sa nem siker\u00FClt.",
                show_alert=True
            )

        except Exception:
            pass


# ============================================================
# ELŐFIZETÉS ELLENŐRZÉS
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
                    "A fizet\u00E9st nem siker\u00FClt "
                    "ellen\u0151rizni. Pr\u00F3b\u00E1ld \u00FAjra."
                )
            )

        except Exception:
            pass


# ============================================================
# SIKERES FIZETÉS
# ============================================================

async def successful_payment(update, context):

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
        "\u2705 Sikeres fizet\u00E9s!\n\n"
        f"\U0001F4E6 {plan}\n"
        f"\U0001F4C5 \u00C9rv\u00E9nyes eddig: "
        f"{expires_at.strftime('%Y.%m.%d. %H:%M')}\n\n"
        "Most m\u00E1r haszn\u00E1lhatod az "
        "AI \u00C1raj\u00E1nlat Pro funkci\u00F3it.",
        reply_markup=main_keyboard()
    )


# ============================================================
# ELŐFIZETÉS STÁTUSZ
# ============================================================

async def status(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "\U0001F4CA <b>Saj\u00E1t el\u0151fizet\u00E9sem</b>\n\n"
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
        "\U0001F4C4 Felhaszn\u00E1l\u00E1si felt\u00E9telek\n\n"
        "Az AI \u00C1raj\u00E1nlat Pro digit\u00E1lis szolg\u00E1ltat\u00E1s. "
        "A v\u00E1s\u00E1rl\u00E1s Telegram Stars haszn\u00E1lat\u00E1val "
        "t\u00F6rt\u00E9nik."
    )


async def paysupport(update, context):

    await update.message.reply_text(
        "\U0001F4B3 Fizet\u00E9si seg\u00EDts\u00E9g\n\n"
        "Ha fizet\u00E9si probl\u00E9m\u00E1d van, \u00EDrd le pontosan, "
        "mi t\u00F6rt\u00E9nt, \u00E9s seg\u00EDt\u00FCnk a hiba "
        "azonos\u00EDt\u00E1s\u00E1ban."
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

    # Új ajánlat
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

    # Cégadatok
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
                "\u26A0\uFE0F Minden mez\u0151 k\u00F6telez\u0151.\n\n"
                "K\u00E9rlek, \u00EDgy k\u00FCldd el:\n\n"
                "C\u00E9gn\u00E9v: ...\n"
                "Telefonsz\u00E1m: ...\n"
                "E-mail: ...\n"
                "C\u00EDm: ...\n"
                "Ad\u00F3sz\u00E1m: ...",
                reply_markup=cancel_keyboard()
            )

            return

        save_company_data(
            update.effective_user.id,
            data
        )

        context.user_data.clear()

        await update.message.reply_text(
            "\u2705 C\u00E9gadatok elmentve!\n\n"
            + company_display(data),
            reply_markup=main_keyboard()
        )

        return

    # AI
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
        "V\u00E1lassz egy funkci\u00F3t a men\u00FCb\u0151l.",
        reply_markup=main_keyboard()
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(update, context):

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

    elif data == "quotes":

        await quotes_menu(
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
# HIBA ESEMÉNYNAPLÓ
# ============================================================

async def error_handler(update, context):

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

    # Parancsok
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

    # Fizetés
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

    # Gombok
    app.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Szöveges üzenetek
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    # Hibák naplózása
    app.add_error_handler(
        error_handler
    )

    print(
        "AI Arjanlat Pro started"
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":

    main()
