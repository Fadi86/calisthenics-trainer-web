"""
core/i18n.py — translates UI chrome (nav labels, page titles, buttons)
between English (default) and Arabic. Exercise names, cues, and library
content always stay in English regardless of this setting, per design.
"""
TRANSLATIONS = {
    "nav_home": {"en": "Home", "ar": "الرئيسية"},
    "nav_assess": {"en": "Assess", "ar": "تقييم"},
    "nav_progress": {"en": "Progress", "ar": "التقدم"},
    "nav_library": {"en": "Library", "ar": "المكتبة"},
    "nav_schedule": {"en": "Schedule", "ar": "الجدول"},
    "nav_calendar": {"en": "Calendar", "ar": "التقويم"},
    "nav_train": {"en": "Train", "ar": "التدريب"},
    "nav_health": {"en": "Health", "ar": "الصحة"},
    "nav_settings": {"en": "Settings", "ar": "الإعدادات"},

    "title_dashboard": {"en": "Dashboard", "ar": "لوحة التحكم"},
    "title_assessment": {"en": "Assessment", "ar": "التقييم"},
    "title_progress": {"en": "Progress", "ar": "التقدم"},
    "title_library": {"en": "Exercise Library", "ar": "مكتبة التمارين"},
    "title_schedule": {"en": "Schedule", "ar": "الجدول"},
    "title_calendar": {"en": "Calendar", "ar": "التقويم"},
    "title_train": {"en": "Train", "ar": "التدريب"},
    "title_health": {"en": "Health Data", "ar": "البيانات الصحية"},
    "title_settings": {"en": "Settings", "ar": "الإعدادات"},
    "title_profile": {"en": "Profile", "ar": "الملف الشخصي"},
    "title_login": {"en": "Login", "ar": "تسجيل الدخول"},

    "btn_save": {"en": "Save", "ar": "حفظ"},
    "btn_generate": {"en": "Generate Schedule", "ar": "توليد الجدول"},
    "btn_start_week": {"en": "Start Week", "ar": "بدء أسبوع"},
    "btn_watch": {"en": "Watch", "ar": "شاهد"},
    "btn_print": {"en": "Print / Save as PDF", "ar": "طباعة / حفظ PDF"},
    "btn_login": {"en": "Log In", "ar": "دخول"},
    "btn_logout": {"en": "Log Out", "ar": "خروج"},
    "btn_edit": {"en": "Edit", "ar": "تعديل"},
    "btn_swap": {"en": "Swap", "ar": "استبدال"},
    "btn_remove": {"en": "Remove", "ar": "حذف"},
    "btn_add_exercise": {"en": "+ Add exercise", "ar": "+ إضافة تمرين"},
    "btn_download_backup": {"en": "Download Backup (.json)", "ar": "تنزيل نسخة احتياطية"},
    "btn_load_backup": {"en": "Load Backup", "ar": "استعادة نسخة احتياطية"},
    "btn_run_assessment": {"en": "Run Assessment", "ar": "تنفيذ التقييم"},
    "btn_log_max": {"en": "Log Max", "ar": "تسجيل الحد الأقصى"},
    "btn_start_session": {"en": "Start", "ar": "بدء"},
    "btn_complete_session": {"en": "Complete", "ar": "إنهاء"},
    "btn_log_set": {"en": "Log Set", "ar": "تسجيل المجموعة"},
    "btn_get_feedback": {"en": "Get Feedback", "ar": "احصل على تقييم"},
    "btn_save_metrics": {"en": "Save Metrics", "ar": "حفظ القياسات"},

    "label_days_per_week": {"en": "Days per week", "ar": "أيام الأسبوع"},
    "label_category": {"en": "Category", "ar": "الفئة"},
    "label_tier": {"en": "Tier", "ar": "المستوى"},
    "label_reps": {"en": "Reps", "ar": "العدات"},
    "label_hold": {"en": "Hold (seconds)", "ar": "ثبات (ثانية)"},
    "label_weight": {"en": "Added weight (kg)", "ar": "الوزن المضاف (كغم)"},
    "label_name": {"en": "Name", "ar": "الاسم"},
    "label_gender": {"en": "Gender", "ar": "الجنس"},
    "label_age": {"en": "Age", "ar": "العمر"},
    "label_weight_body": {"en": "Weight (kg)", "ar": "الوزن (كغم)"},
    "label_height": {"en": "Height (cm)", "ar": "الطول (سم)"},
    "label_language": {"en": "Language", "ar": "اللغة"},
    "label_week": {"en": "Week", "ar": "الأسبوع"},

    "gender_male": {"en": "Male", "ar": "ذكر"},
    "gender_female": {"en": "Female", "ar": "أنثى"},

    "weighted_maxes": {"en": "Weighted Strength Maxes", "ar": "أقصى قوة بأوزان إضافية"},
    "last_assessed": {"en": "Last assessed", "ar": "آخر تقييم"},
    "next_due": {"en": "Next due", "ar": "التقييم القادم"},
    "not_tested": {"en": "not tested yet", "ar": "لم يُختبر بعد"},
}


def t(key, lang="en"):
    entry = TRANSLATIONS.get(key)
    if not entry:
        return key
    return entry.get(lang, entry["en"])
