import asyncio
import html
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, Message, ReplyKeyboardMarkup
)

# ============================================================
# SAFIYA / XOBUNACHI BOT — PYTHON + AIOGRAM 3
# GitHub/Python hosting uchun bitta faylli, SQLite asosidagi versiya.
# TOKEN va ADMIN_IDS ni GitHub Secrets / Environment Variables orqali bering.
# ============================================================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("safiya")

BASE = Path(__file__).resolve().parent
DB_FILE = BASE / "bot.db"

TOKEN = os.getenv("BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", "")).strip()
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

# Ixtiyoriy media File ID lar. Telegramdan bir marta olingan file_id ni Secretga qo'yish mumkin.
WELCOME_VOICE = os.getenv("WELCOME_VOICE_FILE_ID", "").strip()
GAME_PHOTO_IDS = {
    "lotoriya": os.getenv("GAME_LOTORIYA_FILE_ID", "").strip(),
    "darts": os.getenv("GAME_DARTS_FILE_ID", "").strip(),
    "basketbol": os.getenv("GAME_BASKETBOL_FILE_ID", "").strip(),
    "domino": os.getenv("GAME_DOMINO_FILE_ID", "").strip(),
    "bowling": os.getenv("GAME_BOWLING_FILE_ID", "").strip(),
    "bomba": os.getenv("GAME_BOMBA_FILE_ID", "").strip(),
}

DEFAULTS = {
    "currency": "₽",
    "channel": "@Safiyaobunachi",
    "channel_link": "https://t.me/Safiyaobunachi",
    "group": "",
    "post_channel": "",
    "subscription_channel": "",
    "post_reward": "0.15",
    "subscription_reward": "1",
    "group_reward": "0.50",
    "ref_reward": "2",
    "bonus_amount": "0.6",
    "fine_amount": "2",
    "min_order": "10",
    "max_order": "10000",
    "channel_order_price": "1",
    "group_order_price": "1",
    "faq": """❓ <b>Ko'p beriladigan savollar:</b>

⁉️ <b>Bot ishonchlimi?</b>
✅ <i>Botdan foydalanish bo'yicha barcha asosiy ma'lumotlar Yordam bo'limida berilgan.</i>

⁉️ <b>Hisobimni qanday to'ldiraman?</b>
✅ <i>Hisobim → Hisob to'ldirish bo'limidan mavjud usullardan foydalaning.</i>

⁉️ <b>Buyurtmam qancha vaqtda yakunlanadi?</b>
✅ <i>Buyurtma faol ishchilar soniga qarab bosqichma-bosqich bajariladi.</i>""",
    "rules": """⚠️ <b>Qoidalar</b>

• Adminga yolg'on xabar yubormang.
• Murojaat bo'limidan hurmat bilan foydalaning.
• To'lov va balans bo'yicha ma'lumotlarni diqqat bilan kiriting.
• Botdagi buyurtmalarni sun'iy ravishda buzishga urinmang.""",
}

# Original koddagi premium custom emoji ID lar saqlandi.
CE = {
    "ok": "5231212777175005525",
    "back": "5442609577130468928",
    "id": "5841276284155467413",
    "name": "6037220320060903412",
    "pin": "5895708410447401643",
    "key": "5228866754368784302",
    "go": "5460947592835778324",
    "eye": "5463249828450424568",
    "rocket": "5389057356493511934",
}

def pem(key: str, fallback: str) -> str:
    """Telegram premium/custom emoji. Oddiy emoji fallback bilan ishlaydi."""
    eid = CE.get(key)
    return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>' if eid else fallback

def esc(value) -> str:
    return html.escape(str(value), quote=False)

def money(value) -> str:
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "0"

# ------------------------- DATABASE -------------------------

class DB:
    def __init__(self, path: Path):
        self.path = path
        self.init()

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def init(self):
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance REAL DEFAULT 0,
                refs INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS states(
                user_id INTEGER PRIMARY KEY,
                state TEXT DEFAULT '',
                data TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS referrals(
                user_id INTEGER PRIMARY KEY,
                referrer_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS tasks(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                url TEXT NOT NULL,
                reward REAL NOT NULL,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS task_done(
                task_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY(task_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS orders(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                target TEXT NOT NULL,
                amount INTEGER NOT NULL,
                completed INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS order_workers(
                order_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY(order_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS viewed_posts(
                order_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY(order_id,user_id)
            );
            CREATE TABLE IF NOT EXISTS deposits(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            """)
            for k, v in DEFAULTS.items():
                c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))

    def setting(self, key):
        with self.connect() as c:
            row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else DEFAULTS.get(key, "")

    def set_setting(self, key, value):
        with self.connect() as c:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def user(self, uid):
        with self.connect() as c:
            return c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def upsert_user(self, user):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            c.execute("""INSERT INTO users(id,username,first_name,last_seen)
                         VALUES(?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET
                         username=excluded.username, first_name=excluded.first_name,
                         last_seen=excluded.last_seen""",
                      (user.id, user.username or "", user.first_name or "", now))

    def add_balance(self, uid, amount):
        with self.connect() as c:
            c.execute("UPDATE users SET balance=balance+? WHERE id=?", (float(amount), uid))

    def set_balance(self, uid, amount):
        with self.connect() as c:
            c.execute("UPDATE users SET balance=? WHERE id=?", (float(amount), uid))

    def all_user_ids(self):
        with self.connect() as c:
            return [r["id"] for r in c.execute("SELECT id FROM users").fetchall()]

    def count_users(self):
        with self.connect() as c:
            return c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]

    def state(self, uid):
        with self.connect() as c:
            r = c.execute("SELECT state,data FROM states WHERE user_id=?", (uid,)).fetchone()
            return (r["state"], r["data"]) if r else ("", "")

    def set_state(self, uid, state, data=""):
        with self.connect() as c:
            c.execute("""INSERT INTO states(user_id,state,data) VALUES(?,?,?)
                         ON CONFLICT(user_id) DO UPDATE SET state=excluded.state,data=excluded.data""",
                      (uid, state, data))

    def clear_state(self, uid):
        with self.connect() as c:
            c.execute("DELETE FROM states WHERE user_id=?", (uid,))

    def active_tasks(self):
        with self.connect() as c:
            return c.execute("SELECT * FROM tasks WHERE active=1 ORDER BY id").fetchall()

    def add_task(self, title, desc, url, reward):
        with self.connect() as c:
            return c.execute("INSERT INTO tasks(title,description,url,reward) VALUES(?,?,?,?)",
                             (title, desc, url, reward)).lastrowid

    def task_done(self, task_id, uid):
        with self.connect() as c:
            return c.execute("SELECT 1 FROM task_done WHERE task_id=? AND user_id=?", (task_id,uid)).fetchone() is not None

    def complete_task(self, task_id, uid):
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO task_done(task_id,user_id) VALUES(?,?)", (task_id,uid))

    def delete_task(self, task_id):
        with self.connect() as c:
            c.execute("UPDATE tasks SET active=0 WHERE id=?", (task_id,))

    def create_order(self, owner, kind, target, amount):
        with self.connect() as c:
            oid = c.execute("INSERT INTO orders(owner_id,kind,target,amount) VALUES(?,?,?,?)",
                            (owner,kind,target,amount)).lastrowid
            return oid

    def active_order(self, kind, worker):
        with self.connect() as c:
            rows = c.execute("""SELECT o.*,u.username owner_username
                                FROM orders o JOIN users u ON u.id=o.owner_id
                                WHERE o.kind=? AND o.active=1 AND o.completed < o.amount
                                ORDER BY o.id""", (kind,)).fetchall()
            for r in rows:
                if r["owner_id"] == worker:
                    continue
                if c.execute("SELECT 1 FROM order_workers WHERE order_id=? AND user_id=?",
                             (r["id"],worker)).fetchone():
                    continue
                return r
            return None

    def order_progress(self, oid):
        with self.connect() as c:
            return c.execute("SELECT COUNT(*) n FROM order_workers WHERE order_id=?", (oid,)).fetchone()["n"]

    def claim_order(self, oid, uid):
        with self.connect() as c:
            try:
                c.execute("INSERT INTO order_workers(order_id,user_id) VALUES(?,?)", (oid,uid))
            except sqlite3.IntegrityError:
                return False
            c.execute("UPDATE orders SET completed=completed+1 WHERE id=?", (oid,))
            row = c.execute("SELECT completed,amount,owner_id FROM orders WHERE id=?", (oid,)).fetchone()
            if row and row["completed"] >= row["amount"]:
                c.execute("UPDATE orders SET active=0 WHERE id=?", (oid,))
            return True

    def order(self, oid):
        with self.connect() as c:
            return c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()

db = DB(DB_FILE)

# ------------------------- UI -------------------------

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Mablag' yig'ish"), KeyboardButton(text="🛒 Buyurtma")],
        [KeyboardButton(text="💳 Hisobim"), KeyboardButton(text="🎮 O'yinlar")],
        [KeyboardButton(text="🧾 Yordam")],
    ], resize_keyboard=True)

def earn_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖇 Referal", callback_data="ref"),
         InlineKeyboardButton(text="📌 Topshiriqlar", callback_data="tasks")],
        [InlineKeyboardButton(text="📣 Obuna bo'lish", callback_data="earn_sub"),
         InlineKeyboardButton(text="👁 Post ko'rish", callback_data="earn_post")],
        [InlineKeyboardButton(text="➕ Guruhga odam qo'shish", callback_data="earn_group")],
        [InlineKeyboardButton(text="🎁 Bonus", callback_data="bonus")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu")],
    ])

def account_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Hisob to'ldirish", callback_data="deposit"),
         InlineKeyboardButton(text="🔄 O'tkazma", callback_data="transfer")],
        [InlineKeyboardButton(text="📊 Statistikam", callback_data="my_stats")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu")],
    ])

def help_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Ko'p beriladigan savollar", callback_data="faq")],
        [InlineKeyboardButton(text="📜 Qoidalar", callback_data="rules")],
        [InlineKeyboardButton(text="☎️ Administrator", callback_data="support")],
        [InlineKeyboardButton(text="📘 Qo'llanma", callback_data="guide")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu")],
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Asosiy sozlamalar", callback_data="admin_main")],
        [InlineKeyboardButton(text="📢 Kanallar", callback_data="admin_channels"),
         InlineKeyboardButton(text="📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎟 Promokod", callback_data="promo_admin"),
         InlineKeyboardButton(text="🎁 Bonuslar", callback_data="admin_bonus")],
        [InlineKeyboardButton(text="👤 Adminlar", callback_data="admins")],
        [InlineKeyboardButton(text="📋 Topshiriqlar boshqarish", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="📣 Obuna sozlamalari", callback_data="admin_sub"),
         InlineKeyboardButton(text="👁 Post sozlash", callback_data="admin_post")],
        [InlineKeyboardButton(text="➕ Guruh qo'shish sozlamalari", callback_data="admin_group")],
        [InlineKeyboardButton(text="✉️ Xabarnoma", callback_data="broadcast")],
        [InlineKeyboardButton(text="🔎 Foydalanuvchini boshqarish", callback_data="user_manage")],
        [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu")],
    ])

def back_admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
    ])

# ------------------------- BOT HELPERS -------------------------

async def safe_answer(call: CallbackQuery, text="", alert=False):
    try:
        await call.answer(text, show_alert=alert)
    except Exception:
        pass

async def is_subscribed(bot: Bot, uid: int) -> bool:
    """
    Majburiy kanal obunasini xavfsiz tekshiradi.
    Telegram xatosi bo'lsa bot yiqilmaydi — False qaytaradi.
    """
    raw = db.setting("channel")
    if not raw:
        return True
    chat = raw if raw.startswith("@") or raw.startswith("-100") else "@" + raw
    try:
        member = await bot.get_chat_member(chat_id=chat, user_id=uid)
        return member.status in {"creator", "administrator", "member"}
    except Exception as e:
        log.warning("Subscription check failed for %s/%s: %s", chat, uid, e)
        return False

async def require_subscription(message: Message, bot: Bot) -> bool:
    if await is_subscribed(bot, message.from_user.id):
        return True
    ch = db.setting("channel").lstrip("@")
    await message.answer(
        f"<b>🚫 Botdan to'liq foydalanish uchun kanalimizga obuna bo'ling.</b>\n\n"
        f"📣 Kanal: @{esc(ch)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📣 Kanalga o'tish", url=f"https://t.me/{ch}")],
            [InlineKeyboardButton(text="🔄 Tekshirish", callback_data="check_sub")],
        ])
    )
    return False

async def show_menu(target, user):
    u = db.user(user.id)
    bal = money(u["balance"] if u else 0)
    text = (
        f"<b>✨ Safiya Obunachi Bot</b>\n\n"
        f"👋 Assalomu alaykum, <b>{esc(user.first_name or 'foydalanuvchi')}</b>!\n\n"
        f"💳 Balans: <b>{bal} {db.setting('currency')}</b>\n"
        f"👥 Takliflar: <b>{u['refs'] if u else 0}</b>\n\n"
        f"<i>Kerakli bo'limni tanlang:</i>"
    )
    await target.answer(text, reply_markup=main_kb())

def parse_username(value: str) -> Optional[str]:
    v = value.strip()
    v = re.sub(r"^https?://t\.me/", "", v, flags=re.I)
    v = re.sub(r"^t\.me/", "", v, flags=re.I)
    v = v.strip("/").lstrip("@")
    return v if re.fullmatch(r"[A-Za-z0-9_]{5,32}", v) else None

def parse_post_link(value: str):
    v = re.sub(r"\s+", "", value.strip())
    m = re.match(r"^https?://t\.me/(?:s/)?([A-Za-z0-9_]+)/(\d+)(?:\?.*)?$", v, re.I)
    if not m:
        return None
    return m.group(1), int(m.group(2))

# ------------------------- FSM -------------------------

class Form(StatesGroup):
    deposit = State()
    transfer = State()
    support = State()
    order_channel = State()
    order_group = State()
    order_post = State()
    add_task = State()
    set_setting = State()
    broadcast = State()
    user_id = State()
    user_money = State()
    add_admin = State()
    remove_admin = State()

router = Router()

# ------------------------- START -------------------------

@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    db.upsert_user(message.from_user)
    if db.user(message.from_user.id)["banned"]:
        await message.answer("🚫 Siz botdan foydalanish huquqidan mahrum qilingansiz.")
        return
    # /start REF123 ko'rinishidagi referral
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) != message.from_user.id:
        ref = int(parts[1])
        if db.user(ref):
            with db.connect() as c:
                exists = c.execute("SELECT 1 FROM referrals WHERE user_id=?", (message.from_user.id,)).fetchone()
                if not exists:
                    c.execute("INSERT INTO referrals(user_id,referrer_id) VALUES(?,?)", (message.from_user.id,ref))
                    c.execute("UPDATE users SET refs=refs+1 WHERE id=?", (ref,))
                    db.add_balance(ref, float(db.setting("ref_reward")))
    if not await require_subscription(message, bot):
        return
    if WELCOME_VOICE:
        try:
            await bot.send_voice(message.chat.id, WELCOME_VOICE,
                                 caption="<b>🎙 Xush kelibsiz!</b>")
        except Exception:
            pass
    await show_menu(message, message.from_user)

@router.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("<b>👑 Admin panelga xush kelibsiz!</b>", reply_markup=admin_kb())

@router.message(F.text == "📦 Mablag' yig'ish")
async def earn(message: Message, bot: Bot):
    if await require_subscription(message, bot):
        await message.answer(
            "<b>💰 Mablag' yig'ish bo'limi</b>\n\n"
            "Quyidagi usullardan birini tanlang:",
            reply_markup=earn_kb()
        )

@router.message(F.text == "💳 Hisobim")
async def account(message: Message, bot: Bot):
    if not await require_subscription(message, bot): return
    u = db.user(message.from_user.id)
    await message.answer(
        f"<b>💳 Hisobim</b>\n\n"
        f"💰 Balans: <b>{money(u['balance'])} {db.setting('currency')}</b>\n"
        f"👥 Takliflar: <b>{u['refs']}</b>",
        reply_markup=account_kb()
    )

@router.message(F.text == "🧾 Yordam")
async def help_menu(message: Message, bot: Bot):
    if await require_subscription(message, bot):
        await message.answer("<b>🧾 Yordam bo'limi</b>\n\nKerakli bo'limni tanlang:", reply_markup=help_kb())

@router.message(F.text == "🎮 O'yinlar")
async def games(message: Message, bot: Bot):
    if not await require_subscription(message, bot): return
    await message.answer(
        "<b>🎮 O'yinlar</b>\n\n"
        "⚠️ O'yinlar balansdagi mablag' bilan ishlaydi. Mas'uliyat bilan foydalaning.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎲 Aylantirish", callback_data="game_spin")],
            [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu")],
        ])
    )

@router.message(F.text == "🛒 Buyurtma")
async def order_menu(message: Message, bot: Bot):
    if not await require_subscription(message, bot): return
    await message.answer(
        "<b>🛒 Buyurtma</b>\n\nBuyurtma turini tanlang:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📣 Kanal obunachisi", callback_data="order_channel")],
            [InlineKeyboardButton(text="👥 Guruh obunachisi", callback_data="order_group")],
            [InlineKeyboardButton(text="👁 Post ko'rish", callback_data="order_post")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="menu")],
        ])
    )

# ------------------------- EARNING -------------------------

@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_answer(call)
    await call.message.delete()
    await show_menu(call.message, call.from_user)

@router.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery, bot: Bot):
    if await is_subscribed(bot, call.from_user.id):
        await safe_answer(call, "✅ Obuna tasdiqlandi!", True)
        await call.message.edit_text("<b>✅ Obuna tasdiqlandi.</b>\n\nBosh menyudan foydalanishingiz mumkin.",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                         [InlineKeyboardButton(text="🏠 Bosh menyu", callback_data="menu")]
                                     ]))
    else:
        await safe_answer(call, "❌ Hali obuna bo'lmagansiz.", True)

@router.callback_query(F.data == "ref")
async def cb_ref(call: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, call.from_user.id):
        await safe_answer(call, "🚫 Avval kanalga obuna bo'ling.", True); return
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={call.from_user.id}"
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>🖇 Referal tizimi</b>\n\n"
        f"Har bir taklif uchun: <b>{db.setting('ref_reward')} {db.setting('currency')}</b>\n\n"
        f"🔗 Sizning havolangiz:\n<code>{esc(link)}</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📤 Ulashish", switch_inline_query=f"{link}")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="earn_back")],
        ])
    )

@router.callback_query(F.data == "earn_back")
async def cb_earn_back(call: CallbackQuery):
    await safe_answer(call)
    await call.message.edit_text("<b>💰 Mablag' yig'ish</b>\n\nUsulni tanlang:", reply_markup=earn_kb())

@router.callback_query(F.data == "bonus")
async def cb_bonus(call: CallbackQuery):
    uid = call.from_user.id
    with db.connect() as c:
        row = c.execute("SELECT value FROM settings WHERE key='bonus_last_'||?", (uid,)).fetchone()
        if row:
            await safe_answer(call, "🎁 Bonusni bugun allaqachon olgansiz!", True); return
        c.execute("INSERT INTO settings(key,value) VALUES(?,?)", (f"bonus_last_{uid}", datetime.now().date().isoformat()))
    amount = float(db.setting("bonus_amount"))
    db.add_balance(uid, amount)
    await safe_answer(call, f"🎁 Tabriklaymiz! {money(amount)} {db.setting('currency')} qo'shildi.", True)

@router.callback_query(F.data == "tasks")
async def cb_tasks(call: CallbackQuery):
    tasks = db.active_tasks()
    buttons = []
    for t in tasks[:20]:
        if not db.task_done(t["id"], call.from_user.id):
            buttons.append([InlineKeyboardButton(text=f"📌 {t['title'][:35]}", callback_data=f"task:{t['id']}")])
    buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="earn_back")])
    await safe_answer(call)
    await call.message.edit_text(
        "<b>📌 Topshiriqlar</b>\n\n"
        + ("Bajarish uchun topshiriqni tanlang." if tasks else "Hozircha topshiriqlar mavjud emas."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("task:"))
async def cb_task(call: CallbackQuery, bot: Bot):
    tid = int(call.data.split(":")[1])
    with db.connect() as c:
        t = c.execute("SELECT * FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
    if not t:
        await safe_answer(call, "⚠️ Topshiriq topilmadi.", True); return
    if db.task_done(tid, call.from_user.id):
        await safe_answer(call, "❌ Siz bu topshiriqni allaqachon bajargansiz!", True); return
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>{esc(t['title'])}</b>\n\n{esc(t['description'])}\n\n"
        f"💰 Mukofot: <b>{money(t['reward'])} {db.setting('currency')}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Topshiriqqa o'tish", url=t["url"])],
            [InlineKeyboardButton(text="✅ Bajardim", callback_data=f"task_done:{tid}")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="tasks")],
        ])
    )

@router.callback_query(F.data.startswith("task_done:"))
async def cb_task_done(call: CallbackQuery, bot: Bot):
    tid = int(call.data.split(":")[1])
    with db.connect() as c:
        t = c.execute("SELECT * FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
    if not t:
        await safe_answer(call, "⚠️ Topshiriq topilmadi.", True); return
    if db.task_done(tid, call.from_user.id):
        await safe_answer(call, "❌ Allaqachon bajarilgan.", True); return
    db.complete_task(tid, call.from_user.id)
    db.add_balance(call.from_user.id, t["reward"])
    await safe_answer(call, f"✅ Bajarildi! +{money(t['reward'])} {db.setting('currency')}", True)

@router.callback_query(F.data == "earn_sub")
async def cb_earn_sub(call: CallbackQuery, bot: Bot):
    if not await is_subscribed(bot, call.from_user.id):
        await safe_answer(call, "🚫 Avval majburiy kanalga obuna bo'ling.", True); return
    ch = db.setting("subscription_channel").strip().lstrip("@")
    reward = db.setting("subscription_reward")
    if not ch:
        await safe_answer(call, "⚠️ Obuna kanali hali sozlanmagan.", True); return
    await call.message.edit_text(
        f"<b>📣 Obuna bo'lish</b>\n\nKanal: @{esc(ch)}\n"
        f"💰 Mukofot: <b>{esc(reward)} {db.setting('currency')}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📣 Kanalga o'tish", url=f"https://t.me/{ch}")],
            [InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="claim_sub")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="earn_back")],
        ])
    )

@router.callback_query(F.data == "claim_sub")
async def cb_claim_sub(call: CallbackQuery, bot: Bot):
    ch = db.setting("subscription_channel").strip().lstrip("@")
    try:
        m = await bot.get_chat_member(f"@{ch}", call.from_user.id)
        ok = m.status in {"creator", "administrator", "member"}
    except Exception:
        ok = False
    if not ok:
        await safe_answer(call, "⛔ Kanalga obuna bo'lmagansiz!", True); return
    # One subscription reward per channel/user.
    key = f"sub_paid_{call.from_user.id}_{ch.lower()}"
    with db.connect() as c:
        if c.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone():
            await safe_answer(call, "❌ Bu kanal uchun mukofot olingan.", True); return
        c.execute("INSERT INTO settings(key,value) VALUES(?,?)", (key, "1"))
    reward = float(db.setting("subscription_reward"))
    db.add_balance(call.from_user.id, reward)
    await safe_answer(call, f"✅ Obuna bo'ldingiz! +{money(reward)} {db.setting('currency')}", True)

@router.callback_query(F.data == "earn_post")
async def cb_earn_post(call: CallbackQuery):
    ch = db.setting("post_channel").strip().lstrip("@")
    await call.message.edit_text(
        "<b>👁 Post ko'rish</b>\n\n"
        "Faol post ko'rish buyurtmalarini bajaring.\n"
        "Har bir post uchun mukofot olasiz.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            *([[InlineKeyboardButton(text="📣 Kanalga kirish", url=f"https://t.me/{ch}")]] if ch else []),
            [InlineKeyboardButton(text="👀 Shu yerda ko'rish", callback_data="view_order")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="earn_back")],
        ])
    )

@router.callback_query(F.data == "view_order")
async def cb_view_order(call: CallbackQuery):
    order = db.active_order("post", call.from_user.id)
    if not order:
        await safe_answer(call, "🔕 Hozircha faol post buyurtmalari mavjud emas.", True); return
    done = db.order_progress(order["id"])
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>👀 Post ko'rish buyurtmasi</b>\n\n"
        f"📌 Buyurtma: {order['amount']} ta\n"
        f"✅ Bajarildi: {done} ta\n"
        f"🔗 Post: {esc(order['target'])}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Postni ochish", url=order["target"])],
            [InlineKeyboardButton(text="👀 Ko'rdim", callback_data=f"claim_order:post:{order['id']}")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="earn_back")],
        ])
    )

@router.callback_query(F.data == "earn_group")
async def cb_earn_group(call: CallbackQuery):
    ch = db.setting("group").strip().lstrip("@")
    reward = db.setting("group_reward")
    if not ch:
        await safe_answer(call, "⚠️ Guruh hali sozlanmagan.", True); return
    await call.message.edit_text(
        f"<b>➕ Guruhga odam qo'shish</b>\n\n"
        f"👥 Guruh: @{esc(ch)}\n💰 Har bir yangi obunachi: <b>{esc(reward)} {db.setting('currency')}</b>\n\n"
        f"Yangi obunachilarni guruhga qo'shib mukofot oling.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 Guruhga qo'shilish", url=f"https://t.me/{ch}")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="earn_back")],
        ])
    )

@router.callback_query(F.data.startswith("claim_order:"))
async def cb_claim_order(call: CallbackQuery):
    _, kind, oid = call.data.split(":")
    oid = int(oid)
    order = db.order(oid)
    if not order or not order["active"]:
        await safe_answer(call, "⚠️ Bu buyurtma yakunlangan yoki topilmadi.", True); return
    if order["owner_id"] == call.from_user.id:
        await safe_answer(call, "❌ O'z buyurtmangizdan mukofot ololmaysiz.", True); return
    if not db.claim_order(oid, call.from_user.id):
        await safe_answer(call, "❌ Siz bu buyurtmadan allaqachon pul olgansiz!", True); return
    reward = float(db.setting({
        "channel":"channel_order_price",
        "group":"group_order_price",
        "post":"post_reward"
    }[kind]))
    db.add_balance(call.from_user.id, reward)
    await safe_answer(call, f"✅ Bajarildi! +{money(reward)} {db.setting('currency')}", True)

# ------------------------- ACCOUNT -------------------------

@router.callback_query(F.data == "deposit")
async def cb_deposit(call: CallbackQuery, state: FSMContext):
    await safe_answer(call)
    await state.set_state(Form.deposit)
    await call.message.answer(
        "<b>💳 Hisob to'ldirish</b>\n\n"
        "To'ldirmoqchi bo'lgan summani yuboring.\n"
        "<i>GitHub versiyasida real to'lov provayderi ulash uchun alohida payment API kerak bo'ladi.</i>"
    )

@router.message(Form.deposit)
async def deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float((message.text or "").replace(",", "."))
        if amount <= 0: raise ValueError
    except ValueError:
        await message.answer("⚠️ Faqat 0 dan katta raqam kiriting."); return
    with db.connect() as c:
        c.execute("INSERT INTO deposits(user_id,amount,status) VALUES(?,?,?)",
                  (message.from_user.id, amount, "pending"))
    await state.clear()
    await message.answer(
        f"✅ So'rov qabul qilindi: <b>{money(amount)} {db.setting('currency')}</b>\n\n"
        "👑 Admin to'lovni tasdiqlagandan so'ng balansingiz yangilanadi.",
        reply_markup=main_kb()
    )

@router.callback_query(F.data == "my_stats")
async def cb_my_stats(call: CallbackQuery):
    u = db.user(call.from_user.id)
    with db.connect() as c:
        orders = c.execute("SELECT COUNT(*) n FROM orders WHERE owner_id=?", (call.from_user.id,)).fetchone()["n"]
        done = c.execute("SELECT COUNT(*) n FROM order_workers WHERE user_id=?", (call.from_user.id,)).fetchone()["n"]
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>📊 Statistikam</b>\n\n"
        f"💰 Balans: {money(u['balance'])} {db.setting('currency')}\n"
        f"👥 Referallar: {u['refs']}\n"
        f"🛒 Buyurtmalar: {orders}\n"
        f"✅ Bajarilganlar: {done}",
        reply_markup=account_kb()
    )

@router.callback_query(F.data == "transfer")
async def cb_transfer(call: CallbackQuery, state: FSMContext):
    await safe_answer(call)
    await state.set_state(Form.transfer)
    await call.message.answer("👤 Pul yubormoqchi bo'lgan foydalanuvchi ID raqamini va summani `ID summa` ko'rinishida yuboring.")

@router.message(Form.transfer)
async def do_transfer(message: Message, state: FSMContext):
    try:
        a, b = (message.text or "").split(maxsplit=1)
        target, amount = int(a), float(b.replace(",", "."))
        if target == message.from_user.id or amount <= 0: raise ValueError
    except Exception:
        await message.answer("⚠️ Format noto'g'ri. Masalan: `123456789 10`"); return
    sender = db.user(message.from_user.id)
    if not db.user(target):
        await message.answer("❌ Foydalanuvchi topilmadi."); return
    if sender["balance"] < amount:
        await message.answer("⚠️ Balansingiz yetarli emas."); return
    db.add_balance(message.from_user.id, -amount)
    db.add_balance(target, amount)
    await state.clear()
    await message.answer(f"✅ {money(amount)} {db.setting('currency')} o'tkazildi.", reply_markup=main_kb())

@router.callback_query(F.data == "support")
async def cb_support(call: CallbackQuery, state: FSMContext):
    await safe_answer(call)
    await state.set_state(Form.support)
    await call.message.answer("☎️ Adminga yuboriladigan murojaat matnini yuboring:")

@router.message(Form.support)
async def do_support(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    sent = 0
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, f"📨 <b>Yangi murojaat</b>\n\n👤 ID: <code>{message.from_user.id}</code>\n\n{esc(message.text or '')}")
            sent += 1
        except Exception:
            pass
    await message.answer("✅ Murojaatingiz yuborildi." if sent else "⚠️ Admin topilmadi.", reply_markup=main_kb())

@router.callback_query(F.data == "faq")
async def cb_faq(call: CallbackQuery):
    await safe_answer(call)
    await call.message.edit_text(db.setting("faq"), reply_markup=help_kb())

@router.callback_query(F.data == "rules")
async def cb_rules(call: CallbackQuery):
    await safe_answer(call)
    await call.message.edit_text(db.setting("rules"), reply_markup=help_kb())

@router.callback_query(F.data == "guide")
async def cb_guide(call: CallbackQuery):
    await safe_answer(call)
    await call.message.edit_text(
        "<b>📘 Qisqa qo'llanma</b>\n\n"
        "1️⃣ Kanalga obuna bo'ling.\n"
        "2️⃣ Mablag' yig'ish bo'limidan topshiriq bajaring.\n"
        "3️⃣ Buyurtma berish uchun balansni to'ldiring.\n"
        "4️⃣ Admin paneldan sozlamalarni boshqaring.",
        reply_markup=help_kb()
    )

# ------------------------- ORDERS -------------------------

def order_help(kind):
    labels = {
        "channel": ("📣 Kanal buyurtmasi", "Kanal username va miqdorni yuboring. Masalan: @kanal 100"),
        "group": ("👥 Guruh buyurtmasi", "Guruh username va miqdorni yuboring. Masalan: @guruh 100"),
        "post": ("👁 Post buyurtmasi", "Post link va miqdorni yuboring. Masalan: https://t.me/channel/123 100"),
    }
    return labels[kind]

@router.callback_query(F.data == "order_channel")
async def cb_order_channel(call: CallbackQuery, state: FSMContext):
    await safe_answer(call)
    await state.set_state(Form.order_channel)
    await call.message.answer("<b>📣 Kanal buyurtmasi</b>\n\nKanal username va miqdorni yuboring:\n<code>@kanal 100</code>")

@router.message(Form.order_channel)
async def make_channel_order(message: Message, state: FSMContext):
    try:
        target, n = (message.text or "").split()
        target = parse_username(target); n = int(n)
        if not target or n < int(db.setting("min_order")) or n > int(db.setting("max_order")): raise ValueError
    except Exception:
        await message.answer(f"⚠️ Format noto'g'ri yoki miqdor {db.setting('min_order')}-{db.setting('max_order')} oralig'ida bo'lishi kerak."); return
    price = float(db.setting("channel_order_price")) * n
    u = db.user(message.from_user.id)
    if u["balance"] < price:
        await message.answer(f"⚠️ Balansingiz yetarli emas. Kerak: {money(price)} {db.setting('currency')}"); return
    db.add_balance(message.from_user.id, -price)
    oid = db.create_order(message.from_user.id, "channel", f"https://t.me/{target}", n)
    await state.clear()
    await message.answer(f"✅ Buyurtma #{oid} yaratildi!\n\n📣 @{target}\n👥 {n} ta\n💰 {money(price)} {db.setting('currency')}", reply_markup=main_kb())

@router.callback_query(F.data == "order_group")
async def cb_order_group(call: CallbackQuery, state: FSMContext):
    await safe_answer(call)
    await state.set_state(Form.order_group)
    await call.message.answer("<b>👥 Guruh buyurtmasi</b>\n\nGuruh username va miqdorni yuboring:\n<code>@guruh 100</code>")

@router.message(Form.order_group)
async def make_group_order(message: Message, state: FSMContext):
    try:
        target, n = (message.text or "").split()
        target = parse_username(target); n = int(n)
        if not target or n < int(db.setting("min_order")) or n > int(db.setting("max_order")): raise ValueError
    except Exception:
        await message.answer("⚠️ Format yoki miqdor noto'g'ri."); return
    price = float(db.setting("group_order_price")) * n
    u = db.user(message.from_user.id)
    if u["balance"] < price:
        await message.answer(f"⚠️ Balansingiz yetarli emas. Kerak: {money(price)} {db.setting('currency')}"); return
    db.add_balance(message.from_user.id, -price)
    oid = db.create_order(message.from_user.id, "group", f"https://t.me/{target}", n)
    await state.clear()
    await message.answer(f"✅ Buyurtma #{oid} yaratildi!\n\n👥 @{target}\n👥 {n} ta", reply_markup=main_kb())

@router.callback_query(F.data == "order_post")
async def cb_order_post(call: CallbackQuery, state: FSMContext):
    await safe_answer(call)
    await state.set_state(Form.order_post)
    await call.message.answer("<b>👁 Post buyurtmasi</b>\n\nPost link va miqdorni yuboring:\n<code>https://t.me/channel/123 100</code>")

@router.message(Form.order_post)
async def make_post_order(message: Message, state: FSMContext):
    try:
        link, n = (message.text or "").split()
        if not parse_post_link(link): raise ValueError
        n = int(n)
        if n < int(db.setting("min_order")) or n > int(db.setting("max_order")): raise ValueError
    except Exception:
        await message.answer("⚠️ Post linki yoki miqdor noto'g'ri."); return
    price = float(db.setting("post_reward")) * n
    u = db.user(message.from_user.id)
    if u["balance"] < price:
        await message.answer(f"⚠️ Balansingiz yetarli emas. Kerak: {money(price)} {db.setting('currency')}"); return
    db.add_balance(message.from_user.id, -price)
    oid = db.create_order(message.from_user.id, "post", link, n)
    await state.clear()
    await message.answer(f"✅ Post buyurtmasi #{oid} yaratildi!\n\n👁 {link}\n👥 {n} ta", reply_markup=main_kb())

# ------------------------- GAMES -------------------------

@router.callback_query(F.data == "game_spin")
async def game_spin(call: CallbackQuery):
    import secrets
    u = db.user(call.from_user.id)
    bet = 5.0
    if u["balance"] < bet:
        await safe_answer(call, "⚠️ Balansingiz yetarli emas.", True); return
    db.add_balance(call.from_user.id, -bet)
    prize = secrets.choice([0, 0, 0, 5, 10, 15, 25])
    db.add_balance(call.from_user.id, prize)
    await safe_answer(call, f"🎲 Natija: +{money(prize)} {db.setting('currency')}" if prize else "🎲 Afsus, bu safar yutmadingiz.", True)

# ------------------------- ADMIN -------------------------

def is_admin(uid): return uid in ADMIN_IDS

@router.message(F.text == "🗄 Boshqarish")
async def admin_back_message(message: Message):
    if is_admin(message.from_user.id):
        db.clear_state(message.from_user.id)
        await message.answer("<b>👑 Admin panel</b>", reply_markup=admin_kb())

@router.callback_query(F.data == "admin")
async def cb_admin(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text("<b>👑 Admin panel</b>\n\nKerakli bo'limni tanlang:", reply_markup=admin_kb())

@router.callback_query(F.data == "admin_main")
async def cb_admin_main(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>⚙️ Asosiy sozlamalar</b>\n\n"
        f"💱 Valyuta: {esc(db.setting('currency'))}\n"
        f"🖇 Referal narxi: {db.setting('ref_reward')}\n"
        f"⬇️ Min buyurtma: {db.setting('min_order')}\n"
        f"⬆️ Max buyurtma: {db.setting('max_order')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💱 Valyutani o'zgartirish", callback_data="set:currency")],
            [InlineKeyboardButton(text="🖇 Taklif narxini o'zgartirish", callback_data="set:ref_reward")],
            [InlineKeyboardButton(text="⬇️ Min buyurtma", callback_data="set:min_order"),
             InlineKeyboardButton(text="⬆️ Max buyurtma", callback_data="set:max_order")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data == "admin_channels")
async def cb_admin_channels(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    ch = db.setting("channel")
    sub = db.setting("subscription_channel")
    post = db.setting("post_channel")
    group = db.setting("group")
    await call.message.edit_text(
        f"<b>📢 Kanallar va guruhlar</b>\n\n"
        f"🔒 Majburiy kanal: {esc(ch)}\n"
        f"📣 Obuna kanali: @{esc(sub) if sub else '—'}\n"
        f"👁 Post kanali: @{esc(post) if post else '—'}\n"
        f"👥 Guruh: @{esc(group) if group else '—'}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔒 Majburiy kanal", callback_data="set:channel")],
            [InlineKeyboardButton(text="📣 Obuna kanali", callback_data="set:subscription_channel")],
            [InlineKeyboardButton(text="👁 Post kanali", callback_data="set:post_channel")],
            [InlineKeyboardButton(text="👥 Guruh", callback_data="set:group")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    with db.connect() as c:
        users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        banned = c.execute("SELECT COUNT(*) n FROM users WHERE banned=1").fetchone()["n"]
        orders = c.execute("SELECT COUNT(*) n FROM orders").fetchone()["n"]
        active = c.execute("SELECT COUNT(*) n FROM orders WHERE active=1").fetchone()["n"]
        bal = c.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>📊 Statistika</b>\n\n"
        f"👤 Foydalanuvchilar: <b>{users}</b>\n"
        f"🚫 Banlanganlar: <b>{banned}</b>\n"
        f"🛒 Jami buyurtmalar: <b>{orders}</b>\n"
        f"🔥 Faol buyurtmalar: <b>{active}</b>\n"
        f"💰 Umumiy balans: <b>{money(bal)} {db.setting('currency')}</b>",
        reply_markup=back_admin_kb()
    )

@router.callback_query(F.data == "admin_bonus")
async def cb_admin_bonus(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>🎁 Bonuslar</b>\n\nHozirgi bonus: <b>{db.setting('bonus_amount')} {db.setting('currency')}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Miqdorni sozlash", callback_data="set:bonus_amount")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data == "admin_sub")
async def cb_admin_sub(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>📣 Obuna sozlamalari</b>\n\nKanal: @{esc(db.setting('subscription_channel')) if db.setting('subscription_channel') else '—'}\n"
        f"Narx: {db.setting('subscription_reward')} {db.setting('currency')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📣 Kanal username'ini o'zgartirish", callback_data="set:subscription_channel")],
            [InlineKeyboardButton(text="💰 Narxni o'zgartirish", callback_data="set:subscription_reward")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data == "admin_post")
async def cb_admin_post(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>👁 Post ko'rish sozlamalari</b>\n\n"
        f"Kanal: @{esc(db.setting('post_channel')) if db.setting('post_channel') else '—'}\n"
        f"Narx: {db.setting('post_reward')} {db.setting('currency')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📣 Kanal o'zgartirish", callback_data="set:post_channel")],
            [InlineKeyboardButton(text="💰 Narx o'zgartirish", callback_data="set:post_reward")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data == "admin_group")
async def cb_admin_group(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        f"<b>➕ Guruh qo'shish sozlamalari</b>\n\n"
        f"Guruh: @{esc(db.setting('group')) if db.setting('group') else '—'}\n"
        f"Narx: {db.setting('group_reward')} {db.setting('currency')}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📣 Guruh username'ini o'zgartirish", callback_data="set:group")],
            [InlineKeyboardButton(text="💰 Narxni o'zgartirish", callback_data="set:group_reward")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

VALID_SETTINGS = {
    "currency","channel","subscription_channel","post_channel","group",
    "ref_reward","bonus_amount","post_reward","subscription_reward","group_reward",
    "min_order","max_order","channel_order_price","group_order_price","faq","rules"
}

@router.callback_query(F.data.startswith("set:"))
async def cb_set(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    key = call.data.split(":",1)[1]
    if key not in VALID_SETTINGS:
        return
    await safe_answer(call)
    await state.set_state(Form.set_setting)
    await state.update_data(setting_key=key)
    current = db.setting(key)
    await call.message.answer(
        f"<b>📝 Yangi qiymatni yuboring</b>\n\n"
        f"Kalit: <code>{key}</code>\n"
        f"Hozirgi qiymat: <code>{esc(current)}</code>\n\n"
        f"Bekor qilish uchun <b>🗄 Boshqarish</b> tugmasini bosing."
    )

@router.message(Form.set_setting)
async def save_setting(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "🗄 Boshqarish":
        await state.clear(); await message.answer("👑 Admin panel", reply_markup=admin_kb()); return
    data = await state.get_data()
    key = data.get("setting_key")
    value = (message.text or "").strip()
    if key in {"ref_reward","bonus_amount","post_reward","subscription_reward","group_reward","min_order","max_order","channel_order_price","group_order_price"}:
        try:
            n = float(value.replace(",", "."))
            if n <= 0: raise ValueError
            value = money(n)
        except ValueError:
            await message.answer("⚠️ Faqat 0 dan katta raqam kiriting."); return
    if key in {"channel","subscription_channel","post_channel","group"} and value:
        parsed = parse_username(value)
        if not parsed:
            await message.answer("⚠️ Username noto'g'ri. @username yoki https://t.me/username yuboring."); return
        value = "@" + parsed if key == "channel" else parsed
    db.set_setting(key, value)
    await state.clear()
    await message.answer(f"✅ <b>{esc(key)}</b> saqlandi: <code>{esc(value)}</code>", reply_markup=admin_kb())

# ------------------------- ADMIN TASKS -------------------------

@router.callback_query(F.data == "admin_tasks")
async def cb_admin_tasks(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        "<b>📋 Topshiriqlar boshqarish</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Topshiriq qo'shish", callback_data="add_task")],
            [InlineKeyboardButton(text="📑 Topshiriqlar ro'yxati", callback_data="task_list")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data == "add_task")
async def cb_add_task(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await state.set_state(Form.add_task)
    await call.message.answer(
        "<b>📝 Yangi topshiriq qo'shish</b>\n\n"
        "Har biri yangi qatorda:\n"
        "<code>Nomi\nTavsifi\nhttps://link.com\n2.0</code>"
    )

@router.message(Form.add_task)
async def save_task(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "🗄 Boshqarish":
        await state.clear(); await message.answer("👑 Admin panel", reply_markup=admin_kb()); return
    ls = [x.strip() for x in (message.text or "").splitlines() if x.strip()]
    if len(ls) < 4:
        await message.answer("❌ Format noto'g'ri."); return
    try: reward = float(ls[-1].replace(",", "."))
    except: await message.answer("⚠️ Mukofot raqam bo'lishi kerak."); return
    tid = db.add_task(ls[0], "\n".join(ls[1:-2]), ls[-2], reward)
    await state.clear()
    await message.answer(f"✅ Topshiriq #{tid} qo'shildi!", reply_markup=admin_kb())

@router.callback_query(F.data == "task_list")
async def cb_task_list(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    tasks = db.active_tasks()
    buttons = [[InlineKeyboardButton(text=f"🗑 #{t['id']} {t['title'][:28]}", callback_data=f"del_task:{t['id']}")] for t in tasks]
    buttons.append([InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin_tasks")])
    await safe_answer(call)
    await call.message.edit_text("<b>📑 Topshiriqlar ro'yxati</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("del_task:"))
async def cb_del_task(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    db.delete_task(int(call.data.split(":")[1]))
    await safe_answer(call, "✅ Topshiriq o'chirildi!", True)
    await cb_task_list(call)

# ------------------------- ADMIN / BROADCAST / USERS -------------------------

@router.callback_query(F.data == "broadcast")
async def cb_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await state.set_state(Form.broadcast)
    await call.message.answer("✉️ Barcha foydalanuvchilarga yuboriladigan xabarni yuboring.\n\n<i>Matnli xabar.</i>")

@router.message(Form.broadcast)
async def do_broadcast(message: Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id): return
    await state.clear()
    ok = bad = 0
    for uid in db.all_user_ids():
        try:
            await bot.copy_message(uid, message.chat.id, message.message_id)
            ok += 1
        except Exception:
            bad += 1
        await asyncio.sleep(0.04)
    await message.answer(f"📣 Xabarnoma yakunlandi.\n\n✅ Yuborildi: {ok}\n❌ Xato: {bad}", reply_markup=admin_kb())

@router.callback_query(F.data == "user_manage")
async def cb_user_manage(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await state.set_state(Form.user_id)
    await call.message.answer("🔎 Kerakli foydalanuvchining ID raqamini yuboring:")

@router.message(Form.user_id)
async def find_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    if message.text == "🗄 Boshqarish":
        await state.clear(); await message.answer("👑 Admin panel", reply_markup=admin_kb()); return
    try: uid = int(message.text.strip())
    except: await message.answer("⚠️ Faqat ID raqam yuboring."); return
    u = db.user(uid)
    if not u:
        await message.answer("❌ Ushbu foydalanuvchi botdan foydalanmaydi."); return
    await state.update_data(target_uid=uid)
    await state.clear()
    await message.answer(
        f"<b>👤 Foydalanuvchi topildi!</b>\n\n"
        f"ID: <code>{uid}</code>\n"
        f"Balans: <b>{money(u['balance'])} {db.setting('currency')}</b>\n"
        f"Takliflari: <b>{u['refs']}</b>\n"
        f"Ban: <b>{"ha" if u["banned"] else "yo\u02bbq"}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Pul qo'shish", callback_data=f"useradd:{uid}"),
             InlineKeyboardButton(text="➖ Pul ayirish", callback_data=f"usersub:{uid}")],
            [InlineKeyboardButton(text="🔔 Banlash" if not u["banned"] else "🔕 Bandan olish",
                                  callback_data=f"toggleban:{uid}")],
            [InlineKeyboardButton(text="◀️ Orqaga", callback_data="admin")],
        ])
    )

@router.callback_query(F.data.startswith("toggleban:"))
async def cb_toggleban(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split(":")[1])
    with db.connect() as c:
        c.execute("UPDATE users SET banned=CASE banned WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (uid,))
    await safe_answer(call, "✅ Holat o'zgartirildi!", True)

@router.callback_query(F.data.startswith("useradd:"))
async def cb_useradd(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split(":")[1])
    await state.set_state(Form.user_money); await state.update_data(target_uid=uid, op="add")
    await safe_answer(call)
    await call.message.answer("➕ Qancha pul qo'shilsin?")

@router.callback_query(F.data.startswith("usersub:"))
async def cb_usersub(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    uid = int(call.data.split(":")[1])
    await state.set_state(Form.user_money); await state.update_data(target_uid=uid, op="sub")
    await safe_answer(call)
    await call.message.answer("➖ Qancha pul ayirilsin?")

@router.message(Form.user_money)
async def user_money(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    try: amount = float((message.text or "").replace(",", "."))
    except: await message.answer("⚠️ Faqat raqam."); return
    data = await state.get_data()
    uid = data["target_uid"]
    db.add_balance(uid, amount if data["op"] == "add" else -amount)
    await state.clear()
    await message.answer("✅ Foydalanuvchi hisobi yangilandi.", reply_markup=admin_kb())

# ------------------------- ADMINS -------------------------

@router.callback_query(F.data == "admins")
async def cb_admins(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    ids = ", ".join(str(x) for x in sorted(ADMIN_IDS)) or "ADMIN_IDS sozlanmagan"
    await call.message.edit_text(
        f"<b>👤 Adminlar</b>\n\n<code>{ids}</code>\n\n"
        "⚠️ Admin qo'shish/olish GitHub Secrets'dagi <code>ADMIN_IDS</code> orqali amalga oshiriladi.",
        reply_markup=back_admin_kb()
    )

@router.callback_query(F.data == "promo_admin")
async def cb_promo_admin(call: CallbackQuery):
    if not is_admin(call.from_user.id): return
    await safe_answer(call)
    await call.message.edit_text(
        "<b>🎟 Promokod</b>\n\n"
        "Bu GitHub-ready versiyada promokodlar uchun alohida DB jadvali emas, "
        "asosiy iqtisodiy funksiyalar SQLite orqali ishlaydi.",
        reply_markup=back_admin_kb()
    )

# ------------------------- GENERIC TEXT -------------------------

@router.message()
async def fallback(message: Message, bot: Bot):
    db.upsert_user(message.from_user)
    if db.user(message.from_user.id)["banned"]:
        await message.answer("🚫 Siz banlangansiz."); return
    # Admin panel shortcut
    if message.text and message.text.lower() in {"/panel", "admin panel"} and is_admin(message.from_user.id):
        await message.answer("<b>👑 Admin panel</b>", reply_markup=admin_kb()); return
    if await require_subscription(message, bot):
        await message.answer("🏠 Kerakli bo'limni tugmalar orqali tanlang.", reply_markup=main_kb())

# ------------------------- STARTUP -------------------------

async def main():
    if not TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. GitHub Settings → Secrets and variables → Actions "
            "yoki hosting Environment Variables ga BOT_TOKEN qo'ying."
        )
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS bo'sh. Admin panel ishlamaydi.")
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    log.info("Bot started: @%s", me.username)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
