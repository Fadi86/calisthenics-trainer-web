"""
Simulates his EXACT current production database (v4.0.0, single implicit
profile, no profiles table) with realistic existing data, then runs our
new init_db() against it and verifies:
1. Nothing is lost
2. Everything gets correctly assigned to a real profile #1
3. The app actually works afterward (not just that data survived)
"""
import sqlite3
import tempfile
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db as dbmod

tmp = tempfile.mktemp(suffix=".db")
conn = sqlite3.connect(tmp)

conn.executescript("""
CREATE TABLE exercises (id TEXT PRIMARY KEY, name TEXT, category TEXT, subcategory TEXT, tier INTEGER,
    aliases_json TEXT, equipment_json TEXT, prerequisites_json TEXT, regression_of_json TEXT,
    progression_to_json TEXT, metric_type TEXT, metric_unit TEXT, is_assessment INTEGER,
    type TEXT, modality TEXT, rotation_group TEXT, mobility_required_json TEXT, cues_json TEXT,
    common_faults_json TEXT, video_ref TEXT, notes TEXT, primary_muscles_json TEXT, secondary_muscles_json TEXT);
CREATE TABLE schedule_days (id INTEGER PRIMARY KEY, plan_name TEXT, days_per_week INTEGER,
    day_index INTEGER, day_type TEXT, label TEXT, week_number INTEGER DEFAULT 1, week_date TEXT);
CREATE TABLE schedule_items (id INTEGER PRIMARY KEY, schedule_day_id INTEGER, exercise_id TEXT,
    order_index INTEGER, target_sets TEXT, target_low REAL, target_high REAL, metric_type TEXT, role TEXT);
CREATE TABLE assessments (id INTEGER PRIMARY KEY, exercise_id TEXT, date TEXT, reps INTEGER,
    hold_seconds REAL, weight_kg REAL, estimated_1rm REAL, notes TEXT);
CREATE TABLE user_tiers (movement_key TEXT PRIMARY KEY, current_tier INTEGER, updated_at TEXT);
CREATE TABLE sessions (id INTEGER PRIMARY KEY, date TEXT, schedule_day_id INTEGER, day_type TEXT, status TEXT);
CREATE TABLE session_sets (id INTEGER PRIMARY KEY, session_id INTEGER, exercise_id TEXT, set_number INTEGER,
    reps_done INTEGER, hold_done REAL, weight_done REAL, target_low REAL, target_high REAL,
    feedback TEXT, created_at TEXT);
CREATE TABLE health_metrics (id INTEGER PRIMARY KEY, date TEXT, metric TEXT, value REAL, unit TEXT, source TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id=1), name TEXT, gender TEXT, age INTEGER,
    weight_kg REAL, height_cm REAL, updated_at TEXT);
""")

conn.execute("INSERT INTO profile (id, name, gender, age, weight_kg, height_cm, updated_at) "
             "VALUES (1, 'Fadi', 'male', 30, 78.5, 178, '2026-08-01 10:00:00')")
conn.execute("INSERT INTO assessments (exercise_id, date, reps) VALUES ('pull_strict_pullup', '2026-07-30', 12)")
conn.execute("INSERT INTO assessments (exercise_id, date, reps, weight_kg, estimated_1rm) "
             "VALUES ('pull_weighted_pullup', '2026-08-01', 5, 20, 23.3)")
conn.execute("INSERT INTO user_tiers (movement_key, current_tier, updated_at) "
             "VALUES ('pull_pullup', 3, '2026-07-30 10:00:00')")
conn.execute("INSERT INTO schedule_days (id, plan_name, days_per_week, day_index, day_type, label, "
             "week_number, week_date) VALUES (1, 'My Plan', 4, 0, 'pull_front_lever', 'Pull + Front Lever', 1, '2026-07-28')")
conn.execute("INSERT INTO sessions (id, date, schedule_day_id, day_type, status) "
             "VALUES (1, '2026-07-28', 1, 'pull_front_lever', 'completed')")
conn.execute("INSERT INTO session_sets (session_id, exercise_id, set_number, reps_done, target_low, "
             "target_high, created_at) VALUES (1, 'pull_strict_pullup', 1, 10, 8, 12, '2026-07-28 08:00:00')")
conn.execute("INSERT INTO health_metrics (date, metric, value, unit, source) "
             "VALUES ('2026-08-01', 'Resting Heart Rate (bpm)', 62, 'bpm', 'manual')")
conn.execute("INSERT INTO settings (key, value) VALUES ('reassessment_interval_days', '60')")
conn.execute("INSERT INTO settings (key, value) VALUES ('app_password_hash', 'pbkdf2:sha256:somehash')")
conn.commit()
conn.close()

print("Simulated real v4.0.0 production DB with: 1 profile, 2 assessments, 1 schedule week, "
      "1 completed session with 1 set logged, 1 health metric, a set password.")
print()

dbmod.init_db(db_path=tmp, data_dir="data")
conn = dbmod.get_connection(tmp)


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"[{status}] {label}")
    if not cond:
        raise AssertionError(label)


profiles = dbmod.get_profiles(conn)
check(f"exactly 1 profile created from the old data (got {len(profiles)})", len(profiles) == 1)
check("migrated profile keeps the real name 'Fadi'", profiles[0]["name"] == "Fadi")
check("migrated profile keeps real age/weight/height",
      profiles[0]["age"] == 30 and profiles[0]["weight_kg"] == 78.5 and profiles[0]["height_cm"] == 178)
pid = profiles[0]["id"]

assessments = conn.execute("SELECT * FROM assessments WHERE profile_id = ?", (pid,)).fetchall()
check(f"both real assessments preserved and assigned to profile #{pid} (got {len(assessments)})",
      len(assessments) == 2)

tiers = conn.execute("SELECT * FROM user_tiers WHERE profile_id = ?", (pid,)).fetchall()
check("real tier progress preserved with correct profile_id", len(tiers) == 1 and tiers[0]["current_tier"] == 3)

sessions = conn.execute("SELECT * FROM sessions WHERE profile_id = ?", (pid,)).fetchall()
check("completed session preserved", len(sessions) == 1 and sessions[0]["status"] == "completed")

sets = conn.execute("SELECT * FROM session_sets WHERE session_id = ?", (sessions[0]["id"],)).fetchall()
check("logged set still linked to the right session", len(sets) == 1 and sets[0]["reps_done"] == 10)

health = conn.execute("SELECT * FROM health_metrics WHERE profile_id = ?", (pid,)).fetchall()
check("health metric preserved", len(health) == 1 and health[0]["value"] == 62)

pw_hash = dbmod.get_setting(conn, "app_password_hash", "")
check("existing password hash untouched (still logged in as usual)", pw_hash == "pbkdf2:sha256:somehash")

old_gone = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='profile'").fetchone()
check("old singular 'profile' table cleaned up after migration", old_gone is None)

from core import scheduler
plan = scheduler.get_schedule(conn, pid, "My Plan")
check("old schedule week still readable through the real API", len(plan) == 1)

from core import assessment as assess_mod
detail = assess_mod.get_progress_detail(conn, pid)
check("Progress page detail computes correctly on migrated data (picks the genuinely most "
      "recent pullup-pattern assessment, which is the weighted test from 08-01, not the plain one from 07-30)",
      detail["pull"][0]["tier"] == 3 and detail["pull"][0]["last_date"] == "2026-08-01")

conn.close()
os.remove(tmp)
print()
print("MIGRATION FROM REAL v4.0.0 PRODUCTION DATA TO MULTI-PROFILE CONFIRMED SAFE")
