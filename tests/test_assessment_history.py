import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db as dbmod
from core import assessment as assess_mod

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

print("[1] Fix a typo: edit an assessment, tier recomputes correctly...")
r1 = assess_mod.record_assessment(conn, pid, "pull_strict_pullup", reps=3)
check("first entry (typo'd low) sets tier down", r1["assigned_tier"] == 1)
history = assess_mod.get_assessment_history(conn, pid)
assessment_id = history[0]["id"]
new_tier = assess_mod.update_assessment(conn, pid, assessment_id, reps=15)
check("editing to the correct (high) value recomputes tier upward", new_tier == 3)
tier_check = assess_mod.get_current_tier(conn, pid, "pull_pullup")
check("user_tiers table reflects the corrected tier", tier_check == 3)

print("[2] Delete a bad entry - tier falls back to whatever's now most recent...")
r2 = assess_mod.record_assessment(conn, pid, "pull_strict_pullup", reps=3)  # a second entry: a bad day
check("second (weak) entry correctly drops the tier", r2["assigned_tier"] == 1)
history2 = assess_mod.get_assessment_history(conn, pid)
latest_id = history2[0]["id"]
after_delete_tier = assess_mod.delete_assessment(conn, pid, latest_id)
check(f"deleting that entry falls back to the PREVIOUS one's tier (got {after_delete_tier}, expected 3)",
      after_delete_tier == 3)

print("[3] Deleting the ONLY assessment for a pattern resets it to tier 1, not stuck at a stale value...")
history3 = assess_mod.get_assessment_history(conn, pid)
remaining_id = history3[0]["id"]
final_tier = assess_mod.delete_assessment(conn, pid, remaining_id)
check("deleting the last remaining assessment resets to tier 1", final_tier == 1)
history4 = assess_mod.get_assessment_history(conn, pid)
check("assessment history is now empty for this pattern", len(history4) == 0)

print("[4] Injury scenario end-to-end through Progress page...")
assess_mod.record_assessment(conn, pid, "pull_strict_pullup", reps=15)
detail_before = assess_mod.get_progress_detail(conn, pid)
tier_before = next(r for r in detail_before["pull"] if "Pull-up" in r["label"])["tier"]
check(f"strong performance shows correctly (tier={tier_before})", tier_before >= 3)

assess_mod.record_assessment(conn, pid, "pull_strict_pullup", reps=2)
detail_after = assess_mod.get_progress_detail(conn, pid)
row_after = next(r for r in detail_after["pull"] if "Pull-up" in r["label"])
check(f"injury (weak performance) correctly drops the tier (now {row_after['tier']})",
      row_after["tier"] < tier_before)
check("recommendation correctly says 'regress'", row_after["recommendation"] == "regress")

print("[5] History can be filtered by category...")
assess_mod.record_assessment(conn, pid, "push_standard_pushup", reps=10)
pull_history = assess_mod.get_assessment_history(conn, pid, category="pull")
check("category filter only returns pull assessments", all(h["category"] == "pull" for h in pull_history))

print("\nALL ASSESSMENT HISTORY/EDIT/DELETE TESTS PASSED")
conn.close()
os.remove(TMP_DB)
