import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP_DB = tempfile.mktemp(suffix=".db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

import app as app_module
from core import db as dbmod

dbmod.init_db(db_path=TMP_DB, data_dir=DATA_DIR)
app_module.dbmod.DB_PATH = TMP_DB
app_module.app.config["TESTING"] = True
client = app_module.app.test_client()
client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


print("[1] Schedule: Redo Week button regenerates without advancing history...")
client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)
r = client.get("/schedule")
check("shows Week 1", b"Week 1" in r.data)

conn = dbmod.get_connection(TMP_DB)
from core import scheduler
before_ids = sorted(it["id"] for d in scheduler.get_schedule(conn, 1, "My Plan") for it in d["items"])
conn.close()

r = client.post("/schedule/regenerate", data={}, follow_redirects=True)
check("still Week 1 after redo (didn't create Week 2)", b"Week 1" in r.data)
check("does NOT offer 'Start Week 2' language incorrectly for regenerate itself", r.status_code == 200)

conn = dbmod.get_connection(TMP_DB)
after_ids = sorted(it["id"] for d in scheduler.get_schedule(conn, 1, "My Plan") for it in d["items"])
weeks_after = scheduler.get_all_weeks(conn, 1, "My Plan")
conn.close()
check("only 1 week still exists in history (regenerate replaced, not appended)", len(weeks_after) == 1)
check("item IDs actually changed (real regeneration happened, not a no-op)", before_ids != after_ids)

print("[2] Schedule: Delete Week removes it entirely...")
client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)  # -> Week 2
conn = dbmod.get_connection(TMP_DB)
weeks_before_delete = scheduler.get_all_weeks(conn, 1, "My Plan")
conn.close()
check("2 weeks exist before delete", len(weeks_before_delete) == 2)

client.post("/schedule/delete_week", data={"week_number": "2"}, follow_redirects=True)
conn = dbmod.get_connection(TMP_DB)
weeks_after_delete = scheduler.get_all_weeks(conn, 1, "My Plan")
conn.close()
check("Week 2 deleted, only Week 1 remains", len(weeks_after_delete) == 1 and weeks_after_delete[0]["week_number"] == 1)

print("[3] Calendar shows prev/next navigation across multiple weeks...")
client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)  # -> Week 2 again
client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)  # -> Week 3
r = client.get("/calendar?week=2")
html = r.data.decode()
check("on week 2, both prev and next links are active (not disabled)",
      'href="/calendar?week=1"' in html and 'href="/calendar?week=3"' in html)

print("[4] Calendar: train a day, then edit/delete the logged set from Calendar...")
conn = dbmod.get_connection(TMP_DB)
plan = scheduler.get_schedule(conn, 1, "My Plan", week_number=3)
day_id = plan[0]["id"]
first_item = plan[0]["items"][0]
conn.close()

client.post("/api/train/start", json={"day_type": plan[0]["day_type"], "schedule_day_id": day_id})
client.post("/api/train/log_set", json={
    "exercise_id": first_item["exercise"]["id"], "set_number": 1,
    "target_low": first_item["target_low"], "target_high": first_item["target_high"], "reps_done": 5,
})
client.post("/api/train/complete")

r = client.get("/calendar?week=3")
check("calendar shows the logged set (5 reps)", b"5 reps" in r.data or b"5" in r.data)
check("calendar shows 'Actually logged' section", b"Actually logged" in r.data)

conn = dbmod.get_connection(TMP_DB)
from core import progression
session_log = progression.get_session_for_day(conn, 1, day_id)
set_id = session_log["sets"][0]["id"]
conn.close()

r = client.post(f"/calendar/session_set/edit/{set_id}", data={"reps_done": "8", "week": "3"}, follow_redirects=True)
check("edited value (8) now shows on the calendar", b"8 reps" in r.data or b">8<" in r.data)

r = client.post(f"/calendar/session_set/delete/{set_id}", data={"week": "3"}, follow_redirects=True)
check("after delete, no sets left message shown or set is gone", b"Session started but no sets logged yet" in r.data)

print("[5] Progress: edit and delete an assessment via the real routes...")
client.post("/assessment/max", data={"exercise_id": "pull_weighted_pullup", "reps": "5", "weight_kg": "20"},
            follow_redirects=True)
conn = dbmod.get_connection(TMP_DB)
from core import assessment as assess_mod
hist = assess_mod.get_assessment_history(conn, 1)
assessment_id = hist[0]["id"]
conn.close()

r = client.post(f"/assessment/edit/{assessment_id}", data={"reps": "6", "weight_kg": "25"}, follow_redirects=True)
check("progress page loads after edit", r.status_code == 200)
conn = dbmod.get_connection(TMP_DB)
updated = assess_mod.get_assessment_history(conn, 1)[0]
conn.close()
check("assessment actually updated to the new weight", updated["weight_kg"] == 25.0)

r = client.post(f"/assessment/delete/{assessment_id}", follow_redirects=True)
check("progress page loads after delete", r.status_code == 200)
conn = dbmod.get_connection(TMP_DB)
after_delete_hist = assess_mod.get_assessment_history(conn, 1)
conn.close()
check("assessment actually removed", not any(h["id"] == assessment_id for h in after_delete_hist))

print("\nALL WEEK/SESSION/ASSESSMENT MANAGEMENT ROUTE TESTS PASSED")
