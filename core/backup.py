"""
core/backup.py — exports/imports the user's actual progress and history as
a single JSON file, so it can be saved to Google Drive (or anywhere) and
restored later. This is a real backup of the SQLite data, not a simplified
snapshot — assessments, tier progress, session history, and health data
all round-trip.
"""
import json
from core import db as dbmod


def export_backup(conn):
    tables = {
        "assessments": "SELECT * FROM assessments",
        "user_tiers": "SELECT * FROM user_tiers",
        "sessions": "SELECT * FROM sessions",
        "session_sets": "SELECT * FROM session_sets",
        "health_metrics": "SELECT * FROM health_metrics",
        "settings": "SELECT * FROM settings",
        "profile": "SELECT * FROM profile",
    }
    data = {"exported_at": dbmod.now_iso(), "version": 1}
    for name, query in tables.items():
        rows = conn.execute(query).fetchall()
        data[name] = [dict(r) for r in rows]
    return data


def import_backup(conn, data):
    """Replaces the user's progress/history tables with the backup's
    contents. Does NOT touch the exercises table (that's library content,
    always re-synced from exercises.json on launch, not user data)."""
    if data.get("version") != 1:
        raise ValueError("Unrecognized backup format/version.")

    conn.execute("DELETE FROM session_sets")
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM assessments")
    conn.execute("DELETE FROM user_tiers")
    conn.execute("DELETE FROM health_metrics")

    for row in data.get("user_tiers", []):
        conn.execute("INSERT INTO user_tiers (movement_key, current_tier, updated_at) VALUES (?,?,?)",
                     (row["movement_key"], row["current_tier"], row["updated_at"]))

    for row in data.get("assessments", []):
        conn.execute("""
            INSERT INTO assessments (id, exercise_id, date, reps, hold_seconds, weight_kg, estimated_1rm, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """, (row["id"], row["exercise_id"], row["date"], row["reps"], row["hold_seconds"],
              row["weight_kg"], row["estimated_1rm"], row.get("notes")))

    for row in data.get("sessions", []):
        conn.execute("INSERT INTO sessions (id, date, schedule_day_id, day_type, status) VALUES (?,?,?,?,?)",
                     (row["id"], row["date"], row.get("schedule_day_id"), row.get("day_type"), row["status"]))

    for row in data.get("session_sets", []):
        conn.execute("""
            INSERT INTO session_sets (id, session_id, exercise_id, set_number, reps_done, hold_done,
                weight_done, target_low, target_high, feedback, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (row["id"], row["session_id"], row["exercise_id"], row["set_number"], row.get("reps_done"),
              row.get("hold_done"), row.get("weight_done"), row["target_low"], row["target_high"],
              row.get("feedback"), row["created_at"]))

    for row in data.get("health_metrics", []):
        conn.execute("INSERT INTO health_metrics (id, date, metric, value, unit, source) VALUES (?,?,?,?,?,?)",
                     (row["id"], row["date"], row["metric"], row.get("value"), row.get("unit"), row.get("source")))

    for row in data.get("settings", []):
        dbmod.set_setting(conn, row["key"], row["value"])

    for row in data.get("profile", []):
        conn.execute("""
            INSERT INTO profile (id, name, gender, age, weight_kg, height_cm, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, gender=excluded.gender, age=excluded.age,
                weight_kg=excluded.weight_kg, height_cm=excluded.height_cm, updated_at=excluded.updated_at
        """, (row.get("name"), row.get("gender"), row.get("age"), row.get("weight_kg"),
              row.get("height_cm"), row.get("updated_at")))

    conn.commit()
