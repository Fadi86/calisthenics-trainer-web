"""
core/chat.py — a simple shared group chat between all profiles on this
deployment. Intentionally NOT scoped per-profile (unlike everything else
in this app) since the whole point is for the up-to-5 people sharing a
deployment to see each other's messages.
"""
from core import db as dbmod


def send_message(conn, profile_id, message):
    message = message.strip()
    if not message:
        return None
    conn.execute(
        "INSERT INTO chat_messages (profile_id, message, created_at) VALUES (?, ?, ?)",
        (profile_id, message, dbmod.now_iso())
    )
    conn.commit()


def get_messages(conn, limit=200):
    rows = conn.execute("""
        SELECT cm.*, p.name as sender_name FROM chat_messages cm
        LEFT JOIN profiles p ON p.id = cm.profile_id
        ORDER BY cm.id ASC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_messages_since(conn, since_id=0, limit=200):
    rows = conn.execute("""
        SELECT cm.*, p.name as sender_name FROM chat_messages cm
        LEFT JOIN profiles p ON p.id = cm.profile_id
        WHERE cm.id > ? ORDER BY cm.id ASC LIMIT ?
    """, (since_id, limit)).fetchall()
    return [dict(r) for r in rows]
