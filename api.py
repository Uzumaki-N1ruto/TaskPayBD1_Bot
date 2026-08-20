import os
import hmac
import hashlib
import json
import sqlite3
import secrets
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from urllib.parse import parse_qsl, unquote

import requests
from flask import Flask, jsonify, request, send_from_directory, g

app = Flask(__name__, static_folder="static", static_url_path="")

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data, X-Admin-Key"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        return "", 204

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()
DATABASE = os.environ.get("DATABASE", "taskpay.db")
APP_URL = os.environ.get("APP_URL", "").rstrip("/")

BDT_PER_USD = 122.21
AD_REWARD_BDT = 10.00
REFERRAL_REWARD_BDT = 50.00
AD_DURATION_SECONDS = 25
MAX_ADS_PER_DAY = 10
MIN_BDT_WITHDRAW = 1020.00
MIN_USDT_WITHDRAW = 10.00

AD_SESSION_TIMEOUT_SECONDS = 5

DHAKA = ZoneInfo("Asia/Dhaka")

TASKS = {
    "welcome": {
        "title": "Welcome bonus",
        "reward": 50.00,
        "link": "https://t.me/TaskPayBDTasks",
        "category": "JOIN BONUS",
        "type": "telegram",
        "chat": "@TaskPayBDTasks",
        "icon": "telegram"
    },
    "proof": {
        "title": "Payment Proof Channel",
        "reward": 20.00,
        "link": "https://t.me/TaskPayBDOfficial",
        "category": "TELEGRAM",
        "type": "telegram",
        "chat": "@TaskPayBDOfficial",
        "icon": "telegram"
    },
    "youtube": {
        "title": "YouTube Channel",
        "reward": 20.00,
        "link": "https://www.youtube.com/@TaskPayBD",
        "category": "YOUTUBE",
        "type": "external",
        "chat": None,
        "icon": "youtube"
    },
    "official": {
        "title": "Official Channel",
        "reward": 20.00,
        "link": "https://t.me/TaskPayBDUpdates",
        "category": "TELEGRAM",
        "type": "telegram",
        "chat": "@TaskPayBDUpdates",
        "icon": "telegram"
    }
}

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

DEFAULT_LEADERBOARD = [
    {
        "name": "Jannat",
        "count": 4993,
        "avatar": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Arafat",
        "count": 1849,
        "avatar": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Fahim",
        "count": 610,
        "avatar": "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Nayeem",
        "count": 325,
        "avatar": "https://images.unsplash.com/photo-1522075469751-3a6694fb2f61?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Sakib",
        "count": 272,
        "avatar": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Anisha",
        "count": 265,
        "avatar": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Mim",
        "count": 242,
        "avatar": "https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Tania",
        "count": 240,
        "avatar": "https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Nusaiba",
        "count": 234,
        "avatar": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=150&q=80"
    },
    {
        "name": "Sumaiya",
        "count": 229,
        "avatar": "https://images.unsplash.com/photo-1488426862026-3ee34a7d66df?auto=format&fit=crop&w=150&q=80"
    }
]

def now_dhaka():
    return datetime.now(DHAKA)

def today_key():
    return now_dhaka().strftime("%Y-%m-%d")

def db():
    if "db" not in g:
        conn = sqlite3.connect(DATABASE, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    conn = sqlite3.connect(DATABASE)

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

    CREATE INDEX IF NOT EXISTS idx_withdrawals_user
    ON withdrawals(telegram_id);

    CREATE INDEX IF NOT EXISTS idx_ad_sessions_user
    ON ad_sessions(telegram_id);
    """)

    conn.commit()
    conn.close()

def validate_init_data(init_data):
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is not configured")

    if not init_data:
        raise ValueError("Telegram initData is missing")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))

    received_hash = pairs.pop("hash", None)

    if not received_hash:
        raise ValueError("Telegram hash is missing")

    data_check_string = "\n".join(
        f"{key}={pairs[key]}"
        for key in sorted(pairs)
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256
    ).digest()

    calculated = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("Invalid Telegram initData")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except Exception:
        raise ValueError("Invalid Telegram auth_date")

    if abs(
        int(datetime.now(timezone.utc).timestamp()) - auth_date
    ) > 86400:
        raise ValueError("Telegram initData expired")

    raw_user = pairs.get("user")

    if not raw_user:
        raise ValueError("Telegram user is missing")

    try:
        user = json.loads(unquote(raw_user))
    except Exception:
        raise ValueError("Invalid Telegram user data")

    return pairs, user

def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            pairs, tg_user = validate_init_data(
                request.headers.get(
                    "X-Telegram-Init-Data",
                    ""
                )
            )
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": str(e)
            }), 401

        try:
            telegram_id = int(tg_user["id"])
        except Exception:
            return jsonify({
                "ok": False,
                "error": "Invalid Telegram user"
            }), 401

        conn = db()

        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (telegram_id,)
        ).fetchone()

        if not row:
            create_user(
                tg_user,
                pairs.get("start_param")
            )

            row = conn.execute(
                "SELECT * FROM users WHERE telegram_id=?",
                (telegram_id,)
            ).fetchone()

        if row["blocked"]:
            return jsonify({
                "ok": False,
                "error": "Account suspended"
            }), 403

        g.telegram_id = telegram_id
        g.tg_user = tg_user

        return fn(*args, **kwargs)

    return wrapper

def create_user(tg_user, start_param):
    conn = db()

    telegram_id = int(tg_user["id"])

    first_name = str(
        tg_user.get("first_name") or "User"
    )[:100]

    last_name = str(
        tg_user.get("last_name") or ""
    )[:100]

    username = str(
        tg_user.get("username") or ""
    )[:100]

    photo_url = str(
        tg_user.get("photo_url") or ""
    )[:1000]

    joined_at = now_dhaka().isoformat()

    referrer_id = None

    if start_param:
        candidate = str(start_param)

        if candidate.startswith("r"):
            candidate = candidate[1:]

        if candidate.isdigit():
            candidate_id = int(candidate)

            if candidate_id != telegram_id:
                referrer_id = candidate_id

    try:
        conn.execute(
            """
            INSERT INTO users
            (
                telegram_id,
                first_name,
                last_name,
                username,
                photo_url,
                joined_at,
                ads_day,
                referred_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                telegram_id,
                first_name,
                last_name,
                username,
                photo_url,
                joined_at,
                today_key(),
                referrer_id
            )
        )

        conn.commit()

    except sqlite3.IntegrityError:
        return

    if referrer_id:
        try:
            conn.execute("BEGIN IMMEDIATE")

            ref = conn.execute(
                "SELECT telegram_id FROM users WHERE telegram_id=?",
                (referrer_id,)
            ).fetchone()

            if ref:
                conn.execute(
                    """
                    UPDATE users
                    SET
                        referrals=referrals+1,
                        balance=balance+?,
                        total_earned=total_earned+?
                    WHERE telegram_id=?
                    """,
                    (
                        REFERRAL_REWARD_BDT,
                        REFERRAL_REWARD_BDT,
                        referrer_id
                    )
                )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO referrals
                    (
                        referrer_id,
                        referred_id,
                        reward,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        referrer_id,
                        telegram_id,
                        REFERRAL_REWARD_BDT,
                        joined_at
                    )
                )

                conn.commit()

            else:
                conn.rollback()

        except Exception:
            conn.rollback()

def reset_daily_if_needed(row):
    if row["ads_day"] != today_key():
        db().execute(
            """
            UPDATE users
            SET
                ads_watched=0,
                ads_day=?
            WHERE telegram_id=?
            """,
            (
                today_key(),
                row["telegram_id"]
            )
        )

        db().commit()

def user_row():
    row = db().execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (g.telegram_id,)
    ).fetchone()

    if not row:
        raise ValueError("User account could not be created")

    reset_daily_if_needed(row)

    return db().execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (g.telegram_id,)
    ).fetchone()

def get_task_statuses(telegram_id):
    result = {}

    rows = db().execute(
        """
        SELECT task_key, status, completed_at
        FROM task_claims
        WHERE telegram_id=?
        """,
        (telegram_id,)
    ).fetchall()

    for row in rows:
        result[row["task_key"]] = row["status"]

    for key in TASKS:
        result.setdefault(key, "join")

    return result

def get_referrals(telegram_id):
    rows = db().execute(
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
        (telegram_id,)
    ).fetchall()

    result = []

    for row in rows:
        result.append({
            "name": row["first_name"],
            "username": row["username"],
            "date": datetime.fromisoformat(
                row["created_at"]
            ).astimezone(
                DHAKA
            ).strftime("%-d %b %Y").upper()
        })

    return result

def get_history(telegram_id):
    rows = db().execute(
        """
        SELECT
            id,
            method,
            account,
            amount,
            currency,
            status,
            created_at
        FROM withdrawals
        WHERE telegram_id=?
        ORDER BY id DESC
        LIMIT 20
        """,
        (telegram_id,)
    ).fetchall()

    result = []

    for row in rows:
        result.append({
            "id": row["id"],
            "method": row["method"],
            "account": row["account"],
            "amount": row["amount"],
            "currency": row["currency"],
            "status": row["status"],
            "date": datetime.fromisoformat(
                row["created_at"]
            ).astimezone(
                DHAKA
            ).strftime("%-d %b %Y %I:%M %p")
        })

    return result

def build_leaderboard():
    rows = db().execute(
        """
        SELECT
            telegram_id,
            first_name,
            photo_url,
            referrals
        FROM users
        WHERE blocked=0
        ORDER BY referrals DESC, telegram_id ASC
        LIMIT 50
        """
    ).fetchall()

    live = [
        {
            "name": row["first_name"],
            "count": row["referrals"],
            "avatar": row["photo_url"],
            "isCurrentUser": row["telegram_id"] == g.telegram_id
        }
        for row in rows
    ]

    seen = {
        x["name"]
        for x in live
    }

    for item in DEFAULT_LEADERBOARD:
        if item["name"] not in seen:
            live.append(item)

    current = next(
        (
            x
            for x in live
            if x.get("isCurrentUser")
        ),
        None
    )

    if current:
        live = [
            x
            for x in live
            if not x.get("isCurrentUser")
        ]

        live.append(current)

    live.sort(
        key=lambda x: x["count"],
        reverse=True
    )

    return live[:10]

def build_state():
    row = user_row()

    statuses = get_task_statuses(
        g.telegram_id
    )

    tasks = {}

    for key, task in TASKS.items():
        tasks[key] = {
            "title": task["title"],
            "reward": task["reward"],
            "link": task["link"],
            "category": task["category"],
            "type": task["type"],
            "icon": task["icon"],
            "status": statuses[key]
        }

    return {
        "user": {
            "id": str(row["telegram_id"]),
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "username": row["username"],
            "photo_url": row["photo_url"]
        },
        "balance": round(row["balance"], 2),
        "withdrawn": round(row["withdrawn"], 2),
        "totalEarned": round(row["total_earned"], 2),
        "referrals": row["referrals"],
        "adsWatched": row["ads_watched"],
        "adsLimit": MAX_ADS_PER_DAY,
        "joinedDate": datetime.fromisoformat(
            row["joined_at"]
        ).astimezone(
            DHAKA
        ).strftime("%-d %b %Y").upper(),
        "tasks": tasks,
        "referralsList": get_referrals(
            g.telegram_id
        ),
        "withdrawHistory": get_history(
            g.telegram_id
        ),
        "referralLink": (
            f"https://t.me/TaskPayBD1_Bot"
            f"?start=r{row['telegram_id']}"
        ),
        "directAppReferralLink": (
            f"https://t.me/TaskPayBD1_Bot"
            f"?startapp=r{row['telegram_id']}"
        ),
        "bdtPerUsd": BDT_PER_USD,
        "leaderboard": build_leaderboard()
    }

def telegram_api(method, payload):
    if not BOT_TOKEN:
        return None

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload,
            timeout=10
        )

        return response.json()

    except Exception:
        return None

def verify_telegram_membership(user_id, chat):
    data = telegram_api(
        "getChatMember",
        {
            "chat_id": chat,
            "user_id": user_id
        }
    )

    if not data or not data.get("ok"):
        return False

    status = data.get(
        "result",
        {}
    ).get("status")

    return status in {
        "creator",
        "administrator",
        "member"
    }

@app.get("/")
def index():
    return send_from_directory(
        "static",
        "index.html"
    )

@app.get("/health")
def health():
    return jsonify({
        "ok": True
    })

@app.post("/api/bootstrap")
@auth_required
def bootstrap():
    try:
        return jsonify({
            "ok": True,
            "state": build_state()
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"Bootstrap failed: {str(e)}"
        }), 500

@app.post("/api/ad/start")
@auth_required
def start_ad():
    row = user_row()

    if row["ads_watched"] >= MAX_ADS_PER_DAY:
        return jsonify({
            "ok": False,
            "error": "Daily ad limit reached"
        }), 400

    now = int(
        datetime.now(
            timezone.utc
        ).timestamp()
    )

    active = db().execute(
        """
        SELECT id, started_at
        FROM ad_sessions
        WHERE
            telegram_id=?
            AND rewarded=0
            AND completed_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (g.telegram_id,)
    ).fetchone()

    if active:
        age = now - active["started_at"]

        if age >= AD_SESSION_TIMEOUT_SECONDS:
            db().execute(
                """
                UPDATE ad_sessions
                SET completed_at=?
                WHERE id=?
                """,
                (
                    now,
                    active["id"]
                )
            )

            db().commit()

        else:
            return jsonify({
                "ok": False,
                "error": "An ad session is already active"
            }), 400

    session_id = secrets.token_urlsafe(24)

    url = secrets.choice(
        AD_LINKS
    )

    started_at = now

    db().execute(
        """
        INSERT INTO ad_sessions
        (
            id,
            telegram_id,
            url,
            started_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            session_id,
            g.telegram_id,
            url,
            started_at
        )
    )

    db().commit()

    return jsonify({
        "ok": True,
        "sessionId": session_id,
        "url": url,
        "duration": AD_DURATION_SECONDS
    })

@app.post("/api/ad/complete")
@auth_required
def complete_ad():
    payload = request.get_json(
        silent=True
    ) or {}

    session_id = str(
        payload.get("sessionId") or ""
    )

    if not session_id:
        return jsonify({
            "ok": False,
            "error": "Missing ad session"
        }), 400

    conn = db()

    conn.execute(
        "BEGIN IMMEDIATE"
    )

    session = conn.execute(
        """
        SELECT *
        FROM ad_sessions
        WHERE
            id=?
            AND telegram_id=?
        """,
        (
            session_id,
            g.telegram_id
        )
    ).fetchone()

    if not session:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Ad session not found"
        }), 404

    if session["rewarded"]:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Ad already rewarded"
        }), 400

    if session["completed_at"]:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Ad session expired"
        }), 400

    elapsed = (
        int(
            datetime.now(
                timezone.utc
            ).timestamp()
        )
        - session["started_at"]
    )

    if elapsed < AD_DURATION_SECONDS:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": (
                f"Wait "
                f"{AD_DURATION_SECONDS - elapsed} "
                f"more seconds"
            )
        }), 400

    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (g.telegram_id,)
    ).fetchone()

    if row["ads_day"] != today_key():
        conn.execute(
            """
            UPDATE users
            SET
                ads_watched=0,
                ads_day=?
            WHERE telegram_id=?
            """,
            (
                today_key(),
                g.telegram_id
            )
        )

        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (g.telegram_id,)
        ).fetchone()

    if row["ads_watched"] >= MAX_ADS_PER_DAY:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Daily ad limit reached"
        }), 400

    conn.execute(
        """
        UPDATE ad_sessions
        SET
            rewarded=1,
            completed_at=?
        WHERE id=?
        """,
        (
            int(
                datetime.now(
                    timezone.utc
                ).timestamp()
            ),
            session_id
        )
    )

    conn.execute(
        """
        UPDATE users
        SET
            ads_watched=ads_watched+1,
            balance=balance+?,
            total_earned=total_earned+?
        WHERE telegram_id=?
        """,
        (
            AD_REWARD_BDT,
            AD_REWARD_BDT,
            g.telegram_id
        )
    )

    conn.commit()

    return jsonify({
        "ok": True,
        "reward": AD_REWARD_BDT,
        "state": build_state()
    })

@app.post("/api/task/start")
@auth_required
def task_start():
    payload = request.get_json(
        silent=True
    ) or {}

    key = str(
        payload.get("taskKey") or ""
    )

    task = TASKS.get(key)

    if not task:
        return jsonify({
            "ok": False,
            "error": "Invalid task"
        }), 400

    row = db().execute(
        """
        SELECT status
        FROM task_claims
        WHERE
            telegram_id=?
            AND task_key=?
        """,
        (
            g.telegram_id,
            key
        )
    ).fetchone()

    if row and row["status"] == "done":
        return jsonify({
            "ok": False,
            "error": "Task already completed"
        }), 400

    db().execute(
        """
        INSERT INTO task_claims
        (
            telegram_id,
            task_key,
            status
        )
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id, task_key)
        DO UPDATE SET status='claim'
        """,
        (
            g.telegram_id,
            key,
            "claim"
        )
    )

    db().commit()

    return jsonify({
        "ok": True,
        "link": task["link"],
        "state": build_state()
    })

@app.post("/api/task/claim")
@auth_required
def task_claim():
    payload = request.get_json(
        silent=True
    ) or {}

    key = str(
        payload.get("taskKey") or ""
    )

    task = TASKS.get(key)

    if not task:
        return jsonify({
            "ok": False,
            "error": "Invalid task"
        }), 400

    conn = db()

    conn.execute(
        "BEGIN IMMEDIATE"
    )

    existing = conn.execute(
        """
        SELECT status
        FROM task_claims
        WHERE
            telegram_id=?
            AND task_key=?
        """,
        (
            g.telegram_id,
            key
        )
    ).fetchone()

    if not existing or existing["status"] != "claim":
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Open the task first"
        }), 400

    if task["type"] == "telegram":
        if not verify_telegram_membership(
            g.telegram_id,
            task["chat"]
        ):
            conn.rollback()

            return jsonify({
                "ok": False,
                "error": (
                    "Telegram membership could not be verified. "
                    "Make sure you joined the channel and "
                    "the bot can check members."
                )
            }), 400

    conn.execute(
        """
        UPDATE task_claims
        SET
            status='done',
            completed_at=?
        WHERE
            telegram_id=?
            AND task_key=?
        """,
        (
            now_dhaka().isoformat(),
            g.telegram_id,
            key
        )
    )

    conn.execute(
        """
        UPDATE users
        SET
            balance=balance+?,
            total_earned=total_earned+?
        WHERE telegram_id=?
        """,
        (
            task["reward"],
            task["reward"],
            g.telegram_id
        )
    )

    conn.commit()

    return jsonify({
        "ok": True,
        "reward": task["reward"],
        "state": build_state()
    })

@app.post("/api/withdraw")
@auth_required
def withdraw():
    payload = request.get_json(
        silent=True
    ) or {}

    method = str(
        payload.get("method") or ""
    ).lower()

    account = str(
        payload.get("account") or ""
    ).strip()

    amount = payload.get("amount")

    if method not in {
        "bkash",
        "nagad",
        "usdt"
    }:
        return jsonify({
            "ok": False,
            "error": "Invalid payment method"
        }), 400

    try:
        amount = round(
            float(amount),
            2
        )
    except Exception:
        return jsonify({
            "ok": False,
            "error": "Invalid amount"
        }), 400

    if amount <= 0:
        return jsonify({
            "ok": False,
            "error": "Invalid amount"
        }), 400

    if method in {
        "bkash",
        "nagad"
    }:
        if amount < MIN_BDT_WITHDRAW:
            return jsonify({
                "ok": False,
                "error": (
                    f"Minimum withdrawal is "
                    f"৳{MIN_BDT_WITHDRAW:,.2f}"
                )
            }), 400

        if not re.fullmatch(
            r"01\d{9}",
            account
        ):
            return jsonify({
                "ok": False,
                "error": (
                    "Enter a valid 11-digit "
                    "Bangladesh mobile number"
                )
            }), 400

        currency = "BDT"
        bdt_value = amount

    else:
        if amount < MIN_USDT_WITHDRAW:
            return jsonify({
                "ok": False,
                "error": (
                    f"Minimum withdrawal is "
                    f"${MIN_USDT_WITHDRAW:.2f}"
                )
            }), 400

        if not re.fullmatch(
            r"T[1-9A-HJ-NP-Za-km-z]{33}",
            account
        ):
            return jsonify({
                "ok": False,
                "error": (
                    "Enter a valid TRC20 USDT address"
                )
            }), 400

        currency = "USDT"
        bdt_value = round(
            amount * BDT_PER_USD,
            2
        )

    conn = db()

    conn.execute(
        "BEGIN IMMEDIATE"
    )

    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (g.telegram_id,)
    ).fetchone()

    if row["balance"] + 0.000001 < bdt_value:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Insufficient balance"
        }), 400

    pending = conn.execute(
        """
        SELECT id
        FROM withdrawals
        WHERE
            telegram_id=?
            AND status='pending'
        LIMIT 1
        """,
        (g.telegram_id,)
    ).fetchone()

    if pending:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": (
                "You already have a pending withdrawal"
            )
        }), 400

    created_at = now_dhaka().isoformat()

    conn.execute(
        """
        INSERT INTO withdrawals
        (
            telegram_id,
            method,
            account,
            amount,
            currency,
            bdt_value,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            g.telegram_id,
            method,
            account,
            amount,
            currency,
            bdt_value,
            "pending",
            created_at
        )
    )

    conn.execute(
        """
        UPDATE users
        SET
            balance=balance-?,
            withdrawn=withdrawn+?
        WHERE telegram_id=?
        """,
        (
            bdt_value,
            bdt_value,
            g.telegram_id
        )
    )

    conn.commit()

    return jsonify({
        "ok": True,
        "state": build_state()
    })

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        supplied = request.headers.get(
            "X-Admin-Key",
            ""
        )

        if (
            not ADMIN_KEY
            or not hmac.compare_digest(
                supplied,
                ADMIN_KEY
            )
        ):
            return jsonify({
                "ok": False,
                "error": "Unauthorized"
            }), 401

        return fn(*args, **kwargs)

    return wrapper

@app.get("/api/admin/withdrawals")
@admin_required
def admin_withdrawals():
    rows = db().execute(
        """
        SELECT
            w.*,
            u.first_name,
            u.username
        FROM withdrawals w
        JOIN users u
            ON u.telegram_id=w.telegram_id
        ORDER BY w.id DESC
        LIMIT 100
        """
    ).fetchall()

    return jsonify({
        "ok": True,
        "withdrawals": [
            dict(row)
            for row in rows
        ]
    })

@app.post("/api/admin/withdrawal/<int:withdrawal_id>")
@admin_required
def admin_update_withdrawal(
    withdrawal_id
):
    payload = request.get_json(
        silent=True
    ) or {}

    status = str(
        payload.get("status") or ""
    ).lower()

    note = str(
        payload.get("note") or ""
    )[:500]

    if status not in {
        "paid",
        "rejected"
    }:
        return jsonify({
            "ok": False,
            "error": (
                "Status must be paid or rejected"
            )
        }), 400

    conn = db()

    conn.execute(
        "BEGIN IMMEDIATE"
    )

    withdrawal = conn.execute(
        """
        SELECT *
        FROM withdrawals
        WHERE id=?
        """,
        (withdrawal_id,)
    ).fetchone()

    if not withdrawal:
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": "Withdrawal not found"
        }), 404

    if withdrawal["status"] != "pending":
        conn.rollback()

        return jsonify({
            "ok": False,
            "error": (
                "Withdrawal is already processed"
            )
        }), 400

    if status == "rejected":
        conn.execute(
            """
            UPDATE users
            SET
                balance=balance+?,
                withdrawn=withdrawn-?
            WHERE telegram_id=?
            """,
            (
                withdrawal["bdt_value"],
                withdrawal["bdt_value"],
                withdrawal["telegram_id"]
            )
        )

    conn.execute(
        """
        UPDATE withdrawals
        SET
            status=?,
            processed_at=?,
            note=?
        WHERE id=?
        """,
        (
            status,
            now_dhaka().isoformat(),
            note,
            withdrawal_id
        )
    )

    conn.commit()

    return jsonify({
        "ok": True
    })

init_db()

if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
