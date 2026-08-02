import os
import sys
import json
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db as dbmod
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


def make_fake_response(payload_dict):
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(payload_dict).encode("utf-8")
    fake_resp.__enter__ = lambda self: fake_resp
    fake_resp.__exit__ = lambda self, *a: None
    return fake_resp


pid = dbmod.create_profile(conn, "Fadi")

print("[1] _call_gemini builds the correct request (URL, header, role mapping, systemInstruction)...")
with patch("core.trainer_chat.urllib.request.urlopen") as mock_urlopen, \
     patch("core.trainer_chat.urllib.request.Request") as mock_request:
    mock_urlopen.return_value = make_fake_response({
        "candidates": [{"content": {"parts": [{"text": "Great pull-up numbers, work on Back Lever next."}]}}]
    })
    mock_request.return_value = MagicMock()

    messages = [
        {"role": "user", "content": "Here is my progress data..."},
        {"role": "assistant", "content": "Focus on Front Lever."},
        {"role": "user", "content": "Why am I stuck on Back Lever?"},
    ]
    reply = trainer_chat._call_gemini("fake-gemini-key", "gemini-2.5-flash-lite", messages)

    check("returns the correctly parsed reply text", reply == "Great pull-up numbers, work on Back Lever next.")

    call_kwargs = mock_request.call_args
    url_arg = call_kwargs[0][0]
    check(f"URL includes the correct model ('{url_arg}')", "gemini-2.5-flash-lite:generateContent" in url_arg)
    check("URL points at the real Gemini endpoint", "generativelanguage.googleapis.com" in url_arg)
    check("URL also includes the API key as a ?key= query param (dual auth, for maximum compatibility)",
          "?key=fake-gemini-key" in url_arg)

    headers = call_kwargs[1]["headers"]
    check("uses x-goog-api-key header (Gemini's auth scheme, different from Claude's x-api-key)",
          headers.get("x-goog-api-key") == "fake-gemini-key")

    body = json.loads(call_kwargs[1]["data"])
    check("system prompt sent via systemInstruction (not a 'system' message like Claude)",
          "systemInstruction" in body and "parts" in body["systemInstruction"])
    check("'assistant' role correctly converted to Gemini's 'model' role",
          body["contents"][1]["role"] == "model")
    check("'user' role stays 'user'", body["contents"][0]["role"] == "user")
    check("all 3 messages present in contents", len(body["contents"]) == 3)

print("[2] _call_ai dispatches to the right provider based on the setting...")
with patch("core.trainer_chat._call_gemini") as mock_gemini, patch("core.trainer_chat._call_claude") as mock_claude:
    mock_gemini.return_value = "gemini reply"
    mock_claude.return_value = "claude reply"

    r1 = trainer_chat._call_ai("gemini", "key", "gemini-2.5-flash-lite", [])
    check("provider='gemini' calls _call_gemini, not _call_claude", r1 == "gemini reply" and not mock_claude.called)

    r2 = trainer_chat._call_ai("claude", "key", "claude-haiku-4-5-20251001", [])
    check("provider='claude' calls _call_claude", r2 == "claude reply")

print("[3] Full get_initial_recommendation flow works end-to-end with Gemini selected...")
with patch("core.trainer_chat._call_gemini") as mock_gemini:
    mock_gemini.return_value = "Solid work. Push tier is lagging behind Pull - prioritize that next week."
    reply = trainer_chat.get_initial_recommendation(conn, pid, "gemini", "fake-key", "gemini-2.5-flash-lite")
    check("returns the Gemini-sourced recommendation", "Push tier is lagging" in reply)
    history = trainer_chat.get_conversation(conn, pid)
    check("conversation stored correctly regardless of provider used", len(history) == 2)

print("[4] Missing API key raises the same clear error for Gemini too...")
try:
    trainer_chat._call_gemini("", "gemini-2.5-flash-lite", [{"role": "user", "content": "hi"}])
    check("should have raised", False)
except ValueError as e:
    check(f"clear error: '{e}'", "API key" in str(e))

print("[5] A real 404 (bad model name) produces a clear, specific error - not a generic one...")
import urllib.error


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body):
        super().__init__("http://fake", code, "Not Found", {}, None)
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


with patch("core.trainer_chat.urllib.request.urlopen") as mock_urlopen:
    mock_urlopen.side_effect = FakeHTTPError(404, '{"error": {"message": "models/bad-model is not found"}}')
    try:
        trainer_chat._call_gemini("fake-key", "bad-model", [{"role": "user", "content": "hi"}])
        check("should have raised", False)
    except ConnectionError as e:
        check(f"error message includes the actual model name that failed: '{e}'", "bad-model" in str(e))
        check("error message includes the actual 404 response body from Gemini",
              "not found" in str(e).lower())

print("\nALL GEMINI INTEGRATION TESTS PASSED")
conn.close()
os.remove(TMP_DB)
