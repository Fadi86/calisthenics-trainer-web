"""
core/db.py — SQLite storage layer. Zero external dependencies (sqlite3 is
part of the Python standard library). Creates the DB on first run and seeds
the exercise library from data/exercises.json.
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "trainer.db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def get_connection(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS exercises (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    aliases_json TEXT,
    category TEXT NOT NULL,
    subcategory TEXT,
    tier INTEGER NOT NULL,
    equipment_json TEXT,
    prerequisites_json TEXT,
    regression_of_json TEXT,
    progression_to_json TEXT,
    metric_type TEXT,
    metric_unit TEXT,
    is_assessment INTEGER DEFAULT 0,
    type TEXT DEFAULT 'main',
    modality TEXT DEFAULT 'bodyweight',
    rotation_group TEXT,
    mobility_required_json TEXT,
    cues_json TEXT,
    common_faults_json TEXT,
    video_ref TEXT,
    notes TEXT,
    primary_muscles_json TEXT,
    secondary_muscles_json TEXT
);

CREATE TABLE IF NOT EXISTS user_tiers (
    profile_id INTEGER NOT NULL,
    movement_key TEXT NOT NULL,
    current_tier INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (profile_id, movement_key)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id TEXT NOT NULL,
    date TEXT NOT NULL,
    reps INTEGER,
    hold_seconds REAL,
    weight_kg REAL,
    estimated_1rm REAL,
    notes TEXT,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id)
);

CREATE TABLE IF NOT EXISTS schedule_days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_name TEXT NOT NULL,
    days_per_week INTEGER NOT NULL,
    day_index INTEGER NOT NULL,
    day_type TEXT NOT NULL,
    label TEXT
);

CREATE TABLE IF NOT EXISTS schedule_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_day_id INTEGER NOT NULL,
    exercise_id TEXT NOT NULL,
    order_index INTEGER NOT NULL,
    target_sets TEXT,
    target_low REAL,
    target_high REAL,
    metric_type TEXT,
    role TEXT,
    FOREIGN KEY (schedule_day_id) REFERENCES schedule_days(id),
    FOREIGN KEY (exercise_id) REFERENCES exercises(id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    schedule_day_id INTEGER,
    day_type TEXT,
    status TEXT DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS session_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    exercise_id TEXT NOT NULL,
    set_number INTEGER NOT NULL,
    reps_done INTEGER,
    hold_done REAL,
    weight_done REAL,
    target_low REAL,
    target_high REAL,
    feedback TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (exercise_id) REFERENCES exercises(id)
);

CREATE TABLE IF NOT EXISTS health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    unit TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS exercise_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    title TEXT,
    channel TEXT,
    url TEXT NOT NULL,
    is_primary INTEGER DEFAULT 0,
    fetched_at TEXT NOT NULL,
    FOREIGN KEY (exercise_id) REFERENCES exercises(id)
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    gender TEXT,
    age INTEGER,
    weight_kg REAL,
    height_cm REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
"""

MAX_PROFILES = 5

DEFAULT_SETTINGS = {
    "reassessment_interval_days": "60",
    "days_per_week": "4",
    "ai_feedback_mode": "rule_based",   # "rule_based" or "claude_api"
    "ai_api_key": "",
    "ai_model": "claude-haiku-4-5-20251001",
    "youtube_api_key": "",
    "app_password_hash": "",
    "language": "en",
}


def init_db(db_path=None, data_dir=None):
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _ensure_columns(conn)
    _migrate_to_profiles(conn)
    _seed_settings(conn)
    _seed_exercises(conn, data_dir or DATA_DIR)
    _backfill_muscle_data(conn, data_dir or DATA_DIR)
    _seed_manual_videos(conn, data_dir or DATA_DIR)
    conn.close()


def _seed_manual_videos(conn, data_dir):
    """One-time seed of a real, hand-researched starter batch (the 17
    assessment/benchmark exercises) so there's useful content immediately,
    before you ever run fetch_videos.py for full library coverage."""
    path = os.path.join(data_dir, "manual_videos.json")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        videos = json.load(f)
    for v in videos:
        exists = conn.execute(
            "SELECT 1 FROM exercise_videos WHERE exercise_id = ? AND video_id = ?",
            (v["exercise_id"], v["video_id"])
        ).fetchone()
        if exists:
            continue
        conn.execute("""
            INSERT INTO exercise_videos (exercise_id, video_id, title, channel, url, is_primary, fetched_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
        """, (v["exercise_id"], v["video_id"], v.get("title", ""), v.get("channel", ""),
              v["url"], now_iso()))
    conn.commit()


def _ensure_columns(conn):
    """Adds any columns introduced after a user's DB was first created.
    SQLite's CREATE TABLE IF NOT EXISTS won't alter an existing table, so
    this keeps older installs (like an app already run once) working
    after a schema update instead of crashing on missing columns."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(exercises)")}
    new_columns = {
        "primary_muscles_json": "TEXT",
        "secondary_muscles_json": "TEXT",
    }
    for col, coltype in new_columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE exercises ADD COLUMN {col} {coltype}")

    schedule_items_cols = {row["name"] for row in conn.execute("PRAGMA table_info(schedule_items)")}
    if "role" not in schedule_items_cols:
        conn.execute("ALTER TABLE schedule_items ADD COLUMN role TEXT")

    schedule_days_cols = {row["name"] for row in conn.execute("PRAGMA table_info(schedule_days)")}
    if "week_number" not in schedule_days_cols:
        conn.execute("ALTER TABLE schedule_days ADD COLUMN week_number INTEGER DEFAULT 1")
    if "week_date" not in schedule_days_cols:
        conn.execute("ALTER TABLE schedule_days ADD COLUMN week_date TEXT")
    if "profile_id" not in schedule_days_cols:
        conn.execute("ALTER TABLE schedule_days ADD COLUMN profile_id INTEGER")

    for table in ("assessments", "sessions", "health_metrics"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "profile_id" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN profile_id INTEGER")

    conn.commit()


def _backfill_muscle_data(conn, data_dir):
    """If an existing install's rows predate the muscle-tagging columns,
    fill them in from the JSON source without touching anything else."""
    needs_backfill = conn.execute(
        "SELECT COUNT(*) AS c FROM exercises WHERE primary_muscles_json IS NULL"
    ).fetchone()["c"]
    if needs_backfill == 0:
        return
    path = os.path.join(data_dir, "exercises.json")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        exercises = json.load(f)
    for e in exercises:
        conn.execute(
            "UPDATE exercises SET primary_muscles_json = ?, secondary_muscles_json = ? WHERE id = ?",
            (json.dumps(e.get("primary_muscles", [])), json.dumps(e.get("secondary_muscles", [])), e["id"])
        )
    conn.commit()


def _seed_settings(conn):
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()


def _seed_exercises(conn, data_dir):
    """
    Always syncs the exercises table to match exercises.json - this is an
    upsert, not a one-time seed. Runs on every launch. This matters because
    the library has grown multiple times during development (152 -> 172 ->
    195 -> 208 exercises) and will likely grow again; without this, anyone
    who already launched the app once would be permanently stuck on
    whatever exercise count existed at their first run. Safe to run every
    time: it only touches exercise metadata columns, never the user's own
    assessments/sessions/schedule data, which reference exercise_id but
    don't duplicate exercise content.
    """
    path = os.path.join(data_dir, "exercises.json")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        exercises = json.load(f)
    rows = []
    for e in exercises:
        rows.append((
            e["id"], e["name"], json.dumps(e.get("aliases", [])),
            e["category"], e.get("subcategory"), e["tier"],
            json.dumps(e.get("equipment", [])),
            json.dumps(e.get("prerequisites", [])),
            json.dumps(e.get("regression_of", [])),
            json.dumps(e.get("progression_to", [])),
            e["metric"]["type"], e["metric"].get("unit"),
            1 if e.get("is_assessment") else 0,
            e.get("type", "main"), e.get("modality", "bodyweight"),
            e.get("rotation_group"),
            json.dumps(e.get("mobility_required", [])),
            json.dumps(e.get("cues", [])),
            json.dumps(e.get("common_faults", [])),
            e.get("video_ref"), e.get("notes"),
            json.dumps(e.get("primary_muscles", [])),
            json.dumps(e.get("secondary_muscles", [])),
        ))
    conn.executemany("""
        INSERT INTO exercises (id, name, aliases_json, category, subcategory, tier,
            equipment_json, prerequisites_json, regression_of_json, progression_to_json,
            metric_type, metric_unit, is_assessment, type, modality, rotation_group,
            mobility_required_json, cues_json, common_faults_json, video_ref, notes,
            primary_muscles_json, secondary_muscles_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, aliases_json=excluded.aliases_json,
            category=excluded.category, subcategory=excluded.subcategory,
            tier=excluded.tier, equipment_json=excluded.equipment_json,
            prerequisites_json=excluded.prerequisites_json,
            regression_of_json=excluded.regression_of_json,
            progression_to_json=excluded.progression_to_json,
            metric_type=excluded.metric_type, metric_unit=excluded.metric_unit,
            is_assessment=excluded.is_assessment, type=excluded.type,
            modality=excluded.modality, rotation_group=excluded.rotation_group,
            mobility_required_json=excluded.mobility_required_json,
            cues_json=excluded.cues_json, common_faults_json=excluded.common_faults_json,
            video_ref=excluded.video_ref, notes=excluded.notes,
            primary_muscles_json=excluded.primary_muscles_json,
            secondary_muscles_json=excluded.secondary_muscles_json
    """, rows)
    conn.commit()


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
    conn.commit()


def _migrate_to_profiles(conn):
    """
    Multi-profile support (up to MAX_PROFILES). Handles two real scenarios:
    1. Fresh install: nothing to migrate, profiles stays empty until the
       user creates one through the UI.
    2. Existing single-profile install (real production data from before
       this feature existed): migrates the old singular 'profile' table
       (if present) into profiles as profile #1, and backfills profile_id=1
       onto every existing assessment/session/health record/schedule day so
       nothing is lost or orphaned.
    user_tiers' primary key changes from (movement_key) to
    (profile_id, movement_key) - SQLite can't ALTER a primary key, so this
    recreates the table when needed.
    """
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    user_tiers_cols = {row["name"] for row in conn.execute("PRAGMA table_info(user_tiers)")} if "user_tiers" in tables else set()
    needs_recreate = "user_tiers" in tables and "profile_id" not in user_tiers_cols

    profile_count = conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"]
    has_old_profile_table = "profile" in tables
    old_profile_row = None
    if has_old_profile_table:
        old_profile_row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()

    migrating_existing_data = profile_count == 0 and (old_profile_row is not None or needs_recreate
                                                        or _has_any_unscoped_data(conn))

    default_profile_id = None
    if migrating_existing_data:
        name = old_profile_row["name"] if old_profile_row and old_profile_row["name"] else "Profile 1"
        cur = conn.execute(
            "INSERT INTO profiles (name, gender, age, weight_kg, height_cm, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, old_profile_row["gender"] if old_profile_row else None,
             old_profile_row["age"] if old_profile_row else None,
             old_profile_row["weight_kg"] if old_profile_row else None,
             old_profile_row["height_cm"] if old_profile_row else None,
             now_iso(), now_iso())
        )
        default_profile_id = cur.lastrowid
        conn.commit()

        for table in ("assessments", "sessions", "health_metrics", "schedule_days"):
            conn.execute(f"UPDATE {table} SET profile_id = ? WHERE profile_id IS NULL", (default_profile_id,))
        conn.commit()

    if needs_recreate:
        conn.execute("""
            CREATE TABLE user_tiers_new (
                profile_id INTEGER NOT NULL,
                movement_key TEXT NOT NULL,
                current_tier INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (profile_id, movement_key)
            )
        """)
        pid = default_profile_id or 1
        old_rows = conn.execute("SELECT * FROM user_tiers").fetchall()
        for row in old_rows:
            conn.execute(
                "INSERT INTO user_tiers_new (profile_id, movement_key, current_tier, updated_at) VALUES (?,?,?,?)",
                (pid, row["movement_key"], row["current_tier"], row["updated_at"])
            )
        conn.execute("DROP TABLE user_tiers")
        conn.execute("ALTER TABLE user_tiers_new RENAME TO user_tiers")
        conn.commit()

    if has_old_profile_table:
        conn.execute("DROP TABLE profile")
        conn.commit()


def _has_any_unscoped_data(conn):
    """True if any pre-existing row predates profile_id (needs migrating)."""
    for table in ("assessments", "sessions", "health_metrics", "schedule_days"):
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "profile_id" not in cols:
            continue
        row = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE profile_id IS NULL").fetchone()
        if row["c"] > 0:
            return True
    return False


def get_profiles(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM profiles ORDER BY id").fetchall()]


def get_profile(conn, profile_id):
    row = conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    return dict(row) if row else None


def create_profile(conn, name, gender=None, age=None, weight_kg=None, height_cm=None):
    count = conn.execute("SELECT COUNT(*) c FROM profiles").fetchone()["c"]
    if count >= MAX_PROFILES:
        raise ValueError(f"Maximum of {MAX_PROFILES} profiles reached.")
    cur = conn.execute(
        "INSERT INTO profiles (name, gender, age, weight_kg, height_cm, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, gender, age, weight_kg, height_cm, now_iso(), now_iso())
    )
    conn.commit()
    return cur.lastrowid


def update_profile(conn, profile_id, name, gender, age, weight_kg, height_cm):
    conn.execute(
        "UPDATE profiles SET name=?, gender=?, age=?, weight_kg=?, height_cm=?, updated_at=? WHERE id=?",
        (name, gender, age, weight_kg, height_cm, now_iso(), profile_id)
    )
    conn.commit()


def delete_profile(conn, profile_id):
    """Deletes a profile and everything scoped to it. Does not touch
    the shared exercise library."""
    conn.execute("DELETE FROM session_sets WHERE session_id IN (SELECT id FROM sessions WHERE profile_id=?)", (profile_id,))
    conn.execute("DELETE FROM sessions WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM schedule_items WHERE schedule_day_id IN (SELECT id FROM schedule_days WHERE profile_id=?)", (profile_id,))
    conn.execute("DELETE FROM schedule_days WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM assessments WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM user_tiers WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM health_metrics WHERE profile_id = ?", (profile_id,))
    conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
    conn.commit()


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")
