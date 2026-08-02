"""
End-to-end test of the Flask web app using the real Flask test client -
these are genuine HTTP requests through genuine routes/templates, not a
mock. This is a stronger test than anything possible for the desktop GUIs
in this project, since Flask's test client needs no display.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# use a throwaway DB for this test run
os.environ["TRAINER_TEST_DB"] = tempfile.mktemp(suffix=".db")

import app as app_module
from core import db as dbmod

# point the app at a temp DB so we don't touch any real data
TMP_DB = tempfile.mktemp(suffix=".db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
dbmod.init_db(db_path=TMP_DB, data_dir=DATA_DIR)
app_module.dbmod.DB_PATH = TMP_DB  # redirect get_conn()'s default path

app_module.app.config["TESTING"] = True
client = app_module.app.test_client()


def check(label, condition):
    status = "OK" if condition else "FAIL"
    print(f"    [{status}] {label}")
    if not condition:
        raise AssertionError(label)


print("[0] Create and select a profile (now required before anything else)...")
r = client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)
check("profile created and redirected to dashboard", r.status_code == 200 and b"Exercises" in r.data)

print("[1] Dashboard loads...")
r = client.get("/")
check("status 200", r.status_code == 200)
check("shows exercise count", b"Exercises" in r.data)

print("[2] Assessment page loads and submits...")
r = client.get("/assessment?category=pull")
check("status 200", r.status_code == 200)
check("shows category exercises", b"Strict Pull-up" in r.data or b"pullup" in r.data.lower())

r = client.post("/assessment", data={
    "category": "pull", "exercise_id": "pull_strict_pullup", "reps": "12",
})
check("status 200 after submit", r.status_code == 200)
check("shows assigned tier in result", b"Working tier assigned" in r.data)

print("[3] Library page loads with tier badges and detail view...")
r = client.get("/library?category=pull&tier=all&type=all")
check("status 200", r.status_code == 200)
check("shows tier badges", b"T1" in r.data or b"T2" in r.data)

r = client.get("/library?category=pull&exercise=pull_strict_pullup")
check("detail view shows exercise name", b"Strict Pull-up" in r.data)
check("detail view shows watch button", b"Watch on YouTube" in r.data)

print("[4] Schedule generation, tier display, and editing (swap/remove/add)...")
r = client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)
check("status 200", r.status_code == 200)
check("shows day duration estimate", b"min" in r.data)
check("shows tier badges in schedule", b"T1" in r.data or b"T2" in r.data or b"T3" in r.data)

conn = dbmod.get_connection(TMP_DB)
from core import scheduler
plan = scheduler.get_schedule(conn, 1, "My Plan")
first_item = plan[0]["items"][0]
r = client.post(f"/schedule/swap/{first_item['id']}", data={"new_exercise_id": "warmup_jumping_jacks_easy"},
                 follow_redirects=True)
check("swap redirects OK", r.status_code == 200)
plan_after = scheduler.get_schedule(conn, 1, "My Plan")
check("swap actually changed the exercise", plan_after[0]["items"][0]["exercise"]["id"] == "warmup_jumping_jacks_easy")

before_count = len(plan_after[0]["items"])
r = client.post(f"/schedule/remove/{first_item['id']}", follow_redirects=True)
plan_after_remove = scheduler.get_schedule(conn, 1, "My Plan")
check("remove actually removed an item", len(plan_after_remove[0]["items"]) == before_count - 1)

day_id = plan_after_remove[0]["id"]
r = client.post(f"/schedule/add/{day_id}", data={"exercise_id": "pull_strict_pullup", "role": "main"},
                 follow_redirects=True)
plan_after_add = scheduler.get_schedule(conn, 1, "My Plan")
check("add actually added an item",
      any(it["exercise"]["id"] == "pull_strict_pullup" for it in plan_after_add[0]["items"]))

print("[5] Train page loads with timer data attributes...")
r = client.get("/train?day=0")
check("status 200", r.status_code == 200)
check("has timer work seconds data attribute", b"data-work=" in r.data)
check("has timer rest seconds data attribute", b"data-rest=" in r.data)
check("has watch button", b"btn watch" in r.data)

print("[6] Session start/log_set/complete via JSON API...")
r = client.post("/api/train/start", json={"day_type": "pull_front_lever", "schedule_day_id": day_id})
check("start returns session_id", r.status_code == 200 and "session_id" in r.get_json())
sid = r.get_json()["session_id"]

r = client.post("/api/train/log_set", json={
    "exercise_id": "pull_strict_pullup", "set_number": 1, "target_low": 8, "target_high": 12, "reps_done": 15,
})
check("log_set returns feedback message", r.status_code == 200 and "above_target" in r.get_json()["status"])

r = client.post("/api/train/complete")
check("complete returns ok", r.status_code == 200 and r.get_json()["ok"] is True)

print("[7] Chat page loads, can send and see a message...")
r = client.post("/chat", data={"message": "Hello from the test suite"}, follow_redirects=True)
check("status 200", r.status_code == 200)
check("message appears on the page", b"Hello from the test suite" in r.data)

print("[8] Settings page loads and saves...")
r = client.post("/settings", data={
    "interval": "45", "ai_provider": "claude", "ai_api_key": "", "ai_model": "claude-haiku-4-5-20251001",
}, follow_redirects=True)
check("status 200", r.status_code == 200)
saved = dbmod.get_setting(conn, "reassessment_interval_days")
check("interval actually persisted", saved == "45")

conn.close()
os.remove(TMP_DB)
print("\nALL WEB APP TESTS PASSED (real Flask test client, real HTTP requests)")
