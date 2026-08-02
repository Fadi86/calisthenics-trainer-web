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

print("[1] Front Lever and Back Lever show as two separate rows...")
detail = assess_mod.get_progress_detail(conn, PROFILE_ID)
pull_labels = [row["label"] for row in detail["pull"]]
check("Front Lever is its own row", "Skills (Front Lever)" in pull_labels)
check("Back Lever is its own row", "Skills (Back Lever)" in pull_labels)
check("no combined 'Front/Back Lever' row exists anymore",
      not any("Front/Back" in label for label in pull_labels))

print("[2] Exactly the scenario reported: train Front Lever hard, never touch Back Lever...")
assess_mod.record_assessment(conn, PROFILE_ID, "pull_fl_full", hold_seconds=25)
detail = assess_mod.get_progress_detail(conn, PROFILE_ID)
fl_row = next(r for r in detail["pull"] if r["label"] == "Skills (Front Lever)")
bl_row = next(r for r in detail["pull"] if r["label"] == "Skills (Back Lever)")

check(f"Front Lever tier progressed (tier={fl_row['tier']})", fl_row["tier"] >= 4)
check(f"Back Lever stays at the honest untrained tier 1 (tier={bl_row['tier']})", bl_row["tier"] == 1)
check("Back Lever correctly shows 'not tested yet' (no last_date)", bl_row["last_date"] is None)
check("Front Lever's progress does NOT leak into Back Lever's row", fl_row["tier"] != bl_row["tier"])

print("\nALL FRONT/BACK LEVER INDEPENDENCE TESTS PASSED")
conn.close()
os.remove(TMP_DB)
