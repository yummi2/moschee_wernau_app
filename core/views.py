from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import Profile, Assignment
from .forms import ProfileForm
from django.contrib import messages
import calendar
import datetime as dt
from .models import Absence
from zoneinfo import ZoneInfo
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone 
import json
from django.conf import settings

ARABIC_BLOCK_MSG = "يمكن وضع علامة الغياب فقط من يوم الجمعة الساعة 10:00 حتى السبت الساعة 10:00."
ARABIC_ALREADY_MARKED = "لقد تم وضع علامة الغياب لهذا اليوم من قبل."
ARABIC_NOT_PURPLE = "لا يمكن وضع علامة الغياب إلا في الأيام المحددة (باللون البنفسجي)."

ACADEMIC_START = dt.date(2025, 9, 1)
ACADEMIC_END_EXCL = dt.date(2026, 9, 1)
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
        dt.date(2025, 10, 25):  "bg-green-500 text-white",
        dt.date(2025, 12, 20): "bg-green-500 text-white",
        dt.date(2025, 12, 27): "bg-green-500 text-white",
        dt.date(2026, 1, 3): "bg-green-500 text-white",
        dt.date(2026, 2, 14): "bg-green-500 text-white",
        dt.date(2026, 2, 28): "bg-purple-600",
        dt.date(2026, 3, 7): "bg-purple-600",
        dt.date(2026, 3, 14): "bg-purple-600",
        
        dt.date(2026, 3, 21): "bg-blue-300 text-gray-900",

        dt.date(2026, 4, 4):"bg-green-500 text-white",
        dt.date(2026, 4, 11):"bg-green-500 text-white",
        
        dt.date(2026, 5, 2): "bg-green-500 text-white",
        dt.date(2026, 5, 16): "bg-green-500 text-white",

        dt.date(2026, 5, 23): "bg-green-500 text-white",
        dt.date(2026, 5, 30): "bg-green-500 text-white",

        dt.date(2026, 6, 6): "bg-blue-300 text-gray-900",
        dt.date(2026, 7, 25): "bg-pink-300 text-gray-900",


        dt.date(2025, 9, 20): "bg-purple-600",
        dt.date(2025, 9, 27): "bg-purple-600",
        dt.date(2025, 10, 4): "bg-purple-600",
        dt.date(2025, 10, 11): "bg-purple-600",
        dt.date(2025, 10, 18): "bg-purple-600",
        dt.date(2025, 11, 1): "bg-purple-600",
        dt.date(2025, 11, 8): "bg-purple-600",
        dt.date(2025, 11, 15): "bg-purple-600",
        dt.date(2025, 11, 22): "bg-purple-600",
        dt.date(2025, 11, 29): "bg-purple-600",
        dt.date(2025, 12, 6): "bg-purple-600",
        dt.date(2025, 12, 13): "bg-purple-600",
        dt.date(2026, 1, 10): "bg-purple-600",
        dt.date(2026, 1, 17): "bg-purple-600",
        dt.date(2026, 1, 24): "bg-purple-600",
        dt.date(2026, 1, 31): "bg-purple-600",
        dt.date(2026, 2, 7): "bg-purple-600",
        dt.date(2026, 2, 21): "bg-purple-600",
        dt.date(2026, 3, 28): "bg-purple-600",
        dt.date(2026, 4, 18): "bg-purple-600",
        dt.date(2026, 4, 25): "bg-purple-600",
        dt.date(2026, 5, 9): "bg-purple-600",
        dt.date(2026, 6, 13): "bg-purple-600",
        dt.date(2026, 6, 20): "bg-purple-600",
        dt.date(2026, 6, 27): "bg-purple-600",
        dt.date(2026, 7, 4): "bg-purple-600",
        dt.date(2026, 7, 11): "bg-purple-600",
        dt.date(2026, 7, 18): "bg-purple-600",
    }

def is_purple_date(d: dt.date) -> bool:                                           # NEW
    return SPECIAL_DATES.get(d) == "bg-purple-600"    

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

def home(request):
    assignments = []
    today = dt.date.today()
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

    if request.user.is_authenticated:
        # Klassen, in denen der User Lehrer/Schüler ist
        teacher_classes = request.user.classes_as_teacher.all()
        student_classes = request.user.classes_as_student.all()

        if teacher_classes.exists():
            assignments = Assignment.objects.filter(
                classroom__in=teacher_classes
            ).select_related("classroom").order_by("-created_at")[:20]
        elif student_classes.exists():
            assignments = Assignment.objects.filter(
                classroom__in=student_classes
            ).select_related("classroom").order_by("-created_at")[:20]
        else:
            assignments = (Assignment.objects
                           .select_related("classroom")
                           .order_by("-created_at")[:10])
   
    special_map = {
        d.day: cls
        for d, cls in SPECIAL_DATES.items()
        if d.year == y and d.month == m
    }

      # lila Tage (klickbar) dieses Monats
    purple_days = {
        d.day for d, cls in SPECIAL_DATES.items()
        if d.year == y and d.month == m and cls == "bg-purple-600"
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
        "assignments": assignments,
        "cal_year": y, "cal_month": m, "cal_weeks": weeks,
        "cal_month_name": calendar.month_name[m],
        "cal_prev_y": (dt.date(y, m, 1) - dt.timedelta(days=1)).year,
        "cal_prev_m": (dt.date(y, m, 1) - dt.timedelta(days=1)).month,
        "cal_next_y": ((dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1)).year,
        "cal_next_m": ((dt.date(y, m, 28) + dt.timedelta(days=4)).replace(day=1)).month,
        "cal_today": today,
        "special_map": special_map, 
        "purple_days": purple_days,
        "absences": absences,
        "absences_total": absences_total,
    }

    return render(request, "core/home.html", ctx)

@login_required
def profile_view(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)

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

    return render(request, "core/profile.html", {"form": form, "profile": profile})
