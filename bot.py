import os
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import asyncpg
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")
WEBSITE_URL = os.environ.get(
    "WEBSITE_URL",
    "https://uzumaki-n1ruto.github.io/TaskPayBD1_Bot/"
)

REFERRAL_REWARD = 50.00

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
    "welcome_text": (
        "👋 Welcome to TaskPayBD, {first_name}!\n\n"
        "💰 Balance: ৳{balance:.2f}\n"
        "👥 Referrals: {referrals}\n\n"
        "🔗 Your referral link:\n"
        "{referral_link}"
    )
}

db_pool = None


async def setup_database():
    global db_pool

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing.")

    db_pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30
    )

    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT DEFAULT '',
                username TEXT DEFAULT '',
                photo_url TEXT DEFAULT '',
                balance DOUBLE PRECISION NOT NULL DEFAULT 0,
                total_earned DOUBLE PRECISION NOT NULL DEFAULT 0,
                withdrawn DOUBLE PRECISION NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL,
                referrals INTEGER NOT NULL DEFAULT 0,
                ads_watched INTEGER NOT NULL DEFAULT 0,
                ads_day TEXT NOT NULL,
                referred_by BIGINT,
                blocked INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id BIGSERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL UNIQUE,
                reward DOUBLE PRECISION NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_claims (
                telegram_id BIGINT NOT NULL,
                task_key TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'join',
                completed_at TEXT,
                PRIMARY KEY (telegram_id, task_key)
            );

            CREATE TABLE IF NOT EXISTS ad_sessions (
                id TEXT PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                url TEXT NOT NULL,
                started_at BIGINT NOT NULL,
                completed_at BIGINT,
                rewarded INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                method TEXT NOT NULL,
                account TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                currency TEXT NOT NULL,
                bdt_value DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                processed_at TEXT,
                note TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_withdrawals_user
            ON withdrawals(telegram_id);

            CREATE INDEX IF NOT EXISTS idx_ad_sessions_user
            ON ad_sessions(telegram_id);
        """)

        for key, value in DEFAULT_SETTINGS.items():
            await conn.execute(
                """
                INSERT INTO bot_settings(key, value)
                VALUES($1, $2)
                ON CONFLICT(key) DO NOTHING
                """,
                key,
                value
            )


async def close_database():
    global db_pool

    if db_pool:
        await db_pool.close()
        db_pool = None


async def get_setting(key):
    async with db_pool.acquire() as conn:
        value = await conn.fetchval(
            "SELECT value FROM bot_settings WHERE key=$1",
            key
        )

    if value is not None:
        return value

    return DEFAULT_SETTINGS.get(key, "")


async def set_setting(key, value):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO bot_settings(key, value)
            VALUES($1, $2)
            ON CONFLICT(key)
            DO UPDATE SET value=EXCLUDED.value
            """,
            key,
            value
        )


def is_owner(user_id):
    return user_id in OWNER_IDS


async def get_user(user_id):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1",
            user_id
        )


async def ensure_user(user):
    existing = await get_user(user.id)

    now = datetime.now(ZoneInfo("Asia/Dhaka"))

    if existing:
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE users
                SET first_name=$1,
                    last_name=$2,
                    username=$3
                WHERE telegram_id=$4
                """,
                user.first_name or "User",
                user.last_name or "",
                user.username or "",
                user.id
            )

        return await get_user(user.id)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users
            (
                telegram_id,
                first_name,
                last_name,
                username,
                photo_url,
                joined_at,
                ads_day
            )
            VALUES($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT(telegram_id) DO NOTHING
            """,
            user.id,
            user.first_name or "User",
            user.last_name or "",
            user.username or "",
            "",
            now.isoformat(),
            now.strftime("%Y-%m-%d")
        )

    return await get_user(user.id)


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
            InlineKeyboardButton(
                "🌐 Edit Website Button",
                callback_data="button_website"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 Edit Referral Button",
                callback_data="button_referrals"
            )
        ],
        [
            InlineKeyboardButton(
                "♻️ Reset Buttons",
                callback_data="button_reset"
            )
        ],
        [
            InlineKeyboardButton("🔙 Back", callback_data="admin_home")
        ]
    ])


def post_editor_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 Updates Channel",
                callback_data="post_updates"
            )
        ],
        [
            InlineKeyboardButton(
                "💳 Official Channel",
                callback_data="post_official"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Tasks Channel",
                callback_data="post_tasks"
            )
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
    db_user = await ensure_user(user)

    args = context.args

    if args:
        ref_code = args[0]

        if ref_code.startswith("r"):
            try:
                referrer_id = int(ref_code[1:])
            except ValueError:
                referrer_id = None

            if referrer_id and referrer_id != user.id:
                async with db_pool.acquire() as conn:
                    async with conn.transaction():
                        existing_referral = await conn.fetchval(
                            """
                            SELECT referred_id
                            FROM referrals
                            WHERE referred_id=$1
                            """,
                            user.id
                        )

                        if not existing_referral:
                            referrer_exists = await conn.fetchval(
                                """
                                SELECT telegram_id
                                FROM users
                                WHERE telegram_id=$1
                                """,
                                referrer_id
                            )

                            if referrer_exists:
                                now = datetime.now(
                                    ZoneInfo("Asia/Dhaka")
                                ).isoformat()

                                await conn.execute(
                                    """
                                    INSERT INTO referrals
                                    (
                                        referrer_id,
                                        referred_id,
                                        reward,
                                        created_at
                                    )
                                    VALUES($1,$2,$3,$4)
                                    ON CONFLICT(referred_id) DO NOTHING
                                    """,
                                    referrer_id,
                                    user.id,
                                    REFERRAL_REWARD,
                                    now
                                )

                                inserted = await conn.fetchval(
                                    """
                                    SELECT COUNT(*)
                                    FROM referrals
                                    WHERE referred_id=$1
                                    AND referrer_id=$2
                                    """,
                                    user.id,
                                    referrer_id
                                )

                                if inserted:
                                    await conn.execute(
                                        """
                                        UPDATE users
                                        SET referrals=referrals+1,
                                            balance=balance+$1,
                                            total_earned=total_earned+$1
                                        WHERE telegram_id=$2
                                        """,
                                        REFERRAL_REWARD,
                                        referrer_id
                                    )

                                    await conn.execute(
                                        """
                                        UPDATE users
                                        SET referred_by=$1
                                        WHERE telegram_id=$2
                                        """,
                                        referrer_id,
                                        user.id
                                    )

    bot_username = context.bot.username

    referral_link = get_referral_link(
        bot_username,
        user.id
    )

    website_label = await get_setting("website_label")
    website_url = await get_setting("website_url")
    referrals_label = await get_setting("referrals_label")
    welcome_text = await get_setting("welcome_text")

    keyboard = [
        [
            InlineKeyboardButton(
                website_label,
                url=website_url
            )
        ],
        [
            InlineKeyboardButton(
                referrals_label,
                callback_data="my_referrals"
            )
        ]
    ]

    message = welcome_text.format(
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
    db_user = await ensure_user(user)

    async with db_pool.acquire() as conn:
        referred_users = await conn.fetch(
            """
            SELECT u.first_name, u.username, r.created_at
            FROM referrals r
            JOIN users u
            ON u.telegram_id=r.referred_id
            WHERE r.referrer_id=$1
            ORDER BY r.id DESC
            """,
            user.id
        )

    referral_link = get_referral_link(
        context.bot.username,
        user.id
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

    await update.message.reply_text(
        message,
        reply_markup=ReplyKeyboardRemove()
    )


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = await ensure_user(update.effective_user)

    await update.message.reply_text(
        f"💰 Your Balance\n\n"
        f"Available balance: "
        f"৳{db_user['balance']:.2f}\n\n"
        f"Total earned: "
        f"৳{db_user['total_earned']:.2f}\n\n"
        f"👥 Referrals: "
        f"{db_user['referrals']}",
        reply_markup=ReplyKeyboardRemove()
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db_user = await ensure_user(update.effective_user)

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
        await query.answer(
            "⛔ Owner access only.",
            show_alert=True
        )
        return

    action = query.data

    if action.startswith("pay_"):
        await process_withdrawal(
            query,
            int(action.split("_")[1]),
            "paid"
        )
        return

    if action.startswith("reject_"):
        await process_withdrawal(
            query,
            int(action.split("_")[1]),
            "rejected"
        )
        return

    await query.answer()

    if action == "admin_close":
        context.user_data.clear()
        await query.edit_message_text(
            "🔒 Owner panel closed."
        )
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
        async with db_pool.acquire() as conn:
            users = await conn.fetchval(
                "SELECT COUNT(*) FROM users"
            )

            active = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE blocked=0"
            )

            blocked = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE blocked=1"
            )

            balance_total = await conn.fetchval(
                "SELECT COALESCE(SUM(balance),0) FROM users"
            )

            earned = await conn.fetchval(
                "SELECT COALESCE(SUM(total_earned),0) FROM users"
            )

            withdrawn = await conn.fetchval(
                "SELECT COALESCE(SUM(withdrawn),0) FROM users"
            )

            refs = await conn.fetchval(
                "SELECT COALESCE(SUM(referrals),0) FROM users"
            )

            pending = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM withdrawals
                WHERE status='pending'
                """
            )

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
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="admin_home"
                    )
                ]
            ])
        )
        return

    if action in {"admin_withdrawals", "admin_pending"}:
        async with db_pool.acquire() as conn:
            if action == "admin_pending":
                rows = await conn.fetch(
                    """
                    SELECT w.*, u.first_name, u.username
                    FROM withdrawals w
                    JOIN users u
                    ON u.telegram_id=w.telegram_id
                    WHERE w.status='pending'
                    ORDER BY w.id DESC
                    LIMIT 20
                    """
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT w.*, u.first_name, u.username
                    FROM withdrawals w
                    JOIN users u
                    ON u.telegram_id=w.telegram_id
                    ORDER BY w.id DESC
                    LIMIT 20
                    """
                )

        if not rows:
            await query.edit_message_text(
                "💸 Withdrawals\n\n"
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
                f"💰 {row['amount']:.2f} "
                f"{row['currency']}\n"
                f"💵 BDT: "
                f"৳{row['bdt_value']:.2f}\n"
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
        return

    if action == "admin_users":
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT telegram_id,
                       first_name,
                       username,
                       balance,
                       referrals,
                       blocked
                FROM users
                ORDER BY telegram_id DESC
                LIMIT 20
                """
            )

            total = await conn.fetchval(
                "SELECT COUNT(*) FROM users"
            )

        text = (
            f"👥 USERS\n\n"
            f"Total users: {total}\n\n"
        )

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
                f"👤 {row['first_name']} "
                f"{username}\n"
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
        return

    if action == "admin_balance":
        await query.edit_message_text(
            "💰 BALANCE CONTROL\n\n"
            "Choose an action:",
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
            "These settings are saved in PostgreSQL.",
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
            await set_setting(key, value)

        await query.edit_message_text(
            "♻️ Buttons reset to default.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔘 Button Editor",
                        callback_data="button_editor"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Back",
                        callback_data="admin_home"
                    )
                ]
            ])
        )
        return

    if action == "post_editor":
        context.user_data.clear()

        await query.edit_message_text(
            "📝 POST EDITOR\n\n"
            "Choose where to publish the next post:",
            reply_markup=post_editor_keyboard()
        )
        return

    if action.startswith("post_"):
        channel_key = action[5:]
        channel = POST_CHANNELS.get(channel_key)

        if not channel:
            await query.answer(
                "Invalid channel.",
                show_alert=True
            )
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


async def process_withdrawal(
    query,
    withdrawal_id,
    status
):
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            withdrawal = await conn.fetchrow(
                """
                SELECT *
                FROM withdrawals
                WHERE id=$1
                FOR UPDATE
                """,
                withdrawal_id
            )

            if not withdrawal:
                await query.answer(
                    "Withdrawal not found.",
                    show_alert=True
                )
                return

            if withdrawal["status"] != "pending":
                await query.answer(
                    "Already processed.",
                    show_alert=True
                )
                return

            if status == "rejected":
                await conn.execute(
                    """
                    UPDATE users
                    SET balance=balance+$1,
                        withdrawn=withdrawn-$1
                    WHERE telegram_id=$2
                    """,
                    withdrawal["bdt_value"],
                    withdrawal["telegram_id"]
                )

            processed_at = datetime.now(
                ZoneInfo("Asia/Dhaka")
            ).isoformat()

            await conn.execute(
                """
                UPDATE withdrawals
                SET status=$1,
                    processed_at=$2
                WHERE id=$3
                """,
                status,
                processed_at,
                withdrawal_id
            )

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
        f"BDT value: "
        f"৳{withdrawal['bdt_value']:.2f}",
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


async def owner_text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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
            await update.message.reply_text(
                "❌ Use exactly:\n"
                "<telegram_id> <amount>\n\n"
                "Example:\n"
                "123456789 100"
            )
            return

        try:
            telegram_id = int(parts[0])
            amount = float(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid Telegram ID or amount."
            )
            return

        if amount <= 0:
            await update.message.reply_text(
                "❌ Amount must be greater than 0."
            )
            return

        async with db_pool.acquire() as conn:
            target = await conn.fetchrow(
                """
                SELECT *
                FROM users
                WHERE telegram_id=$1
                """,
                telegram_id
            )

            if not target:
                await update.message.reply_text(
                    "❌ User not found."
                )
                return

            await conn.execute(
                """
                UPDATE users
                SET balance=balance+$1,
                    total_earned=total_earned+$1
                WHERE telegram_id=$2
                """,
                amount,
                telegram_id
            )

        new_balance = target["balance"] + amount
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
            await update.message.reply_text(
                "❌ Use exactly:\n"
                "<telegram_id> <amount>\n\n"
                "Example:\n"
                "123456789 100"
            )
            return

        try:
            telegram_id = int(parts[0])
            amount = float(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid Telegram ID or amount."
            )
            return

        if amount <= 0:
            await update.message.reply_text(
                "❌ Amount must be greater than 0."
            )
            return

        async with db_pool.acquire() as conn:
            target = await conn.fetchrow(
                """
                SELECT *
                FROM users
                WHERE telegram_id=$1
                """,
                telegram_id
            )

            if not target:
                await update.message.reply_text(
                    "❌ User not found."
                )
                return

            if target["balance"] < amount:
                await update.message.reply_text(
                    f"❌ User only has "
                    f"৳{target['balance']:.2f}."
                )
                return

            await conn.execute(
                """
                UPDATE users
                SET balance=balance-$1
                WHERE telegram_id=$2
                """,
                amount,
                telegram_id
            )

        new_balance = target["balance"] - amount
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
            await update.message.reply_text(
                "❌ Enter a valid Telegram ID."
            )
            return

        target = await get_user(telegram_id)

        if not target:
            await update.message.reply_text(
                "❌ User not found."
            )
            return

        context.user_data.clear()

        status = (
            "🔴 BLOCKED"
            if target["blocked"]
            else "🟢 ACTIVE"
        )

        await update.message.reply_text(
            f"👤 USER INFORMATION\n\n"
            f"Name: {target['first_name']} "
            f"{target['last_name']}\n"
            f"Username: "
            f"@{target['username'] if target['username'] else 'none'}\n"
            f"Telegram ID: {target['telegram_id']}\n\n"
            f"💰 Balance: "
            f"৳{target['balance']:.2f}\n"
            f"📈 Total earned: "
            f"৳{target['total_earned']:.2f}\n"
            f"💸 Withdrawn: "
            f"৳{target['withdrawn']:.2f}\n"
            f"👥 Referrals: "
            f"{target['referrals']}\n"
            f"📺 Ads watched: "
            f"{target['ads_watched']}\n"
            f"📌 Status: {status}",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "website_button":
        await set_setting(
            "website_label",
            text
        )

        context.user_data["mode"] = "website_url"

        await update.message.reply_text(
            "✅ Button text saved.\n\n"
            "Now send the new website URL.\n\n"
            "Send /cancel to cancel."
        )
        return

    if mode == "website_url":
        if not text.startswith(
            ("https://", "http://")
        ):
            await update.message.reply_text(
                "❌ Send a valid URL beginning "
                "with http:// or https://."
            )
            return

        await set_setting(
            "website_url",
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Website button updated successfully.",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "referrals_button":
        await set_setting(
            "referrals_label",
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Referral button updated successfully.",
            reply_markup=owner_keyboard()
        )
        return

    if mode == "post_message":
        channel = context.user_data.get(
            "post_channel"
        )

        if not channel:
            context.user_data.clear()

            await update.message.reply_text(
                "❌ Post target was lost. "
                "Open Post Editor again.",
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
                "Make sure the bot is an administrator "
                "in that channel and the channel username "
                "is correct."
            )
            return

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ Post published successfully.\n\n"
            f"Channel: {channel}\n"
            f"Message ID: {sent.message_id}",
            reply_markup=owner_keyboard()
        )


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if is_owner(update.effective_user.id):
        context.user_data.clear()

        await update.message.reply_text(
            "❌ Cancelled.",
            reply_markup=owner_keyboard()
        )


async def user_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    if not context.args:
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

    user = await get_user(telegram_id)

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
        f"👤 User Information\n\n"
        f"Name: {user['first_name']} "
        f"{user['last_name']}\n"
        f"Username: "
        f"@{user['username'] if user['username'] else 'none'}\n"
        f"Telegram ID: {user['telegram_id']}\n\n"
        f"💰 Balance: ৳{user['balance']:.2f}\n"
        f"📈 Total earned: "
        f"৳{user['total_earned']:.2f}\n"
        f"💸 Withdrawn: "
        f"৳{user['withdrawn']:.2f}\n"
        f"👥 Referrals: {user['referrals']}\n"
        f"📺 Ads watched: {user['ads_watched']}\n"
        f"📌 Status: {status}",
        reply_markup=owner_keyboard()
    )


async def add_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    context.user_data["mode"] = "add_balance"

    await update.message.reply_text(
        "➕ ADD BALANCE\n\n"
        "Send:\n"
        "<telegram_id> <amount>\n\n"
        "Example:\n"
        "123456789 100\n\n"
        "Send /cancel to cancel."
    )


async def remove_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text(
            "⛔ Owner access only."
        )
        return

    context.user_data["mode"] = "remove_balance"

    await update.message.reply_text(
        "➖ REMOVE BALANCE\n\n"
        "Send:\n"
        "<telegram_id> <amount>\n\n"
        "Example:\n"
        "123456789 100\n\n"
        "Send /cancel to cancel."
    )


async def block_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_owner(update.effective_user.id):
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

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT first_name
            FROM users
            WHERE telegram_id=$1
            """,
            telegram_id
        )

        if not user:
            await update.message.reply_text(
                "❌ User not found."
            )
            return

        await conn.execute(
            """
            UPDATE users
            SET blocked=1
            WHERE telegram_id=$1
            """,
            telegram_id
        )

    await update.message.reply_text(
        f"🚫 {user['first_name']} has been blocked.",
        reply_markup=owner_keyboard()
    )


async def unblock_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_owner(update.effective_user.id):
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

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow(
            """
            SELECT first_name
            FROM users
            WHERE telegram_id=$1
            """,
            telegram_id
        )

        if not user:
            await update.message.reply_text(
                "❌ User not found."
            )
            return

        await conn.execute(
            """
            UPDATE users
            SET blocked=0
            WHERE telegram_id=$1
            """,
            telegram_id
        )

    await update.message.reply_text(
        f"✅ {user['first_name']} has been unblocked.",
        reply_markup=owner_keyboard()
    )


async def my_referrals_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    user = query.from_user

    await ensure_user(user)

    async with db_pool.acquire() as conn:
        referred_users = await conn.fetch(
            """
            SELECT u.first_name,
                   u.username,
                   r.created_at
            FROM referrals r
            JOIN users u
            ON u.telegram_id=r.referred_id
            WHERE r.referrer_id=$1
            ORDER BY r.id DESC
            """,
            user.id
        )

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


async def post_init(application):
    await setup_database()


async def post_shutdown(application):
    await close_database()


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing."
        )

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
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
            pattern=r"^(admin_|pay_|reject_|button_|post_)"
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.User(
                user_id=list(OWNER_IDS)
            ),
            owner_text_handler
        )
    )

    print("TaskPayBD bot is running...")
    print("PostgreSQL database enabled.")
    print(f"Owners: {OWNER_IDS}")

    application.run_polling()


if __name__ == "__main__":
    main()
