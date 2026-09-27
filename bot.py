import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, PreCheckoutQueryHandler, filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
DB_FILE = "arajanlat.db"

PRO_STARS = 1000
PRO_PLUS_STARS = 3000
PRO_DAYS = 7
PRO_PLUS_DAYS = 30
SUBSCRIPTION_PERIOD = 2592000

# -------------------- WEB HEALTH --------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"AI Arjanlat Pro is running!")

    def log_message(self, format, *args):
        return


def run_web_server():
    HTTPServer(("0.0.0.0", PORT), HealthHandler).serve_forever()

# -------------------- DATABASE --------------------
def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        name TEXT NOT NULL, phone TEXT, address TEXT, created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS quotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        client_name TEXT, phone TEXT, address TEXT, work TEXT,
        quantity TEXT, price REAL, material REAL, total REAL, deadline TEXT,
        quote_number TEXT, created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        plan TEXT, stars INTEGER, expires_at TEXT, is_recurring INTEGER DEFAULT 0,
        charge_id TEXT, created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS company_data (
        user_id INTEGER PRIMARY KEY, company_name TEXT, phone TEXT, email TEXT,
        address TEXT, tax_number TEXT, updated_at TEXT
    )""")
    # Migration for older installations.
    cols = {r[1] for r in cur.execute("PRAGMA table_info(quotes)").fetchall()}
    if "total" not in cols:
        cur.execute("ALTER TABLE quotes ADD COLUMN total REAL DEFAULT 0")
    if "quote_number" not in cols:
        cur.execute("ALTER TABLE quotes ADD COLUMN quote_number TEXT")
    conn.commit()
    conn.close()


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def money(v):
    try:
        return f"{float(v):,.0f}".replace(",", " ") + " Ft"
    except Exception:
        return "0 Ft"


def parse_number(s):
    s = str(s).strip().lower().replace("ft", "").replace("huf", "")
    s = s.replace(" ", "").replace(".", "").replace(",", ".")
    return float(s)


def next_quote_number(user_id):
    conn = db()
    row = conn.execute("SELECT COUNT(*) AS n FROM quotes WHERE user_id=?", (user_id,)).fetchone()
    n = int(row["n"] or 0) + 1
    conn.close()
    return f"AJ-{datetime.now().strftime('%Y%m%d')}-{n:04d}"

# -------------------- SUBSCRIPTIONS --------------------
def get_active_subscription(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        expires = datetime.fromisoformat(row["expires_at"])
        if expires > datetime.now():
            return row
    except Exception:
        pass
    return None


def subscription_text(user_id):
    sub = get_active_subscription(user_id)
    if not sub:
        return "â Nincs aktÃ­v elÅfizetÃ©sed."
    exp = datetime.fromisoformat(sub["expires_at"]).strftime("%Y.%m.%d. %H:%M")
    recurring = "Igen" if sub["is_recurring"] else "Nem"
    return (
        f"â AktÃ­v elÅfizetÃ©s\n\n"
        f"ð¦ Csomag: {sub['plan']}\n"
        f"â­ Stars: {sub['stars']}\n"
        f"ð LejÃ¡rat: {exp}\n"
        f"ð Automatikus megÃºjÃ­tÃ¡s: {recurring}"
    )


async def require_subscription(update, context):
    user_id = update.effective_user.id
    if get_active_subscription(user_id):
        return True
    text = (
        "ð Ez a funkciÃ³ aktÃ­v elÅfizetÃ©shez kÃ¶tÃ¶tt.\n\n"
        "Az AI ÃrajÃ¡nlat Pro hasznÃ¡latÃ¡hoz vÃ¡lassz egy elÅfizetÃ©st.\n\n"
        "ðµ PRO â 6 500 Ft / 7 nap\n"
        "ð£ PRO+ â 20 000 Ft / hÃ³"
    )
    kb = [[InlineKeyboardButton("ð³ ElÅfizetÃ©sek", callback_data="subscription")]]
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return False

# -------------------- COMPANY DATA --------------------
def parse_company_data(text):
    data = {}
    labels = {
        "cÃ©gnÃ©v": "company_name", "cegnev": "company_name",
        "telefonszÃ¡m": "phone", "telefonszam": "phone",
        "e-mail": "email", "email": "email",
        "cÃ­m": "address", "cim": "address",
        "adÃ³szÃ¡m": "tax_number", "adoszam": "tax_number",
    }
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        if k in labels:
            data[labels[k]] = v.strip()
    return data


def get_company_data(user_id):
    conn = db()
    row = conn.execute("SELECT * FROM company_data WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_company_data(user_id, data):
    conn = db()
    conn.execute("""INSERT INTO company_data(user_id,company_name,phone,email,address,tax_number,updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET company_name=excluded.company_name,
        phone=excluded.phone,email=excluded.email,address=excluded.address,
        tax_number=excluded.tax_number,updated_at=excluded.updated_at""",
        (user_id, data["company_name"], data["phone"], data["email"], data["address"], data["tax_number"], now_str()))
    conn.commit(); conn.close()


def company_display(data):
    return (
        f"ð¢ CÃ©gnÃ©v: {data['company_name']}\n"
        f"ð Telefon: {data['phone']}\n"
        f"ð§ E-mail: {data['email']}\n"
        f"ð  CÃ­m: {data['address']}\n"
        f"ð§¾ AdÃ³szÃ¡m: {data['tax_number']}"
    )

# -------------------- PDF --------------------
def create_pdf(quote, company, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    font = "Helvetica"
    for fp, name in [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf", "LiberationSans"),
    ]:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont(name, fp)); font = name; break
            except Exception:
                pass

    doc = SimpleDocTemplate(path, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=styles["Title"], fontName=font, fontSize=20, alignment=TA_CENTER, spaceAfter=8)
    normal = ParagraphStyle("normal", parent=styles["Normal"], fontName=font, fontSize=9, leading=13)
    right = ParagraphStyle("right", parent=normal, alignment=TA_RIGHT)
    story = [Paragraph("ÃRAJÃNLAT", title)]
    company_block = (
        f"<b>{company['company_name']}</b><br/>{company['address']}<br/>"
        f"Tel.: {company['phone']}<br/>E-mail: {company['email']}<br/>AdÃ³szÃ¡m: {company['tax_number']}"
    )
    customer_block = (
        f"<b>ÃgyfÃ©l</b><br/>{quote['client_name']}<br/>Tel.: {quote['phone']}<br/>"
        f"CÃ­m: {quote['address']}"
    )
    info = Table([[Paragraph(company_block, normal), Paragraph(customer_block, normal)]], colWidths=[90*mm, 75*mm])
    info.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("BOX", (0,0), (-1,-1), .5, colors.grey),
                              ("INNERGRID", (0,0), (-1,-1), .25, colors.lightgrey), ("PADDING", (0,0), (-1,-1), 7)]))
    story += [info, Spacer(1, 8)]
    story.append(Paragraph(f"AjÃ¡nlatszÃ¡m: <b>{quote['quote_number']}</b> &nbsp;&nbsp; DÃ¡tum: {quote['created_at']}", normal))
    story.append(Spacer(1, 8))
    rows = [
        [Paragraph("Munka", normal), Paragraph("MennyisÃ©g", normal), Paragraph("MunkadÃ­j", normal), Paragraph("Anyag", normal), Paragraph("Ãsszesen", normal)],
        [Paragraph(quote['work'], normal), Paragraph(str(quote['quantity']), normal), Paragraph(money(quote['price']), right),
         Paragraph(money(quote['material']), right), Paragraph(money(quote['total']), right)],
    ]
    table = Table(rows, colWidths=[60*mm, 25*mm, 27*mm, 27*mm, 27*mm], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#eeeeee")),
                               ("GRID", (0,0), (-1,-1), .5, colors.grey), ("VALIGN", (0,0), (-1,-1), "TOP"),
                               ("PADDING", (0,0), (-1,-1), 6)]))
    story += [table, Spacer(1, 10), Paragraph(f"<b>VÃ©gÃ¶sszeg: {money(quote['total'])}</b>", ParagraphStyle("total", parent=right, fontName=font, fontSize=13)),
              Spacer(1, 8), Paragraph(f"Tervezett hatÃ¡ridÅ: <b>{quote['deadline']}</b>", normal), Spacer(1, 18),
              Paragraph("Az ajÃ¡nlat a megadott adatok alapjÃ¡n kÃ©szÃ¼lt. A vÃ©gleges munkadÃ­j a helyszÃ­ni felmÃ©rÃ©s Ã©s az esetleges vÃ¡ltoztatÃ¡sok fÃ¼ggvÃ©nyÃ©ben mÃ³dosulhat.", normal)]
    doc.build(story)

# -------------------- KEYBOARDS --------------------
def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ð Ãj Ã¡rajÃ¡nlat", callback_data="new_quote")],
        [InlineKeyboardButton("ð¥ Ãgyfeleim", callback_data="clients"), InlineKeyboardButton("ð AjÃ¡nlataim", callback_data="quotes")],
        [InlineKeyboardButton("ð¤ AI SegÃ­tÅ", callback_data="ai_help")],
        [InlineKeyboardButton("âï¸ CÃ©gadatok", callback_data="company")],
        [InlineKeyboardButton("ð³ ElÅfizetÃ©sem", callback_data="subscription")],
        [InlineKeyboardButton("ð SegÃ­tsÃ©g", callback_data="help")],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("â¬ï¸ FÅmenÃ¼", callback_data="menu")]])


def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("â MegszakÃ­tÃ¡s", callback_data="cancel")]])

# -------------------- START / MENU --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "ð¤ <b>AI ÃrajÃ¡nlat Pro</b>\n\nKÃ©szÃ­ts professzionÃ¡lis Ã¡rajÃ¡nlatokat gyorsan Ã©s egyszerÅ±en.",
        parse_mode="HTML", reply_markup=main_keyboard())

async def menu_callback(update, context):
    q = update.callback_query; await q.answer(); context.user_data.clear()
    await q.edit_message_text("ð¤ <b>AI ÃrajÃ¡nlat Pro</b>\n\nVÃ¡lassz egy funkciÃ³t:", parse_mode="HTML", reply_markup=main_keyboard())

async def cancel(update, context):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("â MegszakÃ­tva.", reply_markup=main_keyboard())
    else:
        await update.message.reply_text("â MegszakÃ­tva.", reply_markup=main_keyboard())

# -------------------- COMPANY --------------------
async def company_menu(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer()
    data = get_company_data(update.effective_user.id)
    if data:
        text = "âï¸ <b>CÃ©gadatok</b>\n\n" + company_display(data)
        kb = [[InlineKeyboardButton("âï¸ MÃ³dosÃ­tÃ¡s", callback_data="company_edit")], [InlineKeyboardButton("â¬ï¸ FÅmenÃ¼", callback_data="menu")]]
    else:
        text = "âï¸ <b>CÃ©gadatok</b>\n\nMÃ©g nincsenek elmentett cÃ©gadataid.\n\nKÃ¼ldd el egy Ã¼zenetben az alÃ¡bbi formÃ¡ban:\n\nCÃ©gnÃ©v: ...\nTelefonszÃ¡m: ...\nE-mail: ...\nCÃ­m: ...\nAdÃ³szÃ¡m: ..."
        kb = [[InlineKeyboardButton("â¬ï¸ FÅmenÃ¼", callback_data="menu")]]
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def company_edit(update, context):
    q = update.callback_query; await q.answer()
    context.user_data["state"] = "company"
    await q.edit_message_text("âï¸ KÃ¼ldd el a cÃ©gadataidat egyetlen Ã¼zenetben:\n\nCÃ©gnÃ©v: ...\nTelefonszÃ¡m: ...\nE-mail: ...\nCÃ­m: ...\nAdÃ³szÃ¡m: ...", reply_markup=cancel_keyboard())

# -------------------- QUOTE FLOW --------------------
QUOTE_STEPS = ["name", "phone", "address", "work", "quantity", "price", "material", "deadline"]
PROMPTS = {
    "name": "1/8 ð¤ ÃgyfÃ©l neve:",
    "phone": "2/8 ð TelefonszÃ¡m:",
    "address": "3/8 ð  ÃgyfÃ©l cÃ­me:",
    "work": "4/8 ð ï¸ Milyen munkÃ¡ra kÃ©szÃ¼l az ajÃ¡nlat?",
    "quantity": "5/8 ð MennyisÃ©g (pl. 80 mÂ²):",
    "price": "6/8 ð° MunkadÃ­j (Ft):",
    "material": "7/8 ð§± AnyagkÃ¶ltsÃ©g (Ft):",
    "deadline": "8/8 ð HatÃ¡ridÅ (pl. 2026. oktÃ³ber 15.):",
}

async def new_quote(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer()
    context.user_data.clear(); context.user_data["state"] = "quote:name"
    await q.edit_message_text(PROMPTS["name"], reply_markup=cancel_keyboard())

async def handle_quote_text(update, context, state):
    text = update.message.text.strip()
    field = state.split(":", 1)[1]
    if field == "price" or field == "material":
        try:
            value = parse_number(text)
        except Exception:
            await update.message.reply_text("â ï¸ Ãrj be Ã©rvÃ©nyes Ã¶sszeget, pÃ©ldÃ¡ul: 250000", reply_markup=cancel_keyboard()); return
        context.user_data[field] = value
    else:
        context.user_data[field] = text
    idx = QUOTE_STEPS.index(field)
    if idx < len(QUOTE_STEPS)-1:
        nxt = QUOTE_STEPS[idx+1]
        context.user_data["state"] = "quote:" + nxt
        await update.message.reply_text(PROMPTS[nxt], reply_markup=cancel_keyboard())
        return
    await finish_quote(update, context)

async def finish_quote(update, context):
    uid = update.effective_user.id
    if not get_active_subscription(uid):
        context.user_data.clear(); await update.message.reply_text("ð Az elÅfizetÃ©sed lejÃ¡rt.", reply_markup=main_keyboard()); return
    d = context.user_data
    quote_number = next_quote_number(uid)
    total = float(d["price"]) + float(d["material"])
    created = datetime.now().strftime("%Y.%m.%d.")
    conn = db()
    conn.execute("INSERT INTO clients(user_id,name,phone,address,created_at) VALUES(?,?,?,?,?)",
                 (uid,d["name"],d["phone"],d["address"],now_str()))
    conn.execute("INSERT INTO quotes(user_id,client_name,phone,address,work,quantity,price,material,total,deadline,quote_number,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (uid,d["name"],d["phone"],d["address"],d["work"],d["quantity"],d["price"],d["material"],total,d["deadline"],quote_number,created))
    quote_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit(); conn.close()
    context.user_data.clear()
    text = (f"â <b>ÃrajÃ¡nlat elkÃ©szÃ¼lt</b>\n\nð¢ {quote_number}\nð¤ {d['name']}\nð {d['phone']}\nð  {d['address']}\n\n"
            f"ð ï¸ {d['work']}\nð {d['quantity']}\nð° MunkadÃ­j: {money(d['price'])}\nð§± Anyag: {money(d['material'])}\n"
            f"ðµ <b>VÃ©gÃ¶sszeg: {money(total)}</b>\nð HatÃ¡ridÅ: {d['deadline']}")
    kb = [[InlineKeyboardButton("ð PDF elkÃ¼ldÃ©se", callback_data=f"pdf:{quote_id}")],
          [InlineKeyboardButton("ð AjÃ¡nlataim", callback_data="quotes"), InlineKeyboardButton("â¬ï¸ FÅmenÃ¼", callback_data="menu")]]
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

# -------------------- CLIENTS --------------------
async def clients_menu(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer()
    uid = update.effective_user.id
    conn = db(); rows = conn.execute("SELECT * FROM clients WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall(); conn.close()
    if not rows:
        await q.edit_message_text("ð¥ MÃ©g nincs mentett Ã¼gyfeled.", reply_markup=back_keyboard()); return
    text = "ð¥ <b>Ãgyfeleim</b>\n\n" + "\n\n".join(f"<b>{r['name']}</b>\nð {r['phone']}\nð  {r['address']}" for r in rows)
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=back_keyboard())

# -------------------- QUOTES --------------------
async def quotes_menu(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer()
    uid = update.effective_user.id
    conn = db(); rows = conn.execute("SELECT * FROM quotes WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall(); conn.close()
    if not rows:
        await q.edit_message_text("ð MÃ©g nincs mentett ajÃ¡nlatod.", reply_markup=back_keyboard()); return
    buttons = []
    for r in rows:
        buttons.append([InlineKeyboardButton(f"{r['quote_number']} â {r['client_name']}", callback_data=f"quote:{r['id']}")])
    buttons.append([InlineKeyboardButton("â¬ï¸ FÅmenÃ¼", callback_data="menu")])
    await q.edit_message_text("ð <b>AjÃ¡nlataim</b>\n\nVÃ¡lassz egy ajÃ¡nlatot:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))

async def quote_detail(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer()
    qid = int(q.data.split(":")[1]); uid = update.effective_user.id
    conn = db(); r = conn.execute("SELECT * FROM quotes WHERE id=? AND user_id=?", (qid,uid)).fetchone(); conn.close()
    if not r:
        await q.edit_message_text("â Az ajÃ¡nlat nem talÃ¡lhatÃ³.", reply_markup=back_keyboard()); return
    text = (f"ð <b>{r['quote_number']}</b>\n\nð¤ {r['client_name']}\nð {r['phone']}\nð  {r['address']}\n\n"
            f"ð ï¸ {r['work']}\nð {r['quantity']}\nð° MunkadÃ­j: {money(r['price'])}\nð§± Anyag: {money(r['material'])}\n"
            f"ðµ <b>Ãsszesen: {money(r['total'])}</b>\nð HatÃ¡ridÅ: {r['deadline']}\nð KÃ©szÃ¼lt: {r['created_at']}")
    kb = [[InlineKeyboardButton("ð PDF elkÃ¼ldÃ©se", callback_data=f"pdf:{qid}")],
          [InlineKeyboardButton("â¬ï¸ AjÃ¡nlataim", callback_data="quotes")]]
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def send_pdf(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer("PDF kÃ©szÃ¼l...")
    qid = int(q.data.split(":")[1]); uid = update.effective_user.id
    conn = db(); r = conn.execute("SELECT * FROM quotes WHERE id=? AND user_id=?", (qid,uid)).fetchone(); conn.close()
    if not r:
        await q.message.reply_text("â Az ajÃ¡nlat nem talÃ¡lhatÃ³."); return
    company = get_company_data(uid)
    if not company:
        await q.message.reply_text("â ï¸ ElÅbb tÃ¶ltsd ki a CÃ©gadatokat, hogy a PDF fejlÃ©cÃ©ben megjelenhessenek.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("âï¸ CÃ©gadatok", callback_data="company")]])); return
    path = f"/tmp/{r['quote_number']}.pdf"
    try:
        create_pdf(dict(r), company, path)
        with open(path, "rb") as f:
            await q.message.reply_document(document=f, filename=f"{r['quote_number']}.pdf", caption=f"ð ÃrajÃ¡nlat: {r['quote_number']}")
    except Exception as e:
        await q.message.reply_text(f"â A PDF elkÃ©szÃ­tÃ©se nem sikerÃ¼lt: {e}")
    finally:
        try: os.remove(path)
        except OSError: pass

# -------------------- AI HELPER --------------------
async def ai_help(update, context):
    if not await require_subscription(update, context): return
    q = update.callback_query; await q.answer()
    context.user_data["state"] = "ai"
    await q.edit_message_text(
        "ð¤ <b>AI SegÃ­tÅ</b>\n\nÃrd le, miben segÃ­tsek az Ã¡rajÃ¡nlatoddal kapcsolatban.\n\n"
        "PÃ©ldÃ¡ul: âMennyit kÃ©rjek 80 mÂ² tisztasÃ¡gi festÃ©sÃ©rt?â vagy âÃrj rÃ¶vid munkaleÃ­rÃ¡st festÃ©shez.â",
        parse_mode="HTML", reply_markup=cancel_keyboard())

async def ai_answer(update, context):
    # Local helper that works without an external API. It intentionally does not invent live market prices.
    text = update.message.text.strip()
    low = text.lower()
    if any(x in low for x in ["Ã¡r", "mennyi", "mennyit", "ft"]):
        answer = ("ð¤ ÃrajÃ¡nlati tipp:\n\nA pontos munkadÃ­jat a terÃ¼let, felÃ¼let Ã¡llapota, rÃ©tegrend, javÃ­tÃ¡sok, "
                  "anyagminÅsÃ©g Ã©s helyszÃ­n alapjÃ¡n Ã©rdemes meghatÃ¡rozni. Ha megadod a mÂ²-t, a munka tÃ­pusÃ¡t Ã©s "
                  "az anyagkÃ¶ltsÃ©get, kiszÃ¡molom a vÃ©gÃ¶sszeget az ajÃ¡nlatodhoz.")
    elif "leÃ­rÃ¡s" in low or "munkaleÃ­rÃ¡s" in low:
        answer = "ð¤ MunkaleÃ­rÃ¡s minta:\n\nA munkaterÃ¼let elÅkÃ©szÃ­tÃ©se, szÃ¼ksÃ©ges javÃ­tÃ¡sok elvÃ©gzÃ©se, alapozÃ¡s Ã©s a megadott felÃ¼letek szakszerÅ± festÃ©se, majd a munkaterÃ¼let tisztÃ¡n Ã¡tadÃ¡sa."
    else:
        answer = "ð¤ Ãrd le konkrÃ©tan, mit szeretnÃ©l kiszÃ¡molni vagy megfogalmazni, Ã©s segÃ­tek az ajÃ¡nlat elkÃ©szÃ­tÃ©sÃ©ben."
    context.user_data.pop("state", None)
    await update.message.reply_text(answer, reply_markup=main_keyboard())

# -------------------- HELP / PAYMENTS --------------------
async def help_menu(update, context):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "ð <b>SegÃ­tsÃ©g</b>\n\n"
        "1. TÃ¶ltsd ki a CÃ©gadatokat.\n"
        "2. AktÃ­v elÅfizetÃ©ssel kÃ©szÃ­ts Ãºj ajÃ¡nlatot.\n"
        "3. Az elkÃ©szÃ¼lt ajÃ¡nlat elmentÅdik.\n"
        "4. PDF-et kÃ¶zvetlenÃ¼l Telegramon kÃ©rhetsz.\n"
        "5. A korÃ¡bbi ajÃ¡nlatok az AjÃ¡nlataim menÃ¼ben Ã©rhetÅk el.\n\n"
        "A bot az adatokat SQLite adatbÃ¡zisban tÃ¡rolja.", parse_mode="HTML", reply_markup=back_keyboard())

async def subscription_menu(update, context):
    q = update.callback_query; await q.answer()
    text = "ð³ <b>ElÅfizetÃ©s</b>\n\n" + subscription_text(update.effective_user.id) + "\n\nVÃ¡lassz csomagot:"
    kb = [[InlineKeyboardButton("ðµ PRO â 7 nap", callback_data="buy_pro")],
          [InlineKeyboardButton("ð£ PRO+ â 30 nap", callback_data="buy_plus")],
          [InlineKeyboardButton("ð SajÃ¡t elÅfizetÃ©sem", callback_data="status")],
          [InlineKeyboardButton("â¬ï¸ FÅmenÃ¼", callback_data="menu")]]
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))

async def buy_pro(update, context):
    q = update.callback_query; await q.answer()
    await context.bot.send_invoice(update.effective_chat.id, "AI ÃrajÃ¡nlat Pro â PRO", "7 napos hozzÃ¡fÃ©rÃ©s", "AI ÃrajÃ¡nlat Pro PRO", "", "XTR", [LabeledPrice("PRO â 7 nap", PRO_STARS)])

async def buy_plus(update, context):
    q = update.callback_query; await q.answer()
    await context.bot.send_invoice(update.effective_chat.id, "AI ÃrajÃ¡nlat Pro â PRO+", "30 napos hozzÃ¡fÃ©rÃ©s", "AI ÃrajÃ¡nlat Pro PRO+", "", "XTR", [LabeledPrice("PRO+ â 30 nap", PRO_PLUS_STARS)], subscription_period=SUBSCRIPTION_PERIOD)

async def precheckout(update, context):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update, context):
    p = update.message.successful_payment
    uid = update.effective_user.id
    plan = "PRO+" if p.total_amount == PRO_PLUS_STARS else "PRO"
    days = PRO_PLUS_DAYS if plan == "PRO+" else PRO_DAYS
    expires = getattr(p, "subscription_expiration_date", None)
    if expires:
        try:
            expires_dt = datetime.fromtimestamp(expires)
        except Exception:
            expires_dt = datetime.now() + timedelta(days=days)
    else:
        expires_dt = datetime.now() + timedelta(days=days)
    recurring = 1 if plan == "PRO+" else 0
    charge = getattr(p, "telegram_payment_charge_id", "")
    conn = db()
    conn.execute("INSERT INTO subscriptions(user_id,plan,stars,expires_at,is_recurring,charge_id,created_at) VALUES(?,?,?,?,?,?,?)",
                 (uid,plan,p.total_amount,expires_dt.isoformat(),recurring,charge,now_str()))
    conn.commit(); conn.close()
    await update.message.reply_text(f"â Sikeres fizetÃ©s!\n\nð¦ {plan}\nð ÃrvÃ©nyes eddig: {expires_dt.strftime('%Y.%m.%d. %H:%M')}\n\nMost mÃ¡r hasznÃ¡lhatod az AI ÃrajÃ¡nlat Pro funkciÃ³it.", reply_markup=main_keyboard())

async def status(update, context):
    q = update.callback_query; await q.answer()
    await q.edit_message_text("ð <b>SajÃ¡t elÅfizetÃ©sem</b>\n\n" + subscription_text(update.effective_user.id), parse_mode="HTML", reply_markup=back_keyboard())

async def terms(update, context):
    await update.message.reply_text("ð FelhasznÃ¡lÃ¡si feltÃ©telek\n\nAz AI ÃrajÃ¡nlat Pro digitÃ¡lis szolgÃ¡ltatÃ¡s. A vÃ¡sÃ¡rlÃ¡s Telegram Stars hasznÃ¡latÃ¡val tÃ¶rtÃ©nik.")

async def paysupport(update, context):
    await update.message.reply_text("ð³ FizetÃ©si segÃ­tsÃ©g\n\nHa fizetÃ©si problÃ©mÃ¡d van, Ã­rd le pontosan, mi tÃ¶rtÃ©nt, Ã©s segÃ­tÃ¼nk a hiba azonosÃ­tÃ¡sÃ¡ban.")

# -------------------- TEXT ROUTER --------------------
async def text_handler(update, context):
    if not update.message or not update.message.text:
        return
    state = context.user_data.get("state", "")
    if state.startswith("quote:"):
        if await require_subscription(update, context):
            await handle_quote_text(update, context, state)
        return
    if state == "company":
        if not await require_subscription(update, context): return
        data = parse_company_data(update.message.text)
        required = ["company_name", "phone", "email", "address", "tax_number"]
        if any(not data.get(k) for k in required):
            await update.message.reply_text("â ï¸ Minden mezÅ kÃ¶telezÅ. KÃ©rlek, Ã­gy kÃ¼ldd el:\n\nCÃ©gnÃ©v: ...\nTelefonszÃ¡m: ...\nE-mail: ...\nCÃ­m: ...\nAdÃ³szÃ¡m: ...", reply_markup=cancel_keyboard()); return
        save_company_data(update.effective_user.id, data); context.user_data.clear()
        await update.message.reply_text("â CÃ©gadatok elmentve!\n\n" + company_display(data), reply_markup=main_keyboard()); return
    if state == "ai":
        if await require_subscription(update, context): await ai_answer(update, context)
        return
    await update.message.reply_text("VÃ¡lassz egy funkciÃ³t a menÃ¼bÅl.", reply_markup=main_keyboard())

# -------------------- CALLBACK ROUTER --------------------
async def callback_router(update, context):
    data = update.callback_query.data
    if data == "menu": await menu_callback(update, context)
    elif data == "cancel": await cancel(update, context)
    elif data == "new_quote": await new_quote(update, context)
    elif data == "clients": await clients_menu(update, context)
    elif data == "quotes": await quotes_menu(update, context)
    elif data.startswith("quote:"): await quote_detail(update, context)
    elif data.startswith("pdf:"): await send_pdf(update, context)
    elif data == "ai_help": await ai_help(update, context)
    elif data == "company": await company_menu(update, context)
    elif data == "company_edit": await company_edit(update, context)
    elif data == "help": await help_menu(update, context)
    elif data == "subscription": await subscription_menu(update, context)
    elif data == "buy_pro": await buy_pro(update, context)
    elif data == "buy_plus": await buy_plus(update, context)
    elif data == "status": await status(update, context)

# -------------------- MAIN --------------------
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")
    init_db()
    threading.Thread(target=run_web_server, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("terms", terms))
    app.add_handler(CommandHandler("paysupport", paysupport))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("AI ÃrajÃ¡nlat Pro started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
