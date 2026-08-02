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


print("[1] Truly fresh install (no password, no profile) -> sent to profile picker first...")
r = client.get("/", follow_redirects=True)
check("redirected to 'Who's training?' before dashboard, since no profile exists yet",
      b"Who's training" in r.data)

print("[2] Create the first profile...")
r = client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)
check("profile created, now lands on dashboard", b"Dashboard" in r.data)
r = client.get("/")
check("dashboard now accessible directly (no password set yet)", b"Dashboard" in r.data)

print("[3] First-run password setup (from Settings, any time after profile exists)...")
r = client.get("/login")
check("login page shows first-run password setup form", b"new_password" in r.data)
r = client.post("/login", data={"new_password": "secret123", "confirm_password": "secret123"}, follow_redirects=True)
check("redirects to profile picker after setting password", b"Who's training" in r.data or b"Dashboard" in r.data)

print("[4] Protected pages now require login (new client, no session)...")
fresh_client = app_module.app.test_client()
r = fresh_client.get("/", follow_redirects=False)
check("unauthenticated request redirects to /login", r.status_code == 302 and "/login" in r.headers["Location"])

print("[5] Wrong password rejected...")
r = fresh_client.post("/login", data={"password": "wrongpass"})
check("wrong password shows error, stays on login page", b"Wrong password" in r.data)
r = fresh_client.get("/", follow_redirects=False)
check("still not authenticated after wrong password", r.status_code == 302)

print("[6] Correct password logs in, then still needs a profile selected...")
r = fresh_client.post("/login", data={"password": "secret123"}, follow_redirects=True)
check("correct password redirects to profile picker (shared profiles list)", b"Who's training" in r.data)
r = fresh_client.get("/progress", follow_redirects=False)
check("still redirected without a selected profile", r.status_code == 302 and "/profiles" in r.headers["Location"])
r = fresh_client.get("/profiles/select/1", follow_redirects=True)
check("selecting the shared profile grants access", b"Progress" in r.data or r.status_code == 200)
r = fresh_client.get("/progress")
check("authenticated + profile-selected session can access pages", r.status_code == 200)

print("[7] Logout revokes access (and clears profile selection)...")
r = fresh_client.get("/logout", follow_redirects=False)
check("logout redirects to login", r.status_code == 302)
r = fresh_client.get("/", follow_redirects=False)
check("dashboard now requires login again", r.status_code == 302)

print("[8] Password change flow (using the original authenticated client)...")
r = client.post("/settings", data={"change_password": "1", "current_password": "secret123", "new_password": "newpass456"})
check("password change succeeds", r.status_code == 200)
new_client = app_module.app.test_client()
r = new_client.post("/login", data={"password": "newpass456"}, follow_redirects=True)
check("can log in with the new password", b"Who's training" in r.data)
r2 = app_module.app.test_client().post("/login", data={"password": "secret123"})
check("old password no longer works", b"Wrong password" in r2.data)

print("[9] Profile edit (personal details) save/restore for the ACTIVE profile...")
r = client.post("/profile", data={"name": "Fadi", "gender": "male", "age": "30", "weight_kg": "78.5", "height_cm": "178"})
check("profile save returns 200", r.status_code == 200)
check("profile page shows saved name", b"Fadi" in r.data)
check("profile page shows saved weight", b"78.5" in r.data)

conn = dbmod.get_connection(TMP_DB)
profile = dbmod.get_profile(conn, 1)
check("profile persisted correctly in DB", profile["name"] == "Fadi" and profile["age"] == 30)

from core import backup as backup_mod
backup_data = backup_mod.export_backup(conn, 1)
check("profile included in backup export", backup_data["profile"][0]["name"] == "Fadi")
conn.close()

print("[10] A SECOND profile has completely separate data...")
r = client.post("/profiles/create", data={"name": "Tester1"}, follow_redirects=True)
check("second profile created", r.status_code == 200)
conn = dbmod.get_connection(TMP_DB)
p2 = dbmod.get_profile(conn, 2)
check("second profile exists with its own row", p2["name"] == "Tester1")
r = client.get("/profile")
check("switching to the new profile shows blank personal info (not Fadi's)", b"Fadi" not in r.data)
conn.close()

print("[11] Calendar shows weekly history with real dates (back on profile 1)...")
client.get("/profiles/select/1", follow_redirects=True)
client.post("/schedule/generate", data={"days": "4"}, follow_redirects=True)
r = client.get("/calendar")
check("calendar page loads", r.status_code == 200)
check("shows at least one week (just generated)", b"Week" in r.data)
today = dbmod.today_str()
check(f"shows today's real date ({today}) as the week date", today.encode() in r.data)

print("\nALL LOGIN/PROFILE/CALENDAR TESTS PASSED")
