"""
core/library.py — read-side queries over the seeded exercise library.
"""
import json


def _row_to_dict(row):
    d = dict(row)
    for key in ("aliases", "equipment", "prerequisites", "regression_of",
                "progression_to", "mobility_required", "cues", "common_faults",
                "primary_muscles", "secondary_muscles"):
        json_key = f"{key}_json"
        if json_key in d:
            d[key] = json.loads(d.pop(json_key) or "[]")
    d["is_assessment"] = bool(d.get("is_assessment"))
    return d


def get_exercise(conn, exercise_id):
    row = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_exercises(conn, category=None, subcategory=None, tier=None, type_=None, modality=None):
    q = "SELECT * FROM exercises WHERE 1=1"
    params = []
    if category:
        q += " AND category = ?"; params.append(category)
    if subcategory:
        q += " AND subcategory = ?"; params.append(subcategory)
    if tier:
        q += " AND tier = ?"; params.append(tier)
    if type_:
        q += " AND type = ?"; params.append(type_)
    if modality:
        q += " AND modality = ?"; params.append(modality)
    q += " ORDER BY category, subcategory, tier, name"
    rows = conn.execute(q, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_exercise_videos(conn, exercise_id):
    rows = conn.execute(
        "SELECT * FROM exercise_videos WHERE exercise_id = ? ORDER BY is_primary DESC, id",
        (exercise_id,)
    ).fetchall()
    return [dict(r) for r in rows]


SKILL_SUBCATS = {"front_lever", "back_lever", "planche", "muscle_up", "one_arm", "balance", "arm_balance"}

CATEGORY_LABELS = {
    "pull": "Pull", "push": "Push", "legs": "Legs", "core": "Core",
    "handstand": "Handstand", "conditioning": "Conditioning",
    "warmup": "Warm-up", "mobility": "Mobility",
}


def classify_role(exercise):
    """Written text classification for the library's third badge - one of:
    main / skills / mobility / conditioning / extra / accessory.
    'extra' = warm-up prep work; 'accessory' = genuine assistance/secondary
    strength work (type=extra but not warm-up/mobility/conditioning/a skill).
    Kept distinct from the category badge (first badge) so the two don't
    just repeat the same word for warm-up/mobility/conditioning items."""
    cat = exercise["category"]
    if cat == "warmup":
        return "extra", "role-extra"
    if cat == "conditioning":
        return "conditioning", "role-conditioning"
    if cat == "mobility":
        return "mobility", "role-mobility"
    if exercise["subcategory"] in SKILL_SUBCATS:
        return "skills", "role-skill"
    if exercise["type"] == "extra":
        return "accessory", "role-accessory"
    return "main", "role-main"


def get_rotation_siblings(conn, exercise_id):
    """Same rotation_group, i.e. valid lateral swaps at the same difficulty."""
    ex = get_exercise(conn, exercise_id)
    if not ex or not ex.get("rotation_group"):
        return []
    rows = conn.execute(
        "SELECT * FROM exercises WHERE rotation_group = ? AND id != ?",
        (ex["rotation_group"], exercise_id)
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_chain(conn, exercise_id, _seen=None):
    """Walk regression_of/progression_to to build the full ladder, sorted by tier."""
    _seen = _seen or set()
    if exercise_id in _seen:
        return []
    _seen.add(exercise_id)
    ex = get_exercise(conn, exercise_id)
    if not ex:
        return []
    chain = {exercise_id: ex}
    frontier = list(ex.get("regression_of", [])) + list(ex.get("progression_to", []))
    for other_id in frontier:
        for step in get_chain(conn, other_id, _seen):
            chain[step["id"]] = step
    return sorted(chain.values(), key=lambda e: e["tier"])


def categories(conn):
    rows = conn.execute("SELECT DISTINCT category FROM exercises ORDER BY category").fetchall()
    return [r["category"] for r in rows]


def subcategories(conn, category):
    rows = conn.execute(
        "SELECT DISTINCT subcategory FROM exercises WHERE category = ? ORDER BY subcategory",
        (category,)
    ).fetchall()
    return [r["subcategory"] for r in rows]
