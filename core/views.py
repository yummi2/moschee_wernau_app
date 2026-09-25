from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from .models import Profile, Assignment, AssignmentCompletion, Absence, ClassRoom, ChecklistItem, StudentChecklist, WeeklyBanner, TeacherNote, StoryRead, PrayerStatus, RamadanItemDone, QuizScore, TeacherPointAward, LiveCompetition, LiveCompetitionGame, LiveCompetitionParticipant, LiveCompetitionAnswer, DailyQuranReading, StudentPointActivity
from .points import point_balances, student_users
from .parent_points import check_parent_pin, expire_pending_activities, queue_point_activity, rollback_point_activity, set_parent_pin
from .forms import ProfileForm
from django.contrib import messages
import calendar
import datetime as dt
from zoneinfo import ZoneInfo
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, Http404, StreamingHttpResponse
from django.utils import timezone 
import json
from django.conf import settings
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import Q
from .forms import WeeklyBannerForm
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from .ramadan_data import RAMADAN_CONTENT, RAMADAN_ITEMS_META, RAMADAN_ITEMS_ORDER
from django.shortcuts import render
from .stories_data import STORIES
from .fiqh_questions import FIQH_QUESTIONS_ADVANCED
from .ramadan_translations import FIQH_QUESTIONS_DE, ISLAM_QUESTIONS_DE
import math
from .islam_questions import ISLAM_QUESTIONS
from .drawing_links import DRAWING_LINKS_VIEW, DRAWING_LINKS_DOWNLOAD
from django.db.models import Count, Max
from django.core.mail import EmailMessage
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from google.oauth2 import service_account
from googleapiclient.discovery import build
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

LIVE_COMPETITION_TEAM_NAMES = {
    "A": "دعاة المستقبل",
    "B": "صانعات الأمل",
}

DRIVE_LIBRARY_FILES = {
    "rashidi_part": "1MwkfiHsx1qEkTztTb1g66wQ_ECUZ1ZYW",
    "first_quran_reflection": "1-2pyb5N_HX4MAlmNk_76KqsVZxKvREPk",
}

LIBRARY_BOOK_IDS = {
    "missed_prayer",
    "forty_nawawi",
    "charity_types",
    "rashidi_part",
    "first_quran_reflection",
}

REGISTRATION_COLUMNS = [
    ("submitted_at", "تاريخ الإرسال"),
    ("last_name", "اسم العائلة"),
    ("first_name", "الاسم الأول"),
    ("school_class", "الصف"),
    ("birth_date", "تاريخ الميلاد"),
    ("address", "العنوان"),
    ("phone_numbers", "أرقام الهاتف"),
    ("parent_email", "البريد الإلكتروني لولي الأمر"),
    ("photo_permission", "السماح بالتصوير"),
    ("program", "نوع التسجيل"),
]

REGISTRATION_VALUE_LABELS = {
    "yes": "نعم",
    "no": "لا",
    "arabic_and_religion": "عربي وديانة",
    "religion_only": "ديانة",
    "arabic_only": "عربي",
}


def _append_registration_to_google_sheet(data):
    credentials = service_account.Credentials.from_service_account_file(
        settings.GOOGLE_SHEETS_CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    spreadsheet_id = settings.GOOGLE_REGISTRATION_SPREADSHEET_ID
    metadata = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties(title)",
    ).execute()
    sheet_title = metadata["sheets"][0]["properties"]["title"]
    safe_title = sheet_title.replace("'", "''")
    sheet_range = f"'{safe_title}'!A:J"
    header_range = f"'{safe_title}'!A1:J1"
    headers = [label for _, label in REGISTRATION_COLUMNS]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=header_range,
        valueInputOption="RAW",
        body={"values": [headers]},
    ).execute()

    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=sheet_range,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[data[key] for key, _ in REGISTRATION_COLUMNS]]},
    ).execute()

ARABIC_BLOCK_MSG = "يمكن وضع علامة الغياب فقط من يوم الجمعة الساعة 10:00 حتى السبت الساعة 10:00."
ARABIC_ALREADY_MARKED = "لقد تم وضع علامة الغياب لهذا اليوم من قبل."
ARABIC_NOT_PURPLE = "لا يمكن وضع علامة الغياب إلا في الأيام المحددة (باللون البنفسجي)."

ACADEMIC_START = dt.date(2025, 9, 1)
ACADEMIC_END_EXCL = dt.date(2026, 9, 1)
SCHOOL_YEAR_CONTENT_CUTOFF = dt.date(2026, 8, 21)
PRAYERS = [
    (1, "الفجر"),
    (2, "الظهر"),
    (3, "العصر"),
    (4, "المغرب"),
    (5, "العشاء"),
]

COLOR_TEACHING = "calendar-teaching"
COLOR_HOLIDAY = "calendar-holiday"
COLOR_EID = "calendar-eid"
COLOR_FINAL = "calendar-final"

def selected_school_year_ranges(request):
    """Return the calendar and prayer limits for the selected school year."""
    from .school_years import can_switch_school_years

    selected_year = request.session.get("school_year", "2027")
    if not can_switch_school_years(request.user):
        selected_year = "2027"
        request.session["school_year"] = "2027"
    if selected_year == "2026":
        return {
            "year": "2026",
            "calendar_start": dt.date(2025, 9, 1),
            "calendar_end": dt.date(2026, 7, 1),
            "prayer_start": dt.date(2025, 9, 1),
            "prayer_end": dt.date(2026, 8, 31),
        }
    return {
        "year": "2027",
        "calendar_start": dt.date(2026, 9, 1),
        "calendar_end": dt.date(2027, 7, 1),
        "prayer_start": dt.date(2026, 9, 1),
        "prayer_end": dt.date(2027, 8, 31),
    }


class SchoolLoginView(LoginView):
    template_name = "registration/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(settings.SESSION_COOKIE_AGE)
        self.request.session["school_year"] = "2027"
        return response


def registration_information(request):
    if request.method == "POST":
        is_german = request.POST.get("ui_language") == "de"

        def error_response(arabic_message, german_message, status=400):
            return JsonResponse(
                {"ok": False, "message": german_message if is_german else arabic_message},
                status=status,
            )

        required_fields = (
            "last_name", "first_name", "school_class", "birth_date", "street_name",
            "house_number", "postal_code", "city", "phone_numbers", "parent_email",
            "photo_permission", "program",
        )
        data = {field: request.POST.get(field, "").strip() for field in required_fields}
        if any(not data[field] for field in required_fields):
            return error_response("يرجى تعبئة جميع الحقول المطلوبة.", "Bitte füllen Sie alle Pflichtfelder aus.")
        if not data["house_number"].isdigit() or not data["postal_code"].isdigit():
            return error_response(
                "يجب أن يحتوي رقم المنزل والرمز البريدي على أرقام فقط.",
                "Hausnummer und PLZ dürfen nur Ziffern enthalten.",
            )
        if len(data["postal_code"]) != 5:
            return error_response(
                "يجب أن يتكون الرمز البريدي من 5 أرقام.",
                "Die PLZ muss genau fünf Ziffern enthalten.",
            )
        try:
            validate_email(data["parent_email"])
        except ValidationError:
            return error_response("يرجى إدخال بريد إلكتروني صحيح.", "Bitte geben Sie eine gültige E-Mail-Adresse ein.")
        arabic_digits = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        phone_numbers = [
            part.strip().replace(" ", "").translate(arabic_digits)
            for part in data["phone_numbers"].replace("،", ",").split(",")
        ]
        invalid_phone = any(
            not (number[1:] if number.startswith("+") else number).isdigit()
            or not 7 <= len(number[1:] if number.startswith("+") else number) <= 15
            for number in phone_numbers
        )
        if len(phone_numbers) > 2 or invalid_phone:
            return error_response(
                "يرجى إدخال رقم أو رقمين صحيحين، من 7 إلى 15 رقمًا لكل رقم. يمكن أن يبدأ الرقم بـ 0 أو 0049 أو +49، لكن +49 وحدها ليست رقم هاتف.",
                "Bitte geben Sie höchstens zwei gültige Telefonnummern mit jeweils 7 bis 15 Ziffern ein. Die Nummer darf mit 0, 0049 oder +49 beginnen; +49 allein ist jedoch keine Telefonnummer.",
            )
        if data["photo_permission"] not in {"yes", "no"} or data["program"] not in {
            "arabic_and_religion", "religion_only", "arabic_only"
        }:
            return error_response("يرجى التحقق من خيارات التسجيل.", "Bitte prüfen Sie die ausgewählten Anmeldeoptionen.")
        photo_usage = request.POST.getlist("photo_usage")
        allowed_photo_usage = {"video", "instagram"}
        if data["photo_permission"] == "yes" and (
            not photo_usage or any(value not in allowed_photo_usage for value in photo_usage)
        ):
            return error_response(
                "يرجى اختيار مكان استخدام الصور والفيديوهات.",
                "Bitte wählen Sie aus, wo Fotos und Videos verwendet werden dürfen.",
            )

        data["submitted_at"] = timezone.localtime().strftime("%d.%m.%Y %H:%M")
        data["address"] = f"{data['street_name']} {data['house_number']}, {data['postal_code']} {data['city']}"
        data["phone_numbers"] = ", ".join(phone_numbers)
        if data["photo_permission"] == "yes":
            usage_labels = {"video": "فيديو المدرسة", "instagram": "إنستغرام"}
            data["photo_permission"] = "نعم — " + "، ".join(usage_labels[value] for value in photo_usage)
        else:
            data["photo_permission"] = REGISTRATION_VALUE_LABELS[data["photo_permission"]]
        data["program"] = REGISTRATION_VALUE_LABELS[data["program"]]

        try:
            _append_registration_to_google_sheet(data)
            spreadsheet_url = (
                "https://docs.google.com/spreadsheets/d/"
                f"{settings.GOOGLE_REGISTRATION_SPREADSHEET_ID}/edit"
            )
            email = EmailMessage(
                subject="طلب تسجيل جديد للعام الدراسي 2026/2027",
                body=(
                    "السلام عليكم،\n\n"
                    f"وصل طلب تسجيل جديد للطالب: {data['first_name']} {data['last_name']}.\n"
                    f"البريد الإلكتروني لولي الأمر: {data['parent_email']}\n"
                    "تمت إضافة البيانات إلى جدول التسجيلات:\n"
                    f"{spreadsheet_url}\n"
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.REGISTRATION_NOTIFICATION_EMAIL],
            )
            email.send(fail_silently=False)
        except Exception:
            logger.exception("Could not process registration submission")
            return error_response(
                "تعذر حفظ الطلب أو إرسال الإشعار. يرجى التواصل مع إدارة المدرسة.",
                "Die Anmeldung konnte nicht gespeichert oder die Benachrichtigung nicht gesendet werden. Bitte wenden Sie sich an die Schule.",
                status=503,
            )

        return JsonResponse({"ok": True})

    return render(request, "registration/information.html")

    def get_success_url(self):
        return f"{reverse('home')}?tab=home"
ARABIC_WEEKDAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}
GERMAN_WEEKDAYS = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}
GERMAN_PRAYERS = {
    1: "Fadschr",
    2: "Dhuhr",
    3: "Asr",
    4: "Maghrib",
    5: "Ischa",
}
RAMADAN_START = dt.date(2026, 2, 18)
RAMADAN_DAYS = 30

def get_unlocked_ramadan_day(now=None) -> int:
    tz = ZoneInfo("Europe/Berlin")
    now = (now or timezone.now()).astimezone(tz)
    today = now.date()

    delta = (today - RAMADAN_START).days
    unlocked = delta + 1

    if unlocked < 0:
        return 0

    # letzte 2 Tage zusammen öffnen
    if unlocked >= 29:
        return 30

    return max(0, min(RAMADAN_DAYS, unlocked))

def is_user_teacher(user):
    return user.is_authenticated and ClassRoom.objects.filter(teachers=user).exists()


def assignment_deadline(assignment):
    """Use due_at, or Friday 24:00 of the assignment's creation week."""
    if assignment.due_at:
        return timezone.localtime(assignment.due_at)

    created_at = timezone.localtime(assignment.created_at)
    days_until_saturday = (5 - created_at.weekday()) % 7
    saturday = created_at.date() + dt.timedelta(days=days_until_saturday)
    return timezone.make_aware(
        dt.datetime.combine(saturday, dt.time.min),
        ZoneInfo("Europe/Berlin"),
    )


def assignment_progress(assignments, user, now=None):
    now = timezone.localtime(now or timezone.now())
    assignment_ids = [assignment.pk for assignment in assignments]
    done_ids = set(
        AssignmentCompletion.objects.filter(
            user=user,
            assignment_id__in=assignment_ids,
        ).values_list("assignment_id", flat=True)
    )
    counts = {"completed": 0, "urgent": 0, "missed": 0}

    for assignment in assignments:
        assignment.is_done = assignment.pk in done_ids
        if assignment.is_done:
            assignment.progress_state = "completed"
            counts["completed"] += 1
            continue

        deadline = assignment_deadline(assignment)
        if deadline <= now:
            assignment.progress_state = "missed"
            counts["missed"] += 1
        elif now.weekday() == 4:
            assignment.progress_state = "urgent"
            counts["urgent"] += 1
        else:
            assignment.progress_state = "open"

    return counts

def visible_items_for_student(student, school_year="2027"):
    # Items ohne Classroom-Einschränkung ODER an mindestens eine Klasse des Schülers gebunden
    student_cls_ids = ClassRoom.objects.filter(students=student).values_list('id', flat=True)
    items = ChecklistItem.objects.filter(
        Q(classrooms__isnull=True) | Q(classrooms__id__in=student_cls_ids)
    )
    if school_year == "2027":
        items = items.filter(
            Q(created_at__date__gte=SCHOOL_YEAR_CONTENT_CUTOFF)
            | Q(also_show_in_2027=True)
        )
    else:
        items = items.filter(created_at__date__lt=SCHOOL_YEAR_CONTENT_CUTOFF)
    return items.distinct().order_by('order', 'id')


def checked_item_ids_for_year(student, school_year, item_ids):
    """Use the previous year's state until a separate current-year state exists."""
    item_ids = set(item_ids)
    current_states = dict(
        StudentChecklist.objects.filter(
            student=student,
            school_year=school_year,
            item_id__in=item_ids,
        ).values_list("item_id", "checked")
    )
    checked_ids = {
        item_id for item_id, checked in current_states.items() if checked
    }
    if school_year == "2027":
        inherited_item_ids = item_ids - current_states.keys()
        checked_ids.update(
            StudentChecklist.objects.filter(
                student=student,
                school_year="2026",
                checked=True,
                item_id__in=inherited_item_ids,
            ).values_list("item_id", flat=True)
        )
    return checked_ids


# --- Zeitfenster-Helfer ---
def is_within_window_for_date(target_date: dt.date, now: dt.datetime | None = None) -> bool:
    """Erlaubt Markieren nur zwischen Freitag 10:00 und Samstag 10:00 rund um target_date."""
    tz = ZoneInfo("Europe/Berlin")
    now = (now or timezone.now()).astimezone(tz)
    fri = target_date - dt.timedelta(days=1)
    window_start = dt.datetime.combine(fri, dt.time(10, 0, tzinfo=tz))
    window_end   = dt.datetime.combine(target_date, dt.time(10, 0, tzinfo=tz))
    return window_start <= now < window_end


SPECIAL_DATES = {
        dt.date(2025, 10, 25):  COLOR_HOLIDAY,
        dt.date(2025, 12, 20): COLOR_HOLIDAY,
        dt.date(2025, 12, 27): COLOR_HOLIDAY,
        dt.date(2026, 1, 3): COLOR_HOLIDAY,
        dt.date(2026, 2, 14): COLOR_HOLIDAY,
        dt.date(2026, 2, 28): COLOR_TEACHING,
        dt.date(2026, 3, 7): COLOR_TEACHING,
        dt.date(2026, 3, 14): COLOR_TEACHING,
        dt.date(2026, 3, 21): COLOR_EID,
        dt.date(2026, 4, 4):COLOR_HOLIDAY,
        dt.date(2026, 4, 11):COLOR_HOLIDAY,
        dt.date(2026, 5, 2): COLOR_HOLIDAY,
        dt.date(2026, 5, 16): COLOR_HOLIDAY,
        dt.date(2026, 5, 23): COLOR_HOLIDAY,
        dt.date(2026, 5, 30): COLOR_HOLIDAY,
        dt.date(2026, 6, 6): COLOR_EID,
        dt.date(2026, 7, 25): COLOR_FINAL,


        dt.date(2025, 9, 20): COLOR_TEACHING,
        dt.date(2025, 9, 27): COLOR_TEACHING,
        dt.date(2025, 10, 4): COLOR_TEACHING,
        dt.date(2025, 10, 11): COLOR_TEACHING,
        dt.date(2025, 10, 18): COLOR_TEACHING,
        dt.date(2025, 11, 1): COLOR_TEACHING,
        dt.date(2025, 11, 8): COLOR_TEACHING,
        dt.date(2025, 11, 15): COLOR_TEACHING,
        dt.date(2025, 11, 22): COLOR_TEACHING,
        dt.date(2025, 11, 29): COLOR_TEACHING,
        dt.date(2025, 12, 6): COLOR_TEACHING,
        dt.date(2025, 12, 13): COLOR_TEACHING,
        dt.date(2026, 1, 10): COLOR_TEACHING,
        dt.date(2026, 1, 17): COLOR_TEACHING,
        dt.date(2026, 1, 24): COLOR_TEACHING,
        dt.date(2026, 1, 31): COLOR_TEACHING,
        dt.date(2026, 2, 7): COLOR_TEACHING,
        dt.date(2026, 2, 21): COLOR_TEACHING,
        dt.date(2026, 3, 28): COLOR_TEACHING,
        dt.date(2026, 4, 18): COLOR_TEACHING,
        dt.date(2026, 4, 25): COLOR_TEACHING,
        dt.date(2026, 5, 9): COLOR_TEACHING,
        dt.date(2026, 6, 13): COLOR_TEACHING,
        dt.date(2026, 6, 20): COLOR_TEACHING,
        dt.date(2026, 6, 27): COLOR_TEACHING,
        dt.date(2026, 7, 4): COLOR_TEACHING,
        dt.date(2026, 7, 11): COLOR_TEACHING,
        dt.date(2026, 7, 18): COLOR_TEACHING,

        dt.date(2026, 9, 19): COLOR_TEACHING,
        dt.date(2026, 9, 26): COLOR_TEACHING,
        dt.date(2026, 10, 3): COLOR_TEACHING,
        dt.date(2026, 10, 10): COLOR_TEACHING,
        dt.date(2026, 10, 17): COLOR_TEACHING,
        dt.date(2026, 10, 24): COLOR_TEACHING,

        dt.date(2026, 10, 31): COLOR_HOLIDAY,
        dt.date(2026, 11, 7): COLOR_TEACHING,
        dt.date(2026, 11, 14): COLOR_TEACHING,
        dt.date(2026, 11, 21): COLOR_TEACHING,
        dt.date(2026, 11, 28): COLOR_TEACHING,
        dt.date(2026, 12, 5): COLOR_TEACHING,
        dt.date(2026, 12, 12): COLOR_TEACHING,
        dt.date(2026, 12, 19): COLOR_TEACHING,

        dt.date(2026, 12, 26): COLOR_HOLIDAY,
        dt.date(2027, 1, 2): COLOR_HOLIDAY,
        dt.date(2027, 1, 9): COLOR_HOLIDAY,

        dt.date(2027, 1, 16): COLOR_TEACHING,
        dt.date(2027, 1, 23): COLOR_TEACHING,
        dt.date(2027, 1, 30): COLOR_TEACHING,
        dt.date(2027, 2, 6): COLOR_TEACHING,

        dt.date(2027, 2, 13): COLOR_HOLIDAY,

        dt.date(2027, 2, 20): COLOR_TEACHING,
        dt.date(2027, 2, 27): COLOR_TEACHING,
        dt.date(2027, 3, 6): COLOR_TEACHING,
        dt.date(2027, 3, 13): COLOR_EID,
        dt.date(2027, 3, 20): COLOR_TEACHING,

        dt.date(2027, 3, 27): COLOR_HOLIDAY,
        dt.date(2027, 4, 3): COLOR_HOLIDAY,

        dt.date(2027, 4, 10): COLOR_TEACHING,
        dt.date(2027, 4, 17): COLOR_TEACHING,
        dt.date(2027, 4, 24): COLOR_TEACHING,

        dt.date(2027, 5, 1): COLOR_HOLIDAY,
        dt.date(2027, 5, 8): COLOR_TEACHING,

        dt.date(2027, 5, 15): COLOR_TEACHING,

        dt.date(2027, 5, 22): COLOR_HOLIDAY,
        dt.date(2027, 5, 29): COLOR_HOLIDAY,

        dt.date(2027, 6, 5): COLOR_TEACHING,
        dt.date(2027, 6, 12): COLOR_TEACHING,
        dt.date(2027, 6, 19): COLOR_TEACHING,
        dt.date(2027, 6, 26): COLOR_TEACHING,
        dt.date(2027, 7, 3): COLOR_TEACHING,
        dt.date(2027, 7, 10): COLOR_TEACHING,
        dt.date(2027, 7, 17): COLOR_TEACHING,
        dt.date(2027, 7, 24): COLOR_FINAL,
    }

def is_purple_date(d: dt.date) -> bool:                                           # NEW
    return SPECIAL_DATES.get(d) == COLOR_TEACHING    

def teaching_week_number(week_start: dt.date, week_end: dt.date) -> int | None:
    """Return the teaching-week number within the week date's own school year."""
    school_year_start_year = week_start.year if week_start.month >= 9 else week_start.year - 1
    school_year_start = dt.date(school_year_start_year, 9, 1)
    school_year_end = dt.date(school_year_start_year + 1, 9, 1)
    purple_dates = sorted(
        date for date, css_class in SPECIAL_DATES.items()
        if (
            css_class == COLOR_TEACHING
            and school_year_start <= date < school_year_end
        )
    )
    for number, date in enumerate(purple_dates, start=1):
        if week_start <= date <= week_end:
            return number
    return None


def saturday_week_bounds(day: dt.date) -> tuple[dt.date, dt.date]:
    """Return the Saturday-to-Friday week containing day."""
    saturday = day - dt.timedelta(days=(day.weekday() - 5) % 7)
    return saturday, saturday + dt.timedelta(days=6)

def month_neighbors(year, month):
    first = dt.date(year, month, 1)
    prev_last = first - dt.timedelta(days=1)
    next_first = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return (prev_last.year, prev_last.month), (next_first.year, next_first.month)

# --- Abwesenheit markieren ---
@login_required
def mark_absence(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

     # Payload lesen
    try:
        data = json.loads(request.body.decode("utf-8"))
        date_str = data["date"]  # 'YYYY-MM-DD'
        target_date = dt.date.fromisoformat(date_str)
    except Exception:
        return HttpResponseBadRequest("Bad payload")

    # Nur lila Tage
    if not is_purple_date(target_date):
        return JsonResponse({"error": ARABIC_NOT_PURPLE}, status=400)

    # Zeitfenster Freitag 10:00 -> Samstag 10:00
    if not is_within_window_for_date(target_date):
        return JsonResponse({"error": ARABIC_BLOCK_MSG}, status=400)

    # Speichern (idempotent)
    obj, created = Absence.objects.get_or_create(user=request.user, date=target_date)
    if not created:
        return JsonResponse({"error": ARABIC_ALREADY_MARKED}, status=400)

    return JsonResponse({
        "ok": True,
        "total": Absence.objects.filter(user=request.user).count(),
    })

@login_required
def school_year(request):
    from .school_years import can_switch_school_years

    if request.method == "POST":
        selected_year = request.POST.get("school_year")
        allowed_years = {"2026", "2027"} if can_switch_school_years(request.user) else {"2027"}
        if selected_year in allowed_years:
            request.session["school_year"] = selected_year
            next_url = request.POST.get("next", "")
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                return redirect(next_url)
            return redirect(f"{reverse('home')}?tab=home")

        request.session["school_year"] = "2027"

    return redirect(f"{reverse('home')}?tab=home")


def home(request):
    if not request.user.is_authenticated:
        return redirect("login")

    profile = getattr(request.user, "profile", None)
    has_teacher_role = bool(profile and profile.is_teacher) or request.user.classes_as_teacher.exists()
    has_admin_role = request.user.is_superuser or (request.user.is_staff and not has_teacher_role)
    active_home_tab = request.GET.get("tab", "home")
    if (has_teacher_role or has_admin_role) and active_home_tab == "home":
        return admin_statistics(request)

    banner = WeeklyBanner.objects.order_by("-updated_at").first()
    school_year_ranges = selected_school_year_ranges(request)
   
    assignments = []
    today = dt.date.today()
    if request.GET.get("date"):
        try:
            active_date = dt.date.fromisoformat(request.GET["date"])
        except ValueError:
            active_date = today
    else:
        active_date = today

    active_date = min(
        max(active_date, school_year_ranges["prayer_start"]),
        school_year_ranges["prayer_end"],
    )

    prev_week_date = active_date - dt.timedelta(days=7)
    next_week_date = active_date + dt.timedelta(days=7)

    today_real = dt.date.today()
    weekday_real = today_real.weekday()          # 0=Mo … 6=So
    days_since_sunday_real = (weekday_real + 1) % 7
    current_week_start = today_real - dt.timedelta(days=days_since_sunday_real)
    current_week_end = current_week_start + dt.timedelta(days=6)

    weekday_active = active_date.weekday()
    days_since_sunday = (weekday_active + 1) % 7
    week_start = active_date  - dt.timedelta(days=days_since_sunday)
    
    week_days = []
    for i in range(7):
        d = week_start + dt.timedelta(days=i)
        week_days.append({
            "date": d,
            "weekday_ar": ARABIC_WEEKDAYS[d.weekday()],
            "weekday_de": GERMAN_WEEKDAYS[d.weekday()],
            "day": d.day,
            "month": d.month,
            "in_range": school_year_ranges["prayer_start"] <= d <= school_year_ranges["prayer_end"],
        })

    if request.user.is_authenticated:
        statuses = PrayerStatus.objects.filter(
            user=request.user,
            date__range=(week_days[0]["date"], week_days[-1]["date"])
        )
    else:
        statuses = PrayerStatus.objects.none()
    status_map = {
    (s.prayer, s.date): s.prayed
    for s in statuses
    }

    weekly_prayers = []

    for prayer_key, prayer_name in PRAYERS:
        row = {
            "key": prayer_key,
            "name": prayer_name,
            "name_de": GERMAN_PRAYERS[prayer_key],
            "days": []
        }
        for d in week_days:
            row["days"].append({
                "date": d["date"],
                "weekday_ar": d["weekday_ar"],
                "weekday_de": d["weekday_de"],
                "day": d["day"],
                "month": d["month"],
                "in_range": d["in_range"],
                "prayed": status_map.get((prayer_key, d["date"]), False),
            })

        weekly_prayers.append(row)
    try:
        y = int(request.GET.get("y", today.year))
        m = int(request.GET.get("m", today.month))
    except (TypeError, ValueError):
        y, m = today.year, today.month

    # Monat in 1..12 halten
    if m < 1:
        y, m = y - 1, 12
    elif m > 12:
        y, m = y + 1, 1

    requested_month = dt.date(y, m, 1)
    visible_month = min(
        max(requested_month, school_year_ranges["calendar_start"]),
        school_year_ranges["calendar_end"],
    )
    y, m = visible_month.year, visible_month.month

    if request.user.is_authenticated:
        # Klassen, in denen der User Lehrer/Schüler ist
        teacher_classes = request.user.classes_as_teacher.all()
        student_classes = request.user.classes_as_student.all()

        if teacher_classes.exists() or student_classes.exists():
            assignments = Assignment.objects.filter(
                Q(classroom__in=teacher_classes) | Q(classroom__in=student_classes)
            ).select_related("classroom", "created_by").distinct().order_by("-created_at")
        else:
            assignments = (Assignment.objects
                           .select_related("classroom", "created_by")
                           .order_by("-created_at"))

        if school_year_ranges["year"] == "2027":
            assignments = assignments.filter(created_at__date__gte=SCHOOL_YEAR_CONTENT_CUTOFF)
        else:
            assignments = assignments.filter(created_at__date__lt=SCHOOL_YEAR_CONTENT_CUTOFF)

    assignments = list(assignments)
    assignment_counts = {"completed": 0, "urgent": 0, "missed": 0}
    can_complete_assignments = request.user.is_authenticated and bool(assignments)
    can_mark_assignments = can_complete_assignments and school_year_ranges["year"] == "2027"
    if can_complete_assignments:
        assignment_counts = assignment_progress(assignments, request.user)

    # Group the newest assignments into rows by ISO calendar week.
    assignment_weeks = []
    for assignment in assignments:
        classroom_name = assignment.classroom.name.casefold()
        if "قرآن" in classroom_name:
            assignment.color_key = "violet"
            assignment.icon_key = "quran"
        elif "ديانة" in classroom_name:
            assignment.color_key = "amber"
            assignment.icon_key = "mosque"
        elif "عربي" in classroom_name:
            assignment.color_key = "rose"
            assignment.icon_key = "arabic"
        else:
            assignment.color_key = "blue"
            assignment.icon_key = "assignment"
        assignment_date = timezone.localtime(assignment.created_at).date()
        week_start, week_end = saturday_week_bounds(assignment_date)
        week_key = week_start
        if not assignment_weeks or assignment_weeks[-1]["key"] != week_key:
            assignment_weeks.append({
                "key": week_key,
                "start": week_start,
                "end": week_end,
                "number": teaching_week_number(week_start, week_end),
                "assignments": [],
            })
        assignment_weeks[-1]["assignments"].append(assignment)
   
    special_map = {
        d.day: cls
        for d, cls in SPECIAL_DATES.items()
        if d.year == y and d.month == m
    }

      # lila Tage (klickbar) dieses Monats
    purple_days = {
        d.day for d, cls in SPECIAL_DATES.items()
        if d.year == y and d.month == m and cls == COLOR_TEACHING
    }

    # bereits markierte Abwesenheiten für diesen Monat
    absences = set()
    if request.user.is_authenticated:
        month_start = dt.date(y, m, 1)
        next_first = (month_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        absences = {
            a.date.day for a in Absence.objects.filter(
                user=request.user, date__gte=month_start, date__lt=next_first
            )
        }
    absences_count = len(absences)    

    (py, pm), (ny, nm) = month_neighbors(y, m)
    weeks = calendar.monthcalendar(y, m)
    absences_total = 0
    if request.user.is_authenticated:
        absences_total = Absence.objects.filter(
            user=request.user,
            date__gte=ACADEMIC_START,
            date__lt=ACADEMIC_END_EXCL,
        ).count()

    # Kontext IMMER zusammenbauen
    ctx = {
        "banner": banner,
        "assignments": assignments, 
        "assignment_weeks": assignment_weeks,
        "assignment_counts": assignment_counts,
        "show_assignment_stats": request.session.get("school_year", "2027") == "2027",
        "selected_school_year": school_year_ranges["year"],
        "can_complete_assignments": can_complete_assignments,
        "can_mark_assignments": can_mark_assignments,
        "week_days": week_days,
        "weekly_prayers": weekly_prayers,
        "active_date": active_date,
        "prev_week_date": prev_week_date,
        "next_week_date": next_week_date,
        "has_prev_prayer_week": week_days[0]["date"] > school_year_ranges["prayer_start"],
        "has_next_prayer_week": week_days[-1]["date"] < school_year_ranges["prayer_end"],
        "current_week_start": current_week_start,
        "current_week_end": current_week_end,
        "cal_year": y, "cal_month": m, "cal_weeks": weeks,
        "cal_month_name": calendar.month_name[m],
        "cal_prev_y": (dt.date(y, m, 1) - dt.timedelta(days=1)).year,
        "cal_prev_m": (dt.date(y, m, 1) - dt.timedelta(days=1)).month,
        "cal_next_y": ((dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1)).year,
        "cal_next_m": ((dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1)).month,
        "has_cal_prev": dt.date(y, m, 1) > school_year_ranges["calendar_start"],
        "has_cal_next": dt.date(y, m, 1) < school_year_ranges["calendar_end"],
        "cal_today": today,
        "special_map": special_map, 
        "purple_days": purple_days,
        "absences": absences,
        "absences_total": absences_total,
    }

    if request.user.is_authenticated:
        checklist_items = visible_items_for_student(
            request.user,
            school_year_ranges["year"],
        )
        checklist_item_ids = set(checklist_items.values_list("id", flat=True))
        checked_ids = checked_item_ids_for_year(
            request.user,
            school_year_ranges["year"],
            checklist_item_ids,
        )
        ctx.update({
            "checklist_items": checklist_items,
            "checked_item_ids": checked_ids,
        })

        if is_user_teacher(request.user):
            # Lehrer: eigene Notizen (optional per ?student filtern)
            sel_id = request.GET.get('student')
            selected_student = None
            if sel_id:
                selected_student = User.objects.filter(pk=sel_id).first()
            notes_qs = TeacherNote.objects.filter(teacher=request.user)
            if school_year_ranges["year"] == "2027":
                notes_qs = notes_qs.filter(created_at__date__gte=SCHOOL_YEAR_CONTENT_CUTOFF)
            else:
                notes_qs = notes_qs.filter(created_at__date__lt=SCHOOL_YEAR_CONTENT_CUTOFF)
            if selected_student:
                notes_qs = notes_qs.filter(student=selected_student)

            ctx.update({
                "is_teacher": True,
                "selected_student": selected_student,
                "teacher_notes": notes_qs.select_related("student", "classroom").order_by("-created_at")[:30],
                "active_date": active_date,
                "week_days": week_days,
                "weekly_prayers": weekly_prayers,
            })

        else:
            # Schüler: Notizen an mich + eigene Checkliste
            items = visible_items_for_student(request.user, school_year_ranges["year"])
            item_ids = set(items.values_list("id", flat=True))
            checked_ids = checked_item_ids_for_year(
                request.user,
                school_year_ranges["year"],
                item_ids,
            )

            notes_qs = (TeacherNote.objects
                        .filter(student=request.user)
                        .select_related("teacher", "classroom"))
            if school_year_ranges["year"] == "2027":
                notes_qs = notes_qs.filter(created_at__date__gte=SCHOOL_YEAR_CONTENT_CUTOFF)
            else:
                notes_qs = notes_qs.filter(created_at__date__lt=SCHOOL_YEAR_CONTENT_CUTOFF)
            notes_qs = notes_qs.order_by("-created_at")[:30]

            ctx.update({
                "is_teacher": False,
                "checklist_items": items,
                "checked_item_ids": checked_ids,
                "teacher_notes": notes_qs,
                "active_date": active_date,
                "week_days": week_days,
                "weekly_prayers": weekly_prayers,
            })

    ctx["ramadan_open"] = ramadan_is_open()
    ctx["profile"] = (
        Profile.objects.filter(user=request.user).first()
        if request.user.is_authenticated else None
    )
    show_points_bank = school_year_ranges["year"] == "2027"
    ctx["show_points_bank"] = show_points_bank
    if not has_teacher_role and not has_admin_role:
        if show_points_bank:
            quran_readings = DailyQuranReading.objects.filter(student=request.user)
            quran_completed_today = quran_readings.filter(completed_on=timezone.localdate()).first()
            next_portion_index = min(quran_readings.count() + 1, 1208)
            shown_portion_index = (
                quran_completed_today.portion_index if quran_completed_today else next_portion_index
            )
            ctx["daily_quran"] = {
                "page": (shown_portion_index + 1) // 2,
                "half": 1 if shown_portion_index % 2 else 2,
                "completed_today": bool(quran_completed_today),
                "is_complete": quran_readings.count() >= 1208,
            }
        ctx.update(student_top10_achievements(request.user, school_year_ranges))
        if show_points_bank:
            all_balances = point_balances(student_users().select_related("profile"))
            point_ranking = sorted(
                all_balances.values(),
                key=lambda row: (
                    -row["total_points"],
                    (row["user"].get_full_name().strip() or row["user"].username).casefold(),
                ),
            )
            ctx["point_balance"] = all_balances.get(request.user.id)
            ctx["student_point_rank"] = next(
                (position for position, row in enumerate(point_ranking, start=1) if row["user"].id == request.user.id),
                None,
            )
            ctx["student_point_count"] = len(point_ranking)
            ctx["point_awards"] = (
                TeacherPointAward.objects.filter(student=request.user)
                .select_related("teacher")
                .order_by("-created_at", "-id")
            )
    return render(request, "core/home.html", ctx)


@login_required
@require_POST
def complete_daily_quran(request):
    if selected_school_year_ranges(request)["year"] != "2027":
        return HttpResponseForbidden("Daily Quran reading is only available for 2027.")
    if request.user.is_staff or is_user_teacher(request.user):
        return HttpResponseForbidden("Only students can complete the daily Quran reading.")

    today = timezone.localdate()
    with transaction.atomic():
        student = User.objects.select_for_update().get(pk=request.user.pk)
        readings = DailyQuranReading.objects.filter(student=student)
        if readings.filter(completed_on=today).exists():
            messages.info(request, "Die heutige Koran-Aufgabe wurde bereits erledigt.")
            return redirect(f"{reverse('home')}?tab=home")
        portion_index = (readings.aggregate(last=Max("portion_index"))["last"] or 0) + 1
        if portion_index > 1208:
            messages.info(request, "Der gesamte Koran wurde bereits abgeschlossen.")
            return redirect(f"{reverse('home')}?tab=home")
        reading = DailyQuranReading.objects.create(
            student=student,
            portion_index=portion_index,
            completed_on=today,
        )
        queue_point_activity(
            student=student,
            category="quran",
            source_key=reading.pk,
            activity_date=today,
            label_ar=f"ورد القرآن: الصفحة {reading.page_number}، النصف {'الأول' if reading.half_number == 1 else 'الثاني'}",
            label_de=f"Koranlesung: Seite {reading.page_number}, {'erste' if reading.half_number == 1 else 'zweite'} Hälfte",
        )
    return redirect(f"{reverse('home')}?tab=home&activity_saved=1")


@login_required
@require_POST
def mark_assignment_done(request):
    if selected_school_year_ranges(request)["year"] != "2027":
        return HttpResponseForbidden("Assignment completion is disabled for this school year.")

    try:
        data = json.loads(request.body.decode("utf-8"))
        assignment_id = int(data["assignment_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return HttpResponseBadRequest("Bad payload")

    assignment = get_object_or_404(
        Assignment.objects.select_related("classroom"),
        pk=assignment_id,
    )
    can_access_assignment = (
        request.user.is_superuser
        or assignment.classroom.students.filter(pk=request.user.pk).exists()
        or assignment.classroom.teachers.filter(pk=request.user.pk).exists()
        or Profile.objects.filter(
            user=request.user,
            classroom=assignment.classroom,
        ).exists()
    )
    if not can_access_assignment:
        return HttpResponseForbidden("Kein Zugriff")

    completion, created = AssignmentCompletion.objects.get_or_create(
        user=request.user,
        assignment=assignment,
    )
    if created and not request.user.is_staff and not is_user_teacher(request.user):
        queue_point_activity(
            student=request.user,
            category="assignment",
            source_key=assignment.pk,
            activity_date=timezone.localdate(completion.completed_at),
            label_ar=f"الواجب: {assignment.title}",
            label_de=f"Hausaufgabe: {assignment.title}",
        )
    visible_assignments = list(
        Assignment.objects.filter(
            classroom__students=request.user,
        ).select_related("classroom", "created_by").distinct()
    )
    counts = assignment_progress(visible_assignments, request.user)
    return JsonResponse({"ok": True, "counts": counts, "activity_saved": created})


@login_required
def parent_point_approvals(request):
    if request.user.is_staff or is_user_teacher(request.user):
        return HttpResponseForbidden("Only student accounts have parent approvals.")

    expire_pending_activities(request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "change_pin":
            current_pin = request.POST.get("current_pin", "").strip()
            new_pin = request.POST.get("new_pin", "").strip()
            repeated_pin = request.POST.get("repeat_pin", "").strip()
            language = "de" if request.POST.get("ui_language") == "de" else "ar"
            if not check_parent_pin(request.user, current_pin):
                return redirect(f"{reverse('parent_point_approvals')}?pin_change_error=current")
            if not (new_pin.isdigit() and len(new_pin) == 4):
                return redirect(f"{reverse('parent_point_approvals')}?pin_change_error=format")
            if new_pin != repeated_pin:
                return redirect(f"{reverse('parent_point_approvals')}?pin_change_error=mismatch")
            set_parent_pin(request.user, new_pin)
            messages.success(
                request,
                "Der Eltern-PIN wurde geändert." if language == "de" else "تم تغيير الرقم السري للوالدين.",
            )
        elif action == "confirm_day":
            try:
                activity_date = dt.date.fromisoformat(request.POST.get("date", ""))
            except ValueError:
                return HttpResponseBadRequest("Invalid date")
            entered_pin = request.POST.get("pin", "").strip()
            if not check_parent_pin(request.user, entered_pin):
                return redirect(f"{reverse('parent_point_approvals')}?pin_error={activity_date.isoformat()}")
            StudentPointActivity.objects.filter(
                student=request.user,
                activity_date=activity_date,
                status="pending",
                expires_at__gt=timezone.now(),
            ).update(status="confirmed", confirmed_at=timezone.now())
            if request.POST.get("ui_language") == "de":
                messages.success(request, "Die Aktivitäten wurden bestätigt und die Punkte gutgeschrieben.")
            else:
                messages.success(request, "تم تأكيد الأنشطة وإضافة النقاط.")
        elif action == "remove_item":
            try:
                activity_id = int(request.POST.get("activity_id", ""))
            except ValueError:
                return HttpResponseBadRequest("Invalid activity")
            with transaction.atomic():
                activity = get_object_or_404(
                    StudentPointActivity.objects.select_for_update(),
                    pk=activity_id,
                    student=request.user,
                    status="pending",
                )
                rollback_point_activity(activity)
                activity.status = "rejected"
                activity.save(update_fields=("status",))
            if request.POST.get("ui_language") == "de":
                messages.success(request, "Die Aktivität wurde entfernt.")
            else:
                messages.success(request, "تم حذف النشاط.")
        else:
            return HttpResponseBadRequest("Unknown action")
        return redirect("parent_point_approvals")

    activities = list(
        StudentPointActivity.objects.filter(
            student=request.user,
            status="pending",
            expires_at__gt=timezone.now(),
        ).order_by("-activity_date", "created_at", "id")
    )
    days = []
    for activity in activities:
        if not days or days[-1]["date"] != activity.activity_date:
            days.append({"date": activity.activity_date, "activities": []})
        days[-1]["activities"].append(activity)
    return render(request, "core/parent_point_approvals.html", {
        "approval_days": days,
        "pin_error_date": request.GET.get("pin_error", ""),
        "pin_change_error": request.GET.get("pin_change_error", ""),
    })

@login_required
def calendar_page(request):
    today = dt.date.today()
    school_year_ranges = selected_school_year_ranges(request)
    try:
        year = int(request.GET.get("y", today.year))
        month = int(request.GET.get("m", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month

    if month < 1:
        year, month = year - 1, 12
    elif month > 12:
        year, month = year + 1, 1

    requested_month = dt.date(year, month, 1)
    month_start = min(
        max(requested_month, school_year_ranges["calendar_start"]),
        school_year_ranges["calendar_end"],
    )
    year, month = month_start.year, month_start.month
    next_month = (month_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    previous_month = month_start - dt.timedelta(days=1)

    special_map = {
        day.day: css_class
        for day, css_class in SPECIAL_DATES.items()
        if day.year == year and day.month == month
    }
    purple_days = {
        day.day for day, css_class in SPECIAL_DATES.items()
        if day.year == year and day.month == month and css_class == COLOR_TEACHING
    }
    absences = {
        absence.date.day for absence in Absence.objects.filter(
            user=request.user, date__gte=month_start, date__lt=next_month
        )
    }

    calendar_weeks = calendar.monthcalendar(year, month)
    calendar_weeks.extend([[0] * 7 for _ in range(6 - len(calendar_weeks))])

    return render(request, "core/calendar.html", {
        "banner": WeeklyBanner.objects.order_by("-updated_at").first(),
        "cal_year": year,
        "cal_month": month,
        "cal_month_name": calendar.month_name[month],
        "cal_weeks": calendar_weeks,
        "cal_weekdays": [
            {"ar": "الاثنين", "de": "Montag"},
            {"ar": "الثلاثاء", "de": "Dienstag"},
            {"ar": "الأربعاء", "de": "Mittwoch"},
            {"ar": "الخميس", "de": "Donnerstag"},
            {"ar": "الجمعة", "de": "Freitag"},
            {"ar": "السبت", "de": "Samstag"},
            {"ar": "الأحد", "de": "Sonntag"},
        ],
        "cal_weekday_names": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"],
        "cal_prev_y": previous_month.year,
        "cal_prev_m": previous_month.month,
        "cal_next_y": next_month.year,
        "cal_next_m": next_month.month,
        "has_cal_prev": month_start > school_year_ranges["calendar_start"],
        "has_cal_next": month_start < school_year_ranges["calendar_end"],
        "cal_today": today,
        "special_map": special_map,
        "purple_days": purple_days,
        "absences": absences,
        "absences_total": Absence.objects.filter(
            user=request.user,
            date__gte=school_year_ranges["prayer_start"],
            date__lte=school_year_ranges["prayer_end"],
        ).count(),
        "ramadan_open": ramadan_is_open(),
    })

@login_required
def about(request):
    return render(request, "core/about.html")


def mosque_top10_ranking(school_year_ranges):
    """Rank students who qualify in prayer, library and daily Quran by points."""
    if school_year_ranges["year"] != "2027":
        return []

    students = list(student_users().select_related("profile"))
    student_ids = [student.id for student in students]
    students_by_id = {student.id: student for student in students}
    if not student_ids:
        return []

    def display_name(student):
        return student.get_full_name().strip() or student.username

    prayer_rows = (
        PrayerStatus.objects
        .filter(
            user_id__in=student_ids,
            prayed=True,
            date__range=(school_year_ranges["prayer_start"], school_year_ranges["prayer_end"]),
        )
        .values("user_id", "date__year", "date__month")
        .annotate(total=Count("id"))
    )
    prayer_months = {}
    for row in prayer_rows:
        prayer_months.setdefault((row["date__year"], row["date__month"]), []).append(row)
    prayer_top_ids = set()
    for rows in prayer_months.values():
        prayer_top_ids.update(
            row["user_id"]
            for row in sorted(
                rows,
                key=lambda row: (
                    -row["total"],
                    display_name(students_by_id[row["user_id"]]).casefold(),
                ),
            )[:10]
        )

    library_rows = list(
        StoryRead.objects
        .filter(user_id__in=student_ids)
        .values("user_id")
        .annotate(total=Count("id"))
    )
    library_top_ids = {
        row["user_id"]
        for row in sorted(
            library_rows,
            key=lambda row: (
                -row["total"],
                display_name(students_by_id[row["user_id"]]).casefold(),
            ),
        )[:10]
    }

    quran_rows = list(
        DailyQuranReading.objects
        .filter(
            student_id__in=student_ids,
            completed_on__range=(
                school_year_ranges["prayer_start"],
                school_year_ranges["prayer_end"],
            ),
        )
        .values("student_id")
        .annotate(total=Count("id"))
    )
    quran_top_ids = {
        row["student_id"]
        for row in sorted(
            quran_rows,
            key=lambda row: (
                -row["total"],
                display_name(students_by_id[row["student_id"]]).casefold(),
            ),
        )[:10]
    }

    eligible_ids = prayer_top_ids & library_top_ids & quran_top_ids
    balances = point_balances(students)
    return [
        {
            "user": students_by_id[user_id],
            "name": display_name(students_by_id[user_id]),
            "total_points": balances[user_id]["total_points"],
        }
        for user_id in sorted(
            eligible_ids,
            key=lambda user_id: (
                -balances[user_id]["total_points"],
                display_name(students_by_id[user_id]).casefold(),
            ),
        )[:10]
    ]


def student_top10_achievements(user, school_year_ranges):
    """Return the student's lasting Ramadan, prayer and library Top-10 results."""
    student_filter = Q(user__is_staff=False) & (
        Q(user__profile__is_teacher=False) | Q(user__profile__isnull=True)
    )
    name_cache = {}

    def ranking_name(user_id):
        ranked_user = name_cache.get(user_id)
        if ranked_user is None:
            return ""
        return (ranked_user.get_full_name().strip() or ranked_user.username).casefold()

    ramadan_rows = list(
        RamadanItemDone.objects
        .filter(student_filter, done=True, school_year=school_year_ranges["year"])
        .values("user_id", "day")
        .annotate(done_items=Count("item_key", distinct=True))
    )
    ramadan_totals = {}
    for row in ramadan_rows:
        totals = ramadan_totals.setdefault(row["user_id"], {"days": 0, "items": 0})
        done_items = min(row["done_items"], len(RAMADAN_ITEMS_ORDER))
        totals["items"] += done_items
        if done_items >= len(RAMADAN_ITEMS_ORDER):
            totals["days"] += 1

    prayer_rows = list(
        PrayerStatus.objects
        .filter(
            student_filter,
            prayed=True,
            date__range=(school_year_ranges["prayer_start"], school_year_ranges["prayer_end"]),
        )
        .values("user_id", "date__year", "date__month")
        .annotate(total=Count("id"))
    )
    library_rows = list(
        StoryRead.objects
        .filter(student_filter)
        .values("user_id")
        .annotate(total=Count("id"))
    )
    user_ids = set(ramadan_totals)
    user_ids.update(row["user_id"] for row in prayer_rows)
    user_ids.update(row["user_id"] for row in library_rows)
    name_cache.update(User.objects.filter(id__in=user_ids).in_bulk())

    ramadan_rank = None
    ranked_ramadan = []
    if user.id in ramadan_totals:
        ranked_ramadan = sorted(
            ramadan_totals,
            key=lambda user_id: (
                -ramadan_totals[user_id]["days"],
                -ramadan_totals[user_id]["items"],
                ranking_name(user_id),
            ),
        )[:10]
        if user.id in ranked_ramadan:
            ramadan_rank = ranked_ramadan.index(user.id) + 1

    months = {}
    for row in prayer_rows:
        key = (row["date__year"], row["date__month"])
        months.setdefault(key, []).append(row)

    month_names_de = (
        "", "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    )
    month_names_ar = (
        "", "كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران",
        "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول",
    )
    prayer_top10_months = []
    for (year, month), rows in sorted(months.items(), reverse=True):
        ranked_month = sorted(
            rows,
            key=lambda row: (-row["total"], ranking_name(row["user_id"])),
        )[:10]
        ranked_ids = [row["user_id"] for row in ranked_month]
        if user.id in ranked_ids:
            prayer_top10_months.append({
                "year": year,
                "month": month,
                "month_de": month_names_de[month],
                "month_ar": month_names_ar[month],
                "rank": ranked_ids.index(user.id) + 1,
            })

    library_rank = None
    ranked_library = sorted(
        library_rows,
        key=lambda row: (-row["total"], ranking_name(row["user_id"])),
    )[:10]
    ranked_library_ids = [row["user_id"] for row in ranked_library]
    if user.id in ranked_library_ids:
        library_rank = ranked_library_ids.index(user.id) + 1

    ranked_mosque = mosque_top10_ranking(school_year_ranges)
    mosque_top10 = any(entry["user"].id == user.id for entry in ranked_mosque)

    return {
        "ramadan_top10_rank": ramadan_rank,
        "ramadan_top10_year": school_year_ranges["year"],
        "prayer_top10_months": prayer_top10_months,
        "library_top10_rank": library_rank,
        "mosque_top10": mosque_top10,
    }


@login_required
def admin_statistics(request):
    profile = getattr(request.user, "profile", None)
    is_teacher = bool(profile and profile.is_teacher) or request.user.classes_as_teacher.exists()
    # Lehrkräfte benötigen häufig Staff-Zugriff für den Django-Admin. Das allein
    # darf ihnen aber nicht die schulweite Administrator-Übersicht freischalten.
    is_admin = request.user.is_superuser or (request.user.is_staff and not is_teacher)
    if not is_admin and not is_teacher:
        return HttpResponseForbidden("Diese Seite ist nur für die Verwaltung und Lehrkräfte verfügbar.")

    school_year_ranges = selected_school_year_ranges(request)
    show_points_bank = school_year_ranges["year"] == "2027"
    ramadan_year = school_year_ranges["year"]
    prayer_period = request.GET.get("prayer_period", "week")
    if prayer_period not in {"week", "month"}:
        prayer_period = "week"
    if school_year_ranges["year"] == "2026":
        prayer_period = "month"

    student_filter = Q(user__is_staff=False) & (
        Q(user__profile__is_teacher=False) | Q(user__profile__isnull=True)
    )
    required_ramadan_items = len(RAMADAN_ITEMS_ORDER)
    ramadan_days = []
    if is_admin or is_teacher:
        ramadan_days = (
            RamadanItemDone.objects
            .filter(student_filter, done=True, school_year=ramadan_year)
            .values("user_id", "day")
            .annotate(done_items=Count("item_key", distinct=True))
        )

    ramadan_totals = {}
    for entry in ramadan_days:
        user_total = ramadan_totals.setdefault(
            entry["user_id"], {"completed_days": 0, "completed_items": 0}
        )
        done_items = min(entry["done_items"], required_ramadan_items)
        user_total["completed_items"] += done_items
        if done_items >= required_ramadan_items:
            user_total["completed_days"] += 1

    today = timezone.localdate()
    prayer_reference_date = (
        dt.date(2026, 8, 31)
        if school_year_ranges["year"] == "2026"
        else today
    )
    days_since_sunday = (prayer_reference_date.weekday() + 1) % 7
    prayer_week_start = prayer_reference_date - dt.timedelta(days=days_since_sunday)
    prayer_week_end = min(
        prayer_week_start + dt.timedelta(days=6),
        school_year_ranges["prayer_end"],
    )
    if prayer_period == "month":
        prayer_period_start = prayer_reference_date.replace(day=1)
        prayer_period_end = prayer_reference_date.replace(
            day=calendar.monthrange(prayer_reference_date.year, prayer_reference_date.month)[1]
        )
    else:
        prayer_period_start = prayer_week_start
        prayer_period_end = prayer_week_end

    prayer_totals = []
    if is_admin or is_teacher:
        prayer_totals = list(
            PrayerStatus.objects
            .filter(
                student_filter,
                prayed=True,
                date__range=(prayer_period_start, prayer_period_end),
            )
            .values("user_id")
            .annotate(completed_prayers=Count("id"))
        )

    library_totals = list(
        StoryRead.objects
        .filter(user_id__in=student_users().values("id"))
        .values("user_id")
        .annotate(read_items=Count("id"))
    )

    ranked_user_ids = set(ramadan_totals)
    ranked_user_ids.update(entry["user_id"] for entry in prayer_totals)
    ranked_user_ids.update(entry["user_id"] for entry in library_totals)
    ranked_users = User.objects.filter(id__in=ranked_user_ids).select_related("profile").in_bulk()

    def student_name(user):
        full_name = user.get_full_name().strip()
        return full_name or user.username

    ramadan_ranking = sorted(
        (
            {
                "user": ranked_users[user_id],
                "name": student_name(ranked_users[user_id]),
                **totals,
            }
            for user_id, totals in ramadan_totals.items()
            if user_id in ranked_users
        ),
        key=lambda row: (-row["completed_days"], -row["completed_items"], row["name"].casefold()),
    )[:10]

    prayer_ranking = sorted(
        (
            {
                "user": ranked_users[entry["user_id"]],
                "name": student_name(ranked_users[entry["user_id"]]),
                "completed_prayers": entry["completed_prayers"],
            }
            for entry in prayer_totals
            if entry["user_id"] in ranked_users
        ),
        key=lambda row: (-row["completed_prayers"], row["name"].casefold()),
    )[:10]

    library_ranking = sorted(
        (
            {
                "user": ranked_users[entry["user_id"]],
                "name": student_name(ranked_users[entry["user_id"]]),
                "read_items": entry["read_items"],
            }
            for entry in library_totals
            if entry["user_id"] in ranked_users
        ),
        key=lambda row: (-row["read_items"], row["name"].casefold()),
    )[:10]

    show_assignment_tracking = school_year_ranges["year"] == "2027"
    assignments = Assignment.objects.none()
    if show_assignment_tracking:
        assignment_start = school_year_ranges["calendar_start"]
        assignment_end = school_year_ranges["prayer_end"]
        assignments = Assignment.objects.filter(
            Q(due_at__date__range=(assignment_start, assignment_end))
            | Q(due_at__isnull=True, created_at__date__range=(assignment_start, assignment_end))
        ).select_related("classroom", "created_by").prefetch_related(
            "classroom__students", "completions"
        )
        if not is_admin:
            assignments = assignments.filter(
                classroom__teachers=request.user,
                created_by=request.user,
            ).distinct()
        assignments = assignments.order_by("-due_at", "-created_at", "-id")

    assignment_rows = []
    for assignment in assignments:
        students = [student for student in assignment.classroom.students.all() if not student.is_staff]
        students.sort(key=lambda student: student_name(student).casefold())
        completed_ids = {completion.user_id for completion in assignment.completions.all()}
        completed_students = [
            {"user": student, "name": student_name(student)}
            for student in students if student.id in completed_ids
        ]
        pending_students = [
            {"user": student, "name": student_name(student)}
            for student in students if student.id not in completed_ids
        ]
        assignment_rows.append({
            "assignment": assignment,
            "completed_students": completed_students,
            "pending_students": pending_students,
            "student_count": len(students),
        })

    point_ranking = []
    if show_points_bank:
        all_point_balances = point_balances(student_users().select_related("profile"))
        point_ranking = sorted(
            all_point_balances.values(),
            key=lambda row: (
                -row["total_points"],
                student_name(row["user"]).casefold(),
            ),
        )
        for row in point_ranking:
            row["name"] = student_name(row["user"])

    mosque_ranking = mosque_top10_ranking(school_year_ranges)

    teacher_students = User.objects.none()
    if is_teacher and show_points_bank:
        teacher_students = student_users().select_related("profile")
        teacher_students = sorted(teacher_students, key=lambda user: student_name(user).casefold())

    point_awards = TeacherPointAward.objects.select_related("student", "teacher")
    if is_teacher and not is_admin:
        point_awards = point_awards.filter(teacher=request.user)

    quran_students = list(student_users().select_related("profile"))
    latest_quran_by_student = {}
    quran_counts = {
        row["student_id"]: row["total"]
        for row in DailyQuranReading.objects
        .filter(student_id__in=[student.id for student in quran_students])
        .values("student_id")
        .annotate(total=Count("id"))
    }
    for reading in (
        DailyQuranReading.objects
        .filter(student_id__in=[student.id for student in quran_students])
        .select_related("student")
        .order_by("student_id", "-completed_on", "-completed_at")
    ):
        latest_quran_by_student.setdefault(reading.student_id, reading)
    quran_today = timezone.localdate()
    quran_rows = []
    for student in sorted(quran_students, key=lambda item: student_name(item).casefold()):
        latest = latest_quran_by_student.get(student.id)
        quran_rows.append({
            "student": student,
            "name": student_name(student),
            "latest": latest,
            "total": quran_counts.get(student.id, 0),
            "completed_today": bool(latest and latest.completed_on == quran_today),
        })

    return render(request, "core/admin_statistics.html", {
        "is_admin_statistics": is_admin,
        "ramadan_ranking": ramadan_ranking,
        "ramadan_year": ramadan_year,
        "prayer_ranking": prayer_ranking,
        "library_ranking": library_ranking,
        "mosque_ranking": mosque_ranking,
        "prayer_period": prayer_period,
        "prayer_period_start": prayer_period_start,
        "prayer_period_end": prayer_period_end,
        "assignment_rows": assignment_rows,
        "assignment_school_year": school_year_ranges["year"],
        "show_assignment_tracking": show_assignment_tracking,
        "show_points_bank": show_points_bank,
        "point_ranking": point_ranking,
        "teacher_students": teacher_students,
        "can_award_points": is_teacher,
        "point_awards": point_awards,
        "quran_rows": quran_rows,
        "quran_today": quran_today,
        "profile": profile,
    })


@login_required
@require_POST
def award_student_points(request):
    profile = getattr(request.user, "profile", None)
    is_teacher = bool(profile and profile.is_teacher) or request.user.classes_as_teacher.exists()
    if not is_teacher:
        return HttpResponseForbidden("Nur Lehrkräfte dürfen Punkte vergeben.")

    try:
        student_id = int(request.POST.get("student_id", ""))
        points = int(request.POST.get("points", ""))
    except (TypeError, ValueError):
        messages.error(request, "Bitte Schüler und Punktzahl korrekt auswählen.")
        return redirect("admin_statistics")

    if points < 1 or points > 100:
        messages.error(request, "Die Punktzahl muss zwischen 1 und 100 liegen.")
        return redirect("admin_statistics")

    student = get_object_or_404(
        student_users(),
        pk=student_id,
    )
    reason = request.POST.get("reason", "").strip()[:240]
    TeacherPointAward.objects.create(
        student=student,
        teacher=request.user,
        points=points,
        reason=reason,
    )
    messages.success(request, f"{points} Punkte wurden an {student.get_full_name() or student.username} vergeben.")
    return redirect("admin_statistics")


def _can_manage_live_competition(user):
    profile = getattr(user, "profile", None)
    is_teacher = bool(profile and profile.is_teacher) or user.classes_as_teacher.exists()
    return user.is_superuser or (user.is_staff and not is_teacher)


@login_required
def live_competition_setup(request):
    if not _can_manage_live_competition(request.user):
        return HttpResponseForbidden("Dieser Bereich ist nur für die Verwaltung verfügbar.")

    competition = (
        LiveCompetition.objects
        .filter(is_active=True, questions__isnull=False)
        .prefetch_related("questions")
        .distinct()
        .first()
    )
    students = sorted(
        student_users().select_related("profile"),
        key=lambda student: (student.get_full_name().strip() or student.username).casefold(),
    )
    live_games = LiveCompetitionGame.objects.filter(status="live").select_related("competition")[:5]
    return render(request, "core/live_competition_setup.html", {
        "competition": competition,
        "students": students,
        "live_games": live_games,
    })


@login_required
@require_POST
def live_competition_start(request):
    if not _can_manage_live_competition(request.user):
        return HttpResponseForbidden("Dieser Bereich ist nur für die Verwaltung verfügbar.")

    competition = get_object_or_404(LiveCompetition, pk=request.POST.get("competition_id"), is_active=True)
    if not competition.questions.exists():
        messages.error(request, "Dieser Wettbewerb enthält noch keine Fragen.")
        return redirect("live_competition_setup")

    try:
        team_a_ids = {int(value) for value in request.POST.getlist("team_a")}
        team_b_ids = {int(value) for value in request.POST.getlist("team_b")}
    except (TypeError, ValueError):
        messages.error(request, "Die Gruppenauswahl ist ungültig.")
        return redirect("live_competition_setup")

    if not team_a_ids or not team_b_ids:
        messages.error(request, "Beide Gruppen benötigen mindestens ein Kind.")
        return redirect("live_competition_setup")
    if team_a_ids & team_b_ids:
        messages.error(request, "Ein Kind kann nur in einer Gruppe sein.")
        return redirect("live_competition_setup")

    allowed_students = {
        student.id: student
        for student in student_users().filter(id__in=team_a_ids | team_b_ids)
    }
    if set(allowed_students) != team_a_ids | team_b_ids:
        messages.error(request, "Mindestens ein ausgewählter Benutzer ist kein Schüler.")
        return redirect("live_competition_setup")

    with transaction.atomic():
        game = LiveCompetitionGame.objects.create(
            competition=competition,
            created_by=request.user,
        )
        LiveCompetitionParticipant.objects.bulk_create([
            LiveCompetitionParticipant(
                game=game,
                student=allowed_students[student_id],
                team="A" if student_id in team_a_ids else "B",
            )
            for student_id in sorted(team_a_ids | team_b_ids)
        ])
    return redirect("live_competition_game", game_id=game.id)


@login_required
def live_competition_game(request, game_id):
    if not _can_manage_live_competition(request.user):
        return HttpResponseForbidden("Dieser Bereich ist nur für die Verwaltung verfügbar.")

    game = get_object_or_404(
        LiveCompetitionGame.objects.select_related("competition"),
        pk=game_id,
    )
    questions = list(game.competition.questions.all())
    if not questions:
        messages.error(request, "Dieser Wettbewerb enthält keine Fragen.")
        return redirect("live_competition_setup")

    if request.method == "POST" and game.status == "live":
        action = request.POST.get("action")
        with transaction.atomic():
            locked_game = LiveCompetitionGame.objects.select_for_update().get(pk=game.pk)
            question_index = min(locked_game.current_question_index, len(questions) - 1)
            question = questions[question_index]
            existing_answer = LiveCompetitionAnswer.objects.filter(
                game=locked_game, question=question
            ).first()

            if action == "answer" and not existing_answer:
                if question_index == 0:
                    team = request.POST.get("team")
                else:
                    previous_answer = LiveCompetitionAnswer.objects.filter(
                        game=locked_game,
                        question=questions[question_index - 1],
                    ).first()
                    team = (
                        "B" if previous_answer and previous_answer.team == "A" else
                        "A" if previous_answer and previous_answer.team == "B" else
                        None
                    )
                try:
                    selected_option = int(request.POST.get("selected_option", ""))
                except (TypeError, ValueError):
                    selected_option = 0
                if team not in {"A", "B"} or selected_option not in {1, 2, 3, 4}:
                    messages.error(request, "Bitte Gruppe und Antwort auswählen.")
                else:
                    is_correct = selected_option == question.correct_option
                    LiveCompetitionAnswer.objects.create(
                        game=locked_game,
                        question=question,
                        team=team,
                        selected_option=selected_option,
                        is_correct=is_correct,
                    )
                    if is_correct:
                        if team == "A":
                            locked_game.team_a_score += 1
                        else:
                            locked_game.team_b_score += 1
                        locked_game.save(update_fields=("team_a_score", "team_b_score"))

            elif action == "next" and existing_answer:
                if locked_game.current_question_index < len(questions) - 1:
                    locked_game.current_question_index += 1
                    locked_game.save(update_fields=("current_question_index",))

            elif action == "finish" and existing_answer and locked_game.current_question_index >= len(questions) - 1:
                if locked_game.team_a_score > locked_game.team_b_score:
                    locked_game.winner = "A"
                elif locked_game.team_b_score > locked_game.team_a_score:
                    locked_game.winner = "B"
                else:
                    locked_game.winner = ""

                if not locked_game.winner_points_awarded:
                    point_recipients = LiveCompetitionParticipant.objects.filter(
                        game=locked_game
                    ).select_related("student")
                    if locked_game.winner:
                        def awarded_points(participant):
                            return 3 if participant.team == locked_game.winner else 1

                        def award_reason(participant):
                            result = "Siegergruppe" if participant.team == locked_game.winner else "Teilnahme"
                            team_name = LIVE_COMPETITION_TEAM_NAMES[participant.team]
                            return f"Live-Wettbewerb: {locked_game.competition.title} – {result} {team_name}"
                    else:
                        def awarded_points(participant):
                            return 2

                        def award_reason(participant):
                            return f"Live-Wettbewerb: {locked_game.competition.title} – Unentschieden"
                    TeacherPointAward.objects.bulk_create([
                        TeacherPointAward(
                            student=participant.student,
                            teacher=request.user,
                            points=awarded_points(participant),
                            reason=award_reason(participant),
                        )
                        for participant in point_recipients
                    ])
                    locked_game.winner_points_awarded = True
                locked_game.status = "finished"
                locked_game.finished_at = timezone.now()
                locked_game.save(update_fields=("winner", "winner_points_awarded", "status", "finished_at"))
        return redirect("live_competition_game", game_id=game.id)

    game.refresh_from_db()
    current_index = min(game.current_question_index, len(questions) - 1)
    current_question = questions[current_index]
    current_answer = LiveCompetitionAnswer.objects.filter(
        game=game, question=current_question
    ).first()
    previous_answer = None
    if current_index > 0:
        previous_answer = LiveCompetitionAnswer.objects.filter(
            game=game, question=questions[current_index - 1]
        ).first()
    answering_team = (
        "B" if previous_answer and previous_answer.team == "A" else
        "A" if previous_answer and previous_answer.team == "B" else
        None
    )
    option_rows = [
        {"number": number, "text": text, "is_correct": number == current_question.correct_option}
        for number, text in enumerate(current_question.options, start=1)
    ]
    return render(request, "core/live_competition_game.html", {
        "game": game,
        "current_question": current_question,
        "current_answer": current_answer,
        "option_rows": option_rows,
        "question_number": current_index + 1,
        "question_total": len(questions),
        "is_last_question": current_index == len(questions) - 1,
        "answering_team": answering_team,
        "answering_team_name": LIVE_COMPETITION_TEAM_NAMES.get(answering_team, ""),
        "current_answer_team_name": LIVE_COMPETITION_TEAM_NAMES.get(
            current_answer.team if current_answer else None,
            "",
        ),
        "winner_name": LIVE_COMPETITION_TEAM_NAMES.get(game.winner, ""),
    })


@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

    banner = WeeklyBanner.objects.order_by("-updated_at").first()

    if request.method == "POST":
        # prüfen, welcher Button gedrückt wurde
        if request.POST.get("action") == "delete":
            if profile.avatar:
                profile.avatar.delete(save=False)  # Datei von der Platte löschen
            profile.avatar = None
            profile.save()
            messages.success(request, "تم حذف الصورة بنجاح.")  
            return redirect("home")

        # Speichern
        form = ProfileForm(request.POST, request.FILES, instance=profile)  
        if form.is_valid():
            form.save()
            messages.success(request, "تم حفظ الصورة بنجاح.")  
            return redirect("home")
    else:
        form = ProfileForm(instance=profile)

    # Grund-Kontext
    ctx = {"form": form, "profile": profile, "banner": banner}
    ctx["ramadan_open"] = ramadan_is_open()
    
    return render(request, "core/profile.html", ctx)

@login_required
def assignment_detail(request, pk):
    a = get_object_or_404(Assignment, pk=pk)
    now = timezone.now()
    
    # Rollen im Klassenraum
    is_student = a.classroom.students.filter(id=request.user.id).exists()
    is_teacher = a.classroom.teachers.filter(id=request.user.id).exists()
        
    ctx = {
        "assignment": a,
        "is_teacher": is_teacher,
        "is_student": is_student,
    }
    ctx["ramadan_open"] = ramadan_is_open()
    return render(request, "core/assignment_detail.html", ctx)

    
@login_required
@require_POST
def toggle_check(request):
    # nur Lehrer
    if not getattr(request.user.profile, "is_teacher", False):
        return HttpResponseForbidden("Kein Zugriff")

    try:
        data = json.loads(request.body or '{}')
        student_id = int(data['student_id'])
        item_id    = int(data['item_id'])
        checked    = bool(data['checked'])
    except Exception:
        return HttpResponseBadRequest("Bad payload")

    student = User.objects.filter(pk=student_id, is_active=True).first()
    item    = ChecklistItem.objects.filter(pk=item_id).first()
    if not student or not item:
        return HttpResponseBadRequest("Not found")

    # Lehrer darf nur für Schüler toggeln, die in seiner Klasse sind
    same_class = ClassRoom.objects.filter(teachers=request.user, students=student).exists()
    if not same_class:
        return HttpResponseForbidden("Nicht deine Klasse")

    # Item muss für den Schüler sichtbar sein
    selected_year = selected_school_year_ranges(request)["year"]
    vis_ids = set(visible_items_for_student(student, selected_year).values_list('id', flat=True))
    if item.id not in vis_ids:
        return HttpResponseForbidden("Item für diesen Schüler nicht sichtbar")

    obj, _ = StudentChecklist.objects.get_or_create(
        student=student,
        item=item,
        school_year=selected_year,
    )
    obj.checked = checked
    obj.save()
    done = len(checked_item_ids_for_year(student, selected_year, vis_ids))
    total = len(vis_ids)
    return JsonResponse({"ok": True, "done": done, "total": total})

def admin_required(user):
    return user.is_superuser  

@login_required
@user_passes_test(admin_required)
def set_banner(request):
    if request.method == "POST":
        form = WeeklyBannerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("home")
    else:
        form = WeeklyBannerForm()
    return render(request, "set_banner.html", {"form": form})

def library(request):  
    level = request.GET.get("level")
    sid = request.GET.get("sid") 
    p_str = request.GET.get("p", "1")  
    valid_levels = {"beginner": "المبتدئ", "intermediate": "المتوسط", "advanced": "المتقدم", "books": "الكتب"}
    valid_levels_de = {"beginner": "Anfänger", "intermediate": "Mittelstufe", "advanced": "Fortgeschritten", "books": "Bücher"}
    library_books = [
        {
            "id": "first_quran_reflection",
            "external_only": True,
            "title_ar": "أول مرة أتدبر القرآن",
            "title_de": "Zum ersten Mal denke ich über den Koran nach",
            "url": reverse("library_book_pdf", args=["first_quran_reflection"]),
            "external_url": "https://drive.google.com/file/d/1-2pyb5N_HX4MAlmNk_76KqsVZxKvREPk/view",
        },
        {
            "id": "missed_prayer",
            "external_only": True,
            "title_ar": "فاتتني صلاة",
            "title_de": "Mir ist ein Gebet entgangen",
            "url": "https://res.cloudinary.com/drlpkuf9q/image/upload/v1788892606/%D9%85%D9%83%D8%AA%D8%A8%D8%A9_%D9%83%D8%AA%D9%88%D8%A8%D8%A7%D8%AA%D9%8A_-_%D9%83%D8%AA%D8%A7%D8%A8-%D9%81%D8%A7%D8%AA%D8%AA%D9%86%D9%8A-%D8%B5%D9%84%D8%A7%D8%A9_zqe1km.pdf",
        },
        {
            "id": "forty_nawawi",
            "external_only": True,
            "title_ar": "الأربعون النووية",
            "title_de": "Die vierzig Nawawi-Hadithe",
            "url": "https://res.cloudinary.com/drlpkuf9q/image/upload/%D8%A7%D9%84%D8%A7%D9%94%D8%B1%D8%A8%D8%B9%D9%88%D9%86_%D8%A7%D9%84%D9%86%D9%88%D9%88%D9%8A%D8%A9_ngzepk.pdf",
        },
        {
            "id": "charity_types",
            "external_only": True,
            "title_ar": "أنواع الصدقات",
            "title_de": "Arten der Almosen",
            "url": "https://res.cloudinary.com/drlpkuf9q/image/upload/v1788892605/%D8%A7%D9%94%D9%86%D9%88%D8%A7%D8%B9_%D8%A7%D9%84%D8%B5%D8%AF%D9%82%D8%A7%D8%AA_irtgsa.pdf",
        },
        {
            "id": "rashidi_part",
            "external_only": True,
            "title_ar": "الجزء الرشيدي",
            "title_de": "Der Raschidi-Teil",
            "url": reverse("library_book_pdf", args=["rashidi_part"]),
            "external_url": "https://drive.google.com/file/d/1MwkfiHsx1qEkTztTb1g66wQ_ECUZ1ZYW/view",
        },
    ]
    story_titles_de = {
        "beginner": {
            "1": "Satz 1", "2": "Satz 2", "3": "Satz 3", "4": "Satz 4",
        },
        "intermediate": {
            "1": "Schamhaftigkeit vor Allah",
            "2": "Layla und der Gehorsam gegenüber den Eltern",
            "3": "Umar und sein großzügiger Nachbar",
            "4": "Nur und der Besuch bei ihrer Großmutter",
            "5": "Khalid und der Gast",
            "6": "Yusuf und das richtige Verhalten unterwegs",
            "7": "Maryam und die Tischmanieren",
        },
        "advanced": {
            "1": "Die rechtgeleiteten Kalifen",
            "2": "Abu Bakr as-Siddiq",
            "3": "Umar ibn al-Khattab",
            "4": "Uthman ibn Affan",
            "5": "Ali ibn Abi Talib",
            "6": "Khadidscha bint Chuwailid",
            "7": "Hafsa bint Umar – Mutter der Gläubigen",
            "8": "Zainab, Tochter des Gesandten",
            "9": "Fatima az-Zahra, Tochter Muhammads",
            "10": "Prophet Ibrahim (Friede sei mit ihm)",
            "11": "Prophet Musa (Friede sei mit ihm)",
            "12": "Prophet Yunus (Friede sei mit ihm)",
            "13": "Prophet Yusuf (Friede sei mit ihm)",
            "14": "Maryam (Friede sei mit ihr)",
        },
    }
    
    already_read = False
    if not level:
        return render(request, "core/library.html",  {"level": None, "ramadan_open": ramadan_is_open()})

    if level not in valid_levels:
        return redirect(reverse("library"))

    if level == "books":
        read_book_ids = set()
        if request.user.is_authenticated:
            read_book_ids = set(
                StoryRead.objects.filter(user=request.user, level="books")
                .values_list("sid", flat=True)
            )
        for book in library_books:
            book["already_read"] = book["id"] in read_book_ids
        return render(request, "core/library.html", {
            "level": level,
            "level_title": valid_levels[level],
            "level_title_de": valid_levels_de[level],
            "library_books": library_books,
            "ramadan_open": ramadan_is_open(),
        })

    context = {"level": level}
    if sid:
        story_map = STORIES.get(level, {})
        story = story_map.get(sid)
        if not story:
            return redirect(f"{reverse('library')}?level={level}")
        
        if request.user.is_authenticated:
            already_read = StoryRead.objects.filter(
                user=request.user, level=level, sid=sid
            ).exists()

        # Prev/Next berechnen anhand sortierter numerischer IDs
        try:
            p = int(p_str)
        except ValueError:
            p = 1
        total = max(1, len(story["body"]))
        if p < 1: p = 1
        if p > total: p = total

        # Aktueller Absatz
        raw_para = story["body"][p - 1]

        if isinstance(raw_para, dict):
            current_text  = raw_para.get("text", "")
            current_image = raw_para.get("image")
        else:
            current_text  = str(raw_para)
            current_image = None

        # Prev/Next innerhalb der Geschichte (KEIN Wechsel der Story!)
        prev_href = f"{reverse('library')}?level={level}&sid={sid}&p={p-1}" if p > 1 else None
        next_href = f"{reverse('library')}?level={level}&sid={sid}&p={p+1}" if p < total else None

        return render(request, "core/library.html", {
            "level": level,
            "level_title": valid_levels[level],
            "level_title_de": valid_levels_de[level],
            "sid": sid,
            "story": story,
            "story_title_de": story.get("title_de") or story_titles_de[level].get(sid) or story["title"],
            "p":p,
            "total": total,  
            "current_text": current_text,
            "current_image": current_image,
            "prev_href": prev_href,
            "next_href": next_href,
            "already_read": already_read,
            "ramadan_open": ramadan_is_open()
        })

    sentences = []
    for s_id, s_data in STORIES.get(level, {}).items():
        href = f"{reverse('library')}?level={level}&sid={s_id}"
        sentences.append({
            "title": s_data["title"],
            "title_de": s_data.get("title_de") or story_titles_de[level].get(s_id, s_data["title"]),
            "href": href,
        })

    return render(request, "core/library.html", {
        "level": level,
        "level_title": valid_levels[level],
        "level_title_de": valid_levels_de[level],
        "sentences": sentences,
        "already_read": already_read,
        "ramadan_open": ramadan_is_open()
    })


@login_required
def library_book_pdf(request, book_id):
    """Stream an allow-listed Drive PDF through our own origin for PDF.js."""
    drive_file_id = DRIVE_LIBRARY_FILES.get(book_id)
    if not drive_file_id:
        raise Http404("Unknown library book")

    download_url = f"https://drive.usercontent.google.com/download?id={drive_file_id}&export=download"
    headers = {"User-Agent": "DarAlFarahLibrary/1.0"}
    if request.headers.get("Range"):
        headers["Range"] = request.headers["Range"]

    try:
        remote = urlopen(Request(download_url, headers=headers), timeout=45)
    except (HTTPError, URLError, TimeoutError):
        return JsonResponse({"detail": "The PDF is temporarily unavailable."}, status=502)

    def chunks():
        try:
            while chunk := remote.read(64 * 1024):
                yield chunk
        finally:
            remote.close()

    response = StreamingHttpResponse(
        chunks(),
        status=getattr(remote, "status", 200),
        content_type="application/pdf",
    )
    for header in ("Content-Length", "Content-Range", "Accept-Ranges", "Last-Modified"):
        value = remote.headers.get(header)
        if value:
            response[header] = value
    response["Content-Disposition"] = f'inline; filename="{book_id}.pdf"'
    response["Cache-Control"] = "private, max-age=3600"
    return response

@login_required
@require_POST
def mark_story_read(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        level = str(data["level"])
        sid   = str(data["sid"])
    except Exception:
        return HttpResponseBadRequest("Bad payload")

    valid_story_ids = set(STORIES.get(level, {}))
    if level == "books":
        valid_story_ids = LIBRARY_BOOK_IDS
    if sid not in valid_story_ids:
        return HttpResponseBadRequest("Unknown library item")

    story = STORIES.get(level, {}).get(sid)
    if story and story.get("quiz"):
        return JsonResponse({"ok": False, "error": "Quiz required"}, status=400)

    obj, created = StoryRead.objects.get_or_create(user=request.user, level=level, sid=sid)
    if created and not request.user.is_staff and not is_user_teacher(request.user):
        title_ar = story.get("title") if story else f"كتاب المكتبة ({sid.replace('_', ' ')})"
        title_de = story.get("title_de", title_ar) if story else f"Bibliotheksbuch ({sid.replace('_', ' ')})"
        queue_point_activity(
            student=request.user,
            category="library",
            source_key=f"{level}:{sid}",
            activity_date=timezone.localdate(obj.read_at),
            label_ar=f"قراءة: {title_ar}",
            label_de=f"Gelesen: {title_de}",
        )
    return JsonResponse({"ok": True, "created": created, "activity_saved": created})


@login_required
@require_POST
def submit_story_quiz(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        level = str(data["level"])
        sid = str(data["sid"])
        answers = data["answers"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest("Bad payload")

    story = STORIES.get(level, {}).get(sid)
    quiz = story.get("quiz") if story else None
    if not quiz:
        return HttpResponseBadRequest("Unknown story quiz")
    if not isinstance(answers, list) or len(answers) != len(quiz):
        return HttpResponseBadRequest("Incomplete answers")

    correct_count = sum(
        str(answer) == str(question["correct"])
        for answer, question in zip(answers, quiz)
    )
    if correct_count != len(quiz):
        return JsonResponse({
            "ok": True,
            "passed": False,
            "correct_count": correct_count,
            "total": len(quiz),
        })

    reading, created = StoryRead.objects.get_or_create(
        user=request.user, level=level, sid=sid
    )
    if created and not request.user.is_staff and not is_user_teacher(request.user):
        title_ar = story.get("title", "قصة")
        title_de = story.get("title_de", title_ar)
        queue_point_activity(
            student=request.user,
            category="library",
            source_key=f"{level}:{sid}",
            activity_date=timezone.localdate(reading.read_at),
            label_ar=f"قراءة: {title_ar}",
            label_de=f"Gelesen: {title_de}",
        )
    return JsonResponse({
        "ok": True,
        "passed": True,
        "created": created,
        "activity_saved": created,
        "correct_count": correct_count,
        "total": len(quiz),
    })

@login_required
@require_POST
def toggle_prayer(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        prayer = int(data["prayer"])
        date = dt.date.fromisoformat(data["date"])
    except Exception:
        return HttpResponseBadRequest("Bad payload")

    if prayer not in dict(PRAYERS):
        return HttpResponseBadRequest("Unknown prayer")

    school_year_ranges = selected_school_year_ranges(request)
    if not school_year_ranges["prayer_start"] <= date <= school_year_ranges["prayer_end"]:
        return HttpResponseForbidden("Date is outside the selected school year.")

    today = dt.date.today()
    weekday = today.weekday()
    days_since_sunday = (weekday + 1) % 7
    week_start = today - dt.timedelta(days=days_since_sunday)
    week_end = week_start + dt.timedelta(days=6)

    if not (week_start <= date <= week_end):
        return JsonResponse(
            {"ok": False, "error": "outside_current_week"},
            status=403
        )

    obj, _ = PrayerStatus.objects.get_or_create(
        user=request.user,
        date=date,
        prayer=prayer
    )
    obj.prayed = not obj.prayed
    obj.save()

    full_day = PrayerStatus.objects.filter(
        user=request.user,
        date=date,
        prayed=True,
    ).values("prayer").distinct().count() == 5
    activity_saved = False
    if full_day and not request.user.is_staff and not is_user_teacher(request.user):
        _activity, activity_saved = queue_point_activity(
            student=request.user,
            category="prayer",
            source_key=date.isoformat(),
            activity_date=date,
            label_ar=f"إتمام الصلوات الخمس ليوم {date:%d.%m.%Y}",
            label_de=f"Alle fünf Gebete am {date:%d.%m.%Y}",
        )
    elif not full_day:
        StudentPointActivity.objects.filter(
            student=request.user,
            category="prayer",
            source_key=date.isoformat(),
            status="pending",
        ).update(status="rejected")

    return JsonResponse({"ok": True, "prayed": obj.prayed, "activity_saved": activity_saved})

def ramadan_is_open(now=None) -> bool:
    tz = ZoneInfo("Europe/Berlin")
    now = (now or timezone.now()).astimezone(tz)
    return now.date() >= RAMADAN_START


def ramadan_is_available_for_selected_year(request) -> bool:
    """Ramadan content belongs exclusively to the 2026 school-year view."""
    return selected_school_year_ranges(request)["year"] == "2026"


@login_required
def ramadan_plan(request):
    if not ramadan_is_available_for_selected_year(request):
        return redirect(f"{reverse('home')}?tab=home")
    if not ramadan_is_open():
        messages.error(request, "رمضان لم يبدأ بعد.")
        return redirect("home")

    # Wettbewerb (Tage)
    unlocked_day = get_unlocked_ramadan_day()
    total_days = 30
    selected_year = selected_school_year_ranges(request)["year"]
    completed_items = RamadanItemDone.objects.filter(
        user=request.user,
        school_year=selected_year,
        done=True,
    )
    required_items = len(RAMADAN_ITEMS_ORDER)
    daily_counts = {
        entry["day"]: entry["done_items"]
        for entry in completed_items.values("day").annotate(
            done_items=Count("item_key", distinct=True)
        )
    }
    completed_day_numbers = {
        day for day, count in daily_counts.items()
        if count >= required_items
    }
    completed_days = len(completed_day_numbers)
    day_progress = [
        {
            "day": day,
            "locked": day > unlocked_day,
            "complete": day in completed_day_numbers,
            "done_items": min(daily_counts.get(day, 0), required_items),
            "total_items": required_items,
        }
        for day in range(1, total_days + 1)
    ]

    fiqh_questions_all = FIQH_QUESTIONS_ADVANCED
    page_size = 5

    # Aktivität
    quiz_questions_all = ISLAM_QUESTIONS
    drawing_links_view = DRAWING_LINKS_VIEW
    drawing_links_download = DRAWING_LINKS_DOWNLOAD

    # link Nummer aus GET
    drawing_items = [
    {"n": n, "view_url": drawing_links_view[n], "download_url": drawing_links_download[n]}
    for n in sorted(drawing_links_view.keys())
    ]

    def get_page_param(name: str) -> int:
        try:
            p = int(request.GET.get(name, "1"))
        except ValueError:
            p = 1
        return max(1, p)

    def slice_questions(all_qs: list, p: int):
        pages = max(1, math.ceil(len(all_qs) / page_size))
        p = min(p, pages)
        start = (p - 1) * page_size
        end = start + page_size
        return p, pages, all_qs[start:end]

    # --- Aktuelle Seiten (GET) ---
    p_islam = get_page_param("p_islam")
    p_fiqh  = get_page_param("p_fiqh")

    p_islam, pages_islam, islam_page = slice_questions(quiz_questions_all, p_islam)
    p_fiqh,  pages_fiqh,  fiqh_page  = slice_questions(fiqh_questions_all, p_fiqh)

    def add_german_quiz_text(items, translations):
        localized = []
        for item in items:
            question_de, options_de = translations.get(item["id"], (item["q"], item["opts"]))
            localized.append({
                **item,
                "q_de": question_de,
                "localized_options": [
                    {"ar": option_ar, "de": option_de}
                    for option_ar, option_de in zip(item["opts"], options_de)
                ],
            })
        return localized

    islam_page = add_german_quiz_text(islam_page, ISLAM_QUESTIONS_DE)
    fiqh_page = add_german_quiz_text(fiqh_page, FIQH_QUESTIONS_DE)

    # --- Scores pro Quiz (nur für aktuelle Seite) ---
    islam_score = None
    islam_total = len(islam_page)
    fiqh_score = None
    fiqh_total = len(fiqh_page)

    #Antworten speichern (falls du sie später anzeigen willst)
    islam_user_answers = {}
    fiqh_user_answers = {}

    # --- POST Auswertung: nur die Seite, die abgeschickt wurde ---
    if request.method == "POST":
        quiz_type = request.POST.get("quiz_type")  # "islam" oder "fiqh"

        if quiz_type == "islam":
            try:
                posted_p = int(request.POST.get("p_islam", str(p_islam)))
            except ValueError:
                posted_p = p_islam
            posted_p, _, page_questions = slice_questions(quiz_questions_all, posted_p)

            correct = 0
            for item in page_questions:
                picked = request.POST.get(f"q{item['id']}")
                try:
                    picked_i = int(picked) if picked is not None else None
                except ValueError:
                    picked_i = None
                islam_user_answers[item["id"]] = picked_i
                if picked_i == item["correct"]:
                    correct += 1

            islam_score = correct
            islam_total = len(page_questions)

            QuizScore.objects.update_or_create(
                user=request.user,
                quiz_type="islam",
                page=posted_p,
                defaults={
                    "score": islam_score,
                    "total": islam_total,
                }
            )

            # nach Submit auf derselben Seite bleiben
            p_islam = posted_p
            islam_page = add_german_quiz_text(page_questions, ISLAM_QUESTIONS_DE)

        elif quiz_type == "fiqh":
            try:
                posted_p = int(request.POST.get("p_fiqh", str(p_fiqh)))
            except ValueError:
                posted_p = p_fiqh
            posted_p, _, page_questions = slice_questions(fiqh_questions_all, posted_p)

            correct = 0
            for item in page_questions:
                picked = request.POST.get(f"q{item['id']}")
                try:
                    picked_i = int(picked) if picked is not None else None
                except ValueError:
                    picked_i = None
                fiqh_user_answers[item["id"]] = picked_i
                if picked_i == item["correct"]:
                    correct += 1

            fiqh_score = correct
            fiqh_total = len(page_questions)

            QuizScore.objects.update_or_create(
                user=request.user,
                quiz_type="fiqh",
                page=posted_p,
                defaults={
                    "score": fiqh_score,
                    "total": fiqh_total,
                }
            )

            p_fiqh = posted_p
            fiqh_page = add_german_quiz_text(page_questions, FIQH_QUESTIONS_DE)

    return render(request, "core/ramadan_plan.html", {
        "unlocked_day": unlocked_day,
        "selected_school_year": selected_year,
        "eid_unlocked": unlocked_day >= 29,
        "total_days": total_days,
        "completed_days": completed_days,
        "completion_percent": round((completed_days / total_days) * 100),
        "day_progress": day_progress,

        # Islam (5 pro Seite)
        "quiz_questions": islam_page,
        "islam_score": islam_score,
        "islam_total": islam_total,
        "p_islam": p_islam,
        "pages_islam": pages_islam,

        # Fiqh (5 pro Seite)
        "fiqh_questions": fiqh_page,
        "fiqh_score": fiqh_score,
        "fiqh_total": fiqh_total,
        "p_fiqh": p_fiqh,
        "pages_fiqh": pages_fiqh,

        # drawing
        "drawing_items": drawing_items,
    })


@login_required
def ramadan_day(request, day: int):
    from django.http import Http404

    if not ramadan_is_available_for_selected_year(request):
        return redirect(f"{reverse('home')}?tab=home")
    if not ramadan_is_open():
        messages.error(request, "رمضان لم يبدأ بعد.")
        return redirect("home")
    if day < 1 or day > 30:
        raise Http404("Invalid day")
    unlocked_day = get_unlocked_ramadan_day()
    if day > unlocked_day:
        messages.error(request, "هذا اليوم لم يُفتح بعد.")
        return redirect("ramadan_plan")

    day_data = RAMADAN_CONTENT.get(day, {"title": f"{day} رمضان", "items": {}})
    title = day_data.get("title", f"{day} رمضان")
    title_de = f"Ramadan – Tag {day}"

    # aktives item + seite
    item_key = request.GET.get("item", RAMADAN_ITEMS_ORDER[0])
    if item_key not in RAMADAN_ITEMS_ORDER:
        item_key = RAMADAN_ITEMS_ORDER[0]

    try:
        p = int(request.GET.get("p", "1"))
    except ValueError:
        p = 1

    # done status aus DB
    selected_year = selected_school_year_ranges(request)["year"]
    done_qs = RamadanItemDone.objects.filter(
        user=request.user,
        day=day,
        school_year=selected_year,
        done=True,
    )
    done_keys = set(done_qs.values_list("item_key", flat=True))
    all_done = set(RAMADAN_ITEMS_ORDER).issubset(done_keys)
    is_last_item = (item_key == RAMADAN_ITEMS_ORDER[-1])
    results_href = reverse("ramadan_results")



    # (optional) Karten-Daten – nur wenn du sie im Template noch nutzt
    items = []
    for key in RAMADAN_ITEMS_ORDER:
        it = (day_data.get("items", {}) or {}).get(key, {})
        img = it.get("image") or RAMADAN_ITEMS_META.get(key, {}).get("image")
        items.append({
            "key": key,
            "title": it.get("title") or RAMADAN_ITEMS_META[key]["label_de"],
            "image": img,
            "done": key in done_keys,
            "href": reverse("ramadan_day", args=[day]) + f"?item={key}&p=1",
        })

    # Detail: Inhalt + Pagination
    item_data = (day_data.get("items", {}) or {}).get(item_key, {})
    item_title = item_data.get("title") or RAMADAN_ITEMS_META[item_key]["label_de"]
    item_title_de = RAMADAN_ITEMS_META[item_key]["label_de"]
    body = item_data.get("body") or [{"text": "لا يوجد محتوى بعد."}]

    total = max(1, len(body))
    if p < 1: 
        p = 1
    if p > total: 
        p = total

    #nur wenn letzte Seite (p == total)
    on_last_page = (p == total)
    at_end = is_last_item and on_last_page
    show_success = all_done and at_end

    item_image = item_data.get("image") or RAMADAN_ITEMS_META.get(item_key, {}).get("image")

    raw_para = body[p - 1]
    if isinstance(raw_para, dict):
        current_text = raw_para.get("text", "")
        current_image = raw_para.get("image") or item_image
    else:
        current_text = str(raw_para)
        current_image = item_image

    translated_item_texts = {
        "fasting": "Fasten",
        "quran": "Koran lesen",
        "tarawih_witr": "Das Tarawih-Gebet und anschließend das Witr-Gebet verrichten",
        "good_deed": "Einem Fastenden Iftar geben – spenden – helfen – den Eltern helfen",
    }
    current_text_de = translated_item_texts.get(item_key)

    # --- Story-Navigation ---
    order = RAMADAN_ITEMS_ORDER
    idx = order.index(item_key)

    def total_for(k: str) -> int:
        d = (day_data.get("items", {}) or {}).get(k, {})
        b = d.get("body") or [{"text": "لا يوجد محتوى بعد."}]
        return max(1, len(b))

    # NEXT: wenn letzte Seite -> nächstes Item, sonst nächste Seite
    if p < total:
        next_item_key = item_key
        next_p = p + 1
        next_href = reverse("ramadan_day", args=[day]) + f"?item={next_item_key}&p={next_p}"
    else:
        # letzte Seite dieses Items
        if idx < len(order) - 1:
            next_item_key = order[idx + 1]
            next_p = 1
            next_href = reverse("ramadan_day", args=[day]) + f"?item={next_item_key}&p={next_p}"
        else:
            # letztes Item UND letzte Seite -> deaktivieren
            next_href = None

    # PREV: wenn erste Seite -> vorheriges Item (letzte Seite), sonst vorige Seite
    if p > 1:
        prev_item_key = item_key
        prev_p = p - 1
        prev_href = reverse("ramadan_day", args=[day]) + f"?item={prev_item_key}&p={prev_p}"
    else:
        # erste Seite dieses Items
        if idx > 0:
            prev_item_key = order[idx - 1]
            prev_p = total_for(prev_item_key)
            prev_href = reverse("ramadan_day", args=[day]) + f"?item={prev_item_key}&p={prev_p}"
        else:
            # erstes Item UND erste Seite -> deaktivieren (optional)
            prev_href = None
    already_done = item_key in done_keys

    return render(request, "core/ramadan_day.html", {
        "day": day,
        "title": title,
        "title_de": title_de,

        # falls du Karten nicht mehr nutzt, kannst du "items" entfernen
        "items": items,

        "item_key": item_key,
        "item_title": item_title,
        "item_title_de": item_title_de,

        "p": p,
        "total": total,
        "current_text": current_text,
        "current_text_de": current_text_de,
        "current_image": current_image,

        "prev_href": prev_href,
        "next_href": next_href,

        "already_done": already_done,
        "selected_school_year": selected_year,
        "all_done": all_done,
        "at_end": at_end,
        "is_last_item": is_last_item,
        "show_success": show_success,
        "results_href": results_href,

    })


@login_required
@require_POST
def mark_ramadan_item_done(request):
    selected_year = selected_school_year_ranges(request)["year"]
    if selected_year != "2026":
        return HttpResponseForbidden("Ramadan is disabled for this school year.")

    try:
        data = json.loads(request.body.decode("utf-8"))
        day = int(data["day"])
        item_key = str(data["item_key"])
    except Exception:
        return HttpResponseBadRequest("Bad payload")

    if day < 1 or day > 30:
        return HttpResponseBadRequest("Invalid day")

    if item_key not in RAMADAN_ITEMS_ORDER:
        return HttpResponseBadRequest("Invalid item_key")

    obj, created = RamadanItemDone.objects.get_or_create(
        user=request.user,
        day=day,
        item_key=item_key,
        school_year=selected_year,
        defaults={"done": True}
    )
    if not created and not obj.done:
        obj.done = True
        obj.save()

    completed_item_count = (RamadanItemDone.objects
                            .filter(
                                user=request.user,
                                day=day,
                                school_year=selected_year,
                                done=True,
                                item_key__in=RAMADAN_ITEMS_ORDER,
                            )
                            .values("item_key")
                            .distinct()
                            .count())

    all_done = completed_item_count == len(RAMADAN_ITEMS_ORDER)
    activity_saved = False
    if all_done and not request.user.is_staff and not is_user_teacher(request.user):
        _activity, activity_saved = queue_point_activity(
            student=request.user,
            category="ramadan",
            source_key=f"{selected_year}:{day}",
            activity_date=timezone.localdate(),
            label_ar=f"إتمام جميع مهام اليوم {day} من رمضان",
            label_de=f"Alle Aufgaben von Ramadan-Tag {day}",
        )

    return JsonResponse({
        "ok": True,
        "all_done": all_done,
        "activity_saved": activity_saved,
    })

@login_required
def ramadan_results(request):
    if not ramadan_is_available_for_selected_year(request):
        return redirect(f"{reverse('home')}?tab=home")
    if not ramadan_is_open():
        messages.error(request, "رمضان لم يبدأ بعد.")
        return redirect("home")
        
    TOTAL_DAYS = 30

    selected_year = selected_school_year_ranges(request)["year"]
    completed_items = RamadanItemDone.objects.filter(
        user=request.user,
        school_year=selected_year,
        done=True,
    )

    agg = (completed_items
           .values("item_key")
           .annotate(done_days=Count("day", distinct=True)))

    done_map = {row["item_key"]: row["done_days"] for row in agg}

    rows = []
    for key in RAMADAN_ITEMS_ORDER:
        label = RAMADAN_ITEMS_META.get(key, {}).get("label_ar") \
                or RAMADAN_ITEMS_META.get(key, {}).get("label_de") \
                or key
        done_days = min(done_map.get(key, 0), TOTAL_DAYS)
        rows.append({
            "key": key,
            "label": label,
            "label_de": RAMADAN_ITEMS_META.get(key, {}).get("label_de") or label,
            "done": done_days,
            "total": TOTAL_DAYS,
            "percent": round((done_days / TOTAL_DAYS) * 100) if TOTAL_DAYS else 0,
        })

    required_items = len(RAMADAN_ITEMS_ORDER)
    daily_counts = {
        entry["day"]: entry["done_items"]
        for entry in completed_items.values("day").annotate(
            done_items=Count("item_key", distinct=True)
        )
    }
    completed_day_numbers = {
        day for day, count in daily_counts.items()
        if count >= required_items
    }
    completed_days = len(completed_day_numbers)
    completion_percent = round((completed_days / TOTAL_DAYS) * 100)
    day_progress = [
        {
            "day": day,
            "complete": day in completed_day_numbers,
            "done_items": min(daily_counts.get(day, 0), required_items),
            "total_items": required_items,
        }
        for day in range(1, TOTAL_DAYS + 1)
    ]

    return render(request, "core/ramadan_results.html", {
        "rows": rows,
        "total_days": TOTAL_DAYS,
        "selected_school_year": selected_year,
        "completed_days": completed_days,
        "completion_percent": completion_percent,
        "day_progress": day_progress,
    })
