from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)

DATABASE = "taskpay.db"


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "service": "TaskPayBD API"
    })


@app.route("/api/user/<int:user_id>")
def get_user(user_id):
    conn = get_db()

    user = conn.execute(
        """
        SELECT
            id,
            username,
            first_name,
            referral_code,
            referrals,
            balance,
            total_earned,
            created_at
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()

        return jsonify({
            "success": False,
            "error": "User not found"
        }), 404

    referrals = conn.execute(
        """
        SELECT
            u.id,
            u.username,
            u.first_name,
            r.reward,
            r.created_at
        FROM referrals r
        JOIN users u
            ON u.id = r.referred_id
        WHERE r.referrer_id = ?
        ORDER BY r.created_at DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "first_name": user["first_name"],
            "referral_code": user["referral_code"],
            "referrals": user["referrals"],
            "balance": user["balance"],
            "total_earned": user["total_earned"],
            "created_at": user["created_at"]
        },
        "referral_list": [
            {
                "id": item["id"],
                "username": item["username"],
                "first_name": item["first_name"],
                "reward": item["reward"],
                "created_at": item["created_at"]
            }
            for item in referrals
        ]
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )

