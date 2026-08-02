"""
core/health_import.py — imports wearable health data from a CSV or JSON
file dropped into a synced folder (see README.md for the Apple
Watch/Amazfit -> Health Auto Export -> Google Drive/Dropbox bridge).

No live OAuth to Apple/Zepp happens here — that would need a registered
developer app and a hosted backend. This reads files you export yourself,
which is the standard way people get Apple Health data onto a PC.

The exact column/key names in a "Health Auto Export" file can vary by
version and by which metrics you enabled, so both parsers are deliberately
flexible rather than hard-coded to one exact schema. If your file doesn't
import cleanly, check the column names against DATE_KEYS/VALUE hints below
and adjust — that's expected to need a small tweak, not a bug.
"""
import csv
import json
from datetime import datetime

DATE_KEYS = ("date", "Date", "timestamp", "Timestamp", "startDate", "start")


def _try_parse_date(value):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def _to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def import_csv(conn, path, source="csv_import"):
    """
    Generic CSV import: expects one column that looks like a date, and any
    number of other numeric columns treated as separate metrics (column
    name becomes the metric name). This matches a typical Health Auto
    Export CSV where each row is a date and each column is a metric.
    """
    inserted, skipped = 0, 0
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"inserted": 0, "skipped": 0, "error": "Empty or unreadable CSV."}
        date_col = next((c for c in reader.fieldnames if c in DATE_KEYS), reader.fieldnames[0])
        metric_cols = [c for c in reader.fieldnames if c != date_col]

        for row in reader:
            raw_date = row.get(date_col, "")
            dt = _try_parse_date(raw_date)
            date_str = dt.strftime("%Y-%m-%d") if dt else raw_date[:10]
            for col in metric_cols:
                num = _to_number(row.get(col))
                if num is None:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT INTO health_metrics (date, metric, value, unit, source) VALUES (?, ?, ?, ?, ?)",
                    (date_str, col, num, None, source)
                )
                inserted += 1
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def import_json(conn, path, source="json_import"):
    """
    Flexible JSON import. Health Auto Export's JSON shape is broadly
    {"data": {"metrics": [{"name": ..., "units": ..., "data": [{"date": ..., "qty": ...}, ...]}]}}
    but this walks the structure defensively rather than assuming exact
    keys, since export formats do change between app versions.
    """
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    metrics_list = None
    if isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, dict) and "metrics" in data:
            metrics_list = data["metrics"]
    if metrics_list is None:
        return {"inserted": 0, "skipped": 0,
                "error": "Unrecognized JSON shape — expected data.metrics[]. "
                         "Open the file and check the top-level keys, then adjust "
                         "core/health_import.py import_json() to match."}

    inserted, skipped = 0, 0
    for metric in metrics_list:
        name = metric.get("name", "unknown_metric")
        unit = metric.get("units")
        points = metric.get("data", [])
        for point in points:
            raw_date = point.get("date") or point.get("startDate") or point.get("timestamp")
            value = point.get("qty", point.get("value"))
            num = _to_number(value)
            dt = _try_parse_date(raw_date) if raw_date else None
            date_str = dt.strftime("%Y-%m-%d") if dt else (raw_date[:10] if raw_date else None)
            if num is None or date_str is None:
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO health_metrics (date, metric, value, unit, source) VALUES (?, ?, ?, ?, ?)",
                (date_str, name, num, unit, source)
            )
            inserted += 1
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def recent_metrics(conn, profile_id, days=7):
    rows = conn.execute("""
        SELECT date, metric, AVG(value) as avg_value, unit
        FROM health_metrics
        WHERE profile_id = ? AND date >= date('now', ?)
        GROUP BY date, metric
        ORDER BY date DESC
    """, (profile_id, f"-{days} days")).fetchall()
    return [dict(r) for r in rows]
