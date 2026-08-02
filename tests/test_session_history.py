import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db as dbmod
from core import scheduler
from core import progression

TMP_DB = tempfile.mktemp(suffix=".db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
dbmod.init_db(db_path=TMP_DB, data_dir=DATA_DIR)
conn = dbmod.get_connection(TMP_DB)


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


pid = dbmod.create_profile(conn, "Fadi")
plan = scheduler.generate_schedule(conn, pid, 4, plan_name="Test")
day = plan[0]
day_id = day["items"][0]["schedule_day_id"] if "schedule_day_id" in day["items"][0] else None
# fetch the real day_id via get_schedule since generate_schedule's own return doesn't include it directly
fetched = scheduler.get_schedule(conn, pid, "Test")
day_id = fetched[0]["id"]
first_item = fetched[0]["items"][0]

print("[1] No session logged yet for this day -> returns None cleanly...")
check("no session yet", progression.get_session_for_day(conn, pid, day_id) is None)

print("[2] Complete a session with logged sets, retrieve it for Calendar display...")
sid = progression.start_session(conn, pid, day_type=fetched[0]["day_type"], schedule_day_id=day_id)
progression.log_set(conn, sid, first_item["exercise_id"], 1, first_item["target_low"], first_item["target_high"],
                     reps_done=10)
progression.log_set(conn, sid, first_item["exercise_id"], 2, first_item["target_low"], first_item["target_high"],
                     reps_done=9)
progression.complete_session(conn, sid)

session_log = progression.get_session_for_day(conn, pid, day_id)
check("session found for this day", session_log is not None)
check("status is completed", session_log["status"] == "completed")
check("both logged sets present", len(session_log["sets"]) == 2)
check("first set shows the real logged value", session_log["sets"][0]["reps_done"] == 10)

print("[3] Edit a logged set (fix a data-entry mistake)...")
set_id = session_log["sets"][0]["id"]
fb = progression.update_session_set(conn, pid, set_id, reps_done=12)
check("feedback returned reflects the corrected value", "12" in fb["message"])
updated_log = progression.get_session_for_day(conn, pid, day_id)
check("the set now shows the corrected value in the DB", updated_log["sets"][0]["reps_done"] == 12)

print("[4] Delete one logged set...")
progression.delete_session_set(conn, pid, updated_log["sets"][1]["id"])
after_delete = progression.get_session_for_day(conn, pid, day_id)
check("only 1 set remains", len(after_delete["sets"]) == 1)

print("[5] Delete the entire session (history should be fully erasable)...")
progression.delete_session(conn, pid, sid)
check("session is completely gone now", progression.get_session_for_day(conn, pid, day_id) is None)
remaining_sets = conn.execute("SELECT COUNT(*) c FROM session_sets WHERE session_id = ?", (sid,)).fetchone()["c"]
check("no orphaned sets left behind", remaining_sets == 0)

print("[6] Can't edit/delete another profile's session data...")
pid2 = dbmod.create_profile(conn, "Tester1")
sid2 = progression.start_session(conn, pid2, day_type="x", schedule_day_id=day_id)
progression.log_set(conn, sid2, first_item["exercise_id"], 1, 5, 10, reps_done=7)
row = conn.execute("SELECT id FROM session_sets WHERE session_id = ?", (sid2,)).fetchone()
try:
    progression.update_session_set(conn, pid, row["id"], reps_done=99)  # pid trying to edit pid2's set
    check("should have raised ValueError for cross-profile access", False)
except ValueError:
    check("correctly blocked: profile 1 cannot edit profile 2's logged set", True)

print("\nALL SESSION HISTORY TESTS PASSED")
conn.close()
os.remove(TMP_DB)
