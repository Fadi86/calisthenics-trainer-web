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
    movement_key TEXT PRIMARY KEY,
    current_tier INTEGER NOT NULL,
    updated_at TEXT NOT NULL
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
"""

DEFAULT_SETTINGS = {
    "reassessment_interval_days": "60",
    "days_per_week": "4",
    "ai_feedback_mode": "rule_based",   # "rule_based" or "claude_api"
    "ai_api_key": "",
    "ai_model": "claude-haiku-4-5-20251001",
    "youtube_api_key": "",
    "week_number": "1",
}


def init_db(db_path=None, data_dir=None):
    conn = get_connection(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    _ensure_columns(conn)
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


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")
