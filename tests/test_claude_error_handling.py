import os
import sys
import urllib.error
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import trainer_chat


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


class FakeHTTPError(urllib.error.HTTPError):
    def __init__(self, code, body):
        super().__init__("http://fake", code, "error", {}, None)
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


print("[1] Claude: a real HTTPError (e.g. bad model / invalid key) surfaces the DETAILED body...")
print("    (this exact bug was hiding real error detail behind a generic 'Could not reach' message,")
print("     for both Claude and Gemini, until fixed - HTTPError is a subclass of URLError, so the")
print("     except clause order matters: HTTPError must be caught first or it's dead code)")

with patch("core.trainer_chat.urllib.request.urlopen") as mock_urlopen:
    mock_urlopen.side_effect = FakeHTTPError(
        401, '{"error": {"type": "authentication_error", "message": "invalid x-api-key"}}'
    )
    try:
        trainer_chat._call_claude("bad-key", "claude-haiku-4-5-20251001", [{"role": "user", "content": "hi"}])
        check("should have raised", False)
    except ConnectionError as e:
        check(f"error message includes the specific detail from Claude's response body: '{e}'",
              "invalid x-api-key" in str(e))
        check("error message includes the actual HTTP status code (401, not a generic failure)",
              "401" in str(e))
        check("error does NOT contain the old generic 'Could not reach' wording for this case",
              "Could not reach" not in str(e))

print("[2] A genuine network failure (DNS/connection issue, not an HTTP error) still gets the OTHER message...")
with patch("core.trainer_chat.urllib.request.urlopen") as mock_urlopen:
    mock_urlopen.side_effect = urllib.error.URLError("Name or service not known")
    try:
        trainer_chat._call_claude("some-key", "claude-haiku-4-5-20251001", [{"role": "user", "content": "hi"}])
        check("should have raised", False)
    except ConnectionError as e:
        check(f"genuine network errors still get the 'Could not reach' message: '{e}'",
              "Could not reach Claude API" in str(e))

print("\nALL CLAUDE ERROR-HANDLING TESTS PASSED")
