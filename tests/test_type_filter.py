import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import db as dbmod
from core import library

TMP_DB = tempfile.mktemp(suffix=".db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
dbmod.init_db(db_path=TMP_DB, data_dir=DATA_DIR)
conn = dbmod.get_connection(TMP_DB)


def check(label, cond):
    status = "OK" if cond else "FAIL"
    print(f"    [{status}] {label}")
    if not cond:
        raise AssertionError(label)


print("[1] filter_by_role correctly filters by the rich classification...")
all_pull = library.list_exercises(conn, category="pull")
for e in all_pull:
    e["role_label"], e["role_class"] = library.classify_role(e)

skills_only = library.filter_by_role(all_pull, "skills")
check(f"skills filter returns only skill items (got {len(skills_only)})",
      len(skills_only) > 0 and all(library.classify_role(e)[0] == "skills" for e in skills_only))
check("Tuck Front Lever is in the skills filter", any("Front Lever" in e["name"] for e in skills_only))
check("Strict Pull-up is NOT in the skills filter (it's 'main')",
      not any(e["id"] == "pull_strict_pullup" for e in skills_only))

accessory_only = library.filter_by_role(all_pull, "accessory")
check(f"accessory filter returns only accessory items (got {len(accessory_only)})",
      len(accessory_only) > 0 and all(library.classify_role(e)[0] == "accessory" for e in accessory_only))

print("[2] Mobility/conditioning/extra filters work across categories (not tied to one category)...")
all_ex = library.list_exercises(conn)
mobility_only = library.filter_by_role(all_ex, "mobility")
check(f"mobility filter finds items (got {len(mobility_only)})", len(mobility_only) > 0)
check("all returned items are genuinely category=mobility", all(e["category"] == "mobility" for e in mobility_only))

conditioning_only = library.filter_by_role(all_ex, "conditioning")
check(f"conditioning filter finds items (got {len(conditioning_only)})", len(conditioning_only) > 0)

extra_only = library.filter_by_role(all_ex, "extra")
check(f"'extra' filter finds warm-up items specifically (got {len(extra_only)})", len(extra_only) > 0)
check("all 'extra'-filtered items are genuinely category=warmup",
      all(e["category"] == "warmup" for e in extra_only))

print("[3] 'all' still returns everything unfiltered...")
check("type='all' returns the full unfiltered list", len(library.filter_by_role(all_pull, "all")) == len(all_pull))
check("type=None also returns everything", len(library.filter_by_role(all_pull, None)) == len(all_pull))

print("[4] Full library route: dropdown shows all 6 options, filtering actually works end to end...")
import app as app_module
app_module.dbmod.DB_PATH = TMP_DB
app_module.app.config["TESTING"] = True
client = app_module.app.test_client()
client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)

r = client.get("/library")
html = r.data.decode("utf-8")
for opt in ["Main", "Skills", "Mobility", "Conditioning", "Extra", "Accessory"]:
    check(f"type dropdown includes '{opt}'", f">{opt}<" in html)

r = client.get("/library?category=pull&type=skills")
html = r.data.decode("utf-8")
check("filtering by skills on the real route shows Front Lever items", "Front Lever" in html)
check("filtering by skills on the real route hides plain Pull-up (main, not skills)",
      "Strict Pull-up" not in html)

r = client.get("/library?type=mobility")
html = r.data.decode("utf-8")
check("filtering by mobility (no category) shows mobility items", "Pancake Stretch" in html)

conn.close()
os.remove(TMP_DB)
print("\nALL TYPE-FILTER FIX TESTS PASSED")
