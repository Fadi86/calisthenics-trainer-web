"""
core/scheduler.py — builds a weekly schedule from the exercise library,
following the day-segregation rules from PROGRAMMING-GUIDE.md, plus:
  - warm-up items chosen dynamically from the categories trained that day
  - mobility items auto-included from each picked exercise's mobility_required
  - optional extra shoulder/hip mobility toggles
  - a 60-minute (warm-up + main) duration budget that trims lowest-priority
    items first rather than silently going over
"""
import random
from core import library
from core import assessment as assess_mod
from core import db as dbmod

DAY_DEFS_4 = [
    {"day_type": "pull_front_lever", "label": "Pull + Front Lever", "slots": [
        {"category": "pull", "subcats": ["front_lever", "back_lever"], "role": "skill", "pick": 1},
        {"category": "pull", "subcats": ["pullup", "row", "hang", "one_arm"], "role": "main", "pick": 3},
        {"category": "pull", "subcats": None, "role": "extra", "pick": 1, "type_filter": "extra"},
    ]},
    {"day_type": "push_planche", "label": "Push + Planche", "slots": [
        {"category": "push", "subcats": ["planche"], "role": "skill", "pick": 1},
        {"category": "push", "subcats": ["pushup", "dip", "hspu"], "role": "main", "pick": 3},
        {"category": "push", "subcats": None, "role": "extra", "pick": 1, "type_filter": "extra"},
    ]},
    {"day_type": "legs_core_muscle_up", "label": "Legs + Core + Muscle-up", "slots": [
        {"category": "pull", "subcats": ["muscle_up"], "role": "skill", "pick": 1},
        {"category": "legs", "subcats": ["squat", "lunge"], "role": "main", "pick": 2},
        {"category": "core", "subcats": ["lsit", "leg_raise", "dragon_flag", "hollow", "plank", "misc"],
         "role": "main", "pick": 2},
        {"category": "legs", "subcats": None, "role": "extra", "pick": 1, "type_filter": "extra"},
    ]},
    {"day_type": "handstand_conditioning", "label": "Handstand + Conditioning", "slots": [
        {"category": "handstand", "subcats": ["balance", "arm_balance"], "role": "skill", "pick": 2},
        {"category": "conditioning", "subcats": None, "role": "extra", "pick": 2, "type_filter": "extra"},
    ]},
]

DAY_DEFS_5 = [
    DAY_DEFS_4[0],
    DAY_DEFS_4[1],
    {"day_type": "legs", "label": "Legs (Dedicated)", "slots": [
        {"category": "legs", "subcats": ["squat", "lunge"], "role": "main", "pick": 3},
        {"category": "legs", "subcats": ["hinge", "calf", "plyo"], "role": "extra", "pick": 1,
         "type_filter": "extra"},
    ]},
    {"day_type": "core_handstand", "label": "Core + Handstand", "slots": [
        {"category": "handstand", "subcats": ["balance", "arm_balance"], "role": "skill", "pick": 1},
        {"category": "core", "subcats": ["lsit", "leg_raise", "dragon_flag", "hollow", "plank", "misc"],
         "role": "main", "pick": 3},
    ]},
    {"day_type": "muscle_up_conditioning", "label": "Muscle-up + Conditioning", "slots": [
        {"category": "pull", "subcats": ["muscle_up"], "role": "skill", "pick": 1},
        {"category": "conditioning", "subcats": None, "role": "extra", "pick": 3, "type_filter": "extra"},
    ]},
]

# Warm-up picked dynamically from which categories actually appear in a
# day's slots, rather than one fixed hardcoded list per day - so it stays
# correct even if DAY_DEFS_4/5 change later.
GENERAL_RAISE_ID = "warmup_march_in_place"
CATEGORY_TO_WARMUP = {
    "pull": ["warmup_scap_hang", "warmup_wrist_circles"],
    "push": ["warmup_arm_circles", "warmup_wrist_prep"],
    "legs": ["warmup_hip_mobility", "warmup_leg_swings_front_back"],
    "core": ["warmup_hollow_hold", "warmup_cat_cow"],
    "handstand": ["warmup_wrist_prep", "warmup_pogo_hops"],
    "conditioning": ["warmup_jumping_jacks_easy"],
}
MAX_WARMUP_ITEMS = 4  # general raise + up to 3 category-specific items

DURATION_BUDGET_SECONDS = 60 * 60
WARMUP_ITEM_SECONDS = 40
MOBILITY_ITEM_SECONDS = 45


def _pick_for_slot(conn, slot, current_tiers, rng, exclude_ids=None):
    exclude_ids = exclude_ids or set()
    candidates = library.list_exercises(conn, category=slot["category"])
    if slot.get("subcats"):
        candidates = [c for c in candidates if c["subcategory"] in slot["subcats"]]
    type_filter = slot.get("type_filter", "main")
    candidates = [c for c in candidates if c["type"] == type_filter and c["id"] not in exclude_ids]
    if not candidates:
        return []

    eligible = []
    for c in candidates:
        movement_key = f"{c['category']}_{c['subcategory']}"
        cur_tier = current_tiers.get(movement_key, 1)
        if c["tier"] <= cur_tier:
            eligible.append(c)
    if not eligible:
        min_tier = min(c["tier"] for c in candidates)
        eligible = [c for c in candidates if c["tier"] == min_tier]

    max_tier = max(c["tier"] for c in eligible)
    top = [c for c in eligible if c["tier"] == max_tier]
    rng.shuffle(top)
    n = min(slot["pick"], len(top))
    return top[:n]


def _get_all_current_tiers(conn, profile_id):
    rows = conn.execute("SELECT movement_key, current_tier FROM user_tiers WHERE profile_id = ?",
                         (profile_id,)).fetchall()
    return {r["movement_key"]: r["current_tier"] for r in rows}


def _make_item(ex, role):
    lo, hi = assess_mod.tier_range(ex["tier"], ex["metric_type"])
    presc = assess_mod._load_prescriptions()["by_tier"][str(ex["tier"])]
    return {
        "exercise": ex, "role": role, "target_sets": presc["sets"],
        "target_low": lo, "target_high": hi, "metric_type": ex["metric_type"],
    }


def _parse_avg(range_str):
    """'3' -> 3.0, '3-4' -> 3.5"""
    parts = str(range_str).split("-")
    nums = [float(p) for p in parts]
    return sum(nums) / len(nums)


def estimate_item_seconds(item):
    """Rough time estimate for one exercise's block, including rest between
    sets. Used for the 60-minute session budget, not shown as a precise
    promise - training time varies too much person to person for that."""
    role = item["role"]
    if role == "warmup":
        return WARMUP_ITEM_SECONDS
    if role in ("mobility", "mobility_optional"):
        return MOBILITY_ITEM_SECONDS

    tier = item["exercise"]["tier"]
    presc = assess_mod._load_prescriptions()["by_tier"][str(tier)]
    sets_n = _parse_avg(presc["sets"])
    rest_n = _parse_avg(presc["rest_seconds"])

    if item["metric_type"] == "hold_seconds":
        work_per_set = (item["target_low"] + item["target_high"]) / 2
    else:
        reps_avg = (item["target_low"] + item["target_high"]) / 2
        work_per_set = reps_avg * 2.5  # rough seconds-per-rep estimate

    return sets_n * work_per_set + max(0, sets_n - 1) * rest_n


def _build_warmup_ids(day_def, used_ids):
    ids_to_add = [GENERAL_RAISE_ID]
    categories_today = {slot["category"] for slot in day_def["slots"]}
    for cat in categories_today:
        ids_to_add.extend(CATEGORY_TO_WARMUP.get(cat, []))

    chosen = []
    for wid in ids_to_add:
        if len(chosen) >= MAX_WARMUP_ITEMS:
            break
        if wid in used_ids:
            continue
        chosen.append(wid)
        used_ids.add(wid)
    return chosen


def _build_mobility_items(conn, main_picks, used_ids, extra_shoulder=False, extra_hip=False):
    items = []
    required_ids = []
    for p in main_picks:
        for mid in p["exercise"].get("mobility_required", []):
            if mid not in used_ids and mid not in required_ids:
                required_ids.append(mid)

    for mid in required_ids:
        ex = library.get_exercise(conn, mid)
        if ex:
            items.append(_make_item(ex, "mobility"))
            used_ids.add(mid)

    if extra_shoulder:
        candidates = [e for e in library.list_exercises(conn, category="mobility", subcategory="shoulder")
                      if e["id"] not in used_ids]
        if candidates:
            ex = candidates[0]
            items.append(_make_item(ex, "mobility_optional"))
            used_ids.add(ex["id"])

    if extra_hip:
        candidates = [e for e in library.list_exercises(conn, category="mobility", subcategory="hip")
                      if e["id"] not in used_ids]
        if candidates:
            ex = candidates[0]
            items.append(_make_item(ex, "mobility_optional"))
            used_ids.add(ex["id"])

    return items


def _trim_to_budget(picks):
    """Drops lowest-priority items first until under the 60-minute budget:
    optional mobility -> extra role -> main role (from the end). Never
    touches skill, warmup, or required mobility - those are either the
    point of the session or safety-relevant."""
    def total_seconds(items):
        return sum(estimate_item_seconds(p) for p in items)

    picks = list(picks)
    while total_seconds(picks) > DURATION_BUDGET_SECONDS:
        idx = next((i for i, p in enumerate(picks) if p["role"] == "mobility_optional"), None)
        if idx is None:
            extra_indices = [i for i, p in enumerate(picks) if p["role"] == "extra"]
            idx = extra_indices[-1] if extra_indices else None
        if idx is None:
            main_indices = [i for i, p in enumerate(picks) if p["role"] == "main"]
            if len(main_indices) <= 1:
                break  # keep at least one main lift no matter what
            idx = main_indices[-1]
        if idx is None:
            break
        picks.pop(idx)
    return picks


def build_day_exercises(conn, day_def, current_tiers, rng, extra_shoulder=False, extra_hip=False):
    used_ids = set()

    warmup_ids = _build_warmup_ids(day_def, used_ids)
    warmup_items = []
    for wid in warmup_ids:
        ex = library.get_exercise(conn, wid)
        if ex:
            warmup_items.append(_make_item(ex, "warmup"))

    main_picks = []
    for slot in day_def["slots"]:
        for ex in _pick_for_slot(conn, slot, current_tiers, rng, exclude_ids=used_ids):
            used_ids.add(ex["id"])
            main_picks.append(_make_item(ex, slot["role"]))

    mobility_items = _build_mobility_items(conn, main_picks, used_ids, extra_shoulder, extra_hip)

    picks = warmup_items + mobility_items + main_picks
    picks = _trim_to_budget(picks)
    return picks


def generate_schedule(conn, profile_id, days_per_week, plan_name="My Plan", seed=None,
                       extra_shoulder_mobility=False, extra_hip_mobility=False):
    """
    Creates a NEW week's schedule for this profile without deleting
    previous weeks - past weeks stay queryable for the calendar view.
    week_number increments per-profile, week_date records the real
    calendar date it was created.
    """
    if days_per_week not in (4, 5):
        raise ValueError("days_per_week must be 4 or 5")
    day_defs = DAY_DEFS_4 if days_per_week == 4 else DAY_DEFS_5
    rng = random.Random(seed)
    current_tiers = _get_all_current_tiers(conn, profile_id)

    prev_week = conn.execute(
        "SELECT COALESCE(MAX(week_number), 0) AS w FROM schedule_days WHERE plan_name = ? AND profile_id = ?",
        (plan_name, profile_id)
    ).fetchone()["w"]
    week_number = prev_week + 1
    week_date = dbmod.today_str()

    result = []
    for idx, day_def in enumerate(day_defs):
        cur = conn.execute(
            "INSERT INTO schedule_days (plan_name, days_per_week, day_index, day_type, label, "
            "week_number, week_date, profile_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plan_name, days_per_week, idx, day_def["day_type"], day_def["label"],
             week_number, week_date, profile_id)
        )
        day_id = cur.lastrowid
        picks = build_day_exercises(conn, day_def, current_tiers, rng,
                                     extra_shoulder=extra_shoulder_mobility, extra_hip=extra_hip_mobility)
        day_items = []
        for order, p in enumerate(picks):
            conn.execute("""
                INSERT INTO schedule_items (schedule_day_id, exercise_id, order_index,
                    target_sets, target_low, target_high, metric_type, role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (day_id, p["exercise"]["id"], order, p["target_sets"],
                  p["target_low"], p["target_high"], p["metric_type"], p["role"]))
            day_items.append({**p, "exercise_id": p["exercise"]["id"]})
        estimated_seconds = sum(estimate_item_seconds(p) for p in day_items)
        result.append({
            "day_type": day_def["day_type"], "label": day_def["label"], "items": day_items,
            "estimated_minutes": round(estimated_seconds / 60), "week_number": week_number, "week_date": week_date,
        })
        conn.commit()
    return result


def swap_schedule_item(conn, item_id, new_exercise_id):
    """Replace one schedule item's exercise with another, recomputing its
    target sets/reps from the new exercise's tier. Keeps the same role and
    position in the day."""
    row = conn.execute("SELECT * FROM schedule_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError(f"No schedule item with id {item_id}")
    new_ex = library.get_exercise(conn, new_exercise_id)
    if not new_ex:
        raise ValueError(f"No exercise with id {new_exercise_id}")
    item = _make_item(new_ex, row["role"])
    conn.execute("""
        UPDATE schedule_items SET exercise_id = ?, target_sets = ?, target_low = ?,
            target_high = ?, metric_type = ? WHERE id = ?
    """, (new_ex["id"], item["target_sets"], item["target_low"], item["target_high"],
          item["metric_type"], item_id))
    conn.commit()
    return item


def remove_schedule_item(conn, item_id):
    conn.execute("DELETE FROM schedule_items WHERE id = ?", (item_id,))
    conn.commit()


def add_schedule_item(conn, schedule_day_id, exercise_id, role="extra"):
    ex = library.get_exercise(conn, exercise_id)
    if not ex:
        raise ValueError(f"No exercise with id {exercise_id}")
    item = _make_item(ex, role)
    max_order = conn.execute(
        "SELECT COALESCE(MAX(order_index), -1) AS m FROM schedule_items WHERE schedule_day_id = ?",
        (schedule_day_id,)
    ).fetchone()["m"]
    conn.execute("""
        INSERT INTO schedule_items (schedule_day_id, exercise_id, order_index,
            target_sets, target_low, target_high, metric_type, role)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (schedule_day_id, ex["id"], max_order + 1, item["target_sets"], item["target_low"],
          item["target_high"], item["metric_type"], role))
    conn.commit()
    return item


def get_timer_params(item):
    """Work/rest/sets breakdown for the guided interval timer. Not a precise
    prescription - a reasonable default so the timer has something sane to
    count down even for exercises with a wide target range."""
    tier = item["exercise"]["tier"]
    presc = assess_mod._load_prescriptions()["by_tier"][str(tier)]
    sets_n = round(_parse_avg(presc["sets"]))
    rest_seconds = round(_parse_avg(presc["rest_seconds"]))

    if item["metric_type"] == "hold_seconds":
        work_seconds = round(item["target_high"])
    else:
        reps_avg = (item["target_low"] + item["target_high"]) / 2
        work_seconds = max(20, min(60, round(reps_avg * 3)))

    return {"work_seconds": work_seconds, "rest_seconds": rest_seconds, "sets": sets_n}


def get_schedule(conn, profile_id, plan_name="My Plan", week_number=None):
    """Fetch a specific week's schedule, or the latest one if week_number is None."""
    if week_number is None:
        row = conn.execute(
            "SELECT MAX(week_number) AS w FROM schedule_days WHERE plan_name = ? AND profile_id = ?",
            (plan_name, profile_id)
        ).fetchone()
        week_number = row["w"] if row else None
    if week_number is None:
        return []

    days = conn.execute(
        "SELECT * FROM schedule_days WHERE plan_name = ? AND profile_id = ? AND week_number = ? "
        "ORDER BY day_index",
        (plan_name, profile_id, week_number)
    ).fetchall()
    result = []
    for day in days:
        items = conn.execute(
            "SELECT * FROM schedule_items WHERE schedule_day_id = ? ORDER BY order_index", (day["id"],)
        ).fetchall()
        enriched = []
        for it in items:
            ex = library.get_exercise(conn, it["exercise_id"])
            enriched.append({**dict(it), "exercise": ex})
        estimated_seconds = sum(estimate_item_seconds(p) for p in enriched)
        result.append({**dict(day), "items": enriched, "estimated_minutes": round(estimated_seconds / 60)})
    return result


def get_all_weeks(conn, profile_id, plan_name="My Plan"):
    """For the calendar view - every week generated so far, most recent first."""
    rows = conn.execute("""
        SELECT week_number, MIN(week_date) as week_date, days_per_week
        FROM schedule_days WHERE plan_name = ? AND profile_id = ?
        GROUP BY week_number ORDER BY week_number DESC
    """, (plan_name, profile_id)).fetchall()
    return [dict(r) for r in rows]
