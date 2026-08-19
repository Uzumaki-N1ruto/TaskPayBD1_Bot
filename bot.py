import os
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE = os.environ.get("DATABASE", "taskpay.db")

WEBSITE_URL = os.environ.get(
    "WEBSITE_URL",
    "https://uzumaki-n1ruto.github.io/TaskPayBD1_Bot/"
)

REFERRAL_REWARD = 50.00
DHAKA = ZoneInfo("Asia/Dhaka")

OWNER_IDS = {
    7182450475,
    7897571474
}

DEFAULT_BUTTONS = [
    {
        "id": "website",
        "text": "🌐 Open Website",
        "url": WEBSITE_URL,
        "enabled": True
    },
    {
        "id": "referrals",
        "text": "👥 My Referrals",
        "callback": "my_referrals",
        "enabled": True
    }
]


def get_db():
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def setup_database():
    conn = get_db()

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        photo_url TEXT DEFAULT '',
        balance REAL NOT NULL DEFAULT 0,
        total_earned REAL NOT NULL DEFAULT 0,
        withdrawn REAL NOT NULL DEFAULT 0,
        joined_at TEXT NOT NULL,
        referrals INTEGER NOT NULL DEFAULT 0,
        ads_watched INTEGER NOT NULL DEFAULT 0,
        ads_day TEXT NOT NULL,
        referred_by INTEGER,
        blocked INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(referred_by) REFERENCES users(telegram_id)
    );

    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER NOT NULL,
        referred_id INTEGER NOT NULL UNIQUE,
        reward REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(referrer_id) REFERENCES users(telegram_id),
        FOREIGN KEY(referred_id) REFERENCES users(telegram_id)
    );

    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        method TEXT NOT NULL,
        account TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT NOT NULL,
        bdt_value REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        processed_at TEXT,
        note TEXT DEFAULT '',
        FOREIGN KEY(telegram_id) REFERENCES users(telegram_id)
    );

    CREATE TABLE IF NOT EXISTS bot_buttons (
        id TEXT PRIMARY KEY,
        text TEXT NOT NULL,
        url TEXT DEFAULT '',
        callback TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        position INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS post_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_withdrawals_user
    ON withdrawals(telegram_id);
    """)

    for position, button in enumerate(DEFAULT_BUTTONS):
        conn.execute(
            """
            INSERT OR IGNORE INTO bot_buttons
            (id, text, url, callback, enabled, position)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                button["id"],
                button["text"],
                button.get("url", ""),
                button.get("callback", ""),
                1 if button["enabled"] else 0,
                position
            )
        )

    conn.commit()
    conn.close()


def is_owner(user_id):
    return user_id in OWNER_IDS


def owner_only(update):
    user = update.effective_user
    return bool(user and is_owner(user.id))


def now():
    return datetime.now(DHAKA)


def get_user(user_id):
    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return user


def ensure_user(user):
    existing = get_user(user.id)

    if existing:
        return existing

    conn = get_db()

    joined_at = now().isoformat()
    ads_day = now().strftime("%Y-%m-%d")

    conn.execute(
        """
        INSERT OR IGNORE INTO users
        (
            telegram_id,
            first_name,
            last_name,
            username,
            photo_url,
            joined_at,
            ads_day
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user.id,
            user.first_name or "User",
            user.last_name or "",
            user.username or "",
            "",
            joined_at,
            ads_day
        )
    )

    conn.commit()

    created = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (user.id,)
    ).fetchone()

    conn.close()

    return created


def get_buttons():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM bot_buttons
        ORDER BY position ASC
        """
    ).fetchall()

    conn.close()

    return rows


def build_main_keyboard():
    rows = []

    buttons = get_buttons()

    for button in buttons:
        if not button["enabled"]:
            continue

        if button["url"]:
            rows.append([
                InlineKeyboardButton(
                    button["text"],
                    url=button["url"]
                )
            ])

        elif button["callback"]:
            rows.append([
                InlineKeyboardButton(
                    button["text"],
                    callback_data=button["callback"]
                )
            ])

    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    db_user = ensure_user(user)

    referral_link = (
        f"https://t.me/{context.bot.username}"
        f"?start=r{user.id}"
    )

    message = (
        f"👋 Welcome to TaskPayBD, {user.first_name}!\n\n"
        f"💰 Balance: ৳{db_user['balance']:.2f}\n"
        f"👥 Referrals: {db_user['referrals']}\n\n"
        f"🔗 Your referral link:\n"
        f"{referral_link}"
    )

    await update.message.reply_text(
        message,
        reply_markup=build_main_keyboard()
    )


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = ensure_user(user)

    conn = get_db()

    referred_users = conn.execute(
        """
        SELECT
            u.first_name,
            u.username,
            r.created_at
        FROM referrals r
        JOIN users u
            ON u.telegram_id=r.referred_id
        WHERE r.referrer_id=?
        ORDER BY r.id DESC
        """,
        (user.id,)
    ).fetchall()

    conn.close()

    referral_link = (
        f"https://t.me/{context.bot.username}"
        f"?start=r{user.id}"
    )

    message = (
        f"👥 Your Referrals\n\n"
        f"Total referrals: {db_user['referrals']}\n"
        f"Referral earnings: "
        f"৳{db_user['referrals'] * REFERRAL_REWARD:.2f}\n\n"
        f"🔗 Your referral link:\n"
        f"{referral_link}"
    )

    if referred_users:
        message += "\n\n👤 People you referred:\n\n"

        for index, referred in enumerate(
            referred_users,
            start=1
        ):
            name = referred["first_name"]

            if referred["username"]:
                name += f" (@{referred['username']})"

            message += (
                f"{index}. {name}\n"
                f"   +৳{REFERRAL_REWARD:.2f}\n"
            )

    await update.message.reply_text(message)


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = ensure_user(user)

    await update.message.reply_text(
        f"💰 Your Balance\n\n"
        f"Available balance: ৳{db_user['balance']:.2f}\n\n"
        f"Total earned: ৳{db_user['total_earned']:.2f}\n\n"
        f"👥 Referrals: {db_user['referrals']}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = ensure_user(user)

    await update.message.reply_text(
        f"📊 Your TaskPayBD Stats\n\n"
        f"👤 Name: {db_user['first_name']}\n"
        f"🆔 Telegram ID: {db_user['telegram_id']}\n"
        f"👥 Referrals: {db_user['referrals']}\n"
        f"💰 Balance: ৳{db_user['balance']:.2f}\n"
        f"📈 Total earned: ৳{db_user['total_earned']:.2f}\n"
        f"💸 Withdrawn: ৳{db_user['withdrawn']:.2f}"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 TaskPayBD Commands\n\n"
        "/start - Start the bot\n"
        "/referrals - View referrals\n"
        "/balance - View balance\n"
        "/stats - View statistics\n"
        "/admin - Open owner panel\n"
        "/user <id> - View user\n"
        "/addbalance <id> <amount> - Add balance\n"
        "/removebalance <id> <amount> - Remove balance\n"
        "/block <id> - Block user\n"
        "/unblock <id> - Unblock user\n"
        "/help - Show this menu"
    )


def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 Statistics",
                callback_data="admin_stats"
            ),
            InlineKeyboardButton(
                "💸 Withdrawals",
                callback_data="admin_withdrawals"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 Users",
                callback_data="admin_users"
            ),
            InlineKeyboardButton(
                "💰 Balance",
                callback_data="admin_balance_help"
            )
        ],
        [
            InlineKeyboardButton(
                "🔘 Button Editor",
                callback_data="button_editor"
            )
        ],
        [
            InlineKeyboardButton(
                "📝 Post Editor",
                callback_data="post_editor"
            )
        ],
        [
            InlineKeyboardButton(
                "⏳ Pending Withdrawals",
                callback_data="admin_pending"
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Close",
                callback_data="admin_close"
            )
        ]
    ])


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    await update.message.reply_text(
        "🔐 TaskPayBD OWNER PANEL\n\n"
        "You have full owner access.\n\n"
        "👑 Owners:\n"
        "• 7182450475\n"
        "• 7897571474\n\n"
        "Choose an action:",
        reply_markup=admin_keyboard()
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_owner(query.from_user.id):
        await query.answer(
            "⛔ Owner access only.",
            show_alert=True
        )
        return

    await query.answer()

    action = query.data

    if action == "admin_close":
        await query.edit_message_text(
            "🔒 Owner panel closed."
        )
        return

    if action == "admin_home":
        await query.edit_message_text(
            "🔐 TaskPayBD OWNER PANEL\n\n"
            "You have full owner access.\n\n"
            "Choose an action:",
            reply_markup=admin_keyboard()
        )
        return

    if action == "admin_stats":
        await show_admin_stats(query)
        return

    if action in {"admin_withdrawals", "admin_pending"}:
        await show_withdrawals(query, action == "admin_pending")
        return

    if action == "admin_users":
        await show_users(query)
        return

    if action == "admin_balance_help":
        await query.edit_message_text(
            "💰 BALANCE MANAGEMENT\n\n"
            "Use these commands:\n\n"
            "/user <telegram_id>\n"
            "View a user's account.\n\n"
            "/addbalance <telegram_id> <amount>\n"
            "Add money to a user's balance.\n\n"
            "/removebalance <telegram_id> <amount>\n"
            "Remove money from a user's balance.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="admin_home"
                    )
                ]
            ])
        )
        return

    if action == "button_editor":
        await button_editor(query)
        return

    if action.startswith("button_toggle_"):
        button_id = action.replace("button_toggle_", "")
        await toggle_button(query, button_id)
        return

    if action == "post_editor":
        await query.edit_message_text(
            "📝 POST EDITOR\n\n"
            "Use these commands:\n\n"
            "/post\n"
            "Start writing a post.\n\n"
            "After /post, send the message you want to publish.\n\n"
            "The bot will ask where to send it.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="admin_home"
                    )
                ]
            ])
        )
        return

    if action.startswith("pay_"):
        withdrawal_id = int(action.split("_")[1])
        await process_withdrawal(
            query,
            withdrawal_id,
            "paid"
        )
        return

    if action.startswith("reject_"):
        withdrawal_id = int(action.split("_")[1])
        await process_withdrawal(
            query,
            withdrawal_id,
            "rejected"
        )
        return


async def show_admin_stats(query):
    conn = get_db()

    users = conn.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()["count"]

    active = conn.execute(
        "SELECT COUNT(*) AS count FROM users WHERE blocked=0"
    ).fetchone()["count"]

    blocked = conn.execute(
        "SELECT COUNT(*) AS count FROM users WHERE blocked=1"
    ).fetchone()["count"]

    balance_total = conn.execute(
        "SELECT COALESCE(SUM(balance),0) AS total FROM users"
    ).fetchone()["total"]

    earned = conn.execute(
        "SELECT COALESCE(SUM(total_earned),0) AS total FROM users"
    ).fetchone()["total"]

    withdrawn = conn.execute(
        "SELECT COALESCE(SUM(withdrawn),0) AS total FROM users"
    ).fetchone()["total"]

    referrals_total = conn.execute(
        "SELECT COALESCE(SUM(referrals),0) AS total FROM users"
    ).fetchone()["total"]

    pending = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM withdrawals
        WHERE status='pending'
        """
    ).fetchone()["count"]

    conn.close()

    text = (
        "📊 TASKPAYBD STATISTICS\n\n"
        f"👥 Total users: {users}\n"
        f"🟢 Active users: {active}\n"
        f"🔴 Blocked users: {blocked}\n\n"
        f"💰 Total balance: ৳{balance_total:,.2f}\n"
        f"📈 Total earned: ৳{earned:,.2f}\n"
        f"💸 Total withdrawn: ৳{withdrawn:,.2f}\n"
        f"👥 Total referrals: {referrals_total}\n\n"
        f"⏳ Pending withdrawals: {pending}"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="admin_home"
                )
            ]
        ])
    )


async def show_users(query):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            telegram_id,
            first_name,
            username,
            balance,
            referrals,
            blocked
        FROM users
        ORDER BY telegram_id DESC
        LIMIT 20
        """
    ).fetchall()

    total = conn.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()["count"]

    conn.close()

    text = f"👥 USERS\n\nTotal users: {total}\n\n"

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "No username"
        )

        status = (
            "🔴 BLOCKED"
            if row["blocked"]
            else "🟢 ACTIVE"
        )

        text += (
            f"👤 {row['first_name']} {username}\n"
            f"🆔 {row['telegram_id']}\n"
            f"💰 ৳{row['balance']:.2f}\n"
            f"👥 {row['referrals']} referrals\n"
            f"{status}\n\n"
        )

    await query.edit_message_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 Back",
                    callback_data="admin_home"
                )
            ]
        ])
    )


async def show_withdrawals(query, pending_only=False):
    conn = get_db()

    if pending_only:
        rows = conn.execute(
            """
            SELECT
                w.*,
                u.first_name,
                u.username
            FROM withdrawals w
            JOIN users u
                ON u.telegram_id=w.telegram_id
            WHERE w.status='pending'
            ORDER BY w.id DESC
            LIMIT 20
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT
                w.*,
                u.first_name,
                u.username
            FROM withdrawals w
            JOIN users u
                ON u.telegram_id=w.telegram_id
            ORDER BY w.id DESC
            LIMIT 20
            """
        ).fetchall()

    conn.close()

    if not rows:
        await query.edit_message_text(
            "💸 WITHDRAWALS\n\n"
            "No withdrawals found.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="admin_home"
                    )
                ]
            ])
        )
        return

    text = "💸 WITHDRAWALS\n\n"
    keyboard = []

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "No username"
        )

        text += (
            f"🆔 #{row['id']}\n"
            f"👤 {row['first_name']} ({username})\n"
            f"📱 {row['telegram_id']}\n"
            f"💳 {row['method'].upper()}\n"
            f"💰 {row['amount']:.2f} {row['currency']}\n"
            f"💵 BDT: ৳{row['bdt_value']:.2f}\n"
            f"📌 {row['status'].upper()}\n\n"
        )

        if row["status"] == "pending":
            keyboard.append([
                InlineKeyboardButton(
                    f"✅ Pay #{row['id']}",
                    callback_data=f"pay_{row['id']}"
                ),
                InlineKeyboardButton(
                    f"❌ Reject #{row['id']}",
                    callback_data=f"reject_{row['id']}"
                )
            ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="admin_home"
        )
    ])

    await query.edit_message_text(
        text[:4000],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def button_editor(query):
    buttons = get_buttons()

    text = (
        "🔘 BUTTON EDITOR\n\n"
        "Tap a button to enable/disable it.\n\n"
    )

    keyboard = []

    for button in buttons:
        status = "🟢 ON" if button["enabled"] else "🔴 OFF"

        text += (
            f"{button['text']}\n"
            f"ID: {button['id']}\n"
            f"Status: {status}\n\n"
        )

        keyboard.append([
            InlineKeyboardButton(
                f"{status} {button['text']}",
                callback_data=f"button_toggle_{button['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 Back",
            callback_data="admin_home"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def toggle_button(query, button_id):
    conn = get_db()

    button = conn.execute(
        "SELECT * FROM bot_buttons WHERE id=?",
        (button_id,)
    ).fetchone()

    if not button:
        conn.close()

        await query.answer(
            "Button not found.",
            show_alert=True
        )

        return

    new_status = 0 if button["enabled"] else 1

    conn.execute(
        "UPDATE bot_buttons SET enabled=? WHERE id=?",
        (new_status, button_id)
    )

    conn.commit()
    conn.close()

    await query.answer(
        "Button updated."
    )

    await button_editor(query)


async def process_withdrawal(query, withdrawal_id, status):
    conn = get_db()

    conn.execute("BEGIN IMMEDIATE")

    withdrawal = conn.execute(
        "SELECT * FROM withdrawals WHERE id=?",
        (withdrawal_id,)
    ).fetchone()

    if not withdrawal:
        conn.rollback()
        conn.close()

        await query.answer(
            "Withdrawal not found.",
            show_alert=True
        )

        return

    if withdrawal["status"] != "pending":
        conn.rollback()
        conn.close()

        await query.answer(
            "Already processed.",
            show_alert=True
        )

        return

    if status == "rejected":
        conn.execute(
            """
            UPDATE users
            SET balance=balance+?,
                withdrawn=withdrawn-?
            WHERE telegram_id=?
            """,
            (
                withdrawal["bdt_value"],
                withdrawal["bdt_value"],
                withdrawal["telegram_id"]
            )
        )

    processed_at = now().isoformat()

    conn.execute(
        """
        UPDATE withdrawals
        SET status=?,
            processed_at=?
        WHERE id=?
        """,
        (
            status,
            processed_at,
            withdrawal_id
        )
    )

    conn.commit()
    conn.close()

    emoji = "✅" if status == "paid" else "❌"

    await query.answer(
        f"{emoji} Withdrawal #{withdrawal_id} {status}.",
        show_alert=True
    )

    await query.edit_message_text(
        f"{emoji} Withdrawal #{withdrawal_id}\n\n"
        f"Status: {status.upper()}\n"
        f"Amount: {withdrawal['amount']:.2f} "
        f"{withdrawal['currency']}\n"
        f"BDT value: ৳{withdrawal['bdt_value']:.2f}",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💸 Withdrawals",
                    callback_data="admin_withdrawals"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Admin Panel",
                    callback_data="admin_home"
                )
            ]
        ])
    )


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Usage:\n/user <telegram_id>"
        )
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid Telegram ID."
        )
        return

    user = get_user(telegram_id)

    if not user:
        await update.message.reply_text(
            "❌ User not found."
        )
        return

    status = (
        "🔴 BLOCKED"
        if user["blocked"]
        else "🟢 ACTIVE"
    )

    await update.message.reply_text(
        f"👤 USER INFORMATION\n\n"
        f"Name: {user['first_name']} {user['last_name']}\n"
        f"Username: @{user['username'] if user['username'] else 'none'}\n"
        f"Telegram ID: {user['telegram_id']}\n\n"
        f"💰 Balance: ৳{user['balance']:.2f}\n"
        f"📈 Total earned: ৳{user['total_earned']:.2f}\n"
        f"💸 Withdrawn: ৳{user['withdrawn']:.2f}\n"
        f"👥 Referrals: {user['referrals']}\n"
        f"📺 Ads watched: {user['ads_watched']}\n"
        f"📌 Status: {status}"
    )


async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage:\n"
            "/addbalance <telegram_id> <amount>"
        )
        return

    try:
        telegram_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid ID or amount."
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ Amount must be greater than 0."
        )
        return

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    if not user:
        conn.close()

        await update.message.reply_text(
            "❌ User not found."
        )
        return

    conn.execute(
        """
        UPDATE users
        SET balance=balance+?,
            total_earned=total_earned+?
        WHERE telegram_id=?
        """,
        (
            amount,
            amount,
            telegram_id
        )
    )

    conn.commit()

    new_balance = user["balance"] + amount

    conn.close()

    await update.message.reply_text(
        f"✅ Balance added.\n\n"
        f"User: {user['first_name']}\n"
        f"Amount: +৳{amount:.2f}\n"
        f"New balance: ৳{new_balance:.2f}"
    )


async def remove_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage:\n"
            "/removebalance <telegram_id> <amount>"
        )
        return

    try:
        telegram_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid ID or amount."
        )
        return

    if amount <= 0:
        await update.message.reply_text(
            "❌ Amount must be greater than 0."
        )
        return

    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    if not user:
        conn.close()

        await update.message.reply_text(
            "❌ User not found."
        )
        return

    if user["balance"] < amount:
        conn.close()

        await update.message.reply_text(
            f"❌ User only has ৳{user['balance']:.2f}."
        )
        return

    conn.execute(
        """
        UPDATE users
        SET balance=balance-?
        WHERE telegram_id=?
        """,
        (
            amount,
            telegram_id
        )
    )

    conn.commit()

    new_balance = user["balance"] - amount

    conn.close()

    await update.message.reply_text(
        f"✅ Balance removed.\n\n"
        f"User: {user['first_name']}\n"
        f"Amount: -৳{amount:.2f}\n"
        f"New balance: ৳{new_balance:.2f}"
    )


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Usage:\n/block <telegram_id>"
        )
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid Telegram ID."
        )
        return

    if telegram_id in OWNER_IDS:
        await update.message.reply_text(
            "🛡️ You cannot block an owner."
        )
        return

    conn = get_db()

    user = conn.execute(
        "SELECT first_name FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    if not user:
        conn.close()

        await update.message.reply_text(
            "❌ User not found."
        )
        return

    conn.execute(
        "UPDATE users SET blocked=1 WHERE telegram_id=?",
        (telegram_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 {user['first_name']} has been blocked."
    )


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "Usage:\n/unblock <telegram_id>"
        )
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid Telegram ID."
        )
        return

    conn = get_db()

    user = conn.execute(
        "SELECT first_name FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    if not user:
        conn.close()

        await update.message.reply_text(
            "❌ User not found."
        )
        return

    conn.execute(
        "UPDATE users SET blocked=0 WHERE telegram_id=?",
        (telegram_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ {user['first_name']} has been unblocked."
    )


async def my_referrals_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    user = query.from_user
    db_user = ensure_user(user)

    conn = get_db()

    referred_users = conn.execute(
        """
        SELECT
            u.first_name,
            u.username,
            r.created_at
        FROM referrals r
        JOIN users u
            ON u.telegram_id=r.referred_id
        WHERE r.referrer_id=?
        ORDER BY r.id DESC
        """,
        (user.id,)
    ).fetchall()

    conn.close()

    if not referred_users:
        text = (
            "👥 Your Referrals\n\n"
            "You don't have any referrals yet.\n\n"
            "Share your referral link to start earning."
        )
    else:
        text = (
            f"👥 Your Referrals\n\n"
            f"Total: {len(referred_users)}\n\n"
        )

        for index, referred in enumerate(
            referred_users,
            start=1
        ):
            name = referred["first_name"]

            if referred["username"]:
                name += f" (@{referred['username']})"

            text += f"{index}. {name}\n"

    await query.message.reply_text(text)


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner_only(update):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    context.user_data["waiting_for_post"] = True

    await update.message.reply_text(
        "📝 POST EDITOR\n\n"
        "Send me the exact message you want to post.\n\n"
        "You can use normal Telegram formatting.\n\n"
        "Send /cancel to cancel."
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_post"):
        context.user_data.pop("waiting_for_post", None)

        await update.message.reply_text(
            "❌ Post cancelled."
        )
        return

    await update.message.reply_text(
        "Nothing to cancel."
    )


async def post_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not owner_only(update):
        return

    if not context.user_data.get("waiting_for_post"):
        return

    context.user_data.pop("waiting_for_post", None)

    text = update.message.text

    if not text:
        await update.message.reply_text(
            "❌ Only text posts are supported right now."
        )
        return

    conn = get_db()

    conn.execute(
        """
        INSERT INTO post_drafts
        (owner_id, content, created_at)
        VALUES (?, ?, ?)
        """,
        (
            update.effective_user.id,
            text,
            now().isoformat()
        )
    )

    conn.commit()

    draft_id = conn.execute(
        "SELECT last_insert_rowid() AS id"
    ).fetchone()["id"]

    conn.close()

    await update.message.reply_text(
        f"📝 Post saved as draft #{draft_id}.\n\n"
        f"Content:\n{text}\n\n"
        f"⚠️ I have not published it anywhere yet.\n\n"
        f"To publish posts to a channel, the channel/chat ID "
        f"needs to be configured."
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing."
        )

    setup_database()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("referrals", referrals)
    )

    application.add_handler(
        CommandHandler("balance", balance)
    )

    application.add_handler(
        CommandHandler("stats", stats)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    application.add_handler(
        CommandHandler("user", user_command)
    )

    application.add_handler(
        CommandHandler("addbalance", add_balance)
    )

    application.add_handler(
        CommandHandler("removebalance", remove_balance)
    )

    application.add_handler(
        CommandHandler("block", block_user)
    )

    application.add_handler(
        CommandHandler("unblock", unblock_user)
    )

    application.add_handler(
        CommandHandler("post", post_command)
    )

    application.add_handler(
        CommandHandler("cancel", cancel_command)
    )

    application.add_handler(
        CallbackQueryHandler(
            my_referrals_callback,
            pattern="^my_referrals$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^(admin_|button_|pay_|reject_)"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            post_message_handler
        )
    )

    print("TaskPayBD bot is running...")
    print(f"Website: {WEBSITE_URL}")
    print("OWNER 1: 7182450475")
    print("OWNER 2: 7897571474")

    application.run_polling()


if __name__ == "__main__":
    main()
