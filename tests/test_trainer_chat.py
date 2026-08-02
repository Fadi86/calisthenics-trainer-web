import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db as dbmod
from core import assessment as assess_mod
from core import trainer_chat

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

print("[1] build_progress_context reflects REAL data, not placeholders...")
assess_mod.record_assessment(conn, pid, "pull_strict_pullup", reps=15)
assess_mod.record_assessment(conn, pid, "pull_fl_adv_tuck", hold_seconds=8)
assess_mod.record_assessment(conn, pid, "pull_weighted_pullup", reps=5, weight_kg=20)

context = trainer_chat.build_progress_context(conn, pid)
check("mentions Pull-up assessment", "Pull-up" in context)
check("mentions the real tier reached", "tier" in context.lower())
check("mentions Advanced Tuck Front Lever specifically (not just a tier number)",
      "Advanced Tuck Front Lever" in context)
check("mentions the weighted pull-up 1RM", "kg estimated 1RM" in context)
check("mentions untested patterns honestly", "not tested yet" in context)

print("[2] No API key configured -> clear error, no crash...")
try:
    trainer_chat.get_initial_recommendation(conn, pid, api_key="", model="claude-haiku-4-5-20251001")
    check("should have raised", False)
except ValueError as e:
    check(f"clear error message about missing key: '{e}'", "API key" in str(e))

print("[3] Mocked Claude API call - initial recommendation + conversation storage...")
with patch("core.trainer_chat._call_claude") as mock_call:
    mock_call.return_value = "You're strong on pull-ups but Back Lever is untouched - work on that next."
    reply = trainer_chat.get_initial_recommendation(conn, pid, api_key="fake-key", model="claude-haiku-4-5-20251001")
    check("returns the mocked reply", "Back Lever" in reply)

    history = trainer_chat.get_conversation(conn, pid)
    check("conversation has exactly 2 messages (user context + assistant reply)", len(history) == 2)
    check("first message is the user's context-setting turn", history[0]["role"] == "user")
    check("the context turn actually contains the real progress data",
          "Advanced Tuck Front Lever" in history[0]["content"])
    check("second message is the assistant's reply", history[1]["role"] == "assistant")

print("[4] Follow-up question retains full context in the conversation sent to Claude...")
with patch("core.trainer_chat._call_claude") as mock_call:
    mock_call.return_value = "You're stuck because Back Lever needs direct volume - it won't improve from pull-ups alone."
    reply2 = trainer_chat.continue_conversation(conn, pid, "fake-key", "claude-haiku-4-5-20251001",
                                                  "Why am I not progressing on Back Lever?")
    check("returns the follow-up reply", "Back Lever needs direct volume" in reply2)

    sent_messages = mock_call.call_args[0][2]  # (api_key, model, messages)
    check("the ORIGINAL progress context is still included in what's sent to Claude",
          any("Advanced Tuck Front Lever" in m["content"] for m in sent_messages))
    check("the new follow-up question is included too",
          any("not progressing on Back Lever" in m["content"] for m in sent_messages))
    check("conversation now has 4 messages total", len(trainer_chat.get_conversation(conn, pid)) == 4)

print("[5] Clearing the conversation actually wipes it...")
trainer_chat.clear_conversation(conn, pid)
check("conversation is empty after clearing", len(trainer_chat.get_conversation(conn, pid)) == 0)

print("[6] Starting a new recommendation after clearing starts fresh (doesn't append to old)...")
with patch("core.trainer_chat._call_claude") as mock_call:
    mock_call.return_value = "Fresh recommendation."
    trainer_chat.get_initial_recommendation(conn, pid, "fake-key", "claude-haiku-4-5-20251001")
    check("fresh conversation has exactly 2 messages, not more", len(trainer_chat.get_conversation(conn, pid)) == 2)

print("[7] Two profiles' AI conversations never mix...")
pid2 = dbmod.create_profile(conn, "Tester1")
check("profile 2 has no conversation yet (not contaminated by profile 1's)",
      len(trainer_chat.get_conversation(conn, pid2)) == 0)

print("\nALL TRAINER-CHAT (AI RECOMMENDATION) TESTS PASSED")
conn.close()
os.remove(TMP_DB)
