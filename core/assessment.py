"""
core/assessment.py — turns a raw performance (reps, hold time, or weight x
reps) into a tier placement, using the ranges from data/prescriptions.json.
Everything is scoped by profile_id so multiple people's progress never mixes.
"""
import json
import os
from core import db as dbmod
from core import library

_PRESC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "prescriptions.json")


def _load_prescriptions():
    with open(_PRESC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_range(range_str):
    """'8-15' -> (8, 15)"""
    lo, hi = range_str.split("-")
    return float(lo), float(hi)


def tier_range(tier, metric_type):
    presc = _load_prescriptions()
    row = presc["by_tier"][str(tier)]
    if metric_type == "hold_seconds":
        return _parse_range(row["hold_range_seconds"])
    return _parse_range(row["reps_range"])


def estimate_one_rep_max(weight_kg, reps):
    """Epley formula. For weighted calisthenics, 'weight' should be the
    ADDED external load (vest/belt/dumbbell), not bodyweight."""
    if reps is None or reps <= 0:
        return weight_kg
    if reps == 1:
        return weight_kg
    return round(weight_kg * (1 + reps / 30.0), 1)


def classify_performance(conn, exercise_id, reps=None, hold_seconds=None, weight_kg=None):
    """
    Returns a dict describing where this performance sits relative to the
    exercise's own tier, and whether it signals readiness to progress.
    """
    ex = library.get_exercise(conn, exercise_id)
    if not ex:
        raise ValueError(f"Unknown exercise: {exercise_id}")

    metric_type = ex["metric_type"]
    value = hold_seconds if metric_type == "hold_seconds" else reps
    lo, hi = tier_range(ex["tier"], metric_type)

    estimated_1rm = None
    if weight_kg is not None and reps:
        estimated_1rm = estimate_one_rep_max(weight_kg, reps)

    if value is None:
        status = "no_data"
    elif value >= hi:
        status = "at_or_above_top"      # ready to progress
    elif value < lo:
        status = "below_bottom"         # regress or hold at lower tier
    else:
        status = "within_range"

    return {
        "exercise_id": exercise_id,
        "exercise_name": ex["name"],
        "tier": ex["tier"],
        "metric_type": metric_type,
        "value": value,
        "range_low": lo,
        "range_high": hi,
        "status": status,
        "estimated_1rm": estimated_1rm,
        "rotation_group": ex["rotation_group"],
    }


def record_assessment(conn, profile_id, exercise_id, reps=None, hold_seconds=None, weight_kg=None, notes=None):
    result = classify_performance(conn, exercise_id, reps, hold_seconds, weight_kg)
    conn.execute("""
        INSERT INTO assessments (profile_id, exercise_id, date, reps, hold_seconds, weight_kg, estimated_1rm, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (profile_id, exercise_id, dbmod.today_str(), reps, hold_seconds, weight_kg, result["estimated_1rm"], notes))
    conn.commit()

    # Update this profile's working tier for this movement pattern.
    ex = library.get_exercise(conn, exercise_id)
    new_tier = ex["tier"]
    if result["status"] == "at_or_above_top":
        new_tier = min(ex["tier"] + 1, 6)
    elif result["status"] == "below_bottom":
        new_tier = max(ex["tier"] - 1, 1)

    if ex.get("category") and ex.get("subcategory"):
        movement_key = f"{ex['category']}_{ex['subcategory']}"
        conn.execute("""
            INSERT INTO user_tiers (profile_id, movement_key, current_tier, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id, movement_key) DO UPDATE SET current_tier = excluded.current_tier,
                updated_at = excluded.updated_at
        """, (profile_id, movement_key, new_tier, dbmod.now_iso()))
        conn.commit()

    result["assigned_tier"] = new_tier
    return result


def get_current_tier(conn, profile_id, movement_key, default=1):
    row = conn.execute("SELECT current_tier FROM user_tiers WHERE profile_id = ? AND movement_key = ?",
                        (profile_id, movement_key)).fetchone()
    return row["current_tier"] if row else default


def last_assessment_date(conn, profile_id):
    row = conn.execute("SELECT MAX(date) AS d FROM assessments WHERE profile_id = ?", (profile_id,)).fetchone()
    return row["d"] if row else None


CORE_CATEGORIES = ["pull", "push", "core", "legs"]


def get_weighted_max(conn, profile_id, exercise_id):
    row = conn.execute("""
        SELECT a.*, e.metric_type, e.name as exercise_name FROM assessments a
        JOIN exercises e ON e.id = a.exercise_id
        WHERE a.profile_id = ? AND a.exercise_id = ? AND (a.estimated_1rm IS NOT NULL OR a.weight_kg IS NOT NULL)
        ORDER BY a.id DESC LIMIT 1
    """, (profile_id, exercise_id)).fetchone()
    return dict(row) if row else None


# Curated "known calisthenics skills" per category - shown on the Progress
# page. Uses subcategory (movement pattern), not individual grip variants,
# since tier is tracked per pattern, not per exercise variant.
CURATED_PATTERNS = {
    "pull": [("pullup", "Pull-up / Chin-up"), ("muscle_up", "Muscle-up"),
             ("front_lever", "Skills (Front Lever)"), ("back_lever", "Skills (Back Lever)")],
    "push": [("pushup", "Push-up"), ("dip", "Dip"), ("planche", "Skills (Planche)")],
    "core": [("lsit", "L-sit"), ("dragon_flag", "Dragon Flag"), ("leg_raise", "Leg Raise / Toes-to-Bar")],
    "legs": [("squat", "Squat / Pistol"), ("hinge", "Hinge / Nordic Curl"), ("lunge", "Lunge")],
}


def _next_due(conn, last_date):
    if not last_date:
        return None
    interval = int(dbmod.get_setting(conn, "reassessment_interval_days", "60"))
    from datetime import datetime, timedelta
    d = datetime.strptime(last_date[:10], "%Y-%m-%d")
    return (d + timedelta(days=interval)).strftime("%Y-%m-%d")


def _review_text(status):
    if status == "at_or_above_top":
        return "Ready for the next tier — try progressing this pattern.", "progress"
    if status == "below_bottom":
        return "Below range — hold here, focus on form before adding reps.", "regress"
    return "On track for this tier — keep training here.", "hold"


# Explicit, hand-curated stage order per skill - deliberately NOT using
# library.get_chain() here, since that walks the general regression_of/
# progression_to graph and would merge Front Lever + Back Lever together
# (they share German Hang as a common prerequisite), recreating the exact
# "one masks the other" problem this page exists to avoid.
SKILL_STAGES = {
    "front_lever": ["pull_german_hang", "pull_fl_tuck", "pull_fl_adv_tuck", "pull_fl_one_leg",
                    "pull_fl_straddle", "pull_fl_full", "pull_fl_oa_tuck", "pull_fl_oa_full"],
    "back_lever": ["pull_bl_tuck", "pull_bl_adv_tuck", "pull_bl_straddle", "pull_bl_full", "pull_bl_oa"],
    "planche": ["push_planche_lean", "push_planche_tuck", "push_planche_adv_tuck",
                "push_planche_straddle", "push_planche_hold_full", "push_planche_full"],
    "muscle_up": ["pull_explosive_pullup", "pull_muscleup_kip", "pull_muscleup_strict_bar",
                  "pull_muscleup_strict_ring"],
}


def get_skill_stages(conn, profile_id, category, subcategory):
    """Ordered stage checklist for one skill (Tuck -> Straddle -> Full, etc.)
    with each stage marked reached/not-reached, and the specific stage most
    recently tested. 'Reached' is based on ORDINAL POSITION in this explicit
    chain, not on comparing raw tier numbers - several stages share the same
    tier (Advanced Tuck, One-Leg, Straddle, and Full front lever are ALL
    tier 4), so a tier-number comparison here would wrongly mark every
    same-tier stage as reached the moment any one of them is tested."""
    stage_ids = SKILL_STAGES.get(subcategory)
    if not stage_ids:
        return None

    placeholders = ",".join("?" * len(stage_ids))
    last_row = conn.execute(f"""
        SELECT exercise_id FROM assessments WHERE profile_id = ? AND exercise_id IN ({placeholders})
        ORDER BY id DESC LIMIT 1
    """, (profile_id, *stage_ids)).fetchone()
    last_tested_id = last_row["exercise_id"] if last_row else None
    last_tested_index = stage_ids.index(last_tested_id) if last_tested_id in stage_ids else -1

    stages = []
    for idx, eid in enumerate(stage_ids):
        ex = library.get_exercise(conn, eid)
        if not ex:
            continue
        stages.append({
            "id": eid, "name": ex["name"], "tier": ex["tier"],
            "reached": idx <= last_tested_index,
            "is_last_tested": eid == last_tested_id,
        })
    return stages


def get_progress_detail(conn, profile_id):
    """Rich per-pattern breakdown for the Progress page: tier, last/next
    assessment dates, and a short recommendation, curated to the well-known
    calisthenics skills rather than every internal subcategory. Each skill
    is tracked and shown independently - Front Lever and Back Lever, for
    instance, never get merged into one number, since training one hard
    while neglecting the other is common and shouldn't be hidden."""
    detail = {}
    for cat, patterns in CURATED_PATTERNS.items():
        rows = []
        for subcat, label in patterns:
            tier = _tier_for(conn, profile_id, cat, subcat)
            last = _latest_assessment_for_subcats(conn, profile_id, cat, [subcat])
            stages = get_skill_stages(conn, profile_id, cat, subcat)
            review, rec, next_stage_name = (None, None, None)
            if last:
                review, rec = _review_text(last["status"])
                if rec == "progress":
                    next_stage_name = _next_stage_name(stages, last["exercise_id"]) \
                        if stages else _next_stage_name_generic(conn, last["exercise_id"])
            rows.append({
                "label": label, "tier": tier,
                "last_date": last["date"] if last else None,
                "next_due": _next_due(conn, last["date"]) if last else None,
                "review": review, "recommendation": rec,
                "exercise_name": last["exercise_name"] if last else None,
                "stages": stages,
                "next_stage_name": next_stage_name,
            })
        detail[cat] = rows
    return detail


def _next_stage_name(stages, last_exercise_id):
    """Next entry in the explicit hand-curated stage chain, by position -
    correct even when the next stage shares the current tier number."""
    ids = [s["id"] for s in stages]
    if last_exercise_id not in ids:
        return None
    idx = ids.index(last_exercise_id)
    return stages[idx + 1]["name"] if idx + 1 < len(stages) else None


def _next_stage_name_generic(conn, exercise_id):
    """Fallback for patterns without a hand-curated chain (plain ladders
    like pull-up/push-up/squat) - uses the exercise's own progression_to."""
    row = conn.execute("SELECT progression_to_json FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    if not row or not row["progression_to_json"]:
        return None
    targets = json.loads(row["progression_to_json"])
    if not targets:
        return None
    next_ex = conn.execute("SELECT name FROM exercises WHERE id = ?", (targets[0],)).fetchone()
    return next_ex["name"] if next_ex else None


def _tier_for(conn, profile_id, category, subcategory):
    row = conn.execute("SELECT current_tier FROM user_tiers WHERE profile_id = ? AND movement_key = ?",
                        (profile_id, f"{category}_{subcategory}")).fetchone()
    return row["current_tier"] if row else 1


def _latest_assessment_for_subcats(conn, profile_id, category, subcats):
    placeholders = ",".join("?" * len(subcats))
    row = conn.execute(f"""
        SELECT a.*, e.name as exercise_name, e.tier as ex_tier, e.metric_type as ex_metric_type
        FROM assessments a
        JOIN exercises e ON e.id = a.exercise_id
        WHERE a.profile_id = ? AND e.category = ? AND e.subcategory IN ({placeholders})
        ORDER BY a.id DESC LIMIT 1
    """, (profile_id, category, *subcats)).fetchone()
    if not row:
        return None
    row = dict(row)
    value = row["hold_seconds"] if row["ex_metric_type"] == "hold_seconds" else row["reps"]
    lo, hi = tier_range(row["ex_tier"], row["ex_metric_type"])
    if value is None:
        row["status"] = "no_data"
    elif value >= hi:
        row["status"] = "at_or_above_top"
    elif value < lo:
        row["status"] = "below_bottom"
    else:
        row["status"] = "within_range"
    return row
