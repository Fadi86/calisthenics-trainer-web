import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP_DB = tempfile.mktemp(suffix=".db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

import app as app_module
from core import db as dbmod
from core import library

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


print("[1] classify_role logic on known exercises...")
conn = dbmod.get_connection(TMP_DB)

cases = [
    ("pull_strict_pullup", "main"),          # category=pull, type=main, not a skill subcat
    ("pull_fl_tuck", "skill"),                # subcategory=front_lever
    ("push_planche_tuck", "skill"),           # subcategory=planche
    ("pull_muscleup_strict_bar", "skill"),    # subcategory=muscle_up
    ("hs_freestanding_hold", "skill"),        # category=handstand, subcategory=balance
    ("warmup_march_in_place", "warm-up"),     # category=warmup
    ("mob_hip_pancake", "mobility"),          # category=mobility
    ("cond_burpee", "conditioning"),          # category=conditioning
    ("pull_band_pullapart", "accessory"),     # category=pull, type=extra, not a skill subcat
]
for ex_id, expected in cases:
    ex = library.get_exercise(conn, ex_id)
    label, css_class = library.classify_role(ex)
    check(f"{ex_id} -> '{label}' (expected '{expected}')", label == expected)

print("[2] Library page renders text badges, no emoji...")
r = client.get("/library?category=pull")
check("status 200", r.status_code == 200)
html = r.data.decode("utf-8")
check("no emoji characters in the page", not any(c in html for c in "💪🔼🦵🎯🤸🏃🔥🧘"))
check("shows written category label 'Pull'", "Pull" in html)
check("shows written role label (main/skill/accessory)",
      any(label in html for label in ["main", "skill", "accessory"]))

print("[3] Library detail view shows category + role badges as text...")
r = client.get("/library?category=pull&exercise=pull_fl_tuck")
detail_html = r.data.decode("utf-8")
check("detail shows 'skill' label for front lever", "skill" in detail_html)
check("detail shows 'Pull' category label", "Pull" in detail_html)
check("no emoji in detail view", not any(c in detail_html for c in "💪🔼🦵🎯🤸🏃🔥🧘"))

conn.close()
os.remove(TMP_DB)
print("\nALL LIBRARY BADGE TESTS PASSED")
