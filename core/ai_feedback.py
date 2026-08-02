"""
core/ai_feedback.py — training feedback that factors in recent health data.

Two modes, chosen in Settings:
  - "rule_based" (default, no internet/API key needed): straightforward
    heuristics on resting HR / sleep / recent session misses.
  - "claude_api": sends a short, anonymized summary to the Claude API using
    YOUR OWN Anthropic API key (paid, usage-billed to you — this app does
    not include or embed any key). Uses urllib from the standard library,
    so no extra pip install is needed for this part either.
"""
import json
import urllib.request
import urllib.error

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def rule_based_feedback(recent_health, recent_set_statuses):
    """
    recent_health: list of {date, metric, avg_value, unit} from health_import.recent_metrics()
    recent_set_statuses: list of status strings from the last few logged sets
                         ("above_target" / "in_range" / "below_target")
    """
    messages = []

    resting_hr = [m for m in recent_health if "resting" in m["metric"].lower()
                  and "heart" in m["metric"].lower()]
    if resting_hr:
        latest = resting_hr[0]["avg_value"]
        if latest and latest > 65:
            messages.append(
                f"Resting heart rate is reading {latest:.0f} bpm — a bit elevated. "
                f"Consider an easier session today or extra rest between sets."
            )

    sleep_rows = [m for m in recent_health if "sleep" in m["metric"].lower()]
    if sleep_rows:
        latest = sleep_rows[0]["avg_value"]
        if latest and latest < 6:
            messages.append(
                f"Recent sleep logged at {latest:.1f}h — under 6 hours. "
                f"Skill work (front lever/planche/handstand) is the first thing to scale back on low sleep."
            )

    if recent_set_statuses:
        below_count = recent_set_statuses.count("below_target")
        if below_count >= 3:
            messages.append(
                "Several recent sets landed below target range. That's a normal signal to "
                "hold at the current tier rather than push forward this week."
            )
        elif recent_set_statuses.count("above_target") >= 3:
            messages.append(
                "Multiple sets above target range recently — you're likely close to a "
                "tier progression on this movement."
            )

    if not messages:
        messages.append("Nothing unusual in recent data — training as planned looks fine.")
    return messages


def claude_api_feedback(api_key, model, recent_health, recent_sessions_summary):
    """
    Sends a short summary (no name, no raw identifiers) to the Claude API
    and returns the text response. Raises on network/auth errors so the
    caller can fall back to rule_based_feedback.
    """
    if not api_key:
        raise ValueError("No API key configured — set one in Settings, or use rule_based mode.")

    prompt = (
        "You are a calisthenics coach. Based on this recent health and training data, "
        "give 2-3 short, practical sentences of feedback for today's session. "
        "Be direct and specific, no filler.\n\n"
        f"Recent health metrics: {json.dumps(recent_health)[:2000]}\n"
        f"Recent training performance: {recent_sessions_summary}\n"
    )

    body = json.dumps({
        "model": model,
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not reach Claude API: {e}")

    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "\n".join(parts).strip() or "No response text returned."


def get_feedback(conn_settings_getter, recent_health, recent_set_statuses, recent_sessions_summary=""):
    """
    conn_settings_getter: a callable returning (mode, api_key, model) from
    the settings table, so this module doesn't need to import db directly.
    """
    mode, api_key, model = conn_settings_getter()
    if mode == "claude_api":
        try:
            text = claude_api_feedback(api_key, model, recent_health, recent_sessions_summary)
            return {"source": "claude_api", "messages": [text]}
        except Exception as e:
            fallback = rule_based_feedback(recent_health, recent_set_statuses)
            fallback.insert(0, f"(AI feedback unavailable: {e}. Showing rule-based feedback instead.)")
            return {"source": "rule_based_fallback", "messages": fallback}
    return {"source": "rule_based", "messages": rule_based_feedback(recent_health, recent_set_statuses)}
