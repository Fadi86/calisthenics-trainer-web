"""
core/trainer_chat.py — "Instant Trainer Recommendation" on the Progress
page: sends the profile's real progress data to Claude OR Gemini (via the
user's own API key, set in Settings - BYOK, nothing embedded in the app)
and gets a coaching-style recommendation, then supports follow-up
questions with the original data still in context, so "why am I stuck
here" gets a real answer instead of a generic one.

Gemini has a genuinely free tier (no credit card) which may suit casual,
low-volume use like this better than a paid-only provider - both are
supported, chosen in Settings.

Uses urllib from the standard library, same as the old ai_feedback.py
pattern, so no extra pip install is needed.
"""
import json
import urllib.request
import urllib.error
from core import db as dbmod
from core import assessment as assess_mod

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

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
        raise ValueError("No API key configured — set your own API key in Settings first.")
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
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise ConnectionError(f"Claude API returned an error ({e.code}): {detail[:200]}")
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not reach Claude API: {e}")

    if "error" in data:
        raise ConnectionError(f"Claude API error: {data['error'].get('message', data['error'])}")
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip() or "No response text returned."


def _call_gemini(api_key, model, messages):
    """Gemini uses 'user'/'model' roles (not 'user'/'assistant'), and a
    separate systemInstruction field rather than a 'system' message. The
    API key is sent both as the x-goog-api-key header AND as a ?key= query
    param - different Gemini doc versions/client libraries expect one or
    the other, so sending both costs nothing and removes the ambiguity."""
    if not api_key:
        raise ValueError("No API key configured — set your own API key in Settings first.")

    contents = [{"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"]}]} for m in messages]
    body = json.dumps({
        "contents": contents,
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"maxOutputTokens": 400},
    }).encode("utf-8")
    url = GEMINI_URL_TEMPLATE.format(model=model) + f"?key={api_key}"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise ConnectionError(f"Gemini API returned an error ({e.code}) for model '{model}': {detail[:300]}")
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not reach Gemini API: {e}")

    if "error" in data:
        raise ConnectionError(f"Gemini API error: {data['error'].get('message', data['error'])}")
    candidates = data.get("candidates", [])
    if not candidates:
        return "No response text returned."
    parts = candidates[0].get("content", {}).get("parts", [])
    return "\n".join(p.get("text", "") for p in parts).strip() or "No response text returned."


def _call_ai(provider, api_key, model, messages):
    if provider == "gemini":
        return _call_gemini(api_key, model, messages)
    return _call_claude(api_key, model, messages)


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


def get_initial_recommendation(conn, profile_id, provider, api_key, model):
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
    reply = _call_ai(provider, api_key, model, [{"role": "user", "content": user_turn}])
    save_message(conn, profile_id, "user", user_turn)
    save_message(conn, profile_id, "assistant", reply)
    return reply


def continue_conversation(conn, profile_id, provider, api_key, model, new_message):
    """Follow-up question - the full stored conversation (which starts with
    the real progress data) is replayed as context, so 'why am I stuck
    here' gets an answer grounded in the actual numbers, not a generic one."""
    history = get_conversation(conn, profile_id)
    if not history:
        return get_initial_recommendation(conn, profile_id, provider, api_key, model)

    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": new_message})
    reply = _call_ai(provider, api_key, model, messages)
    save_message(conn, profile_id, "user", new_message)
    save_message(conn, profile_id, "assistant", reply)
    return reply
