"""
core/reminders.py — time-based reassessment reminder. This checks on app
launch; it can't push OS notifications while the app is closed unless you
add a Windows Task Scheduler entry that launches main.py periodically
(see README.md for the one-line command to set that up).
"""
from datetime import datetime
from core import db as dbmod
from core import assessment as assess_mod


def days_since_last_assessment(conn):
    last = assess_mod.last_assessment_date(conn)
    if not last:
        return None
    delta = datetime.now() - datetime.strptime(last, "%Y-%m-%d")
    return delta.days


def is_reassessment_due(conn):
    interval = int(dbmod.get_setting(conn, "reassessment_interval_days", "60"))
    days = days_since_last_assessment(conn)
    if days is None:
        return True, "No assessment on record yet."
    if days >= interval:
        return True, f"Last full assessment was {days} days ago (interval: {interval} days)."
    return False, f"Last assessment was {days} days ago; next due in {interval - days} days."
