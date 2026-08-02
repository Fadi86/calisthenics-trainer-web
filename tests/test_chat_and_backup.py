import os
import sys
import tempfile
import json
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP_DB = tempfile.mktemp(suffix=".db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

import app as app_module
from core import db as dbmod
from core import backup as backup_mod

dbmod.init_db(db_path=TMP_DB, data_dir=DATA_DIR)
app_module.dbmod.DB_PATH = TMP_DB
app_module.app.config["TESTING"] = True
client = app_module.app.test_client()


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


print("[1] Health tab is genuinely gone...")
client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)
r = client.get("/health", follow_redirects=False)
check("no /health route exists anymore (404, now that auth/profile checks pass through)", r.status_code == 404)
r = client.get("/")
check("no 'Health' link in the nav", b">Health<" not in r.data and b"nav_health" not in r.data)
check("Chat link IS in the nav", b"Chat" in r.data)

print("[2] Two different profiles both see the same shared chat...")
client.post("/chat", data={"message": "Hi, this is Fadi"}, follow_redirects=True)
client.post("/profiles/create", data={"name": "Tester1"}, follow_redirects=True)
r = client.post("/chat", data={"message": "Hi, this is Tester1"}, follow_redirects=True)
check("Tester1's page shows Fadi's earlier message too (shared, not per-profile)",
      b"Hi, this is Fadi" in r.data)
check("Tester1's page shows their own message", b"Hi, this is Tester1" in r.data)
check("sender name 'Fadi' is attributed correctly", b"Fadi" in r.data)
check("sender name 'Tester1' is attributed correctly", b"Tester1" in r.data)

print("[3] Chat API polling returns only NEW messages since a given id...")
conn = dbmod.get_connection(TMP_DB)
from core import chat as chat_mod
all_msgs = chat_mod.get_messages(conn)
check("2 messages total so far", len(all_msgs) == 2)
first_id = all_msgs[0]["id"]
newer = chat_mod.get_messages_since(conn, since_id=first_id)
check("get_messages_since only returns messages after the given id", len(newer) == 1)
check("the newer message is Tester1's", newer[0]["message"] == "Hi, this is Tester1")

print("[4] Automatic backup writes a real separate file...")
backup_dir = backup_mod.BACKUP_DIR
for old in glob.glob(os.path.join(backup_dir, "backup_*.json")):
    os.remove(old)

path = backup_mod.write_auto_backup(conn)
check("backup file actually created on disk", os.path.exists(path))
check("backup file lives outside the git repo's tracked area (data/backups/)",
      "data/backups" in path or "data\\backups" in path)

with open(path) as f:
    data = json.load(f)
check("backup contains both profiles", len(data["profiles"]) == 2)
check("backup contains the chat log", len(data["chat_messages"]) == 2)
check("backup includes Fadi's chat message specifically",
      any(m["message"] == "Hi, this is Fadi" for m in data["chat_messages"]))

print("[5] Auto-backup respects the 24h interval (doesn't spam files every request)...")
before_count = len(glob.glob(os.path.join(backup_dir, "backup_*.json")))
result = backup_mod.maybe_run_auto_backup(conn, min_interval_hours=24)
check("second call within the interval does nothing", result is None)
after_count = len(glob.glob(os.path.join(backup_dir, "backup_*.json")))
check("no new file was created", before_count == after_count)

print("[6] Old backups get rotated out beyond the keep-limit...")
import time
original_keep = backup_mod.KEEP_LAST_N_BACKUPS
backup_mod.KEEP_LAST_N_BACKUPS = 3
for i in range(5):
    backup_mod.write_auto_backup(conn)
    time.sleep(1.1)  # ensure distinct timestamps for distinct filenames
remaining = glob.glob(os.path.join(backup_dir, "backup_*.json"))
check(f"only the last 3 backups are kept (found {len(remaining)})", len(remaining) == 3)
backup_mod.KEEP_LAST_N_BACKUPS = original_keep

for f in glob.glob(os.path.join(backup_dir, "backup_*.json")):
    os.remove(f)
conn.close()
os.remove(TMP_DB)
print("\nALL CHAT AND AUTO-BACKUP TESTS PASSED")
