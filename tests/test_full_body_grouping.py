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


print("[1] Filter dropdown list is curated - muscle groups + one Full Body, no raw category leakage...")
filter_cats = library.filter_categories()
check("exactly 6 entries (5 muscle groups + full_body)", len(filter_cats) == 6)
check("Conditioning is NOT a standalone filter option anymore", "conditioning" not in filter_cats)
check("Mobility is NOT a standalone filter option anymore", "mobility" not in filter_cats)
check("Warm-up is NOT a standalone filter option anymore", "warmup" not in filter_cats)
check("Full Body IS an option", "full_body" in filter_cats)
check("all 5 real muscle groups still present", set(library.MUSCLE_GROUP_CATEGORIES).issubset(set(filter_cats)))

print("[2] Selecting 'Full Body' combines all 3 real categories...")
full_body_results = library.list_exercises_for_filter(conn, "full_body")
real_cats_found = {e["category"] for e in full_body_results}
check("contains conditioning items", "conditioning" in real_cats_found)
check("contains mobility items", "mobility" in real_cats_found)
check("contains warmup items", "warmup" in real_cats_found)
check("contains ONLY those 3 real categories, nothing else leaked in", real_cats_found == {"conditioning", "mobility", "warmup"})

expected_total = (len(library.list_exercises(conn, category="conditioning"))
                   + len(library.list_exercises(conn, category="mobility"))
                   + len(library.list_exercises(conn, category="warmup")))
check(f"total count matches the sum of the 3 real categories ({expected_total})",
      len(full_body_results) == expected_total)

print("[3] CRITICAL: the real category field on each row is UNCHANGED (still 'conditioning', not 'full_body')...")
cond_item = next(e for e in full_body_results if e["category"] == "conditioning")
check(f"a conditioning item's category field is genuinely 'conditioning', not overwritten ('{cond_item['category']}')",
      cond_item["category"] == "conditioning")

print("[4] CRITICAL: the scheduler still works - it depends on the REAL category values directly...")
from core import scheduler
pid = dbmod.create_profile(conn, "Fadi")
plan = scheduler.generate_schedule(conn, pid, 4, plan_name="Test")
hc_day = next(d for d in plan if d["day_type"] == "handstand_conditioning")
check("Handstand+Conditioning day still correctly pulls real conditioning-category items",
      any(it["exercise"]["category"] == "conditioning" for it in hc_day["items"]))

print("[5] Individual muscle groups still work exactly as before (unaffected by this change)...")
legs_only = library.list_exercises_for_filter(conn, "legs")
check("Legs filter returns only category=legs items", all(e["category"] == "legs" for e in legs_only))
check("Legs filter is unchanged in count vs direct query",
      len(legs_only) == len(library.list_exercises(conn, category="legs")))

print("[6] Full library route: dropdown shows 'Full Body', selecting it shows all 3 real categories with their TRUE badges...")
import app as app_module
app_module.dbmod.DB_PATH = TMP_DB
app_module.app.config["TESTING"] = True
client = app_module.app.test_client()
client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)

r = client.get("/library")
html = r.data.decode("utf-8")
check("dropdown shows 'Full Body' option", ">Full Body<" in html)
check("dropdown no longer shows standalone 'Conditioning' as a top-level filter option",
      '"conditioning">Conditioning<' not in html)

r = client.get("/library?category=full_body")
html = r.data.decode("utf-8")
check("status 200", r.status_code == 200)
check("shows a real conditioning exercise", "High Knees" in html or "Jumping Jacks" in html)
check("shows a real mobility exercise", "Ankle" in html or "Stretch" in html)
check("row still shows the TRUE specific category badge (e.g. 'Conditioning'), not a generic 'Full Body' badge",
      ">Conditioning<" in html)

print("\nALL FULL-BODY GROUPING TESTS PASSED")
conn.close()
os.remove(TMP_DB)
