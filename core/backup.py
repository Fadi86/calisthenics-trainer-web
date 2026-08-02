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


"""
core/backup.py — exports/imports ONE profile's progress and history as a
single JSON file, so it can be saved to Google Drive (or anywhere) and
restored later. Scoped per-profile since multiple people now share these
tables (up to db.MAX_PROFILES) - importing never touches anyone else's data,
and row IDs are remapped on import rather than reused, since blindly
reinserting old numeric IDs could collide with a different profile's rows
in the same table.

Also handles the automatic all-profiles safety backup: a JSON snapshot
written to disk periodically (data/backups/), completely separate from
both the live database AND the git repo - a `git pull` + reload can never
touch it, and it survives even if the live database were somehow lost.
"""
import json
import os
import glob
from core import db as dbmod

BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "backups")
KEEP_LAST_N_BACKUPS = 14


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


def export_all_profiles(conn):
    """Everything, for every profile, plus the shared chat log - the
    complete safety-net snapshot."""
    profiles = dbmod.get_profiles(conn)
    return {
        "exported_at": dbmod.now_iso(),
        "version": 2,
        "profiles": {str(p["id"]): export_backup(conn, p["id"]) for p in profiles},
        "chat_messages": [dict(r) for r in conn.execute("SELECT * FROM chat_messages ORDER BY id").fetchall()],
    }


def write_auto_backup(conn):
    """Writes a timestamped snapshot to data/backups/ - a real file on
    disk, outside the database and outside the git repo, so neither a
    `git pull` deployment nor a database problem can take both copies down
    at once. Keeps the last KEEP_LAST_N_BACKUPS files, deletes older ones."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    data = export_all_profiles(conn)
    timestamp = dbmod.now_iso().replace(":", "-").replace(" ", "_")
    path = os.path.join(BACKUP_DIR, f"backup_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    existing = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_*.json")))
    for old_path in existing[:-KEEP_LAST_N_BACKUPS]:
        os.remove(old_path)

    return path


def maybe_run_auto_backup(conn, min_interval_hours=24):
    """Call this on any request - cheap to check, only actually writes a
    file when the last backup is stale. No external cron/scheduled-task
    dependency needed."""
    from datetime import datetime, timedelta
    last = dbmod.get_setting(conn, "last_auto_backup_at", "")
    if last:
        try:
            last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_dt < timedelta(hours=min_interval_hours):
                return None
        except ValueError:
            pass
    path = write_auto_backup(conn)
    dbmod.set_setting(conn, "last_auto_backup_at", dbmod.now_iso())
    return path


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
