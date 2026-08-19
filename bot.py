import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")

DATABASE = "taskpay.db"
WEBSITE_URL = "https://uzumaki-n1ruto.github.io/TaskPayBD1_Bot/"
REFERRAL_REWARD = 50.00


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def setup_database():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT NOT NULL,
            referral_code TEXT UNIQUE NOT NULL,
            referred_by INTEGER,
            referrals INTEGER DEFAULT 0,
            balance REAL DEFAULT 0,
            total_earned REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            reward REAL DEFAULT 50,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users(id),
            FOREIGN KEY (referred_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()


def get_user(user_id):
    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    conn.close()

    return user


def get_user_by_referral_code(code):
    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE referral_code = ?",
        (code,)
    ).fetchone()

    conn.close()

    return user


def get_next_referral_code(conn):
    rows = conn.execute(
        "SELECT referral_code FROM users"
    ).fetchall()

    highest = 0

    for row in rows:
        code = row["referral_code"]

        if not code:
            continue

        if code.startswith("r") and code[1:].isdigit():
            number = int(code[1:])

            if number > highest:
                highest = number

    return f"r{highest + 1:03d}"


def create_user(user, referral_code=None):
    conn = get_db()

    existing = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user.id,)
    ).fetchone()

    if existing:
        conn.close()
        return existing, False

    own_code = get_next_referral_code(conn)

    referrer = None

    if referral_code:
        referral_code = referral_code.strip()

        referrer = conn.execute(
            "SELECT * FROM users WHERE referral_code = ?",
            (referral_code,)
        ).fetchone()

        if referrer and referrer["id"] == user.id:
            referrer = None

    conn.execute(
        """
        INSERT INTO users (
            id,
            username,
            first_name,
            referral_code,
            referred_by
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user.id,
            user.username or "",
            user.first_name or "User",
            own_code,
            referrer["id"] if referrer else None
        )
    )

    if referrer:
        conn.execute(
            """
            INSERT INTO referrals (
                referrer_id,
                referred_id,
                reward
            )
            VALUES (?, ?, ?)
            """,
            (
                referrer["id"],
                user.id,
                REFERRAL_REWARD
            )
        )

        conn.execute(
            """
            UPDATE users
            SET referrals = referrals + 1,
                balance = balance + ?,
                total_earned = total_earned + ?
            WHERE id = ?
            """,
            (
                REFERRAL_REWARD,
                REFERRAL_REWARD,
                referrer["id"]
            )
        )

    conn.commit()

    created_user = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user.id,)
    ).fetchone()

    conn.close()

    return created_user, True


def get_referral_link(bot_username, referral_code):
    return f"https://t.me/{bot_username}?start={referral_code}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referral_code = None

    if context.args:
        referral_code = context.args[0]

    db_user, created = create_user(
        user,
        referral_code
    )

    bot_username = context.bot.username

    referral_link = get_referral_link(
        bot_username,
        db_user["referral_code"]
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🌐 Open Website",
                url=WEBSITE_URL
            )
        ],
        [
            InlineKeyboardButton(
                "👥 My Referrals",
                callback_data="my_referrals"
            )
        ]
    ]

    if created and db_user["referred_by"]:
        message = (
            f"🎉 Welcome to TaskPayBD, {user.first_name}!\n\n"
            f"You joined through a referral link.\n\n"
            f"Your referrer received "
            f"৳{REFERRAL_REWARD:.2f}.\n\n"
            f"💰 Your balance: ৳{db_user['balance']:.2f}\n"
            f"👥 Your referrals: {db_user['referrals']}\n\n"
            f"🔗 Your referral link:\n"
            f"{referral_link}"
        )
    else:
        message = (
            f"👋 Welcome to TaskPayBD, {user.first_name}!\n\n"
            f"💰 Balance: ৳{db_user['balance']:.2f}\n"
            f"👥 Referrals: {db_user['referrals']}\n\n"
            f"🔗 Your referral link:\n"
            f"{referral_link}"
        )

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    db_user = get_user(user.id)

    if not db_user:
        db_user, _ = create_user(user)

    bot_username = context.bot.username

    referral_link = get_referral_link(
        bot_username,
        db_user["referral_code"]
    )

    conn = get_db()

    referred_users = conn.execute(
        """
        SELECT
            u.first_name,
            u.username,
            r.created_at
        FROM referrals r
        JOIN users u
            ON u.id = r.referred_id
        WHERE r.referrer_id = ?
        ORDER BY r.created_at DESC
        """,
        (user.id,)
    ).fetchall()

    conn.close()

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

        for index, referred in enumerate(referred_users, start=1):
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

    db_user = get_user(user.id)

    if not db_user:
        db_user, _ = create_user(user)

    await update.message.reply_text(
        f"💰 Your Balance\n\n"
        f"Available balance: ৳{db_user['balance']:.2f}\n\n"
        f"Total earned: ৳{db_user['total_earned']:.2f}\n\n"
        f"👥 Referrals: {db_user['referrals']}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    db_user = get_user(user.id)

    if not db_user:
        db_user, _ = create_user(user)

    await update.message.reply_text(
        f"📊 Your TaskPayBD Stats\n\n"
        f"👤 Name: {db_user['first_name']}\n"
        f"🆔 Telegram ID: {db_user['id']}\n"
        f"🔗 Referral code: {db_user['referral_code']}\n"
        f"👥 Referrals: {db_user['referrals']}\n"
        f"💰 Balance: ৳{db_user['balance']:.2f}\n"
        f"📈 Total earned: ৳{db_user['total_earned']:.2f}"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 TaskPayBD Commands\n\n"
        "/start - Start the bot\n"
        "/referrals - View your referrals\n"
        "/balance - View your balance\n"
        "/stats - View your statistics\n"
        "/help - Show this menu"
    )


async def my_referrals_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    db_user = get_user(user.id)

    if not db_user:
        db_user, _ = create_user(user)

    conn = get_db()

    referred_users = conn.execute(
        """
        SELECT
            u.first_name,
            u.username,
            r.created_at
        FROM referrals r
        JOIN users u
            ON u.id = r.referred_id
        WHERE r.referrer_id = ?
        ORDER BY r.created_at DESC
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

        for index, referred in enumerate(referred_users, start=1):
            name = referred["first_name"]

            if referred["username"]:
                name += f" (@{referred['username']})"

            text += f"{index}. {name}\n"

    await query.message.reply_text(text)


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. "
            "Set it with: export BOT_TOKEN='YOUR_TOKEN'"
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
        CallbackQueryHandler(
            my_referrals_callback,
            pattern="^my_referrals$"
        )
    )

    print("TaskPayBD bot is running...")
    print(f"Website: {WEBSITE_URL}")

    application.run_polling()


if __name__ == "__main__":
    main()

