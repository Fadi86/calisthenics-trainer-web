"""
app.py — Calisthenics Trainer, web version.

Same core engine as the Windows app (core/ is byte-for-byte the same code),
just a Flask front end instead of CustomTkinter — so you can open it from
any phone browser instead of dealing with iOS sideloading.

Supports up to db.MAX_PROFILES (5) people sharing one deployment - one app
password gates the whole site, then each visit picks which profile's data
to view/edit. No per-person password; fine for a small trusted testing group.

Run: python app.py
Then open http://localhost:5000 on this machine, or http://<this-pc-lan-ip>:5000
from your phone on the same WiFi. See README.md for making it reachable
from anywhere (not just home WiFi).
"""
import os
import json
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, redirect, url_for, jsonify, session as flask_session, Response, flash

from core import db as dbmod
from core import library
from core import assessment as assess_mod
from core import scheduler
from core import progression
from core import chat as chat_mod
from core import trainer_chat
from core import reminders
from core import video_fetch
from core import backup as backup_mod
from core.i18n import t as translate
from core.version import APP_VERSION

app = Flask(__name__)
PLAN_NAME = "My Plan"


def get_conn():
    return dbmod.get_connection()


def _init_secret_key():
    conn = get_conn()
    key = dbmod.get_setting(conn, "flask_secret_key", "")
    if not key:
        key = secrets.token_hex(32)
        dbmod.set_setting(conn, "flask_secret_key", key)
    conn.close()
    return key


def current_profile_id():
    return flask_session.get("profile_id")


@app.before_request
def require_login_and_profile():
    if request.endpoint in ("login", "static"):
        return
    conn = get_conn()
    password_hash = dbmod.get_setting(conn, "app_password_hash", "")
    if password_hash and not flask_session.get("authenticated"):
        conn.close()
        return redirect(url_for("login"))
    try:
        backup_mod.maybe_run_auto_backup(conn)
    except Exception:
        pass  # never let a backup hiccup break the actual request
    conn.close()
    if request.endpoint in ("profiles_view", "profile_create", "profile_select", "profile_delete"):
        return
    if not current_profile_id():
        return redirect(url_for("profiles_view"))


@app.route("/login", methods=["GET", "POST"])
def login():
    conn = get_conn()
    password_hash = dbmod.get_setting(conn, "app_password_hash", "")
    error = None
    first_run = not password_hash

    if request.method == "POST":
        if first_run:
            new_pw = request.form.get("new_password", "")
            confirm = request.form.get("confirm_password", "")
            if len(new_pw) < 4:
                error = "Password must be at least 4 characters."
            elif new_pw != confirm:
                error = "Passwords don't match."
            else:
                dbmod.set_setting(conn, "app_password_hash", generate_password_hash(new_pw))
                flask_session["authenticated"] = True
                conn.close()
                return redirect(url_for("profiles_view"))
        else:
            entered = request.form.get("password", "")
            if check_password_hash(password_hash, entered):
                flask_session["authenticated"] = True
                conn.close()
                return redirect(url_for("dashboard"))
            error = "Wrong password."

    conn.close()
    return render_template("login.html", first_run=first_run, error=error)


@app.route("/logout")
def logout():
    flask_session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Profiles (up to MAX_PROFILES people sharing this one deployment)
# ---------------------------------------------------------------------------
@app.route("/profiles")
def profiles_view():
    conn = get_conn()
    profiles = dbmod.get_profiles(conn)
    conn.close()
    return render_template("profiles.html", profiles=profiles, max_profiles=dbmod.MAX_PROFILES)


@app.route("/profiles/create", methods=["POST"])
def profile_create():
    conn = get_conn()
    name = request.form.get("name", "").strip()
    error = None
    if not name:
        error = "Name is required."
    else:
        try:
            new_id = dbmod.create_profile(conn, name)
            flask_session["profile_id"] = new_id
            conn.close()
            return redirect(url_for("dashboard"))
        except ValueError as e:
            error = str(e)
    profiles = dbmod.get_profiles(conn)
    conn.close()
    return render_template("profiles.html", profiles=profiles, max_profiles=dbmod.MAX_PROFILES, error=error)


@app.route("/profiles/select/<int:profile_id>")
def profile_select(profile_id):
    flask_session["profile_id"] = profile_id
    return redirect(url_for("dashboard"))


@app.route("/profiles/delete/<int:profile_id>", methods=["POST"])
def profile_delete(profile_id):
    conn = get_conn()
    dbmod.delete_profile(conn, profile_id)
    conn.close()
    if current_profile_id() == profile_id:
        flask_session.pop("profile_id", None)
    return redirect(url_for("profiles_view"))


@app.context_processor
def inject_globals():
    conn = get_conn()
    lang = dbmod.get_setting(conn, "language", "en")
    active_profile = None
    pid = current_profile_id()
    if pid:
        active_profile = dbmod.get_profile(conn, pid)
    conn.close()
    return {"app_version": APP_VERSION, "t": lambda key: translate(key, lang), "lang": lang,
            "active_profile": active_profile}


def resolve_watch_url(conn, exercise):
    videos = library.get_exercise_videos(conn, exercise["id"])
    if videos:
        return videos[0]["url"]
    return video_fetch.get_exercise_youtube_search_url(exercise["name"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    conn = get_conn()
    pid = current_profile_id()
    due, reason = reminders.is_reassessment_due(conn, pid)
    ex_count = conn.execute("SELECT COUNT(*) c FROM exercises").fetchone()["c"]
    as_count = conn.execute("SELECT COUNT(*) c FROM assessments WHERE profile_id = ?", (pid,)).fetchone()["c"]
    se_count = conn.execute("SELECT COUNT(*) c FROM sessions WHERE status='completed' AND profile_id = ?",
                             (pid,)).fetchone()["c"]
    conn.close()
    return render_template("dashboard.html", due=due, reason=reason,
                            ex_count=ex_count, as_count=as_count, se_count=se_count)


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------
CORE_CATEGORIES = ["pull", "push", "core", "legs"]


@app.route("/assessment", methods=["GET", "POST"])
def assessment():
    conn = get_conn()
    pid = current_profile_id()
    categories = CORE_CATEGORIES
    selected_category = request.values.get("category", categories[0])
    exercises = library.list_exercises(conn, category=selected_category)
    result = None

    if request.method == "POST":
        exercise_id = request.form.get("exercise_id")
        reps = request.form.get("reps") or None
        hold = request.form.get("hold_seconds") or None
        weight = request.form.get("weight_kg") or None
        ex = library.get_exercise(conn, exercise_id)
        expects_hold = ex["metric_type"] == "hold_seconds"

        if expects_hold and not hold:
            result = {"error": f"{ex['name']} is measured by hold time — fill in the Hold field."}
        elif not expects_hold and not reps:
            result = {"error": f"{ex['name']} is measured by reps — fill in the Reps field."}
        else:
            result = assess_mod.record_assessment(
                conn, pid, exercise_id,
                reps=int(reps) if reps else None,
                hold_seconds=float(hold) if hold else None,
                weight_kg=float(weight) if weight else None,
            )

    conn.close()
    return render_template("assessment.html", categories=categories, selected_category=selected_category,
                            exercises=exercises, result=result)


@app.route("/assessment/max", methods=["POST"])
def assessment_max():
    conn = get_conn()
    pid = current_profile_id()
    exercise_id = request.form.get("exercise_id")
    weight = float(request.form.get("weight_kg"))
    ex = library.get_exercise(conn, exercise_id)
    if ex["metric_type"] == "hold_seconds":
        hold = float(request.form.get("hold_seconds"))
        assess_mod.record_assessment(conn, pid, exercise_id, hold_seconds=hold, weight_kg=weight)
    else:
        reps = int(request.form.get("reps"))
        assess_mod.record_assessment(conn, pid, exercise_id, reps=reps, weight_kg=weight)
    conn.close()
    return redirect(url_for("progress_view"))


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------
@app.route("/progress")
def progress_view():
    conn = get_conn()
    pid = current_profile_id()
    detail = assess_mod.get_progress_detail(conn, pid)
    pullup_max = assess_mod.get_weighted_max(conn, pid, "pull_weighted_pullup")
    dip_max = assess_mod.get_weighted_max(conn, pid, "push_weighted_dip")
    plank_max = assess_mod.get_weighted_max(conn, pid, "core_weighted_plank")
    history = assess_mod.get_assessment_history(conn, pid, limit=25)
    ai_conversation = trainer_chat.get_conversation(conn, pid)
    conn.close()
    return render_template("progress.html", detail=detail, pullup_max=pullup_max, dip_max=dip_max,
                            plank_max=plank_max, history=history, ai_conversation=ai_conversation)


@app.route("/progress/ai_recommendation", methods=["POST"])
def progress_ai_recommendation():
    conn = get_conn()
    pid = current_profile_id()
    provider = dbmod.get_setting(conn, "ai_provider", "claude")
    api_key = dbmod.get_setting(conn, "ai_api_key", "")
    model = dbmod.get_setting(conn, "ai_model", "claude-haiku-4-5-20251001")
    try:
        trainer_chat.get_initial_recommendation(conn, pid, provider, api_key, model)
    except (ValueError, ConnectionError) as e:
        flash(str(e), "ai_error")
    conn.close()
    return redirect(url_for("progress_view"))


@app.route("/api/trainer_chat/send", methods=["POST"])
def api_trainer_chat_send():
    conn = get_conn()
    pid = current_profile_id()
    provider = dbmod.get_setting(conn, "ai_provider", "claude")
    api_key = dbmod.get_setting(conn, "ai_api_key", "")
    model = dbmod.get_setting(conn, "ai_model", "claude-haiku-4-5-20251001")
    message = request.get_json(force=True).get("message", "").strip()
    if not message:
        conn.close()
        return jsonify({"error": "Empty message"}), 400
    try:
        reply = trainer_chat.continue_conversation(conn, pid, provider, api_key, model, message)
        conn.close()
        return jsonify({"reply": reply})
    except (ValueError, ConnectionError) as e:
        conn.close()
        return jsonify({"error": str(e)}), 400


@app.route("/progress/ai_clear", methods=["POST"])
def progress_ai_clear():
    conn = get_conn()
    pid = current_profile_id()
    trainer_chat.clear_conversation(conn, pid)
    conn.close()
    return redirect(url_for("progress_view"))


@app.route("/assessment/edit/<int:assessment_id>", methods=["POST"])
def assessment_edit(assessment_id):
    conn = get_conn()
    pid = current_profile_id()
    reps = request.form.get("reps")
    hold = request.form.get("hold_seconds")
    weight = request.form.get("weight_kg")
    try:
        assess_mod.update_assessment(
            conn, pid, assessment_id,
            reps=int(reps) if reps else None,
            hold_seconds=float(hold) if hold else None,
            weight_kg=float(weight) if weight else None,
        )
    except ValueError:
        pass
    conn.close()
    return redirect(url_for("progress_view"))


@app.route("/assessment/delete/<int:assessment_id>", methods=["POST"])
def assessment_delete(assessment_id):
    conn = get_conn()
    pid = current_profile_id()
    try:
        assess_mod.delete_assessment(conn, pid, assessment_id)
    except ValueError:
        pass
    conn.close()
    return redirect(url_for("progress_view"))


@app.route("/profile", methods=["GET", "POST"])
def profile_view():
    conn = get_conn()
    pid = current_profile_id()
    if request.method == "POST":
        dbmod.update_profile(
            conn, pid, request.form.get("name", ""), request.form.get("gender", ""),
            int(request.form.get("age")) if request.form.get("age") else None,
            float(request.form.get("weight_kg")) if request.form.get("weight_kg") else None,
            float(request.form.get("height_cm")) if request.form.get("height_cm") else None,
        )
    profile = dbmod.get_profile(conn, pid)
    conn.close()
    return render_template("profile.html", profile=profile)


@app.route("/calendar")
def calendar_view():
    conn = get_conn()
    pid = current_profile_id()
    weeks = scheduler.get_all_weeks(conn, pid, PLAN_NAME)
    week_numbers = [w["week_number"] for w in weeks]
    selected_week = request.args.get("week", type=int) or (week_numbers[0] if week_numbers else None)
    plan = scheduler.get_schedule(conn, pid, PLAN_NAME, week_number=selected_week) if weeks else []
    for day in plan:
        for item in day["items"]:
            item["watch_url"] = resolve_watch_url(conn, item["exercise"])
        day["session"] = progression.get_session_for_day(conn, pid, day["id"])

    sorted_weeks = sorted(week_numbers)
    prev_week, next_week = None, None
    if selected_week in sorted_weeks:
        idx = sorted_weeks.index(selected_week)
        prev_week = sorted_weeks[idx - 1] if idx > 0 else None
        next_week = sorted_weeks[idx + 1] if idx < len(sorted_weeks) - 1 else None
    conn.close()
    return render_template("calendar.html", weeks=weeks, plan=plan, selected_week=selected_week,
                            prev_week=prev_week, next_week=next_week)


@app.route("/calendar/session_set/edit/<int:set_id>", methods=["POST"])
def calendar_edit_set(set_id):
    conn = get_conn()
    pid = current_profile_id()
    reps = request.form.get("reps_done")
    hold = request.form.get("hold_done")
    week = request.form.get("week", type=int)
    try:
        progression.update_session_set(conn, pid, set_id,
                                        reps_done=int(reps) if reps else None,
                                        hold_done=float(hold) if hold else None)
    except ValueError:
        pass
    conn.close()
    return redirect(url_for("calendar_view", week=week))


@app.route("/calendar/session_set/delete/<int:set_id>", methods=["POST"])
def calendar_delete_set(set_id):
    conn = get_conn()
    pid = current_profile_id()
    week = request.form.get("week", type=int)
    try:
        progression.delete_session_set(conn, pid, set_id)
    except ValueError:
        pass
    conn.close()
    return redirect(url_for("calendar_view", week=week))


@app.route("/calendar/session/delete/<int:session_id>", methods=["POST"])
def calendar_delete_session(session_id):
    conn = get_conn()
    pid = current_profile_id()
    week = request.form.get("week", type=int)
    try:
        progression.delete_session(conn, pid, session_id)
    except ValueError:
        pass
    conn.close()
    return redirect(url_for("calendar_view", week=week))


# ---------------------------------------------------------------------------
# Library (shared across all profiles - it's reference content, not personal data)
# ---------------------------------------------------------------------------
@app.route("/library")
def library_view():
    conn = get_conn()
    categories = ["all"] + library.filter_categories()
    category = request.args.get("category", "all")
    tier = request.args.get("tier", "all")
    type_ = request.args.get("type", "all")

    exercises = library.list_exercises_for_filter(
        conn,
        category=None if category == "all" else category,
        tier=None if tier == "all" else int(tier),
    )
    for e in exercises:
        e["role_label"], e["role_class"] = library.classify_role(e)
    exercises = library.filter_by_role(exercises, type_)

    related = []
    if category in library.MUSCLE_GROUP_CATEGORIES:
        related = library.get_related_prep_exercises(conn, category)
        if tier != "all":
            related = [e for e in related if e["tier"] == int(tier)]
        for e in related:
            e["role_label"], e["role_class"] = library.classify_role(e)
        related = library.filter_by_role(related, type_)

    detail_id = request.args.get("exercise")
    detail = None
    watch_url = None
    if detail_id:
        detail = library.get_exercise(conn, detail_id)
        if detail:
            detail["siblings"] = library.get_rotation_siblings(conn, detail_id)
            detail["role_label"], detail["role_class"] = library.classify_role(detail)
            watch_url = resolve_watch_url(conn, detail)
    conn.close()
    return render_template("library.html", categories=categories, category=category, tier=tier,
                            type_=type_, exercises=exercises, detail=detail, watch_url=watch_url,
                            category_labels=library.CATEGORY_LABELS, related=related)


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------
@app.route("/schedule")
def schedule_view():
    conn = get_conn()
    pid = current_profile_id()
    plan = scheduler.get_schedule(conn, pid, PLAN_NAME)
    for day in plan:
        for item in day["items"]:
            item["watch_url"] = resolve_watch_url(conn, item["exercise"])
    all_exercises = library.list_exercises(conn)
    week_number = plan[0]["week_number"] if plan else 1
    conn.close()
    return render_template("schedule.html", plan=plan, all_exercises=all_exercises, week_number=week_number)


@app.route("/schedule/generate", methods=["POST"])
def schedule_generate():
    conn = get_conn()
    pid = current_profile_id()
    days = int(request.form.get("days", 4))
    extra_shoulder = request.form.get("extra_shoulder") == "on"
    extra_hip = request.form.get("extra_hip") == "on"
    scheduler.generate_schedule(conn, pid, days, plan_name=PLAN_NAME,
                                 extra_shoulder_mobility=extra_shoulder, extra_hip_mobility=extra_hip)
    conn.close()
    return redirect(url_for("schedule_view"))


@app.route("/schedule/regenerate", methods=["POST"])
def schedule_regenerate():
    """Redo THIS week with fresh picks - doesn't advance to a new week."""
    conn = get_conn()
    pid = current_profile_id()
    extra_shoulder = request.form.get("extra_shoulder") == "on"
    extra_hip = request.form.get("extra_hip") == "on"
    try:
        scheduler.regenerate_current_week(conn, pid, plan_name=PLAN_NAME,
                                           extra_shoulder_mobility=extra_shoulder, extra_hip_mobility=extra_hip)
    except ValueError:
        pass  # nothing to regenerate yet - fine, just no-op
    conn.close()
    return redirect(url_for("schedule_view"))


@app.route("/schedule/delete_week", methods=["POST"])
def schedule_delete_week():
    conn = get_conn()
    pid = current_profile_id()
    week_number = request.form.get("week_number", type=int)
    if week_number:
        scheduler.delete_week(conn, pid, week_number, plan_name=PLAN_NAME)
    conn.close()
    return redirect(url_for("schedule_view"))


@app.route("/schedule/swap/<int:item_id>", methods=["POST"])
def schedule_swap(item_id):
    conn = get_conn()
    new_exercise_id = request.form.get("new_exercise_id")
    scheduler.swap_schedule_item(conn, item_id, new_exercise_id)
    conn.close()
    return redirect(url_for("schedule_view"))


@app.route("/schedule/remove/<int:item_id>", methods=["POST"])
def schedule_remove(item_id):
    conn = get_conn()
    scheduler.remove_schedule_item(conn, item_id)
    conn.close()
    return redirect(url_for("schedule_view"))


@app.route("/schedule/add/<int:day_id>", methods=["POST"])
def schedule_add(day_id):
    conn = get_conn()
    exercise_id = request.form.get("exercise_id")
    role = request.form.get("role", "extra")
    scheduler.add_schedule_item(conn, day_id, exercise_id, role=role)
    conn.close()
    return redirect(url_for("schedule_view"))


@app.route("/api/exercises")
def api_exercises():
    """Used by the swap/add picker dropdowns (AJAX)."""
    conn = get_conn()
    category = request.args.get("category")
    exercises = library.list_exercises(conn, category=category if category else None)
    conn.close()
    return jsonify([{"id": e["id"], "name": e["name"], "tier": e["tier"]} for e in exercises])


# ---------------------------------------------------------------------------
# Train (with guided work/rest timer)
# ---------------------------------------------------------------------------
@app.route("/train")
def train_view():
    conn = get_conn()
    pid = current_profile_id()
    plan = scheduler.get_schedule(conn, pid, PLAN_NAME)
    day_index = int(request.args.get("day", 0))
    day = plan[day_index] if plan and day_index < len(plan) else None
    if day:
        for item in day["items"]:
            item["watch_url"] = resolve_watch_url(conn, item["exercise"])
            item["timer"] = scheduler.get_timer_params(item)
    session_id = flask_session.get("active_session_id")
    conn.close()
    return render_template("train.html", plan=plan, day=day, day_index=day_index, session_id=session_id)


@app.route("/api/train/start", methods=["POST"])
def api_train_start():
    conn = get_conn()
    pid = current_profile_id()
    data = request.get_json(force=True)
    sid = progression.start_session(conn, pid, day_type=data.get("day_type"),
                                      schedule_day_id=data.get("schedule_day_id"))
    flask_session["active_session_id"] = sid
    conn.close()
    return jsonify({"session_id": sid})


@app.route("/api/train/complete", methods=["POST"])
def api_train_complete():
    conn = get_conn()
    sid = flask_session.get("active_session_id")
    if sid:
        progression.complete_session(conn, sid)
        flask_session.pop("active_session_id", None)
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/train/log_set", methods=["POST"])
def api_train_log_set():
    conn = get_conn()
    data = request.get_json(force=True)
    sid = flask_session.get("active_session_id")
    if not sid:
        conn.close()
        return jsonify({"error": "No active session"}), 400
    fb = progression.log_set(
        conn, sid, data["exercise_id"], data["set_number"], data["target_low"], data["target_high"],
        reps_done=data.get("reps_done"), hold_done=data.get("hold_done"),
    )
    conn.close()
    return jsonify(fb)


# ---------------------------------------------------------------------------
# Chat (shared between all profiles on this deployment - intentionally
# NOT profile-scoped, since the point is for everyone to see each other)
# ---------------------------------------------------------------------------
@app.route("/chat", methods=["GET", "POST"])
def chat_view():
    conn = get_conn()
    pid = current_profile_id()
    if request.method == "POST":
        message = request.form.get("message", "")
        chat_mod.send_message(conn, pid, message)
    messages = chat_mod.get_messages(conn)
    conn.close()
    return render_template("chat.html", messages=messages, my_profile_id=pid)


@app.route("/api/chat/messages")
def api_chat_messages():
    conn = get_conn()
    since_id = request.args.get("since", 0, type=int)
    messages = chat_mod.get_messages_since(conn, since_id)
    conn.close()
    return jsonify(messages)


@app.route("/api/chat/send", methods=["POST"])
def api_chat_send():
    conn = get_conn()
    pid = current_profile_id()
    data = request.get_json(force=True)
    chat_mod.send_message(conn, pid, data.get("message", ""))
    conn.close()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Settings (app-wide password/language shared; backup is per-active-profile)
# ---------------------------------------------------------------------------
@app.route("/settings/export")
def settings_export():
    conn = get_conn()
    pid = current_profile_id()
    data = backup_mod.export_backup(conn, pid)
    conn.close()
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=trainer-backup-{dbmod.today_str()}.json"},
    )


@app.route("/settings/export_all")
def settings_export_all():
    """Downloads everyone's data at once, plus the chat log - the same
    content as the automatic safety-net file, on demand."""
    conn = get_conn()
    data = backup_mod.export_all_profiles(conn)
    conn.close()
    return Response(
        json.dumps(data, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=trainer-ALL-PROFILES-backup-{dbmod.today_str()}.json"},
    )


@app.route("/settings/import", methods=["POST"])
def settings_import():
    conn = get_conn()
    pid = current_profile_id()
    file = request.files.get("backup_file")
    if not file:
        conn.close()
        return redirect(url_for("settings_view"))
    try:
        data = json.load(file.stream)
        backup_mod.import_backup(conn, pid, data)
    except Exception as e:
        conn.close()
        return render_template("settings.html", current=_current_settings(conn), import_error=str(e))
    conn.close()
    return redirect(url_for("dashboard"))


def _current_settings(conn):
    return {
        "interval": dbmod.get_setting(conn, "reassessment_interval_days", "60"),
        "ai_provider": dbmod.get_setting(conn, "ai_provider", "claude"),
        "ai_api_key": dbmod.get_setting(conn, "ai_api_key", ""),
        "ai_model": dbmod.get_setting(conn, "ai_model", "claude-haiku-4-5-20251001"),
        "language": dbmod.get_setting(conn, "language", "en"),
    }


@app.route("/settings", methods=["GET", "POST"])
def settings_view():
    conn = get_conn()
    password_error = None
    if request.method == "POST":
        if "change_password" in request.form:
            current = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            stored_hash = dbmod.get_setting(conn, "app_password_hash", "")
            if stored_hash and not check_password_hash(stored_hash, current):
                password_error = "Current password is incorrect."
            elif len(new_pw) < 4:
                password_error = "New password must be at least 4 characters."
            else:
                dbmod.set_setting(conn, "app_password_hash", generate_password_hash(new_pw))
        else:
            dbmod.set_setting(conn, "reassessment_interval_days", request.form.get("interval", "60"))
            dbmod.set_setting(conn, "ai_provider", request.form.get("ai_provider", "claude"))
            dbmod.set_setting(conn, "ai_api_key", request.form.get("ai_api_key", ""))
            dbmod.set_setting(conn, "ai_model", request.form.get("ai_model", "claude-haiku-4-5-20251001"))
            dbmod.set_setting(conn, "language", request.form.get("language", "en"))

    current = _current_settings(conn)
    conn.close()
    return render_template("settings.html", current=current, password_error=password_error)


def create_app():
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    dbmod.init_db(data_dir=data_dir)
    app.secret_key = _init_secret_key()
    return app


# Runs at import time, not just when executed directly - this matters
# because real hosting (PythonAnywhere, Render, gunicorn, etc.) imports
# `app` via WSGI and never executes the __main__ block below, so the
# database would otherwise never get created on a real deployment.
create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
