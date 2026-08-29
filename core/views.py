from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from .models import Profile, Assignment, AssignmentCompletion, Absence, ClassRoom, ChecklistItem, StudentChecklist, WeeklyBanner, TeacherNote, StoryRead, PrayerStatus, RamadanItemDone,  QuizScore
from .forms import ProfileForm
from django.contrib import messages
import calendar
import datetime as dt
from zoneinfo import ZoneInfo
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.utils import timezone 
import json
from django.conf import settings
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView
from django.db.models import Q
from .forms import WeeklyBannerForm
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from .ramadan_data import RAMADAN_CONTENT, RAMADAN_ITEMS_META, RAMADAN_ITEMS_ORDER
from django.shortcuts import render
from .stories_data import STORIES
from .fiqh_questions import FIQH_QUESTIONS_ADVANCED
import math
from .islam_questions import ISLAM_QUESTIONS
from .drawing_links import DRAWING_LINKS_VIEW, DRAWING_LINKS_DOWNLOAD
from django.db.models import Count
from django.core.mail import EmailMessage
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

logger = logging.getLogger(__name__)

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
        phone_numbers = [part.strip().replace(" ", "") for part in data["phone_numbers"].replace("،", ",").split(",")]
        if len(phone_numbers) > 2 or any(not number.isdigit() or len(number) > 11 for number in phone_numbers):
            return error_response(
                "يرجى إدخال رقم أو رقمين فقط، وبحد أقصى 11 رقمًا لكل رقم.",
                "Bitte geben Sie höchstens zwei Telefonnummern mit jeweils maximal 11 Ziffern ein.",
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
        items = items.filter(created_at__date__gte=SCHOOL_YEAR_CONTENT_CUTOFF)
    else:
        items = items.filter(created_at__date__lt=SCHOOL_YEAR_CONTENT_CUTOFF)
    return items.distinct().order_by('order', 'id')


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
        dt.date(2027, 5, 8): COLOR_HOLIDAY,

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
    """Return the sequential number only for a week containing a purple teaching date."""
    purple_dates = sorted(
        date for date, css_class in SPECIAL_DATES.items()
        if (
            css_class == COLOR_TEACHING
            and ACADEMIC_START <= date < ACADEMIC_END_EXCL
        )
    )
    for number, date in enumerate(purple_dates, start=1):
        if week_start <= date <= week_end:
            return number
    return None

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

    return JsonResponse({"ok": True})

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
            "days": []
        }
        for d in week_days:
            row["days"].append({
                "date": d["date"],
                "weekday_ar": d["weekday_ar"],
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

        if teacher_classes.exists():
            assignments = Assignment.objects.filter(
                classroom__in=teacher_classes
            ).select_related("classroom", "created_by").order_by("-created_at")
        elif student_classes.exists():
            assignments = Assignment.objects.filter(
                classroom__in=student_classes
            ).select_related("classroom", "created_by").order_by("-created_at")
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
        monday = assignment_date - dt.timedelta(days=assignment_date.weekday())
        week_key = monday.isocalendar()[:2]
        if not assignment_weeks or assignment_weeks[-1]["key"] != week_key:
            assignment_weeks.append({
                "key": week_key,
                "start": monday,
                "end": monday + dt.timedelta(days=6),
                "number": teaching_week_number(monday, monday + dt.timedelta(days=6)),
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
        checked_ids = set(
            StudentChecklist.objects
            .filter(student=request.user, checked=True)
            .values_list("item_id", flat=True)
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
            checked_ids = set(StudentChecklist.objects
                              .filter(student=request.user, checked=True)
                              .values_list('item_id', flat=True))

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
    return render(request, "core/home.html", ctx)


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

    AssignmentCompletion.objects.get_or_create(
        user=request.user,
        assignment=assignment,
    )
    visible_assignments = list(
        Assignment.objects.filter(
            classroom__students=request.user,
        ).select_related("classroom", "created_by").distinct()
    )
    counts = assignment_progress(visible_assignments, request.user)
    return JsonResponse({"ok": True, "counts": counts})

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

    obj, _ = StudentChecklist.objects.get_or_create(student=student, item=item)
    obj.checked = checked
    obj.save()
    done = StudentChecklist.objects.filter(student=student, checked=True, item_id__in=vis_ids).count()
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
    valid_levels = {"beginner": "المبتدئ", "intermediate": "المتوسط", "advanced": "المتقدم"}
    
    already_read = False
    if not level:
        return render(request, "core/library.html",  {"level": None, "ramadan_open": ramadan_is_open()})

    if level not in valid_levels:
        return redirect(reverse("library"))

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
            "sid": sid,
            "story": story,
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
        sentences.append({"title": s_data["title"], "href": href})

    return render(request, "core/library.html", {
        "level": level,
        "level_title": valid_levels[level],
        "sentences": sentences,
        "already_read": already_read,
        "ramadan_open": ramadan_is_open()
    })

@login_required
@require_POST
def mark_story_read(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
        level = str(data["level"])
        sid   = str(data["sid"])
    except Exception:
        return HttpResponseBadRequest("Bad payload")

    obj, created = StoryRead.objects.get_or_create(user=request.user, level=level, sid=sid)
    return JsonResponse({"ok": True, "created": created})

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

    return JsonResponse({"ok": True, "prayed": obj.prayed})

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
            islam_page = page_questions

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
            fiqh_page = page_questions

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

        # falls du Karten nicht mehr nutzt, kannst du "items" entfernen
        "items": items,

        "item_key": item_key,
        "item_title": item_title,

        "p": p,
        "total": total,
        "current_text": current_text,
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

    return JsonResponse({
        "ok": True,
        "all_done": completed_item_count == len(RAMADAN_ITEMS_ORDER),
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
