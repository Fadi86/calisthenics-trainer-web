"""
core/backup.py — exports/imports ONE profile's progress and history as a
single JSON file, so it can be saved to Google Drive (or anywhere) and
restored later. Scoped per-profile since multiple people now share these
tables (up to db.MAX_PROFILES) - importing never touches anyone else's data,
and row IDs are remapped on import rather than reused, since blindly
reinserting old numeric IDs could collide with a different profile's rows
in the same table.
"""
import json
from core import db as dbmod


def export_backup(conn, profile_id):
    data = {"exported_at": dbmod.now_iso(), "version": 2, "profile_id_hint": profile_id}

    data["profile"] = [dbmod.get_profile(conn, profile_id)] if dbmod.get_profile(conn, profile_id) else []
    data["assessments"] = [dict(r) for r in conn.execute(
        "SELECT * FROM assessments WHERE profile_id = ?", (profile_id,)).fetchall()]
    data["user_tiers"] = [dict(r) for r in conn.execute(
        "SELECT * FROM user_tiers WHERE profile_id = ?", (profile_id,)).fetchall()]
    data["health_metrics"] = [dict(r) for r in conn.execute(
        "SELECT * FROM health_metrics WHERE profile_id = ?", (profile_id,)).fetchall()]

    sessions = [dict(r) for r in conn.execute(
        "SELECT * FROM sessions WHERE profile_id = ?", (profile_id,)).fetchall()]
    data["sessions"] = sessions
    session_ids = [s["id"] for s in sessions]
    if session_ids:
        placeholders = ",".join("?" * len(session_ids))
        data["session_sets"] = [dict(r) for r in conn.execute(
            f"SELECT * FROM session_sets WHERE session_id IN ({placeholders})", session_ids).fetchall()]
    else:
        data["session_sets"] = []

    return data


def import_backup(conn, profile_id, data):
    """Replaces THIS profile's progress/history with the backup's contents.
    Never touches another profile's rows, and never reuses the backup's old
    numeric IDs (they could belong to someone else's data in these shared
    tables now) - session IDs are remapped so session_sets still point at
    the right (new) session."""
    if data.get("version") not in (1, 2):
        raise ValueError("Unrecognized backup format/version.")

    conn.execute("DELETE FROM session_sets WHERE session_id IN "
                 "(SELECT id FROM sessions WHERE profile_id = ?)", (profile_id,))
    conn.execute("DELETE FROM sessions WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM assessments WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM user_tiers WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM health_metrics WHERE profile_id = ?", (profile_id,))

    for row in data.get("user_tiers", []):
        conn.execute("""
            INSERT INTO user_tiers (profile_id, movement_key, current_tier, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id, movement_key) DO UPDATE SET current_tier=excluded.current_tier,
                updated_at=excluded.updated_at
        """, (profile_id, row["movement_key"], row["current_tier"], row["updated_at"]))

    for row in data.get("assessments", []):
        conn.execute("""
            INSERT INTO assessments (profile_id, exercise_id, date, reps, hold_seconds, weight_kg,
                estimated_1rm, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """, (profile_id, row["exercise_id"], row["date"], row.get("reps"), row.get("hold_seconds"),
              row.get("weight_kg"), row.get("estimated_1rm"), row.get("notes")))

    session_id_map = {}
    for row in data.get("sessions", []):
        cur = conn.execute(
            "INSERT INTO sessions (date, schedule_day_id, day_type, status, profile_id) VALUES (?,?,?,?,?)",
            (row["date"], row.get("schedule_day_id"), row.get("day_type"), row["status"], profile_id)
        )
        session_id_map[row["id"]] = cur.lastrowid

    for row in data.get("session_sets", []):
        new_session_id = session_id_map.get(row["session_id"])
        if new_session_id is None:
            continue  # orphaned in the source data - skip rather than guess
        conn.execute("""
            INSERT INTO session_sets (session_id, exercise_id, set_number, reps_done, hold_done,
                weight_done, target_low, target_high, feedback, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (new_session_id, row["exercise_id"], row["set_number"], row.get("reps_done"),
              row.get("hold_done"), row.get("weight_done"), row["target_low"], row["target_high"],
              row.get("feedback"), row["created_at"]))

    for row in data.get("health_metrics", []):
        conn.execute(
            "INSERT INTO health_metrics (date, metric, value, unit, source, profile_id) VALUES (?,?,?,?,?,?)",
            (row["date"], row["metric"], row.get("value"), row.get("unit"), row.get("source"), profile_id)
        )

    profile_rows = data.get("profile", [])
    if profile_rows:
        p = profile_rows[0]
        dbmod.update_profile(conn, profile_id, p.get("name"), p.get("gender"), p.get("age"),
                              p.get("weight_kg"), p.get("height_cm"))

    conn.commit()
