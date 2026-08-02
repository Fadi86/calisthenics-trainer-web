import os
import sys
import tempfile
from unittest.mock import patch

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
client.post("/assessment", data={"category": "pull", "exercise_id": "pull_strict_pullup", "reps": "15"})


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


print("[1] No API key set -> clicking the button shows a clear error, not a crash...")
r = client.post("/progress/ai_recommendation", data={}, follow_redirects=True)
check("status 200 (no crash)", r.status_code == 200)
check("shows the missing-API-key error", b"API key" in r.data)
check("still shows the initial button (no conversation started)", b"Get Instant Trainer Recommendation" in r.data)

print("[2] Set an API key in Settings, then get a (mocked) recommendation...")
client.post("/settings", data={
    "interval": "60", "ai_provider": "claude", "ai_api_key": "fake-test-key",
    "ai_model": "claude-haiku-4-5-20251001", "language": "en",
})

with patch("core.trainer_chat._call_claude") as mock_call:
    mock_call.return_value = "Solid pull-up numbers. Front Lever is lagging - test it this week."
    r = client.post("/progress/ai_recommendation", data={}, follow_redirects=True)
    check("status 200", r.status_code == 200)
    check("shows the recommendation text on the page", b"Front Lever is lagging" in r.data)
    check("shows the follow-up chat input now", b"ai-chat-input" in r.data)
    check("shows the Clear conversation button", b"Clear conversation" in r.data)

print("[3] Follow-up question via the JSON API, with mocked reply...")
with patch("core.trainer_chat._call_claude") as mock_call:
    mock_call.return_value = "You're stuck on Front Lever because it needs dedicated tuck work, not just pull-ups."
    r = client.post("/api/trainer_chat/send", json={"message": "why am I stuck on front lever"})
    check("status 200", r.status_code == 200)
    data = r.get_json()
    check("reply contains the mocked response", "dedicated tuck work" in data["reply"])

    call_args = mock_call.call_args[0]
    sent_messages = call_args[2]
    check("original progress context still present in what's sent (grounded answer, not generic)",
          any("pull_strict_pullup" in m["content"] or "Pull-up" in m["content"] for m in sent_messages))

print("[4] Conversation persists across page reloads (shows on GET /progress)...")
r = client.get("/progress")
check("shows the original recommendation still", b"Front Lever is lagging" in r.data)
check("shows the follow-up Q&A too", b"stuck on Front Lever" in r.data or b"dedicated tuck work" in r.data)

print("[5] Clear conversation resets to the initial button...")
r = client.post("/progress/ai_clear", follow_redirects=True)
check("back to showing the initial 'Get recommendation' button", b"Get Instant Trainer Recommendation" in r.data)
check("old recommendation text is gone", b"Front Lever is lagging" not in r.data)

print("[6] A network/API failure shows a real error, doesn't crash the page...")
with patch("core.trainer_chat._call_claude") as mock_call:
    mock_call.side_effect = ConnectionError("Could not reach Claude API: timeout")
    r = client.post("/progress/ai_recommendation", data={}, follow_redirects=True)
    check("status 200 (handled gracefully)", r.status_code == 200)
    check("shows the connection error message", b"Could not reach Claude API" in r.data)

print("\nALL AI RECOMMENDATION ROUTE TESTS PASSED")
