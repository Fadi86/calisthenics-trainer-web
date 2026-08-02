"""
core/assessment.py — turns a raw performance (reps, hold time, or weight x
reps) into a tier placement, using the ranges from data/prescriptions.json.
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


def record_assessment(conn, exercise_id, reps=None, hold_seconds=None, weight_kg=None, notes=None):
    result = classify_performance(conn, exercise_id, reps, hold_seconds, weight_kg)
    conn.execute("""
        INSERT INTO assessments (exercise_id, date, reps, hold_seconds, weight_kg, estimated_1rm, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (exercise_id, dbmod.today_str(), reps, hold_seconds, weight_kg, result["estimated_1rm"], notes))
    conn.commit()

    # Update the working tier for this rotation_group.
    ex = library.get_exercise(conn, exercise_id)
    new_tier = ex["tier"]
    if result["status"] == "at_or_above_top":
        new_tier = min(ex["tier"] + 1, 6)
    elif result["status"] == "below_bottom":
        new_tier = max(ex["tier"] - 1, 1)

    if ex.get("category") and ex.get("subcategory"):
        movement_key = f"{ex['category']}_{ex['subcategory']}"
        conn.execute("""
            INSERT INTO user_tiers (movement_key, current_tier, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(movement_key) DO UPDATE SET current_tier = excluded.current_tier,
                updated_at = excluded.updated_at
        """, (movement_key, new_tier, dbmod.now_iso()))
        conn.commit()

    result["assigned_tier"] = new_tier
    return result


def get_current_tier(conn, movement_key, default=1):
    row = conn.execute("SELECT current_tier FROM user_tiers WHERE movement_key = ?",
                        (movement_key,)).fetchone()
    return row["current_tier"] if row else default


def last_assessment_date(conn):
    row = conn.execute("SELECT MAX(date) AS d FROM assessments").fetchone()
    return row["d"] if row else None


CORE_CATEGORIES = ["pull", "push", "core", "legs"]


def get_progress_summary(conn):
    """Per-category (pull/push/core/legs) max tier reached + latest assessment,
    for the Progress page."""
    summary = {}
    for cat in CORE_CATEGORIES:
        rows = conn.execute("""
            SELECT ut.current_tier FROM user_tiers ut WHERE ut.movement_key LIKE ?
        """, (f"{cat}_%",)).fetchall()
        max_tier = max([r["current_tier"] for r in rows], default=1)

        last = conn.execute("""
            SELECT a.*, e.name as exercise_name, e.metric_type
            FROM assessments a JOIN exercises e ON e.id = a.exercise_id
            WHERE e.category = ?
            ORDER BY a.id DESC LIMIT 1
        """, (cat,)).fetchone()
        summary[cat] = {"max_tier": max_tier, "last_assessment": dict(last) if last else None}
    return summary


def get_weighted_max(conn, exercise_id):
    row = conn.execute("""
        SELECT a.*, e.metric_type, e.name as exercise_name FROM assessments a
        JOIN exercises e ON e.id = a.exercise_id
        WHERE a.exercise_id = ? AND (a.estimated_1rm IS NOT NULL OR a.weight_kg IS NOT NULL)
        ORDER BY a.id DESC LIMIT 1
    """, (exercise_id,)).fetchone()
    return dict(row) if row else None


# Curated "known calisthenics skills" per category - shown on the Progress
# page. Uses subcategory (movement pattern), not individual grip variants,
# since tier is tracked per pattern, not per exercise variant.
CURATED_PATTERNS = {
    "pull": [("pullup", "Pull-up / Chin-up"), ("muscle_up", "Muscle-up"),
             ("__lever__", "Skills (Front/Back Lever)")],
    "push": [("pushup", "Push-up"), ("dip", "Dip"), ("planche", "Skills (Planche)")],
    "core": [("lsit", "L-sit"), ("dragon_flag", "Dragon Flag"), ("leg_raise", "Leg Raise / Toes-to-Bar")],
    "legs": [("squat", "Squat / Pistol"), ("hinge", "Hinge / Nordic Curl"), ("lunge", "Lunge")],
}


def _next_due(conn, last_date):
    if not last_date:
        return None
    interval = int(dbmod.get_setting(conn, "reassessment_interval_days", "60"))
    from datetime import datetime, timedelta
    d = datetime.strptime(last_date, "%Y-%m-%d") if len(last_date) == 10 else datetime.strptime(last_date[:10], "%Y-%m-%d")
    return (d + timedelta(days=interval)).strftime("%Y-%m-%d")


def _review_text(status):
    if status == "at_or_above_top":
        return "Ready for the next tier — try progressing this pattern.", "progress"
    if status == "below_bottom":
        return "Below range — hold here, focus on form before adding reps.", "regress"
    return "On track for this tier — keep training here.", "hold"


def get_progress_detail(conn):
    """Rich per-pattern breakdown for the Progress page: tier, last/next
    assessment dates, and a short recommendation, curated to the well-known
    calisthenics skills rather than every internal subcategory."""
    detail = {}
    for cat, patterns in CURATED_PATTERNS.items():
        rows = []
        for subcat, label in patterns:
            if subcat == "__lever__":
                tier_fl = _tier_for(conn, "pull", "front_lever")
                tier_bl = _tier_for(conn, "pull", "back_lever")
                tier = max(tier_fl, tier_bl)
                last = _latest_assessment_for_subcats(conn, "pull", ["front_lever", "back_lever"])
            else:
                tier = _tier_for(conn, cat, subcat)
                last = _latest_assessment_for_subcats(conn, cat, [subcat])
            review, rec = (None, None)
            if last:
                review, rec = _review_text(last["status"])
            rows.append({
                "label": label, "tier": tier,
                "last_date": last["date"] if last else None,
                "next_due": _next_due(conn, last["date"]) if last else None,
                "review": review, "recommendation": rec,
                "exercise_name": last["exercise_name"] if last else None,
            })
        detail[cat] = rows
    return detail


def _tier_for(conn, category, subcategory):
    row = conn.execute("SELECT current_tier FROM user_tiers WHERE movement_key = ?",
                        (f"{category}_{subcategory}",)).fetchone()
    return row["current_tier"] if row else 1


def _latest_assessment_for_subcats(conn, category, subcats):
    placeholders = ",".join("?" * len(subcats))
    row = conn.execute(f"""
        SELECT a.*, e.name as exercise_name, e.tier as ex_tier, e.metric_type as ex_metric_type
        FROM assessments a
        JOIN exercises e ON e.id = a.exercise_id
        WHERE e.category = ? AND e.subcategory IN ({placeholders})
        ORDER BY a.id DESC LIMIT 1
    """, (category, *subcats)).fetchone()
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
