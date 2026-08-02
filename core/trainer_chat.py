"""
core/trainer_chat.py — "Instant Trainer Recommendation" on the Progress
page: sends the profile's real progress data to Claude (via the user's own
API key, set in Settings - same BYOK pattern as the old health feedback
feature) and gets a coaching-style recommendation, then supports follow-up
questions with the original data still in context, so "why am I stuck
here" gets a real answer instead of a generic one.

Uses urllib from the standard library, same as ai_feedback.py, so no
extra pip install is needed.
"""
import json
import urllib.request
import urllib.error
from core import db as dbmod
from core import assessment as assess_mod

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = (
    "You are a calisthenics coach reviewing a trainee's real progress data. "
    "Be direct, specific, and encouraging but honest - reference the actual numbers "
    "and movement patterns given to you, not generic advice. Keep responses "
    "conversational and reasonably short (a few sentences to a short paragraph), "
    "like a coach texting back, not an essay."
)


def build_progress_context(conn, profile_id):
    """A compact text summary of this profile's real progress - what gets
    sent to Claude as context, both for the initial recommendation and
    every follow-up question in the conversation."""
    detail = assess_mod.get_progress_detail(conn, profile_id)
    lines = ["Current progress by movement pattern:"]
    for cat, rows in detail.items():
        for row in rows:
            line = f"- {cat.capitalize()} / {row['label']}: tier {row['tier']}"
            if row["last_date"]:
                line += f", last tested {row['last_date']} ({row['exercise_name']}), status: {row['review']}"
            else:
                line += ", not tested yet"
            lines.append(line)

    lines.append("\nWeighted strength maxes:")
    for ex_id, label in [("pull_weighted_pullup", "Weighted Pull-up"),
                          ("push_weighted_dip", "Weighted Dip"),
                          ("core_weighted_plank", "Weighted Plank")]:
        m = assess_mod.get_weighted_max(conn, profile_id, ex_id)
        if m:
            if ex_id == "core_weighted_plank":
                lines.append(f"- {label}: {m['weight_kg']}kg for {m['hold_seconds']}s")
            else:
                lines.append(f"- {label}: {m['estimated_1rm']}kg estimated 1RM")
        else:
            lines.append(f"- {label}: not tested yet")

    history = assess_mod.get_assessment_history(conn, profile_id, limit=10)
    if history:
        lines.append("\nMost recent assessments (newest first):")
        for h in history:
            val = h["hold_seconds"] if h["hold_seconds"] is not None else h["reps"]
            unit = "s" if h["hold_seconds"] is not None else " reps"
            lines.append(f"- {h['date']}: {h['exercise_name']} — {val}{unit}")

    return "\n".join(lines)


def _call_claude(api_key, model, messages):
    if not api_key:
        raise ValueError("No API key configured — set your own Anthropic API key in Settings first.")
    body = json.dumps({
        "model": model,
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL, data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not reach Claude API: {e}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise ConnectionError(f"Claude API returned an error ({e.code}): {detail[:200]}")

    if "error" in data:
        raise ConnectionError(f"Claude API error: {data['error'].get('message', data['error'])}")
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip() or "No response text returned."


def get_conversation(conn, profile_id):
    rows = conn.execute(
        "SELECT * FROM trainer_chat_messages WHERE profile_id = ? ORDER BY id", (profile_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def save_message(conn, profile_id, role, content):
    conn.execute(
        "INSERT INTO trainer_chat_messages (profile_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (profile_id, role, content, dbmod.now_iso())
    )
    conn.commit()


def clear_conversation(conn, profile_id):
    conn.execute("DELETE FROM trainer_chat_messages WHERE profile_id = ?", (profile_id,))
    conn.commit()


def get_initial_recommendation(conn, profile_id, api_key, model):
    """Starts a fresh conversation: clears any old one, builds context from
    real progress data, asks for a recommendation, stores both the
    (invisible) context-setting turn and the visible recommendation."""
    clear_conversation(conn, profile_id)
    context = build_progress_context(conn, profile_id)
    user_turn = (
        f"Here is my current calisthenics progress data:\n\n{context}\n\n"
        "Give me an honest, specific recommendation - what should I focus on next, "
        "and is anything concerning (e.g. a pattern lagging far behind, or stuck at "
        "the same tier for a while)?"
    )
    reply = _call_claude(api_key, model, [{"role": "user", "content": user_turn}])
    save_message(conn, profile_id, "user", user_turn)
    save_message(conn, profile_id, "assistant", reply)
    return reply


def continue_conversation(conn, profile_id, api_key, model, new_message):
    """Follow-up question - the full stored conversation (which starts with
    the real progress data) is replayed as context, so 'why am I stuck
    here' gets an answer grounded in the actual numbers, not a generic one."""
    history = get_conversation(conn, profile_id)
    if not history:
        return get_initial_recommendation(conn, profile_id, api_key, model)

    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": new_message})
    reply = _call_claude(api_key, model, messages)
    save_message(conn, profile_id, "user", new_message)
    save_message(conn, profile_id, "assistant", reply)
    return reply
