from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from .models import Profile, Assignment, Absence, ClassRoom, ChecklistItem, StudentChecklist, WeeklyBanner, TeacherNote, StoryRead, PrayerStatus, RamadanItemDone,  QuizScore
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
from django.db.models import Q
from .forms import WeeklyBannerForm
from django.urls import reverse
from .ramadan_data import RAMADAN_CONTENT, RAMADAN_ITEMS_META, RAMADAN_ITEMS_ORDER
from django.shortcuts import render
from .stories_data import STORIES
from .fiqh_questions import FIQH_QUESTIONS_ADVANCED
import math
from .islam_questions import ISLAM_QUESTIONS
from .drawing_links import DRAWING_LINKS_VIEW, DRAWING_LINKS_DOWNLOAD
from django.db.models import Count

ARABIC_BLOCK_MSG = "يمكن وضع علامة الغياب فقط من يوم الجمعة الساعة 10:00 حتى السبت الساعة 10:00."
ARABIC_ALREADY_MARKED = "لقد تم وضع علامة الغياب لهذا اليوم من قبل."
ARABIC_NOT_PURPLE = "لا يمكن وضع علامة الغياب إلا في الأيام المحددة (باللون البنفسجي)."

ACADEMIC_START = dt.date(2025, 9, 1)
ACADEMIC_END_EXCL = dt.date(2026, 9, 1)
PRAYERS = [
    (1, "الفجر"),
    (2, "الظهر"),
    (3, "العصر"),
    (4, "المغرب"),
    (5, "العشاء"),
]
ARABIC_WEEKDAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}

def is_user_teacher(user):
    return user.is_authenticated and ClassRoom.objects.filter(teachers=user).exists()

def visible_items_for_student(student):
    # Items ohne Classroom-Einschränkung ODER an mindestens eine Klasse des Schülers gebunden
    student_cls_ids = ClassRoom.objects.filter(students=student).values_list('id', flat=True)
    return (ChecklistItem.objects
            .filter(Q(classrooms__isnull=True) | Q(classrooms__id__in=student_cls_ids))
            .distinct()
            .order_by('order', 'id'))


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
        dt.date(2026, 2, 28): "bg-purple-600 text-white",
        dt.date(2026, 3, 7): "bg-purple-600 text-white",
        dt.date(2026, 3, 14): "bg-purple-600 text-white",
        
        dt.date(2026, 3, 21): "bg-blue-300 text-gray-900 text-white",

        dt.date(2026, 4, 4):"bg-green-500 text-white text-white",
        dt.date(2026, 4, 11):"bg-green-500 text-white text-white",
        
        dt.date(2026, 5, 2): "bg-green-500 text-white text-white",
        dt.date(2026, 5, 16): "bg-green-500 text-white text-white",

        dt.date(2026, 5, 23): "bg-green-500 text-white text-white",
        dt.date(2026, 5, 30): "bg-green-500 text-white text-white",

        dt.date(2026, 6, 6): "bg-blue-300 text-gray-900 text-white",
        dt.date(2026, 7, 25): "bg-pink-300 text-gray-900 text-white",


        dt.date(2025, 9, 20): "bg-purple-600 text-white",
        dt.date(2025, 9, 27): "bg-purple-600 text-white",
        dt.date(2025, 10, 4): "bg-purple-600 text-white",
        dt.date(2025, 10, 11): "bg-purple-600 text-white",
        dt.date(2025, 10, 18): "bg-purple-600 text-white",
        dt.date(2025, 11, 1): "bg-purple-600 text-white",
        dt.date(2025, 11, 8): "bg-purple-600 text-white",
        dt.date(2025, 11, 15): "bg-purple-600 text-white",
        dt.date(2025, 11, 22): "bg-purple-600 text-white",
        dt.date(2025, 11, 29): "bg-purple-600 text-white",
        dt.date(2025, 12, 6): "bg-purple-600 text-white",
        dt.date(2025, 12, 13): "bg-purple-600 text-white",
        dt.date(2026, 1, 10): "bg-purple-600 text-white",
        dt.date(2026, 1, 17): "bg-purple-600 text-white",
        dt.date(2026, 1, 24): "bg-purple-600 text-white",
        dt.date(2026, 1, 31): "bg-purple-600 text-white",
        dt.date(2026, 2, 7): "bg-purple-600 text-white",
        dt.date(2026, 2, 21): "bg-purple-600 text-white",
        dt.date(2026, 3, 28): "bg-purple-600 text-white",
        dt.date(2026, 4, 18): "bg-purple-600 text-white",
        dt.date(2026, 4, 25): "bg-purple-600 text-white",
        dt.date(2026, 5, 9): "bg-purple-600 text-white",
        dt.date(2026, 6, 13): "bg-purple-600 text-white",
        dt.date(2026, 6, 20): "bg-purple-600 text-white",
        dt.date(2026, 6, 27): "bg-purple-600 text-white",
        dt.date(2026, 7, 4): "bg-purple-600 text-white",
        dt.date(2026, 7, 11): "bg-purple-600 text-white",
        dt.date(2026, 7, 18): "bg-purple-600 text-white",
    }

def is_purple_date(d: dt.date) -> bool:                                           # NEW
    return SPECIAL_DATES.get(d) == "bg-purple-600 text-white"    

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

    banner = WeeklyBanner.objects.order_by("-updated_at").first()
   
    assignments = []
    today = dt.date.today()
    if request.GET.get("date"):
        try:
            active_date = dt.date.fromisoformat(request.GET["date"])
        except ValueError:
            active_date = today
    else:
        active_date = today

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
        if d.year == y and d.month == m and cls == "bg-purple-600 text-white"
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
        "week_days": week_days,
        "weekly_prayers": weekly_prayers,
        "active_date": active_date,
        "prev_week_date": prev_week_date,
        "next_week_date": next_week_date,
        "current_week_start": current_week_start,
        "current_week_end": current_week_end,
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

    if request.user.is_authenticated:
        if is_user_teacher(request.user):
            # Lehrer: eigene Notizen (optional per ?student filtern)
            sel_id = request.GET.get('student')
            selected_student = None
            if sel_id:
                selected_student = User.objects.filter(pk=sel_id).first()
            notes_qs = TeacherNote.objects.filter(teacher=request.user)
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
            items = visible_items_for_student(request.user)
            checked_ids = set(StudentChecklist.objects
                              .filter(student=request.user, checked=True)
                              .values_list('item_id', flat=True))

            notes_qs = (TeacherNote.objects
                        .filter(student=request.user)
                        .select_related("teacher", "classroom")
                        .order_by("-created_at")[:30])

            ctx.update({
                "is_teacher": False,
                "checklist_items": items,
                "checked_item_ids": checked_ids,
                "teacher_notes": notes_qs,
                "active_date": active_date,
                "week_days": week_days,
                "weekly_prayers": weekly_prayers,
            })

    return render(request, "core/home.html", ctx)

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
    vis_ids = set(visible_items_for_student(student).values_list('id', flat=True))
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
        return render(request, "core/library.html", {"level": None})

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

@login_required
def ramadan_plan(request):
    # Wettbewerb (Tage)
    days = [{"day": d, "title": f"🌙 {d} رمضان"} for d in range(1, 31)]
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
        "days": days,

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

    if day < 1 or day > 30:
        raise Http404("Invalid day")

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
    done_qs = RamadanItemDone.objects.filter(user=request.user, day=day, done=True)
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
        "all_done": all_done,
        "at_end": at_end,
        "is_last_item": is_last_item,
        "show_success": show_success,
        "results_href": results_href,

    })


@login_required
@require_POST
def mark_ramadan_item_done(request):
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
        user=request.user, day=day, item_key=item_key,
        defaults={"done": True}
    )
    if not created and not obj.done:
        obj.done = True
        obj.save()

    return JsonResponse({"ok": True})

@login_required
def ramadan_results(request):
    TOTAL_DAYS = 30

    agg = (RamadanItemDone.objects
           .filter(user=request.user, done=True)
           .values("item_key")
           .annotate(done_days=Count("day", distinct=True)))

    done_map = {row["item_key"]: row["done_days"] for row in agg}

    rows = []
    for key in RAMADAN_ITEMS_ORDER:
        label = RAMADAN_ITEMS_META.get(key, {}).get("label_ar") \
                or RAMADAN_ITEMS_META.get(key, {}).get("label_de") \
                or key
        rows.append({
            "key": key,
            "label": label,
            "done": done_map.get(key, 0),
            "total": TOTAL_DAYS,
        })

    return render(request, "core/ramadan_results.html", {
        "rows": rows,
        "total_days": TOTAL_DAYS,
    })
