
import os
import sqlite3
import json
import hmac
import hashlib
import secrets
import time
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE = os.environ.get("DATABASE", "taskpay.db")
WEBSITE_URL = os.environ.get("WEBSITE_URL", "https://uzumaki-n1ruto.github.io/TaskPayBD1_Bot/")
REFERRAL_REWARD = 50.00
BDT_PER_USD = 122.21
AD_REWARD = 10.00
MAX_ADS = 10
AD_SECONDS = 25
AD_LINKS = [
    "https://youtube.com/shorts/QKQLl0VQw6I?si=oWzwF_JFcu9b96Gl",
    "https://youtube.com/shorts/RtUEhRlqcF4?si=QQaPldQUd7bAQvRu",
    "https://youtube.com/shorts/DXMFCrGSxcg?si=vhQdzi_JavwH5HaW",
    "https://youtube.com/shorts/ZV6ov1vN7p0?si=sEl3DHCBwzSh_jMr",
    "https://youtube.com/shorts/Z_khK3dd7bw?si=sBPm_crQ-La2YpIc",
    "https://youtube.com/shorts/xelHWngAHBk?si=zhAEOkY_vulRJRow",
    "https://youtube.com/shorts/gRNG27bz030?si=_I99Ip5eaeGvcPeC",
    "https://youtube.com/shorts/5ZKCfwyWnsU?si=QyztD7LJUA8d8tQk",
    "https://youtube.com/shorts/u49VfbSJ8-o?si=rKqtyg1gVMitdY0g",
    "https://youtube.com/shorts/XUXIstcmVuw?si=sEjXEGGMsIKzQ4iq"
]
TASKS = {
    "welcome": {"title": "Welcome bonus", "reward": 50.0, "link": "https://t.me/TaskPayBDTasks", "category": "JOIN BONUS", "type": "telegram", "icon": "telegram", "chat": "@TaskPayBDTasks"},
    "proof": {"title": "Payment Proof Channel", "reward": 20.0, "link": "https://t.me/TaskPayBDOfficial", "category": "TELEGRAM", "type": "telegram", "icon": "telegram", "chat": "@TaskPayBDOfficial"},
    "youtube": {"title": "YouTube Channel", "reward": 20.0, "link": "https://www.youtube.com/@TaskPayBD", "category": "YOUTUBE", "type": "external", "icon": "youtube"},
    "official": {"title": "Official Channel", "reward": 20.0, "link": "https://t.me/TaskPayBDUpdates", "category": "TELEGRAM", "type": "telegram", "icon": "telegram", "chat": "@TaskPayBDUpdates"}
}

OWNER_IDS = {
    7182450475,
    7897571474
}

POST_CHANNELS = {
    "updates": "@TaskPayBDUpdates",
    "official": "@TaskPayBDOfficial",
    "tasks": "@TaskPayBDTasks"
}

DEFAULT_SETTINGS = {
    "website_label": "🌐 Open Website",
    "website_url": WEBSITE_URL,
    "referrals_label": "👥 My Referrals",
    "welcome_text": "👋 Welcome to TaskPayBD, {first_name}!\n\n💰 Balance: ৳{balance:.2f}\n👥 Referrals: {referrals}\n\n🔗 Your referral link:\n{referral_link}"
}


def get_db():
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
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

    CREATE TABLE IF NOT EXISTS task_claims (
        telegram_id INTEGER NOT NULL,
        task_key TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'join',
        completed_at TEXT,
        PRIMARY KEY (telegram_id, task_key),
        FOREIGN KEY(telegram_id) REFERENCES users(telegram_id)
    );

    CREATE TABLE IF NOT EXISTS ad_sessions (
        id TEXT PRIMARY KEY,
        telegram_id INTEGER NOT NULL,
        url TEXT NOT NULL,
        started_at INTEGER NOT NULL,
        completed_at INTEGER,
        rewarded INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(telegram_id) REFERENCES users(telegram_id)
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

    CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(telegram_id);
    CREATE INDEX IF NOT EXISTS idx_ad_sessions_user ON ad_sessions(telegram_id);
    """)

    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO bot_settings(key, value) VALUES(?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()


def get_setting(key):
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM bot_settings WHERE key=?",
        (key,)
    ).fetchone()
    conn.close()

    if row:
        return row["value"]

    return DEFAULT_SETTINGS.get(key, "")


def set_setting(key, value):
    conn = get_db()
    conn.execute(
        """
        INSERT INTO bot_settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value)
    )
    conn.commit()
    conn.close()


def is_owner(user_id):
    return user_id in OWNER_IDS


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

    now = datetime.now(ZoneInfo("Asia/Dhaka"))
    conn = get_db()

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
            now.isoformat(),
            now.strftime("%Y-%m-%d")
        )
    )

    conn.commit()

    created = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (user.id,)
    ).fetchone()

    conn.close()

    return created


def owner_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"),
            InlineKeyboardButton("💸 Withdrawals", callback_data="admin_withdrawals")
        ],
        [
            InlineKeyboardButton("👥 Users", callback_data="admin_users"),
            InlineKeyboardButton("💰 Balance", callback_data="admin_balance")
        ],
        [
            InlineKeyboardButton("🔘 Button Editor", callback_data="button_editor")
        ],
        [
            InlineKeyboardButton("📝 Post Editor", callback_data="post_editor")
        ],
        [
            InlineKeyboardButton("⏳ Pending Withdrawals", callback_data="admin_pending")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="admin_close")
        ]
    ])


def balance_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Balance", callback_data="balance_add"),
            InlineKeyboardButton("➖ Remove Balance", callback_data="balance_remove")
        ],
        [
            InlineKeyboardButton("🔎 Search User", callback_data="balance_search")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_home")
        ]
    ])


def button_editor_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🌐 Edit Website Button", callback_data="button_website")
        ],
        [
            InlineKeyboardButton("👥 Edit Referral Button", callback_data="button_referrals")
        ],
        [
            InlineKeyboardButton("♻️ Reset Buttons", callback_data="button_reset")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_home")
        ]
    ])


def post_editor_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📢 Updates Channel", callback_data="post_updates")
        ],
        [
            InlineKeyboardButton("💳 Official Channel", callback_data="post_official")
        ],
        [
            InlineKeyboardButton("📋 Tasks Channel", callback_data="post_tasks")
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_home")
        ]
    ])


def get_referral_link(bot_username, user_id):
    return f"https://t.me/{bot_username}?start=r{user_id}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    db_user = ensure_user(user)

    bot_username = context.bot.username
    referral_link = get_referral_link(bot_username, user.id)

    keyboard = [
        [
            InlineKeyboardButton(
                get_setting("website_label"),
                url=get_setting("website_url")
            )
        ],
        [
            InlineKeyboardButton(
                get_setting("referrals_label"),
                callback_data="my_referrals"
            )
        ]
    ]

    message = get_setting("welcome_text").format(
        first_name=user.first_name or "User",
        balance=db_user["balance"],
        referrals=db_user["referrals"],
        referral_link=referral_link
    )

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    try:
        remove_message = await update.message.reply_text(
            "\u2063",
            reply_markup=ReplyKeyboardRemove()
        )
        await remove_message.delete()
    except Exception:
        pass


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_user = ensure_user(user)

    conn = get_db()

    referred_users = conn.execute(
        """
        SELECT u.first_name, u.username, r.created_at
        FROM referrals r
        JOIN users u ON u.telegram_id=r.referred_id
        WHERE r.referrer_id=?
        ORDER BY r.id DESC
        """,
        (user.id,)
    ).fetchall()

    conn.close()

    referral_link = get_referral_link(context.bot.username, user.id)

    message = (
        f"👥 Your Referrals\n\n"
        f"Total referrals: {db_user['referrals']}\n"
        f"Referral earnings: ৳{db_user['referrals'] * REFERRAL_REWARD:.2f}\n\n"
        f"🔗 Your referral link:\n{referral_link}"
    )

    if referred_users:
        message += "\n\n👤 People you referred:\n\n"

        for index, referred in enumerate(referred_users, start=1):
            name = referred["first_name"]

            if referred["username"]:
                name += f" (@{referred['username']})"

            message += f"{index}. {name}\n   +৳{REFERRAL_REWARD:.2f}\n"

    await update.message.reply_text(
        message,
        reply_markup=ReplyKeyboardRemove()
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = ensure_user(update.effective_user)

    await update.message.reply_text(
        f"💰 Your Balance\n\n"
        f"Available balance: ৳{db_user['balance']:.2f}\n\n"
        f"Total earned: ৳{db_user['total_earned']:.2f}\n\n"
        f"👥 Referrals: {db_user['referrals']}",
        reply_markup=ReplyKeyboardRemove()
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = ensure_user(update.effective_user)

    await update.message.reply_text(
        f"📊 Your TaskPayBD Stats\n\n"
        f"👤 Name: {db_user['first_name']}\n"
        f"🆔 Telegram ID: {db_user['telegram_id']}\n"
        f"👥 Referrals: {db_user['referrals']}\n"
        f"💰 Balance: ৳{db_user['balance']:.2f}\n"
        f"📈 Total earned: ৳{db_user['total_earned']:.2f}\n"
        f"💸 Withdrawn: ৳{db_user['withdrawn']:.2f}",
        reply_markup=ReplyKeyboardRemove()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 TaskPayBD Commands\n\n"
        "/start - Start the bot\n"
        "/referrals - View referrals\n"
        "/balance - View balance\n"
        "/stats - View statistics\n"
        "/admin - Owner panel\n"
        "/user <telegram_id> - User information\n"
        "/addbalance <telegram_id> <amount>\n"
        "/removebalance <telegram_id> <amount>\n"
        "/block <telegram_id>\n"
        "/unblock <telegram_id>",
        reply_markup=ReplyKeyboardRemove()
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()

    if not is_owner(update.effective_user.id):
        await update.message.reply_text(
            "⛔ Owner access only.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    await update.message.reply_text(
        "🔐 TaskPayBD OWNER PANEL\n\n"
        "You have full owner access.\n\n"
        "Choose an action:",
        reply_markup=owner_keyboard()
    )

    try:
        remove_message = await update.message.reply_text(
            "\u2063",
            reply_markup=ReplyKeyboardRemove()
        )
        await remove_message.delete()
    except Exception:
        pass


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_owner(query.from_user.id):
        await query.answer("⛔ Owner access only.", show_alert=True)
        return

    action = query.data

    if action.startswith("pay_"):
        await process_withdrawal(query, int(action.split("_")[1]), "paid")
        return

    if action.startswith("reject_"):
        await process_withdrawal(query, int(action.split("_")[1]), "rejected")
        return

    await query.answer()

    if action == "admin_close":
        context.user_data.clear()
        await query.edit_message_text("🔒 Owner panel closed.")
        return

    if action == "admin_home":
        context.user_data.clear()
        await query.edit_message_text(
            "🔐 TaskPayBD OWNER PANEL\n\n"
            "You have full owner access.\n\n"
            "Choose an action:",
            reply_markup=owner_keyboard()
        )
        return

    if action == "admin_stats":
        conn = get_db()

        users = conn.execute("SELECT COUNT(*) count FROM users").fetchone()["count"]
        active = conn.execute("SELECT COUNT(*) count FROM users WHERE blocked=0").fetchone()["count"]
        blocked = conn.execute("SELECT COUNT(*) count FROM users WHERE blocked=1").fetchone()["count"]
        balance_total = conn.execute("SELECT COALESCE(SUM(balance),0) total FROM users").fetchone()["total"]
        earned = conn.execute("SELECT COALESCE(SUM(total_earned),0) total FROM users").fetchone()["total"]
        withdrawn = conn.execute("SELECT COALESCE(SUM(withdrawn),0) total FROM users").fetchone()["total"]
        refs = conn.execute("SELECT COALESCE(SUM(referrals),0) total FROM users").fetchone()["total"]
        pending = conn.execute("SELECT COUNT(*) count FROM withdrawals WHERE status='pending'").fetchone()["count"]

        conn.close()

        await query.edit_message_text(
            "📊 TaskPayBD STATISTICS\n\n"
            f"👥 Total users: {users}\n"
            f"🟢 Active users: {active}\n"
            f"🔴 Blocked users: {blocked}\n\n"
            f"💰 Total balance: ৳{balance_total:,.2f}\n"
            f"📈 Total earned: ৳{earned:,.2f}\n"
            f"💸 Total withdrawn: ৳{withdrawn:,.2f}\n"
            f"👥 Total referrals: {refs}\n"
            f"⏳ Pending withdrawals: {pending}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="admin_home")]
            ])
        )
        return

    if action in {"admin_withdrawals", "admin_pending"}:
        conn = get_db()

        if action == "admin_pending":
            rows = conn.execute(
                """
                SELECT w.*, u.first_name, u.username
                FROM withdrawals w
                JOIN users u ON u.telegram_id=w.telegram_id
                WHERE w.status='pending'
                ORDER BY w.id DESC
                LIMIT 20
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT w.*, u.first_name, u.username
                FROM withdrawals w
                JOIN users u ON u.telegram_id=w.telegram_id
                ORDER BY w.id DESC
                LIMIT 20
                """
            ).fetchall()

        conn.close()

        if not rows:
            await query.edit_message_text(
                "💸 Withdrawals\n\nNo withdrawals found.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="admin_home")]
                ])
            )
            return

        text = "💸 WITHDRAWALS\n\n"
        keyboard = []

        for row in rows:
            username = f"@{row['username']}" if row["username"] else "No username"

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
                    InlineKeyboardButton(f"✅ Pay #{row['id']}", callback_data=f"pay_{row['id']}"),
                    InlineKeyboardButton(f"❌ Reject #{row['id']}", callback_data=f"reject_{row['id']}")
                ])

        keyboard.append([
            InlineKeyboardButton("🔙 Back", callback_data="admin_home")
        ])

        await query.edit_message_text(
            text[:4000],
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if action == "admin_users":
        conn = get_db()

        rows = conn.execute(
            """
            SELECT telegram_id, first_name, username, balance, referrals, blocked
            FROM users
            ORDER BY telegram_id DESC
            LIMIT 20
            """
        ).fetchall()

        total = conn.execute("SELECT COUNT(*) count FROM users").fetchone()["count"]
        conn.close()

        text = f"👥 USERS\n\nTotal users: {total}\n\n"

        for row in rows:
            username = f"@{row['username']}" if row["username"] else "No username"
            status = "🔴 BLOCKED" if row["blocked"] else "🟢 ACTIVE"

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
                [InlineKeyboardButton("🔙 Back", callback_data="admin_home")]
            ])
        )
        return

    if action == "admin_balance":
        await query.edit_message_text(
            "💰 BALANCE CONTROL\n\nChoose an action:",
            reply_markup=balance_keyboard()
        )
        return

    if action == "balance_add":
        context.user_data["mode"] = "add_balance"
        await query.edit_message_text(
            "➕ ADD BALANCE\n\n"
            "Send:\n"
            "<telegram_id> <amount>\n\n"
            "Example:\n"
            "123456789 100\n\n"
            "Send /cancel to cancel."
        )
        return

    if action == "balance_remove":
        context.user_data["mode"] = "remove_balance"
        await query.edit_message_text(
            "➖ REMOVE BALANCE\n\n"
            "Send:\n"
            "<telegram_id> <amount>\n\n"
            "Example:\n"
            "123456789 100\n\n"
            "Send /cancel to cancel."
        )
        return

    if action == "balance_search":
        context.user_data["mode"] = "search_user"
        await query.edit_message_text(
            "🔎 SEARCH USER\n\n"
            "Send the user's Telegram ID.\n\n"
            "Send /cancel to cancel."
        )
        return

    if action == "button_editor":
        context.user_data.clear()
        await query.edit_message_text(
            "🔘 BUTTON EDITOR\n\n"
            "These settings are saved in the database and affect the bot menu.",
            reply_markup=button_editor_keyboard()
        )
        return

    if action == "button_website":
        context.user_data["mode"] = "website_button"
        await query.edit_message_text(
            "🌐 EDIT WEBSITE BUTTON\n\n"
            "Send the new button text.\n\n"
            "Example:\n"
            "🌐 Open TaskPayBD\n\n"
            "Send /cancel to cancel."
        )
        return

    if action == "button_referrals":
        context.user_data["mode"] = "referrals_button"
        await query.edit_message_text(
            "👥 EDIT REFERRAL BUTTON\n\n"
            "Send the new button text.\n\n"
            "Example:\n"
            "👥 My Referrals\n\n"
            "Send /cancel to cancel."
        )
        return

    if action == "button_reset":
        for key, value in DEFAULT_SETTINGS.items():
            set_setting(key, value)

        await query.edit_message_text(
            "♻️ Buttons reset to default.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔘 Button Editor", callback_data="button_editor")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_home")]
            ])
        )
        return

    if action == "post_editor":
        context.user_data.clear()
        await query.edit_message_text(
            "📝 POST EDITOR\n\nChoose where to publish the next post:",
            reply_markup=post_editor_keyboard()
        )
        return

    if action.startswith("post_"):
        channel_key = action[5:]
        channel = POST_CHANNELS.get(channel_key)

        if not channel:
            await query.answer("Invalid channel.", show_alert=True)
            return

        context.user_data["mode"] = "post_message"
        context.user_data["post_channel"] = channel

        await query.edit_message_text(
            f"📝 POST EDITOR\n\n"
            f"Target: {channel}\n\n"
            "Send the text you want the bot to post there.\n\n"
            "Send /cancel to cancel.\n\n"
            "The bot must be an admin in that channel."
        )
        return


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
        await query.answer("Withdrawal not found.", show_alert=True)
        return

    if withdrawal["status"] != "pending":
        conn.rollback()
        conn.close()
        await query.answer("Already processed.", show_alert=True)
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

    processed_at = datetime.now(ZoneInfo("Asia/Dhaka")).isoformat()

    conn.execute(
        """
        UPDATE withdrawals
        SET status=?, processed_at=?
        WHERE id=?
        """,
        (status, processed_at, withdrawal_id)
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
        f"Amount: {withdrawal['amount']:.2f} {withdrawal['currency']}\n"
        f"BDT value: ৳{withdrawal['bdt_value']:.2f}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 Withdrawals", callback_data="admin_withdrawals")],
            [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_home")]
        ])
    )


async def owner_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return

    mode = context.user_data.get("mode")
    if not mode:
        return

    text = (update.message.text or "").strip()
    if not text:
        return

    if mode == "add_balance":
        parts = text.split()

        if len(parts) != 2:
            await update.message.reply_text("❌ Use exactly:\n<telegram_id> <amount>\n\nExample:\n123456789 100")
            return

        try:
            telegram_id = int(parts[0])
            amount = float(parts[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid Telegram ID or amount.")
            return

        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return

        conn = get_db()
        target = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()

        if not target:
            conn.close()
            await update.message.reply_text("❌ User not found.")
            return

        conn.execute(
            """
            UPDATE users
            SET balance=balance+?,
                total_earned=total_earned+?
            WHERE telegram_id=?
            """,
            (amount, amount, telegram_id)
        )

        conn.commit()
        new_balance = target["balance"] + amount
        conn.close()
        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Balance added.\n\n"
            f"User: {target['first_name']}\n"
            f"Amount: +৳{amount:.2f}\n"
            f"New balance: ৳{new_balance:.2f}",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "remove_balance":
        parts = text.split()

        if len(parts) != 2:
            await update.message.reply_text("❌ Use exactly:\n<telegram_id> <amount>\n\nExample:\n123456789 100")
            return

        try:
            telegram_id = int(parts[0])
            amount = float(parts[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid Telegram ID or amount.")
            return

        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0.")
            return

        conn = get_db()
        target = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()

        if not target:
            conn.close()
            await update.message.reply_text("❌ User not found.")
            return

        if target["balance"] < amount:
            conn.close()
            await update.message.reply_text(f"❌ User only has ৳{target['balance']:.2f}.")
            return

        conn.execute(
            "UPDATE users SET balance=balance-? WHERE telegram_id=?",
            (amount, telegram_id)
        )

        conn.commit()
        new_balance = target["balance"] - amount
        conn.close()
        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Balance removed.\n\n"
            f"User: {target['first_name']}\n"
            f"Amount: -৳{amount:.2f}\n"
            f"New balance: ৳{new_balance:.2f}",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "search_user":
        try:
            telegram_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ Enter a valid Telegram ID.")
            return

        target = get_user(telegram_id)

        if not target:
            await update.message.reply_text("❌ User not found.")
            return

        context.user_data.clear()
        status = "🔴 BLOCKED" if target["blocked"] else "🟢 ACTIVE"

        await update.message.reply_text(
            f"👤 USER INFORMATION\n\n"
            f"Name: {target['first_name']} {target['last_name']}\n"
            f"Username: @{target['username'] if target['username'] else 'none'}\n"
            f"Telegram ID: {target['telegram_id']}\n\n"
            f"💰 Balance: ৳{target['balance']:.2f}\n"
            f"📈 Total earned: ৳{target['total_earned']:.2f}\n"
            f"💸 Withdrawn: ৳{target['withdrawn']:.2f}\n"
            f"👥 Referrals: {target['referrals']}\n"
            f"📺 Ads watched: {target['ads_watched']}\n"
            f"📌 Status: {status}",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "website_button":
        set_setting("website_label", text)
        context.user_data["mode"] = "website_url"

        await update.message.reply_text(
            "✅ Button text saved.\n\nNow send the new website URL.\n\nSend /cancel to cancel."
        )
        return

    if mode == "website_url":
        if not text.startswith(("https://", "http://")):
            await update.message.reply_text("❌ Send a valid URL beginning with http:// or https://.")
            return

        set_setting("website_url", text)
        context.user_data.clear()

        await update.message.reply_text(
            "✅ Website button updated successfully.",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "referrals_button":
        set_setting("referrals_label", text)
        context.user_data.clear()

        await update.message.reply_text(
            "✅ Referral button updated successfully.",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "post_message":
        channel = context.user_data.get("post_channel")

        if not channel:
            context.user_data.clear()
            await update.message.reply_text(
                "❌ Post target was lost. Open Post Editor again.",
                reply_markup=owner_keyboard()
            )
            return

        try:
            sent = await context.bot.send_message(
                chat_id=channel,
                text=text
            )
        except Exception:
            await update.message.reply_text(
                "❌ I couldn't post there.\n\n"
                "Make sure the bot is an administrator in that channel and the channel username is correct."
            )
            return

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Post published successfully.\n\n"
            f"Channel: {channel}\n"
            f"Message ID: {sent.message_id}",
            reply_markup=owner_keyboard()
        )
        return


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_owner(update.effective_user.id):
        context.user_data.clear()
        await update.message.reply_text(
            "❌ Cancelled.",
            reply_markup=owner_keyboard()
        )


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner access only.")
        return

    if not context.args:
        await update.message.reply_text("Usage:\n/user <telegram_id>")
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID.")
        return

    user = get_user(telegram_id)

    if not user:
        await update.message.reply_text("❌ User not found.")
        return

    status = "🔴 BLOCKED" if user["blocked"] else "🟢 ACTIVE"

    await update.message.reply_text(
        f"👤 User Information\n\n"
        f"Name: {user['first_name']} {user['last_name']}\n"
        f"Username: @{user['username'] if user['username'] else 'none'}\n"
        f"Telegram ID: {user['telegram_id']}\n\n"
        f"💰 Balance: ৳{user['balance']:.2f}\n"
        f"📈 Total earned: ৳{user['total_earned']:.2f}\n"
        f"💸 Withdrawn: ৳{user['withdrawn']:.2f}\n"
        f"👥 Referrals: {user['referrals']}\n"
        f"📺 Ads watched: {user['ads_watched']}\n"
        f"📌 Status: {status}",
        reply_markup=owner_keyboard()
    )


async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner access only.")
        return

    context.user_data["mode"] = "add_balance"

    await update.message.reply_text(
        "➕ ADD BALANCE\n\n"
        "Send:\n<telegram_id> <amount>\n\n"
        "Example:\n123456789 100\n\n"
        "Send /cancel to cancel."
    )


async def remove_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner access only.")
        return

    context.user_data["mode"] = "remove_balance"

    await update.message.reply_text(
        "➖ REMOVE BALANCE\n\n"
        "Send:\n<telegram_id> <amount>\n\n"
        "Example:\n123456789 100\n\n"
        "Send /cancel to cancel."
    )


async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner access only.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage:\n/block <telegram_id>")
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID.")
        return

    if telegram_id in OWNER_IDS:
        await update.message.reply_text("🛡️ You cannot block an owner.")
        return

    conn = get_db()
    user = conn.execute(
        "SELECT first_name FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    if not user:
        conn.close()
        await update.message.reply_text("❌ User not found.")
        return

    conn.execute(
        "UPDATE users SET blocked=1 WHERE telegram_id=?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🚫 {user['first_name']} has been blocked.",
        reply_markup=owner_keyboard()
    )


async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner access only.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage:\n/unblock <telegram_id>")
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid Telegram ID.")
        return

    conn = get_db()
    user = conn.execute(
        "SELECT first_name FROM users WHERE telegram_id=?",
        (telegram_id,)
    ).fetchone()

    if not user:
        conn.close()
        await update.message.reply_text("❌ User not found.")
        return

    conn.execute(
        "UPDATE users SET blocked=0 WHERE telegram_id=?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ {user['first_name']} has been unblocked.",
        reply_markup=owner_keyboard()
    )


async def my_referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    ensure_user(user)

    conn = get_db()

    referred_users = conn.execute(
        """
        SELECT u.first_name, u.username, r.created_at
        FROM referrals r
        JOIN users u ON u.telegram_id=r.referred_id
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
        text = f"👥 Your Referrals\n\nTotal: {len(referred_users)}\n\n"

        for index, referred in enumerate(referred_users, start=1):
            name = referred["first_name"]

            if referred["username"]:
                name += f" (@{referred['username']})"

            text += f"{index}. {name}\n"

    await query.message.reply_text(text)



app = Flask(__name__)

def api_ok(payload=None, status=200):
    data = {"ok": True}
    if payload:
        data.update(payload)
    return jsonify(data), status

def api_error(message, status=400):
    return jsonify({"ok": False, "error": message}), status

def telegram_api(method, payload=None):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = urllib.parse.urlencode(payload or {}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=12) as response:
        data = json.loads(response.read().decode())
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))
    return data.get("result")

def validate_init_data(init_data):
    if not init_data or not BOT_TOKEN:
        return None, "Telegram authentication data is missing."
    try:
        values = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", "")
        if not received_hash:
            return None, "Invalid Telegram authentication data."
        data_check_string = "\n".join(f"{k}={values[k]}" for k in sorted(values))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None, "Telegram authentication verification failed."
        auth_date = int(values.get("auth_date", "0"))
        if not auth_date or time.time() - auth_date > 86400:
            return None, "Telegram authentication data has expired."
        tg_user = json.loads(values.get("user", "{}"))
        if not tg_user.get("id"):
            return None, "Telegram user data is missing."
        return {"user": tg_user, "start_param": values.get("start_param", "")}, None
    except Exception:
        return None, "Invalid Telegram authentication data."

def get_api_user():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    auth, error = validate_init_data(init_data)
    if error:
        return None, error
    tg = auth["user"]
    class WebUser:
        pass
    user = WebUser()
    user.id = int(tg["id"])
    user.first_name = tg.get("first_name", "User")
    user.last_name = tg.get("last_name", "")
    user.username = tg.get("username", "")
    user.photo_url = tg.get("photo_url", "")
    return (user, auth.get("start_param", "")), None

def process_referral(user_id, start_param):
    if not start_param or not start_param.startswith("r"):
        return
    try:
        referrer_id = int(start_param[1:])
    except ValueError:
        return
    if referrer_id == user_id:
        return
    conn = get_db()
    user = conn.execute("SELECT referred_by FROM users WHERE telegram_id=?", (user_id,)).fetchone()
    referrer = conn.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (referrer_id,)).fetchone()
    already = conn.execute("SELECT id FROM referrals WHERE referred_id=?", (user_id,)).fetchone()
    if user and referrer and not user["referred_by"] and not already:
        now = datetime.now(ZoneInfo("Asia/Dhaka")).isoformat()
        conn.execute("UPDATE users SET referred_by=? WHERE telegram_id=?", (referrer_id, user_id))
        conn.execute("UPDATE users SET referrals=referrals+1, balance=balance+?, total_earned=total_earned+? WHERE telegram_id=?", (REFERRAL_REWARD, REFERRAL_REWARD, referrer_id))
        conn.execute("INSERT INTO referrals(referrer_id,referred_id,reward,created_at) VALUES(?,?,?,?)", (referrer_id, user_id, REFERRAL_REWARD, now))
        conn.commit()
    conn.close()

def reset_ads_if_needed(conn, user_id):
    today = datetime.now(ZoneInfo("Asia/Dhaka")).strftime("%Y-%m-%d")
    row = conn.execute("SELECT ads_day FROM users WHERE telegram_id=?", (user_id,)).fetchone()
    if row and row["ads_day"] != today:
        conn.execute("UPDATE users SET ads_watched=0, ads_day=? WHERE telegram_id=?", (today, user_id))
        conn.commit()

def ensure_task_rows(conn, user_id):
    for key in TASKS:
        conn.execute("INSERT OR IGNORE INTO task_claims(telegram_id,task_key,status) VALUES(?,?,?)", (user_id, key, "join"))
    conn.commit()

def build_state(user_id, tg_user=None):
    conn = get_db()
    reset_ads_if_needed(conn, user_id)
    user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        return None
    ensure_task_rows(conn, user_id)
    claims = conn.execute("SELECT task_key,status FROM task_claims WHERE telegram_id=?", (user_id,)).fetchall()
    claim_map = {r["task_key"]: r["status"] for r in claims}
    referrals = conn.execute("SELECT u.first_name,u.username,r.created_at FROM referrals r JOIN users u ON u.telegram_id=r.referred_id WHERE r.referrer_id=? ORDER BY r.id DESC", (user_id,)).fetchall()
    leaderboard = conn.execute("SELECT telegram_id,first_name,photo_url,referrals FROM users WHERE blocked=0 ORDER BY referrals DESC,telegram_id ASC LIMIT 20").fetchall()
    history = conn.execute("SELECT method,account,amount,currency,status,created_at FROM withdrawals WHERE telegram_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    conn.close()
    bot_username = os.environ.get("BOT_USERNAME", "TaskPayBD1_Bot")
    user_info = {
        "id": str(user["telegram_id"]),
        "first_name": user["first_name"],
        "username": user["username"],
        "photo_url": (tg_user or {}).get("photo_url", "") if tg_user else user["photo_url"]
    }
    tasks = {}
    for key, task in TASKS.items():
        tasks[key] = {k: v for k, v in task.items() if k != "chat"}
        tasks[key]["status"] = claim_map.get(key, "join")
    referral_link = f"https://t.me/{bot_username}?start=r{user_id}"
    return {
        "user": user_info,
        "balance": float(user["balance"]),
        "totalEarned": float(user["total_earned"]),
        "withdrawn": float(user["withdrawn"]),
        "referrals": int(user["referrals"]),
        "adsWatched": int(user["ads_watched"]),
        "referralLink": referral_link,
        "directAppReferralLink": referral_link,
        "referralCode": f"r{user_id}",
        "joinedDate": datetime.fromisoformat(user["joined_at"]).strftime("%d %b %Y").upper(),
        "tasks": tasks,
        "referralsList": [{"name": r["first_name"], "date": datetime.fromisoformat(r["created_at"]).strftime("%d %b %Y").upper()} for r in referrals],
        "leaderboard": [{"name": r["first_name"], "count": int(r["referrals"]), "avatar": r["photo_url"] or "", "isCurrentUser": int(r["telegram_id"]) == user_id} for r in leaderboard],
        "withdrawHistory": [{"method": r["method"], "account": r["account"], "amount": float(r["amount"]), "currency": r["currency"], "status": r["status"], "date": datetime.fromisoformat(r["created_at"]).strftime("%d %b %Y %H:%M")} for r in history]
    }

def verify_membership(user_id, chat):
    try:
        member = telegram_api("getChatMember", {"chat_id": chat, "user_id": user_id})
        return member.get("status") in {"creator", "administrator", "member"}
    except Exception:
        return False

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def api_options(path):
    return ("", 204)

@app.get("/api/health")
def api_health():
    return api_ok({"service": "TaskPayBD", "status": "online"})

@app.post("/api/bootstrap")
def api_bootstrap():
    auth, error = get_api_user()
    if error:
        return api_error(error, 401)
    user, start_param = auth
    before = get_user(user.id)
    db_user = ensure_user(user)
    if before is None:
        process_referral(user.id, start_param)
    state = build_state(user.id, {"photo_url": user.photo_url})
    if db_user["blocked"]:
        return api_error("This account is blocked.", 403)
    return api_ok({"state": state})

@app.post("/api/task/start")
def api_task_start():
    auth, error = get_api_user()
    if error:
        return api_error(error, 401)
    user, _ = auth
    key = (request.get_json(silent=True) or {}).get("taskKey", "")
    task = TASKS.get(key)
    if not task:
        return api_error("Task not found.", 404)
    conn = get_db()
    reset_ads_if_needed(conn, user.id)
    db_user = conn.execute("SELECT blocked FROM users WHERE telegram_id=?", (user.id,)).fetchone()
    if not db_user:
        conn.close()
        ensure_user(user)
        conn = get_db()
    if db_user and db_user["blocked"]:
        conn.close()
        return api_error("This account is blocked.", 403)
    conn.execute("INSERT OR IGNORE INTO task_claims(telegram_id,task_key,status) VALUES(?,?,?)", (user.id, key, "join"))
    conn.execute("UPDATE task_claims SET status='claim' WHERE telegram_id=? AND task_key=? AND status='join'", (user.id, key))
    conn.commit()
    conn.close()
    return api_ok({"state": build_state(user.id, {"photo_url": user.photo_url}), "link": task["link"]})

@app.post("/api/task/claim")
def api_task_claim():
    auth, error = get_api_user()
    if error:
        return api_error(error, 401)
    user, _ = auth
    key = (request.get_json(silent=True) or {}).get("taskKey", "")
    task = TASKS.get(key)
    if not task:
        return api_error("Task not found.", 404)
    conn = get_db()
    row = conn.execute("SELECT status FROM task_claims WHERE telegram_id=? AND task_key=?", (user.id, key)).fetchone()
    if not row or row["status"] != "claim":
        conn.close()
        return api_error("Start the task first.")
    if task["type"] == "telegram" and not verify_membership(user.id, task["chat"]):
        conn.close()
        return api_error("Join the Telegram channel first, then try Claim again.")
    now = datetime.now(ZoneInfo("Asia/Dhaka")).isoformat()
    reward = float(task["reward"])
    conn.execute("UPDATE task_claims SET status='done', completed_at=? WHERE telegram_id=? AND task_key=?", (now, user.id, key))
    conn.execute("UPDATE users SET balance=balance+?, total_earned=total_earned+? WHERE telegram_id=?", (reward, reward, user.id))
    conn.commit()
    conn.close()
    return api_ok({"reward": reward, "state": build_state(user.id, {"photo_url": user.photo_url})})

@app.post("/api/ad/start")
def api_ad_start():
    auth, error = get_api_user()
    if error:
        return api_error(error, 401)
    user, _ = auth
    conn = get_db()
    reset_ads_if_needed(conn, user.id)
    db_user = conn.execute("SELECT ads_watched,blocked FROM users WHERE telegram_id=?", (user.id,)).fetchone()
    if not db_user:
        conn.close()
        ensure_user(user)
        conn = get_db()
        db_user = conn.execute("SELECT ads_watched,blocked FROM users WHERE telegram_id=?", (user.id,)).fetchone()
    if db_user["blocked"]:
        conn.close()
        return api_error("This account is blocked.", 403)
    if db_user["ads_watched"] >= MAX_ADS:
        conn.close()
        return api_error("Daily ad limit reached.")
    active = conn.execute("SELECT id FROM ad_sessions WHERE telegram_id=? AND rewarded=0 AND completed_at IS NULL ORDER BY started_at DESC LIMIT 1", (user.id,)).fetchone()
    if active:
        conn.close()
        return api_error("An ad session is already active.")
    session_id = secrets.token_urlsafe(18)
    url = AD_LINKS[int.from_bytes(os.urandom(4), "big") % len(AD_LINKS)]
    conn.execute("INSERT INTO ad_sessions(id,telegram_id,url,started_at) VALUES(?,?,?,?)", (session_id, user.id, url, int(time.time())))
    conn.commit()
    conn.close()
    return api_ok({"sessionId": session_id, "url": url, "seconds": AD_SECONDS, "reward": AD_REWARD})

@app.post("/api/ad/complete")
def api_ad_complete():
    auth, error = get_api_user()
    if error:
        return api_error(error, 401)
    user, _ = auth
    session_id = (request.get_json(silent=True) or {}).get("sessionId", "")
    conn = get_db()
    session = conn.execute("SELECT * FROM ad_sessions WHERE id=? AND telegram_id=?", (session_id, user.id)).fetchone()
    if not session:
        conn.close()
        return api_error("Ad session not found.")
    if session["rewarded"] or session["completed_at"]:
        conn.close()
        return api_error("This ad session was already completed.")
    if time.time() - session["started_at"] < AD_SECONDS:
        conn.close()
        return api_error("Ad timer has not finished yet.")
    reset_ads_if_needed(conn, user.id)
    db_user = conn.execute("SELECT ads_watched,blocked FROM users WHERE telegram_id=?", (user.id,)).fetchone()
    if db_user["blocked"] or db_user["ads_watched"] >= MAX_ADS:
        conn.close()
        return api_error("Daily ad limit reached or account blocked.")
    completed_at = int(time.time())
    conn.execute("UPDATE ad_sessions SET completed_at=?,rewarded=1 WHERE id=?", (completed_at, session_id))
    conn.execute("UPDATE users SET ads_watched=ads_watched+1,balance=balance+?,total_earned=total_earned+? WHERE telegram_id=?", (AD_REWARD, AD_REWARD, user.id))
    conn.commit()
    conn.close()
    return api_ok({"reward": AD_REWARD, "state": build_state(user.id, {"photo_url": user.photo_url})})

@app.post("/api/withdraw")
def api_withdraw():
    auth, error = get_api_user()
    if error:
        return api_error(error, 401)
    user, _ = auth
    data = request.get_json(silent=True) or {}
    method = str(data.get("method", "")).lower()
    account = str(data.get("account", "")).strip()
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    if method not in {"bkash", "nagad", "usdt"}:
        return api_error("Invalid payment method.")
    if not account:
        return api_error("Enter your account or address.")
    if method == "usdt":
        if amount < 10:
            return api_error("Minimum USDT withdrawal is $10.00.")
        currency = "USDT"
        bdt_value = amount * BDT_PER_USD
    else:
        if amount < 1020:
            return api_error("Minimum bKash/Nagad withdrawal is ৳1,020.00.")
        currency = "BDT"
        bdt_value = amount
    conn = get_db()
    user_row = conn.execute("SELECT balance,blocked FROM users WHERE telegram_id=?", (user.id,)).fetchone()
    if not user_row:
        conn.close()
        return api_error("Account not found.", 404)
    if user_row["blocked"]:
        conn.close()
        return api_error("This account is blocked.", 403)
    if user_row["balance"] < bdt_value:
        conn.close()
        return api_error(f"Insufficient balance. Available: ৳{user_row['balance']:.2f}")
    now = datetime.now(ZoneInfo("Asia/Dhaka")).isoformat()
    conn.execute("INSERT INTO withdrawals(telegram_id,method,account,amount,currency,bdt_value,status,created_at) VALUES(?,?,?,?,?,?,?,?)", (user.id, method, account, amount, currency, bdt_value, "pending", now))
    conn.execute("UPDATE users SET balance=balance-?,withdrawn=withdrawn+? WHERE telegram_id=?", (bdt_value, bdt_value, user.id))
    conn.commit()
    conn.close()
    return api_ok({"state": build_state(user.id, {"photo_url": user.photo_url})})

def run_api():
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing.")

    setup_database()

    threading.Thread(target=run_api, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("referrals", referrals))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CommandHandler("user", user_command))
    application.add_handler(CommandHandler("addbalance", add_balance))
    application.add_handler(CommandHandler("removebalance", remove_balance))
    application.add_handler(CommandHandler("block", block_user))
    application.add_handler(CommandHandler("unblock", unblock_user))
    application.add_handler(CommandHandler("cancel", cancel_command))

    application.add_handler(
        CallbackQueryHandler(
            my_referrals_callback,
            pattern="^my_referrals$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^(admin_|pay_|reject_|button_|post_)"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.User(user_id=list(OWNER_IDS)),
            owner_text_handler
        )
    )

    print("TaskPayBD bot is running...")
    print(f"Website: {get_setting('website_url')}")
    print(f"Owners: {OWNER_IDS}")

    application.run_polling()


if __name__ == "__main__":
    main()
