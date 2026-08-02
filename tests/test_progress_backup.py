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


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


print("[1] Assessment limited to 4 core categories + weighted max section...")
r = client.get("/assessment")
check("status 200", r.status_code == 200)
check("shows Strength Max Test section", b"Strength Max Test" in r.data)
check("shows Weighted Pull-up field", b"Weighted Pull-up" in r.data)
check("shows Weighted Dip field", b"Weighted Dip" in r.data)
check("does not show handstand as a category option", b'value="handstand"' not in r.data)
check("does show legs as a category option", b'value="legs"' in r.data)

print("[2] Log a weighted pull-up max...")
r = client.post("/assessment/max", data={"exercise_id": "pull_weighted_pullup", "reps": "5", "weight_kg": "20"},
                 follow_redirects=True)
check("redirects to progress page with 200", r.status_code == 200)
check("shows estimated 1RM on progress page", b"est. 1RM" in r.data)

print("[3] Progress page shows Pull/Push/Core/Legs...")
r = client.get("/progress")
check("status 200", r.status_code == 200)
check("shows Pull", b"Pull" in r.data)
check("shows Push", b"Push" in r.data)
check("shows Core", b"Core" in r.data)
check("shows Legs", b"Legs" in r.data)
check("shows Weighted Strength Maxes section", b"Weighted Strength Maxes" in r.data)
check("shows the pull-up max we just logged (Epley 1RM of 20kg x 5 reps = 23.3kg)", b"23.3 kg est. 1RM" in r.data)

print("[4] Weekly schedule rotation with week counter...")
r = client.get("/schedule")
check("shows Week 1 placeholder before any schedule exists", b"Week 1" in r.data)
r = client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)
check("status 200", r.status_code == 200)
check("first-ever generate produces the real Week 1", b"Week 1" in r.data)
check("button now offers Start Week 2", b"Start Week 2" in r.data)
r = client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)
check("second generate advances to Week 2", b"Week 2" in r.data)
check("button now offers Start Week 3", b"Start Week 3" in r.data)

print("[5] Backup export produces real downloadable JSON with our data...")
r = client.get("/settings/export")
check("status 200", r.status_code == 200)
check("has attachment content-disposition", "attachment" in r.headers.get("Content-Disposition", ""))
import json
data = json.loads(r.data)
check("backup contains assessments", len(data["assessments"]) >= 1)
check("backup contains the weighted pullup assessment with correct Epley 1RM",
      any(a["exercise_id"] == "pull_weighted_pullup" and a["estimated_1rm"] == 23.3 for a in data["assessments"]))
check("backup contains profile table (even if empty)", "profile" in data)

print("[6] Backup import restores state into a FRESH database...")
fresh_db = tempfile.mktemp(suffix=".db")
dbmod.init_db(db_path=fresh_db, data_dir=DATA_DIR)
app_module.dbmod.DB_PATH = fresh_db
r_fresh = client.get("/progress")
check("fresh db shows no weighted max yet", b"not tested yet" in r_fresh.data)

from io import BytesIO
r = client.post("/settings/import", data={
    "backup_file": (BytesIO(json.dumps(data).encode()), "backup.json")
}, content_type="multipart/form-data", follow_redirects=True)
check("import redirects OK", r.status_code == 200)

r_after = client.get("/progress")
check("restored progress shows the weighted pullup max", b"est. 1RM" in r_after.data)

print("\nALL PROGRESS/BACKUP FEATURE TESTS PASSED")
