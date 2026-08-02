"""
core/progression.py — live feedback while training, plus the session-over-
session progression/regression rule from PROGRAMMING-GUIDE.md.
"""
from core import db as dbmod
from core import library


def start_session(conn, profile_id, day_type=None, schedule_day_id=None):
    cur = conn.execute(
        "INSERT INTO sessions (date, schedule_day_id, day_type, status, profile_id) VALUES (?, ?, ?, 'in_progress', ?)",
        (dbmod.today_str(), schedule_day_id, day_type, profile_id)
    )
    conn.commit()
    return cur.lastrowid


def complete_session(conn, session_id):
    conn.execute("UPDATE sessions SET status = 'completed' WHERE id = ?", (session_id,))
    conn.commit()


def log_set(conn, session_id, exercise_id, set_number, target_low, target_high,
            reps_done=None, hold_done=None, weight_done=None):
    """
    Logs one set and returns immediate feedback comparing it to the
    prescribed target range for that exercise's current tier.
    """
    value = hold_done if hold_done is not None else reps_done
    feedback = _live_feedback(value, target_low, target_high)

    conn.execute("""
        INSERT INTO session_sets (session_id, exercise_id, set_number, reps_done, hold_done,
            weight_done, target_low, target_high, feedback, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (session_id, exercise_id, set_number, reps_done, hold_done, weight_done,
          target_low, target_high, feedback["message"], dbmod.now_iso()))
    conn.commit()
    return feedback


def _live_feedback(value, target_low, target_high):
    if value is None:
        return {"status": "no_data", "message": "No value logged for this set."}
    if value >= target_high:
        return {"status": "above_target",
                 "message": f"Hit {value:g}, at/above your top target ({target_high:g}). "
                             f"Do this again next session and you're ready to progress."}
    if value < target_low:
        return {"status": "below_target",
                 "message": f"Logged {value:g}, below your target floor ({target_low:g}). "
                             f"That's OK — watch your form on the next set."}
    return {"status": "in_range",
            "message": f"Logged {value:g}, right in your target range "
                        f"({target_low:g}-{target_high:g}). Solid work."}


def evaluate_progress(conn, exercise_id, lookback_sessions=2):
    """
    Looks at the LAST SET of each of the most recent N sessions for this
    exercise. If all were at/above the top of range -> recommend progress.
    If all were below the bottom of range -> recommend regress. Otherwise
    -> hold at the current tier.
    """
    rows = conn.execute("""
        SELECT ss.* FROM session_sets ss
        JOIN sessions s ON s.id = ss.session_id
        WHERE ss.exercise_id = ?
        ORDER BY s.date DESC, ss.id DESC
    """, (exercise_id,)).fetchall()

    if not rows:
        return {"recommendation": "hold", "reason": "No logged sets yet."}

    # last set per distinct session, most recent N sessions
    seen_sessions = []
    last_set_per_session = []
    for r in rows:
        if r["session_id"] not in seen_sessions:
            seen_sessions.append(r["session_id"])
            last_set_per_session.append(r)
        if len(seen_sessions) >= lookback_sessions:
            break

    if len(last_set_per_session) < lookback_sessions:
        return {"recommendation": "hold",
                "reason": f"Only {len(last_set_per_session)} session(s) logged; "
                          f"need {lookback_sessions} to evaluate."}

    ex = library.get_exercise(conn, exercise_id)
    statuses = []
    for r in last_set_per_session:
        value = r["hold_done"] if r["hold_done"] is not None else r["reps_done"]
        statuses.append(_live_feedback(value, r["target_low"], r["target_high"])["status"])

    if all(s == "above_target" for s in statuses):
        next_id = ex["progression_to"][0] if ex.get("progression_to") else None
        return {"recommendation": "progress",
                "reason": f"Top of range hit for {lookback_sessions} sessions in a row.",
                "next_exercise_id": next_id}
    if all(s == "below_target" for s in statuses):
        prev_id = ex["regression_of"][0] if ex.get("regression_of") else None
        return {"recommendation": "regress",
                "reason": f"Below range for {lookback_sessions} sessions in a row.",
                "previous_exercise_id": prev_id}
    return {"recommendation": "hold", "reason": "Mixed results — stay at this tier for now."}
