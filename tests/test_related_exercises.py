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


print("[1] Selecting 'Legs' surfaces leg-relevant mobility/warmup, by muscle tag...")
related = library.get_related_prep_exercises(conn, "legs")
related_names = [e["name"] for e in related]
related_categories = {e["category"] for e in related}
check(f"found some related items (got {len(related)})", len(related) > 0)
check("all related items are from warmup/mobility/conditioning, not 'legs' itself",
      related_categories.issubset({"warmup", "mobility", "conditioning"}))
check("Pancake Stretch (adductors/hamstrings -> legs) is included",
      "Pancake Stretch (Straddle Forward Fold)" in related_names)
check("Ankle Dorsiflexion (calves -> legs) is included",
      any("Ankle Dorsiflexion" in n for n in related_names))

print("[2] A push-specific warmup does NOT show under Legs...")
push_specific = [e for e in library.list_exercises(conn, category="warmup")
                 if "front_delts" in e.get("primary_muscles", []) and "hip_flexors" not in e.get("primary_muscles", [])]
check("found at least one genuinely push-only warmup item to test with", len(push_specific) > 0)
for e in push_specific:
    check(f"'{e['name']}' (push-only) correctly excluded from Legs' related list", e["id"] not in [r["id"] for r in related])

print("[3] Shoulder-related mobility shows under BOTH Push and Pull (legitimately dual-relevant)...")
push_related = {e["id"] for e in library.get_related_prep_exercises(conn, "push")}
pull_related = {e["id"] for e in library.get_related_prep_exercises(conn, "pull")}
overlap = push_related & pull_related
check(f"at least one shoulder item appears under both Push and Pull (got {len(overlap)})", len(overlap) > 0)

print("[4] Conditioning/pure-full-body items with no mapped muscle tag simply don't force-appear anywhere false...")
handstand_related = library.get_related_prep_exercises(conn, "handstand")
check("handstand related list doesn't error and returns a list", isinstance(handstand_related, list))

print("[5] Full library route renders the related section correctly...")
import app as app_module
app_module.dbmod.DB_PATH = TMP_DB
app_module.app.config["TESTING"] = True
client = app_module.app.test_client()
client.post("/profiles/create", data={"name": "Fadi"}, follow_redirects=True)
r = client.get("/library?category=legs")
html = r.data.decode("utf-8")
check("status 200", r.status_code == 200)
check("shows the 'Related warm-up & mobility' section header", "Related warm-up" in html)
check("Pancake Stretch appears on the Legs page even though its category is Mobility",
      "Pancake Stretch" in html)

print("\nALL RELATED-EXERCISE LINKING TESTS PASSED")
conn.close()
os.remove(TMP_DB)
