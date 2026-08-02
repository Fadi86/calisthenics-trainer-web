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


PROFILE_ID = dbmod.create_profile(conn, "Fadi")

print("[1] get_skill_stages returns the full ordered chain for front lever...")
stages = assess_mod.get_skill_stages(conn, PROFILE_ID, "pull", "front_lever")
names = [s["name"] for s in stages]
check("has all 8 stages in order", len(stages) == 8)
check("starts with German Hang", names[0] == "German Hang")
check("ends with One-Arm Front Lever", names[-1] == "One-Arm Front Lever")

print("[2] THE EXACT BUG SCENARIO: Advanced Tuck vs Straddle both tier 4 - must be distinguishable...")
assess_mod.record_assessment(conn, PROFILE_ID, "pull_fl_adv_tuck", hold_seconds=8)
detail = assess_mod.get_progress_detail(conn, PROFILE_ID)
fl_row = next(r for r in detail["pull"] if r["label"] == "Skills (Front Lever)")

check(f"tier shows 4 (still ambiguous alone: {fl_row['tier']})", fl_row["tier"] == 4)
check("but exercise_name correctly identifies THIS specific stage",
      fl_row["exercise_name"] == "Advanced Tuck Front Lever")

stage_lookup = {s["name"]: s for s in fl_row["stages"]}
check("Advanced Tuck is marked as the last-tested stage",
      stage_lookup["Advanced Tuck Front Lever"]["is_last_tested"] is True)
check("Straddle Front Lever is NOT marked as last-tested (this is the actual bug being fixed)",
      stage_lookup["Straddle Front Lever"]["is_last_tested"] is False)
check("Full Front Lever is NOT marked reached either",
      stage_lookup["Full Front Lever"]["reached"] is False)
check("but Tuck Front Lever (earlier stage) IS marked reached",
      stage_lookup["Tuck Front Lever"]["reached"] is True)

print("[3] Next-stage hint only appears when ready to progress...")
check("no next_stage_name yet (within range, not at ceiling)", fl_row["next_stage_name"] is None)

assess_mod.record_assessment(conn, PROFILE_ID, "pull_fl_adv_tuck", hold_seconds=25)
detail2 = assess_mod.get_progress_detail(conn, PROFILE_ID)
fl_row2 = next(r for r in detail2["pull"] if r["label"] == "Skills (Front Lever)")
check("recommendation is 'progress' now", fl_row2["recommendation"] == "progress")
check("next_stage_name correctly suggests the actual next exercise in THIS chain (One-Leg, not Straddle)",
      fl_row2["next_stage_name"] == "One-Leg Front Lever")

print("[4] Back Lever's stage list is genuinely separate from Front Lever's...")
bl_stages = assess_mod.get_skill_stages(conn, PROFILE_ID, "pull", "back_lever")
bl_names = [s["name"] for s in bl_stages]
check("back lever stages don't include any front lever names", not any("Front" in n for n in bl_names))
check("back lever has its own 5-stage chain", len(bl_stages) == 5)

print("[5] Rows without a hand-curated stage chain (e.g. Pull-up) have stages=None...")
pullup_row = next(r for r in detail2["pull"] if "Pull-up" in r["label"])
check("pullup row has stages=None (no ambiguous multi-stage chain to disambiguate)", pullup_row["stages"] is None)

print("\nALL SKILL-STAGE CHECKLIST TESTS PASSED")
conn.close()
os.remove(TMP_DB)
