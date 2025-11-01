from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from .models import Profile, Assignment, Absence, ClassRoom, ChecklistItem, StudentChecklist, WeeklyBanner, TeacherNote  
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


ARABIC_BLOCK_MSG = "يمكن وضع علامة الغياب فقط من يوم الجمعة الساعة 10:00 حتى السبت الساعة 10:00."
ARABIC_ALREADY_MARKED = "لقد تم وضع علامة الغياب لهذا اليوم من قبل."
ARABIC_NOT_PURPLE = "لا يمكن وضع علامة الغياب إلا في الأيام المحددة (باللون البنفسجي)."

ACADEMIC_START = dt.date(2025, 9, 1)
ACADEMIC_END_EXCL = dt.date(2026, 9, 1)

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

    context = {"level": level}
    STORIES = {
        "beginner": {
            "1": {
                "title": "جملة 1",
                "body": [
                    {
                        "text": "قَمَرٌ مُنِيرٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_200,c_fill/v1761307112/unnamed_srp4ov.png"
                    },
                    {
                        "text":"وَرْدٌ أَحْمَرٌ",
                        
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_300,c_fill/v1761308536/unnamed_jjffci.png"
                    },
                    {
                        "text":"طريقٌ طَويلٌ",
                        
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_200,c_fill/v1761308547/unnamed_eww7ki.jpg"
                    },
                    {
                        "text":"طِفْلٌ سَعِيدٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_300,c_fill/v1761308554/unnamed_v54mt6.jpg"
                    },
                    {
                        "text":"بَحْرٌ هَادِئٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_200,c_fill/v1761308561/unnamed_fqyxhl.jpg"
                    },
                    
                ],
            },"2": {
                "title": "جملة 2",
                "body": [
                    {
                        "text": "حِصَانٌ سَرِيعٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_200,c_fill/v1761310629/pexels-helenalopes-1996333_dykak1.jpg"
                    },
                    {
                        "text":"سَمَاءٌ صَافيَةٌ",
                        
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_400,h_300,c_fill/v1761310764/pexels-zozz-544554_a5dfxt.jpg"
                    },
                    {
                        "text":"زَهْرَةٌ بَيْضَاءُ",
                        
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_400,c_fill/v1761310829/pexels-julia-mayer-325140421-16811625_n8jn8n.jpg"
                    },
                    {
                        "text":"جَبَلٌ شَاهِقٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_300,c_fill/v1761310882/pexels-pixabay-417173_ghyqhd.jpg"
                    },
                    {
                        "text":"نَجْمٌ لَامِعٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_300,c_fill/v1761311380/71083_aur_2-3umr_jw2k5o.jpg"
                    },
                    
                ],
            },
            "3": {
                "title": "جملة 3",
             "body": [
                {
                        "text": "طَائِرٌ جَمِيلٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_200,c_fill/v1761311915/pexels-pixabay-255435_py3tt5.jpg"
                    },
                    {
                        "text":"كِتَابٌ جَدِيدٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_400,h_300,c_fill/v1761312003/pexels-pixabay-415071_lk76to.jpg"
                    },
                    {
                        "text":"بَيْتٌ كَبِيرٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_500,h_400,c_fill/v1761312058/pexels-binyaminmellish-106399_melme1.jpg"
                    },
                    {
                        "text":"قِطٌّ لَطِيفٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_500,h_300,c_fill/v1761312102/pexels-didsss-1276553_douktw.jpg"
                    },
                    {
                        "text":"كَلْبٌ وَفِيٌّ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_300,c_fill/v1761312117/pexels-svetozar-milashevich-99573-1490908_llqjzf.jpg"
                    },
                ]},
            "4": {
                "title": "جملة 4",
             "body": [
                {
                        "text": "سَيَّارَةٌ سَرِيعَةٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_200,c_fill/v1761312309/pexels-garvin-st-villier-719266-3311574_peianw.jpg"
                    },
                    {
                        "text":"شَجَرَةٌ خَضْرَاءُ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_400,h_300,c_fill/v1761312307/pexels-minan1398-1313807_gga6av.jpg"
                    },
                    {
                        "text":"نَهْرٌ صَافٍ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_400,c_fill/v1761312305/pexels-pixabay-2438_uuupla.jpg"
                    },
                    {
                        "text":"قِمَّةٌ جَلِيلَةٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_300,h_300,c_fill/v1761312375/pexels-christopher-politano-978995-34273345_nzvbv4.jpg"
                    },
                    {
                        "text":"مَطَرٌ غَزِيرٌ",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_500,h_300,c_fill/v1761312304/pexels-pixabay-459451_wb52uu.jpg"
                    },
                ]},
        },
        "intermediate": {
            "1": {
                "title": "الحياءُ مِنَ اللهِ",
                "body": [
                        {
                        "text":"""فِي يَوْمٍ مِنَ الأَيَّامِ، مَشَى أَحْمَدُ مَعَ صَدِيقِهِ سَامِي إِلَى المَسْجِدِ.

                                    رَأَى أَحْمَدُ فِي الطَّرِيقِ قِطْعَةَ شُوكُولَاتَةٍ فِي الدُّكَّانِ، فَفَكَّرَ أَنْ يَأْخُذَهَا.
                                    
                                    قَالَ لَهُ سَامِي:

                                     اتَّقِ اللهَ يَا أَحْمَدُ، فَاللهُ يَرَاكَ فِي كُلِّ مَكَانٍ.

                                    فَاسْتَحْيَا أَحْمَدُ، وَأَرْجَعَ الشُّوكُولَاتَةَ، وَقَالَ:

                                     لَنْ أَفْعَلَ مَا يُغْضِبُ اللهَ.

                                    فَقَالَ سَامِي:

                                    أَحْسَنْتَ، مَنْ يَسْتَحِ مِنَ اللهِ يَفْعَلُ الخَيْرَ دَائِمًا.

                                    ثُمَّ دَخَلَا المَسْجِدَ، وَصَلَّيَا وَقُلُوبُهُمَا مُمْتَلِئَةٌ بِالفَرَحِ.""",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_500,h_300,c_fill/v1761313613/unnamed_tccb5a.jpg"
                    },
                ]
            }, 
            "2": {
                "title": "قِصَّةُ لَيْلَى وَالطَّاعَةُ لِلوَالِدَيْنِ",
                "body": [
                        {
                        "text":"""فِي صَبَاحٍ جَمِيلٍ، نَادَتِ الأُمُّ:

                                    يَا لَيْلَى، هَيَّا إِلَى الصَّلَاةِ وَالْمَدْرَسَةِ.
                                    
                                    فَقَالَتْ لَيْلَى: حَاضِرٌ يَا أُمِّي.
                                    
                                    بَعْدَ المَدْرَسَةِ، رَأَتْ لَيْلَى أُمَّهَا تَتْعَبُ فِي المَطْبَخِ، فَقَالَتْ:

                                    اسْتَرِيحِي يَا أُمِّي، سَأُسَاعِدُكِ.

                                    وَسَمِعَتْ أَبَاهَا يَقُولُ:

                                    يَا لَيْلَى، أَحْضِرِي كِتَابِي.

                                    فَأَتَتْهُ بِهِ مُبْتَسِمَةً.

                                    فَقَالَ أَبُوهَا: أَنْتِ بِنْتٌ بَارَّةٌ.

                                    فَقَالَتْ لَيْلَى:

                                    أُحِبُّكُمَا وَسَأُبَرُّكُمَا دَائِمًا.""",
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_600,h_500,c_fill/v1761313620/unnamed_ja9lfw.jpg"
                    },
                ]
            },
            "3": {
                "title": "قِصَّةُ عُمَرَ وَجَارِهِ الكَرِيمِ",
                "body": [
                        {
                        "text":"""فِي يَوْمٍ مِنَ الأَيَّامِ، كَانَ عُمَرُ يَلْعَبُ بِكُرَتِهِ أَمَامَ البَيْتِ،

                                فَسَقَطَتِ الكُرَةُ فِي حَدِيقَةِ جَارِهِمْ عَمِّ سَعِيدٍ.

                                طَرَقَ عُمَرُ البَابَ وَقَالَ:

                                السَّلَامُ عَلَيْكُمْ يَا عَمِّي، هَلْ أَأْخُذُ كُرَتِي؟

                                فَفَتَحَ الجَارُ البَابَ وَقَالَ:

                                خُذْهَا يَا بُنَيَّ، وَشُكْرًا عَلَى أَدَبِكَ.

                                فَقَالَ عُمَرُ:

                                أُمِّي تُعَلِّمُنِي أَنْ أُحْسِنَ إِلَى جِيرَانِي.

                                وَفِي الْمَسَاءِ، أَخَذَ عُمَرُ طَبَقًا مِنَ الطَّعَامِ لِعَمِّ سَعِيدٍ الْمَرِيضِ، وَقَالَ:

                                هَذَا لَكَ يَا عَمِّي، نَتَمَنَّى لَكَ الشِّفَاءَ.

                                فَابْتَسَمَ الجَارُ وَقَالَ:

                                جَزَاكَ اللهُ خَيْرًا يَا عُمَرُ، أَنْتَ جَارٌ طَيِّبٌ.
                        """,
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_600,h_500,c_fill/v1761313627/unnamed_vmfvo1.jpg"
                    },
                ]
            },
            "4": {
                "title": "قِصَّةُ نُورٍ وَزِيَارَةُ الْجَدَّةِ",
                "body": [
                        {
                        "text":"""فِي يَوْمٍ جَمِيلٍ، قَالَتِ الأُمُّ لِابْنَتِهَا نُورٍ:

                                يَا نُورُ، سَنَذْهَبُ الْيَوْمَ لِزِيَارَةِ جَدَّتِكِ.

                                فَقَالَتْ نُورٌ بِفَرَحٍ:

                                يَا سَلَامُ! أُحِبُّ جَدَّتِي كَثِيرًا، سَآخُذُ لَهَا رَسْمَةً رَسَمْتُهَا فِي المَدْرَسَةِ.

                                لَمَّا وَصَلَتْ نُورٌ مَعَ أُمِّهَا إِلَى بَيْتِ الْجَدَّةِ، قَدَّمَتْ نُورٌ رَسْمَتَهَا وَقَالَتْ:

                                هَذِهِ لَكِ يَا جَدَّتِي، لِأَنِّي أُحِبُّكِ.

                                فَسُرَّتِ الجَدَّةُ وَقَالَتْ:

                                جَزَاكِ اللهُ خَيْرًا يَا حَبِيبَتِي، أَنْتِ بِنْتٌ طَيِّبَةٌ، وَصِلَةُ الرَّحِمِ تُرْضِي اللهَ.

                                وَفِي طَرِيقِ العَوْدَةِ، قَالَتِ الأُمُّ:

                                أَحْسَنْتِ يَا نُورُ، فَمَنْ يَزُرْ أَقَارِبَهُ وَيُحِبَّهُمْ، يَكُونُ مِنَ الأَبْرَارِ.

                        """,
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_700,h_500,c_fill/v1761313635/unnamed_g554fo.jpg"
                    },
                ]
            },
            "5": {
                "title": "قِصَّةُ خَالِدٍ وَالضَّيْفِ",
                "body": [
                        {
                        "text":"""فِي يَوْمٍ مِنَ الأَيَّامِ، كَانَ خَالِدٌ يَجْلِسُ مَعَ أُمِّهِ فِي البَيْتِ.

                                طَرَقَ البَابَ رَجُلٌ كَبِيرٌ، فَقَالَتِ الأُمُّ:

                                يَا خَالِدُ، هَذَا ضَيْفُنَا، افْتَحِ البَابَ وَرَحِّبْ بِهِ.

                                فَفَتَحَ خَالِدٌ البَابَ وَقَالَ بِأَدَبٍ:

                                أَهْلًا وَسَهْلًا، تَفَضَّلْ يَا عَمِّي.

                                قَدَّمَتِ الأُمُّ كَأْسًا مِنَ العَصِيرِ، وَقَالَ خَالِدٌ:

                                هَذَا لَكَ يَا عَمِّي، أَرْجُو أَنْ يُعْجِبَكَ.

                                فَابْتَسَمَ الضَّيْفُ وَقَالَ:

                                بَارَكَ اللهُ فِيكَ يَا بُنَيَّ، أَنْتَ وَلَدٌ كَرِيمٌ.

                                فَقَالَتِ الأُمُّ:

                                النَّبِيُّ ﷺ قَالَ: (مَنْ كَانَ يُؤْمِنُ بِاللهِ وَاليَوْمِ الآخِرِ فَلْيُكْرِمْ ضَيْفَهُ).

                                فَرِحَ خَالِدٌ وَقَالَ:

                                سَأُكْرِمُ ضُيُوفَنَا دَائِمًا لِأَنَّ اللهَ يُحِبُّ الكِرَامَ.
                        """,
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_700,h_500,c_fill/v1761313645/unnamed_zbgkif.jpg"
                    },
                ]
            },
            "6": {
                "title": "قِصَّةُ يُوسُفَ وَآدَابِ الطَّرِيقِ",
                "body": [
                        {
                        "text":"""فِي يَوْمٍ جَمِيلٍ، خَرَجَ يُوسُفُ لِيَلْعَبَ مَعَ أَصْدِقَائِهِ أَمَامَ البَيْتِ.

                                    رَآهُ أَبُوهُ وَقَالَ:

                                    يَا يُوسُفُ، احْذَرِ الطَّرِيقَ، وَالتَزِمْ آدَابَهُ.

                                    سَأَلَ يُوسُفُ:

                                    وَمَا هِيَ آدَابُ الطَّرِيقِ يَا أَبِي؟

                                    قَالَ الأَبُ:

                                    لَا تُؤْذِ أَحَدًا، وَلَا تَرْمِ الأَوْسَاخَ، وَسَاعِدْ مَنْ يَحْتَاجُ.

                                    فَقَالَ يُوسُفُ:

                                    حَسَنًا يَا أَبِي، سَأَكُونُ طَيِّبًا فِي الطَّرِيقِ.

                                    وَبَيْنَمَا كَانَ يَلْعَبُ، رَأَى عَجُوزًا تَسْقُطُ عَصَاهَا، فَأَسْرَعَ يُسَاعِدُهَا.

                                    قَالَتِ العَجُوزُ:

                                    جَزَاكَ اللهُ خَيْرًا يَا بُنَيَّ، أَنْتَ وَلَدٌ مُؤَدَّبٌ.

                                    فَرِحَ يُوسُفُ وَقَالَ:

                                    سَأَتَّبِعُ آدَابَ الطَّرِيقِ دَائِمًا، لِأَرْضِيَ اللهَ وَوَالِدَيَّ.
                        """,
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_700,h_500,c_fill/v1761313653/unnamed_amvtpy.jpg"
                    },
                ]
            },
            "7": {
                "title": "قِصَّةُ مَرْيَمَ وَآدَابِ الطَّعَامِ",
                "body": [
                        {
                        "text":"""فِي يَوْمٍ مِنَ الأَيَّامِ، جَلَسَتْ مَرْيَمُ مَعَ أُسْرَتِهَا لِتَتَنَاوَلَ الطَّعَامَ.

                                    قَبْلَ أَنْ تَأْكُلَ، قَالَتْ لَهَا أُمُّهَا:

                                    يَا مَرْيَمُ، قُولِي: “بِسْمِ اللهِ” قَبْلَ الأَكْلِ.

                                    فَقَالَتْ مَرْيَمُ بِصَوْتٍ جَمِيلٍ:

                                    بِسْمِ اللهِ الرَّحْمَنِ الرَّحِيمِ.

                                    ثُمَّ بَدَأَتْ تَأْكُلُ بِيَدِهَا اليُمْنَى، وَلَا تُسْرِفُ فِي الأَكْلِ.

                                    عِنْدَمَا فَرَغَتْ، مَسَحَتْ فَمَهَا وَقَالَتْ:

                                    الْحَمْدُ لِلَّهِ الَّذِي أَطْعَمَنِي وَسَقَانِي.

                                    ابْتَسَمَ أَبُوهَا وَقَالَ:

                                    أَحْسَنْتِ يَا مَرْيَمُ، مَنْ يَتَّبِعْ آدَابَ الطَّعَامِ يُحِبُّهُ اللهُ وَيُبَارِكْ فِي طَعَامِهِ.

                                    فَرِحَتْ مَرْيَمُ وَقَالَتْ:

                                    سَأَتَذَكَّرُ آدَابَ الطَّعَامِ دَائِمًا.
                        """,
                        "image": "https://res.cloudinary.com/drlpkuf9q/image/upload/w_700,h_500,c_fill/v1761313661/unnamed_hp6x1n.jpg"
                    },
                ]
            },
        },
        "advanced": 
        { 
            "1": {
                "title": "الخُلَفَاءُ الرَّاشِدُونَ",
                "body":
                [
                    {
                        "text":"""
                                <span style="color:green; font-weight:bold;"> قَادَةٌ وَقُدْوَة</span><br>        
                                بعد وفاةِ النَّبِيِّ مُحَمَّدٍ (صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ)، تَعَاقَبَ عَلَى حُكْمِ الدَّوْلَةِ الإِسْلَامِيَّةِ أَرْبَعَةٌ مِنَ الصَّحَابَةِ الكِرَامِ،
                                 عُرِفُوا بِاسْمِ "الخُلَفَاءِ الرَّاشِدِينَ" لِحُسْنِ سِيرَتِهِمْ وَعَدْلِهِمْ وَاتِّبَاعِهِمْ لِسُنَّةِ النَّبِيِّ. وَهُمْ:
                                • أَبُو بَكْرٍ الصِّدِّيقُ (رَضِيَ اللهُ عَنْهُ)
                                • عُمَرُ بْنُ الخَطَّابِ (رَضِيَ اللهُ عَنْهُ)
                                • عُثْمَانُ بْنُ عَفَّانَ (رَضِيَ اللهُ عَنْهُ)
                                • عَلِيُّ بْنُ أَبِي طَالِبٍ (رَضِيَ اللهُ عَنْهُ)
                                
                                <span style="color:green; font-weight:bold;">1. أَبُو بَكْرٍ الصِّدِّيقُ (رَضِيَ اللهُ عَنْهُ): صَاحِبُ الرَّسُولِ</span><br>    
                                كَانَ أَوَّلَ مَنْ أَسْلَمَ مِنَ الرِّجَالِ، وَصَاحَبَ الرَّسُولَ (صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ) فِي هِجْرَتِهِ.
                                • أَبْرَزُ أَعْمَالِهِ:
                                • حَرْبُ المُرْتَدِّينَ: قَامَ بِتَوْحِيدِ جَزِيرَةِ العَرَبِ بَعْدَ أَنْ ارْتَدَّتْ بَعْضُ القَبَائِلِ عَنِ الإِسْلَامِ.
                                • جَمْعُ القُرْآنِ: أَمَرَ بِجَمْعِ القُرْآنِ الكَرِيمِ فِي مُصْحَفٍ وَاحِدٍ بَعْدَ اسْتِشْهَادِ عَدَدٍ كَبِيرٍ مِنَ حُفَّاظِهِ فِي المَعَارِكِ.
                                • مِنْ أَقْوَالِهِ المَشْهُورَةِ: "أَيُّهَا النَّاسُ، إِنْ كُنْتُمْ تَعْبُدُونَ مُحَمَّدًا،
                                 فَإِنَّ مُحَمَّدًا قَدْ مَاتَ، وَإِنْ كُنْتُمْ تَعْبُدُونَ اللهَ، فَإِنَّ اللهَ حَيٌّ لَا يَمُوتُ."

                                <span style="color:green; font-weight:bold;">2. عُمَرُ بْنُ الخَطَّابِ (رَضِيَ اللهُ عَنْهُ): الفَارُوقُ</span><br> 
                                كَانَ قَوِيًّا وَعَادِلًا، وَلُقِّبَ بِـ"الفَارُوقِ" لِأَنَّهُ فَرَّقَ بَيْنَ الحَقِّ وَالبَاطِلِ.
                                • أَبْرَزُ أَعْمَالِهِ:
                                • فَتْحُ بِلَادٍ جَدِيدَةٍ: فِي عَهْدِهِ، اتَّسَعَتِ الدَّوْلَةُ الإِسْلَامِيَّةُ بِشَكْلٍ كَبِيرٍ، حَيْثُ فُتِحَتْ بِلَادُ الشَّامِ وَالعِرَاقِ وَمِصْرَ.
                                • تَأْسِيسُ الدَّوَاوِينِ: أَنْشَأَ دَوَاوِينَ (وِزَارَاتٍ) لِتَنْظِيمِ شُؤُونِ الدَّوْلَةِ، مِثْلَ دِيوَانِ الجُنْدِ وَدِيوَانِ العَطَاءِ.
                                • مِنْ مَوَاقِفِهِ الهَامَّةِ: كَانَ يَخْرُجُ لَيْلًا يَتَفَقَّدُ أَحْوَالَ رَعِيَّتِهِ لِيَتَأَكَّدَ مِنْ عَدَالَةِ حُكْمِهِ.
                                

                                <span style="color:green; font-weight:bold;">3. عُثْمَانُ بْنُ عَفَّانَ (رَضِيَ اللهُ عَنْهُ): ذُو النُّورَيْنِ</span><br> 
                                عُرِفَ بِكَرَمِهِ الشَّدِيدِ وَحَيَائِهِ، وَلُقِّبَ بِـذِي النُّورَيْنِ لِزَوَاجِهِ مِنْ ابْنَتَيْ النَّبِيِّ.
                                • أَبْرَزُ أَعْمَالِهِ:
                                • جَمْعُ القُرْآنِ: أَمَرَ بِنَسْخِ القُرْآنِ فِي نُسَخٍ مُتَعَدِّدَةٍ، وَتَوْزِيعِهَا عَلَى الأَمْصَارِ (المُدُنِ) لِتَوْحِيدِ قِرَاءَتِهِ.
                                • تَوْسِيعُ المَسْجِدِ النَّبَوِيِّ: قَامَ بِتَوْسِيعِ المَسْجِدِ النَّبَوِيِّ فِي المَدِينَةِ المُنَوَّرَةِ
                                 لِيَسْتَوْعِبَ أَعْدَادَ المُسْلِمِينَ المُتَزَايِدَةَ.
                                • مِنْ أَقْوَالِهِ: "لَوْ طَهُرَتْ قُلُوبُكُمْ لَمْ تَشْبَعْ مِنْ كَلَامِ رَبِّكُمْ."
                               
                               <span style="color:green; font-weight:bold;">4. عَلِيُّ بْنُ أَبِي طَالِبٍ (رَضِيَ اللهُ عَنْهُ): أَبُو الحَسَنَيْنِ</span><br> 
                                كَانَ شُجَاعًا وَحَكِيمًا، وَهُوَ ابْنُ عَمِّ النَّبِيِّ وَزَوْجُ ابْنَتِهِ فَاطِمَةَ.
                                • أَبْرَزُ أَعْمَالِهِ:
                                • تَنْظِيمُ شُرْطَةٍ لَيْلِيَّةٍ: أَنْشَأَ نِظَامًا لِلشُّرْطَةِ لِحِفْظِ الأَمْنِ لَيْلًا فِي المُدُنِ.
                                • نَقْلُ عاصِمَةِ الخِلَافَةِ: نَقَلَ مَرْكَزَ الحُكْمِ مِنَ المَدِينَةِ المُنَوَّرَةِ إِلَى الكُوفَةِ فِي العِرَاقِ.
                                • مِنْ أَقْوَالِهِ: "العِلْمُ أَفْضَلُ مِنَ المَالِ؛ لِأَنَّ العِلْمَ يَحْرُسُكَ، وَأَنْتَ تَحْرُسُ المَالَ."
                                هَؤُلَاءِ القَادَةُ العِظَامُ تَرَكُوا لَنَا مِثَالًا فِي العَدْلِ وَالشَّجَاعَةِ وَالحِكْمَةِ،
                                 وَأَرْسَوْا قَوَاعِدَ دَوْلَةٍ قَوِيَّةٍ بَنَتْ مَجْدًا حَضَارِيًّا عَظِيمًا.
                        """
                    },
                ]
            },
            
            "2": 
            {
                "title": "أبو بكر الصديق",
                "body":
                [
                    {
                        "text":"""
                            <span style="color:green; font-weight:bold;">أبو بكر الصدِّيق: أوَّل الخلفاءِ الرَّاشِدينَ </span><br>
                            إنَّ عبدَ اللهِ بنَ أبي قُحافةَ التَّيميَّ القُرشيَّ، المعروفَ بأبي بكرٍ الصِّدِّيقِ (رضي الله عنه)،
                             يُعَدُّ أزكى النَّاسِ وأحبَّهم إلى قلبِ النبيِّ محمدٍ صلى الله عليه وسلم بعدَ زوجتِهِ عائشةَ.
                              وُلِدَ بمكَّةَ بعدَ عامِ الفيلِ بِسنتَيْنِ تقريبًا،
                               وكانَ قبلَ الإسلامِ تاجرًا أمينًا، ذا مالٍ وفيرٍ، ومن أشرافِ قريشٍ وأهلِ مَشورتِها.

                               <span style="color:green; font-weight:bold;">إسلامُه ولقبُ الصِّدِّيقِ</span><br>
                            كانَ أبو بكرٍ رضي الله عنه أوَّلَ من آمَنَ بالرَّسولِ مِنَ الرِّجالِ الأحرارِ.
                             ولُقِّبَ بـ"الصِّدِّيقِ" لمُبادرتِهِ بالتَّصديقِ الْمُطلَقِ للنبيِّ في كلِّ ما جاءَ بهِ،
                              وعلى الأخصِّ حادثةَ الإسراءِ والمعراجِ، عندما كذَّبَهُ النَّاسُ.
                               وقد سخَّرَ مالَهُ وجاهَهُ لنُصرةِ الإسلامِ، فأعتَقَ كثيرًا من العبيدِ الذينَ عُذِّبوا بسببِ إيمانِهم،
                                مثلَ بلالٍ الحبشيِّ رضي الله عنهُ.

                                 <span style="color:green; font-weight:bold;">مواقفُهُ في نُصرةِ الدَّعوةِ</span><br>
                            برزَتْ عظمةُ أبي بكرٍ في مراحلَ مفصليَّةٍ في تاريخِ الإسلامِ:
                            1. رفيقُ الهجرةِ: كانَ ثانيَ اثنينِ معَ النَّبيِّ صلى الله عليه وسلم في رحلةِ الهجرةِ إلى المدينةِ،
                             وقد حفظَ القرآنُ هذا الموقفَ العظيمَ في قولِهِ تعالى:
                              { إِلَّا تَنصُرُوهُ فَقَدْ نَصَرَهُ اللَّهُ إِذْ أَخْرَجَهُ الَّذِينَ كَفَرُوا ثَانِيَ اثْنَيْنِ إِذْ هُمَا فِي الْغَارِ إِذْ يَقُولُ لِصَاحِبِهِ لَا تَحْزَنْ إِنَّ اللَّهَ مَعَنَا }
                            2. بذلُ المالِ والنَّفسِ: كانَ في كلِّ غزوةٍ بجانبِ الرَّسولِ، بل وتبرَّعَ بكلِّ مالِهِ لجيشِ غزوةِ تبوكَ،
                             وعندما سألَهُ النبيُّ صلى الله عليه وسلم: "ماذا أبقَيْتَ لأهلِكَ؟"،
                              أجابَ: "أَبقَيْتُ لهمُ اللهَ ورسولَهُ".
                            3. الثَّباتُ يومَ وفاةِ الرَّسولِ: كانَ أكثرَ النَّاسِ ثباتًا عندَ وفاةِ النَّبيِّ صلى الله عليه وسلم،
                             حيثُ خطبَ في النَّاسِ قولَهُ الشَّهيرَ: "مَنْ كانَ يَعبُدُ مُحمَّدًا،
                              فإنَّ مُحمَّدًا قد ماتَ، ومَنْ كانَ يَعبُدُ اللهَ، فإنَّ اللهَ حيٌّ لا يموتُ".
                            
                            <span style="color:green; font-weight:bold;">أُسُسُ الخِلافةِ وأبرزُ الأفعال</span><br>  
                            تولَّى أبو بكرٍ الخلافةَ بعدَ بيعةِ السَّقيفةِ، ومدَّةُ خِلافتهِ سنتانِ وثلاثةُ أشهرٍ.
                            
                            <span style="color:green; font-weight:bold;">1. أقوالُهُ في تحديدِ سِياسَةِ الحُكمِ:</span><br>  
                            في أوَّلِ خُطبةٍ لَهُ بعدَ تولِّي الخلافةِ، أرسى أبو بكرٍ قواعدَ العدلِ والحُكمِ الرَّاشدِ،
                             ومن أهمِّ ما قالَ:
                            • "أيُّها النَّاسُ، إنِّي قد وُلِّيتُ عليكم ولستُ بخيرِكُمْ، فإنْ أحسنتُ فأعينوني،
                             وإنْ أسأتُ فَقَوِّموني." (يُرسِّي مبدأَ الشُّورى والمساءلةِ).
                            • "الصِّدقُ أمانةٌ، والكذبُ خيانةٌ.
                            " (يُحدِّدُ القيمةَ الأخلاقيَّةَ الأساسيَّةَ في التَّعاملِ).
                            • "الضَّعيفُ فيكُمْ قويٌّ عندي حتَّى آخذَ الحقَّ لَهُ،
                             والقويُّ فيكُمْ ضعيفٌ عندي حتَّى آخذَ الحقَّ مِنهُ." (يُجسِّدُ مبدأَ المساواةِ وتحقيقِ العدلِ).
                            
                            <span style="color:green; font-weight:bold;">2. أبرزُ أفعالِهِ الإداريَّةِ والعسكريَّةِ:</span><br>       
                            • حربُ الرِّدَّةِ: أظهرَ أبو بكرٍ حزمًا عظيمًا في قتالِ مانعي الزَّكاةِ والمُرتدِّينَ بعدَ وفاةِ النَّبيِّ،
                             قائلًا: "واللهِ لَأُقاتِلَنَّ مَنْ فرَّقَ بينَ الصَّلاةِ والزَّكاةِ". ووحَّدَ بذلكَ صفوفَ المُسلمينَ.
                            • جمعُ القُرآنِ: بأمرٍ منْهُ واقتراحٍ من عُمرَ بنِ الخطَّابِ،
                             قامَ زيدُ بنُ ثابتٍ بجمعِ آياتِ القرآنِ الكريمِ وكتابتِها في مصحفٍ واحدٍ
                              خوفًا من ضياعِها بعدَ استشهادِ حُفَّاظِ القرآنِ في مَعارِكِ الرِّدَّةِ.
                            • بَدءُ الفتوحاتِ: أرسلَ الجيوشَ الإسلاميَّةَ لفتْحِ بلادِ الشَّامِ والعراقِ لِنشْرِ رسالةِ الإسلامِ.
                        """
                    },
                ]
            },
            "3": {
                "title": "عُمَرُ بْنُ الخَطَّابِ",
                "body":
                [
                    {
                        "text":"""
                                <span style="color:green; font-weight:bold;"> الفَارُوقُ وَأَمِيرُ المُؤْمِنِينَ</span><br>
                                عُمَرُ بْنُ الخَطَّابِ بْنِ نُفَيْلٍ القُرَشِيُّ العَدَوِيُّ (رضي الله عنه) مِنْ أَعْظَمِ شَخْصِيَّاتِ التَّارِيخِ الإسْلامِيِّ.
                                وُلِدَ فِي مَكَّةَ بَعْدَ عَامِ الفِيلِ بِثَلَاثَ عَشْرَةَ سَنَةً تَقْرِيبًا.
                                كَانَ قَبْلَ إسْلامِهِ مِنْ أَشَدِّ المُعَارِضِينَ لِلإسْلامِ،
                                يَتَّصِفُ بِالقُوَّةِ وَالشِّدَّةِ وَالهَيْبَةِ، وَكَانَ لَهُ مَكَانَةٌ عَظِيمَةٌ فِي قَوْمِهِ قُرَيْشٍ.

                               <span style="color:green; font-weight:bold;"> إِسْلامُ عُمَرَ وَفَتْحٌ لِلْمُسْلِمِين</span><br>
                                كَانَ إسْلامُ عُمَرَ (رضي الله عنه) حَدَثًا مِفْصَلِيًّا فِي تَارِيخِ الدَّعْوَةِ.
                                فَقَدْ دَعَا لَهُ الرَّسُولُ (صلى الله عليه وسلم) فَقَالَ:
                                "اللَّهُمَّ أَعِزَّ الإسْلامَ بِأَحَبِّ هَذَيْنِ الرَّجُلَيْنِ إلَيْكَ: بِأَبِي جَهْلٍ أَوْ بِعُمَرَ بْنِ الخَطَّابِ" (رَوَاهُ التِّرْمِذِيُّ).
                                فَاسْتَجَابَ اللهُ لِدَعْوَتِهِ، وَأَسْلَمَ عُمَرُ فِي السَّنَةِ السَّادِسَةِ مِنَ البَعْثَةِ.
                                بِإسْلامِهِ، عَزَّ المُسْلِمُونَ وَخَرَجُوا لِأَوَّلِ مَرَّةٍ لِلصَّلَاةِ عَلَانِيَةً فِي الكَعْبَةِ،
                                 وَلِذَلِكَ لُقِّبَ بـ الفَارُوقِ؛ لِأَنَّ اللهَ فَرَّقَ بِهِ بَيْنَ الحَقِّ وَالبَاطِلِ.

                                 <span style="color:green; font-weight:bold;"> بَطُولَاتُهُ وَإِنْجَازَاتُهُ</span><br>
                                شَارَكَ عُمَرُ فِي كُلِّ الغَزَوَاتِ مَعَ الرَّسُولِ (صلى الله عليه وسلم)،
                                مُبْدِيًا شَجَاعَةً وَحِنْكَةً كَبِيرَةً. بَعْدَ وَفَاةِ النَّبِيِّ،
                                كَانَ سَنَدًا قَوِيًّا لِأَبِي بَكْرٍ الصِّدِّيقِ فِي حَرْبِ الرِّدَّةِ وَتَثْبِيتِ دَوْلَةِ الإسْلامِ.
                                وَبَعْدَ أَنْ تَقَلَّدَ خِلافَةَ المُسْلِمِينَ عَامَ 13 هـ (634 م)،
                                امْتَدَّتْ بُطُولَاتُهُ لِتَشْمَلَ الإدَارَةَ وَالقِيَادَةَ المُمْتَازَةَ. فِي عَهْدِهِ، تَمَّتْ أَعْظَمُ الفُتُوحَاتِ:
                                1. فَتْحُ الشَّامِ وَفِلَسْطِينَ: سَقَطَتْ فِي عَهْدِهِ أَهَمُّ مُدُنِ الشَّامِ،
                                وَمِنْ أَبْرَزِهَا مَعْرَكَةُ اليَرْمُوكِ (15 هـ)، وَفَتْحُ القُدْسِ حَيْثُ جَاءَ بِنَفْسِهِ لِيَتَسَلَّمَ مَفَاتِيحَهَا
                                وَكَتَبَ لِأَهْلِهَا العُهْدَةَ العُمَرِيَّةَ، وَهِيَ وَثِيقَةُ أَمَانٍ وَتَسَامُحٍ.
                                2. فَتْحُ العِرَاقِ وَفَارِسَ: حَسَمَ الإسْلامُ سَيْطَرَتَهُ عَلَى سَاسَانِيِّي الفُرْسِ فِي مَعْرَكَتَيِ القَادِسِيَّةِ (15 هـ) ونَهَاوَنْدَ (21 هـ)،
                                وَهَكَذَا انْهَارَتْ إمْبَرَاطُورِيَّةُ فَارِسَ.
                                3. فَتْحُ مِصْرَ: قَادَ عَمْرُو بْنُ العَاصِ الجُيُوشَ بِتَوْجِيهٍ مِنْهُ وَفُتِحَتْ مِصْرُ.
                                وَلَمْ تَقْتَصِرْ إنْجَازَاتُهُ عَلَى الجَانِبِ العَسْكَرِيِّ، بَلْ أَنْشَأَ دَوَاوِينَ لِتَنْظِيمِ الدَّوْلَةِ (مِثْلَ دِيوَانِ الجُنْدِ وَالخَرَاجِ)،
                                وَأَسَّسَ بَيْتَ المَالِ، وَنَظَّمَ القَضَاءَ، وَاتَّخَذَ التَّقْوِيمَ الهِجْرِيَّ مَبْدَأً لِتَارِيخِ الدَّوْلَةِ الإسْلامِيَّةِ.

                                <span style="color:green; font-weight:bold;">مِنْ أَقْوَالِهِ المَشْهُورَةِ</span><br>
                                تَرَكَ عُمَرُ (رضي الله عنه) مَجْمُوعَةً مِنْ الأَقْوَالِ الخَالِدَةِ الَّتِي تَعْكِسُ حِكْمَتَهُ وَعَدْلَهُ وَزُهْدَهُ:
                                • "لَوْ عَثَرَتْ شَاةٌ بِالعِرَاقِ لَسَأَلْتُ نَفْسِي: لِمَ لَمْ أُسَوِّ لَهَا الطَّرِيقَ يَا عُمَرُ؟"
                                • (يُبَيِّنُ هَذَا القَوْلُ شِدَّةَ إحْسَاسِهِ بِالمَسْؤُولِيَّةِ عَنْ كُلِّ فَرْدٍ وَكُلِّ شَيْءٍ فِي دَوْلَتِهِ).
                                • "مَتَى اسْتَعْبَدْتُمُ النَّاسَ وَقَدْ وَلَدَتْهُمْ أُمَّهَاتُهُمْ أَحْرَارًا؟"
                                • (هَذَا القَوْلُ يُعَدُّ مِنْ أَعْظَمِ الدُّرُوسِ فِي الحُرِّيَّةِ وَكَرَامَةِ الإنْسَانِ،
                                قَالَهُ عِنْدَمَا حَاسَبَ وَالِيَهُ عَمْرَو بْنَ العَاصِ وَابْنَهُ).
                                • "أَخْوَفُ مَا أَخَافُ عَلَيْكُمْ: رَجُلٌ قَرَأَ القُرْآنَ، حَتَّى إذَا رُؤِيَتْ عَلَيْهِ بَهْجَةُ القُرْآنِ،
                                وَكَانَ رِدَاءَهُ الإسْلامُ، غَيَّرَهُ إلَى مَا شَاءَ اللهُ فَانْسَلَخَ مِنْهُ وَنَبَذَهُ وَرَاءَ ظَهْرِهِ."
                                • (يُحَذِّرُ مِنْ الرِّيَاءِ وَالتَّزَيُّنِ بِالدِّينِ مِنْ غَيْرِ عَمَلٍ صَادِقٍ).

                                <span style="color:green; font-weight:bold;">وَفَاتُهُ</span><br>
                                اُسْتُشْهِدَ عُمَرُ (رضي الله عنه) فِي آخِرِ ذِي الحِجَّةِ عَامَ 23 هـ (644 م) عَلَى يَدِ أَبِي لُؤْلُؤَةَ المَجُوسِيِّ (غُلامُ المُغِيرَةِ بْنِ شُعْبَةَ)
                                وَهُوَ يُصَلِّي بِالنَّاسِ صَلاةَ الفَجْرِ. بَقِيَتْ خِلافَتُهُ عَشْرَ سَنَوَاتٍ وَسِتَّةَ أَشْهُرٍ وَبِضْعَةَ أَيَّامٍ،
                                وَدُفِنَ بِجِوَارِ صَاحِبَيْهِ الرَّسُولِ وَأَبِي بَكْرٍ فِي الحُجْرَةِ النَّبَوِيَّةِ.
                                لَقَدْ كَانَتْ حَيَاةُ عُمَرَ مِثَالاً لِلزُّهْدِ وَالعَدْلِ وَالقُوَّةِ فِي الحَقِّ،
                                مِمَّا جَعَلَ مِنْهُ شَخْصِيَّةً فَرِيدَةً فِي تَارِيخِ الإسْلامِ

                        """
                    },
                ]
            },
            "4": {
                "title": "عُثْمَانُ بْنُ عَفَّانَ",
                "body":[
                    {
                        "text":"""
                            <span style="color:green; font-weight:bold;">الخَلِيفَةُ عُثْمَانُ بْنُ عَفَّانَ (ذُو النُّورَيْنِ)</span><br>
                            اَلْخَلِيفَةُ الثَّالِثُ مِنْ اَلْخُلَفَاءِ اَلرَّاشِدِينَ، وَأَحَدُ اَلْعَشَرَةِ اَلْمُبَشَّرِينَ بِالْجَنَّةِ.
                            هُوَ عُثْمَانُ بْنُ عَفَّانَ بْنِ أَبِي اَلْعَاصِ، مِنْ بَنِي أُمَيَّةَ مِنْ قُرَيْشٍ.
                             يَلْتَقِي نَسَبُهُ بِالرَّسُولِ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ} فِي عَبْدِ مَنَافٍ.
                            عُرِفَ عُثْمَان {رَضِيَ اَللَّهُ عَنْهُ}} بِكَثْرَةِ اَلْحَيَاءِ،
                             وَ اَلْكَرَمِ، وَ اَلْجُودِ، وَ اَللِّينِ، وَ رَجَاحَةِ اَلْعَقْلِ.

                            • لَقَبُ ذِي اَلنُّورَيْنِ: لُقِّبَ بِهَذَا اَللَّقَبِ اَلْجَلِيلِ لِأَنَّهُ تَزَوَّجَ اِبْنَتَيِ اَلرَّسُولِ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ}:
                             رُقَيَّةَ ثُمَّ بَعْدَ وَفَاتِهَا تَزَوَّجَ أُخْتَهَا أُمَّ كُلْثُومٍ {رَضِيَ اَللَّهُ عَنْهُمَا}.
                            كَانَ عُثْمَانُ {رَضِيَ اَللَّهُ عَنْهُ} مِنْ أَغْنِيَاءِ قُرَيْشٍ وَتُجَّارِهِمْ،
                             وَلَكِنَّهُ اِسْتَخْدَمَ مَالَهُ فِي طَاعَةِ اَللَّهِ، وَمِنْ أَبْرَزِ مَوَاقِفِهِ فِي اَلْإِنْفَاقِ:
                            - اِشْتَرَى اَلْبِئْرَ مِنَ يَهُودِيٍّ فِي اَلْمَدِينَةِ وَوَهَبَهَا لِلْمُسْلِمِينَ بَعْدَ اَلْهِجْرَةِ لِتَكُونَ مَاؤُهَا مُتَاحًا لِلْجَمِيعِ.
                            - تَجْهِيزُ جَيْشِ اَلْعُسْرَةِ: عِنْدَمَا اِسْتَعَدَّ اَلْمُسْلِمُونَ لِغَزْوَةِ تَبُوكَ،
                             جَهَّزَ عُثْمَانُ جُزْءًا كَبِيرًا مِنَ اَلْجَيْشِ بِالْمَالِ وَالسِّلَاحِ وَاَلرَّوَاحِلِ،
                              حَتَّى قَالَ اَلنَّبِيُّ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ}: "مَا ضَرَّ عُثْمَانَ مَا فَعَلَ بَعْدَ اَلْيَوْمِ".

                            3. أَهَمُّ إِنْجَازَاتِهِ فِي اَلْخِلَافَةِ (23 - 35 هـ)
                            تَوَلَّى عُثْمَانُ {رَضِيَ اَللَّهُ عَنْهُ} اَلْخِلَافَةَ بَعْدَ وَفَاةِ عُمَرَ بْنِ اَلْخَطَّابِ،
                             وَاِسْتَمَرَّتْ اِثْنَتَيْ عَشْرَةَ سَنَةً، وَكَانَ مِنْ أَهَمِّ إِنْجَازَاتِهِ:
                           
                            1. جَمْعُ اَلْقُرْآنِ اَلْكَرِيمِ (اَلْمُصْحَفُ اَلْإِمَامُ): لَاحَظَ عُثْمَانُ اِخْتِلَافَ اَلْمُسْلِمِينَ فِي بَعْضِ وُجُوهِ قِرَاءَةِ اَلْقُرْآنِ
                             بِسَبَبِ اِتِّسَاعِ اَلْفُتُوحَاتِ،
                             فَأَمَرَ بِنَسْخِ عِدَّةِ نُسَخٍ مِنْ اَلْقُرْآنِ عَلَى لَهْجَةِ قُرَيْشٍ (مُصْحَفِ حَفْصَةَ)
                              وَتَوْزِيعِهَا عَلَى اَلْأَمْصَارِ اَلْإِسْلَامِيَّةِ لِتَوْحِيدِهِمْ عَلَى قِرَاءَةٍ وَاحِدَةٍ.
                            
                            2. إِنْشَاءُ اَلْأُسْطُولِ اَلْبَحْرِيِّ اَلْإِسْلَامِيِّ: كَانَ هَذَا اَلْأُسْطُولُ اَلْأَوَّلُ فِي اَلْإِسْلَامِ،
                             وَقَدْ أَنْشِئَ لِحِمَايَةِ شَوَاطِئِ اَلْمُسْلِمِينَ مِنْ هَجَمَاتِ اَلرُّومِ،
                              وَلِيُسَاهِمَ فِي اَلْفُتُوحَاتِ (مِثْلَ فَتْحِ جَزِيرَةِ قُبْرُص).
                           
                            3. تَوْسِعَةُ اَلْمَسْجِدِ اَلْحَرَامِ وَاَلْمَسْجِدِ اَلنَّبَوِيِّ:
                             زَادَ عُثْمَانُ فِي مِسَاحَةِ اَلْمَسْجِدَيْنِ لِاِسْتِيعَابِ أَعْدَادِ اَلْمُسْلِمِينَ اَلْمُتَزَايِدَةِ.

                        """
                    }
                ]
            },
            "5": {
                "title": "عَلِيُّ بْنُ أَبِي طَالِبٍ",
                "body":
                [
                    {
                        "text":"""
                                <span style="color:green; font-weight:bold;"> الشَّجَاعَةُ، الْعِلْمُ، وَالْخِلَافَةُ</span><br>        
                                عَلِيُّ بْنُ أَبِي طَالِبٍ بْنِ عَبْدِ الْمُطَّلِبِ الْهَاشِمِيُّ الْقُرَشِيُّ،
                                 هُوَ اِبْنُ عَمِّ النَّبِيِّ مُحَمَّدٍ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ)، وَأَحَدُ سَادَاتِ قُرَيْشٍ نَسَبًا.
                                  وُلِدَ فِي مَكَّةَ الْمُكَرَّمَةِ قَبْلَ الْبِعْثَةِ النَّبَوِيَّةِ بِعَشْرِ سَنَوَاتٍ تَقْرِيبًا.
                                   نَشَأَ عَلِيٌّ فِي كَنَفِ النَّبِيِّ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ) فِي طُفُولَتِهِ؛
                                    حَيْثُ أَخَذَهُ الرَّسُولُ لِيَكْفُلَهُ تَخْفِيفًا لِلْعِبْءِ عَنْ عَمِّهِ أَبِي طَالِبٍ الَّذِي كَانَ كَثِيرَ الْعِيَالِ.
                                     وَبِذَلِكَ تَرَعْرَعَ عَلِيٌّ عَلَى الْأَخْلَاقِ النَّبَوِيَّةِ الْعَالِيَةِ.
                                كَانَ عَلِيٌّ أَوَّلَ مَنْ أَسْلَمَ مِنَ الصِّبْيَانِ، فَلَمْ يَسْجُدْ لِصَنَمٍ قَطُّ، وَلِهَذَا يُقَالُ لَهُ "كَرَّمَ اللَّهُ وَجْهَهُ".
                                 وَأَعْظَمُ مَوَاقِفِهِ قَبْلَ الْهِجْرَةِ كَانَتْ لَيْلَةَ الْهِجْرَةِ، حَيْثُ نَامَ فِي فِرَاشِ الرَّسُولِ،
                                  مُعَرِّضًا نَفْسَهُ لِلْخَطَرِ وَالْقَتْلِ مِنْ قُرَيْشٍ، لِيَتَمَكَّنَ النَّبِيُّ مِنْ الْخُرُوجِ سَالِمًا،
                                   وَهُوَ مَوْقِفٌ يُعَدُّ قِمَّةَ الْفِدَاءِ وَالتَّضْحِيَةِ.
                                فِي الْمَدِينَةِ الْمُنَوَّرَةِ، آخَى النَّبِيُّ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ) بَيْنَ عَلِيٍّ وَنَفْسِهِ.
                                 وَتَزَوَّجَ مِنْ اِبْنَتِهِ فَاطِمَةَ الزَّهْرَاءِ،
                                  وَأَنْجَبَ مِنْهَا سِبْطَيِ النُّبُوَّةِ، الْحَسَنَ وَ الْحُسَيْنَ.
                                شَارَكَ عَلِيٌّ فِي جَمِيعِ الْغَزَوَاتِ مَعَ النَّبِيِّ إِلَّا غَزْوَةَ تَبُوكَ،
                                 حَيْثُ اِسْتَخْلَفَهُ الرَّسُولُ عَلَى الْمَدِينَةِ.
                                  وَكَانَ عَلَمًا فِي الْقِتَالِ وَالشَّجَاعَةِ، وَشَاهِدًا عَلَى ذَلِكَ:

                                1. غَزْوَةُ بَدْرٍ: بَدَأَهَا بِالْمُبَارَزَةِ فَقَتَلَ الْوَلِيدَ بْنَ عُتْبَةَ،
                                 وَكَانَ لَهُ دَوْرٌ كَبِيرٌ فِي حَسْمِ الْمَعْرَكَةِ لِصَالِحِ الْمُسْلِمِينَ.

                                2. غَزْوَةُ الْخَنْدَقِ: قَتَلَ فِيهَا الْفَارِسَ الْمَشْهُورَ عَمْرَو بْنَ عَبْدِ وُدٍّ، وَبِذَلِكَ كَسَرَ شَوْكَةَ الْأَحْزَابِ.

                                3. غَزْوَةُ خَيْبَرَ: حَيْثُ أَعْطَاهُ النَّبِيُّ الرَّايَةَ 
                                بَعْدَ أَنْ قَالَ: "لَأُعْطِيَنَّ الرَّايَةَ غَدًا رَجُلًا يُحِبُّ اللَّهَ وَرَسُولَهُ وَيُحِبُّهُ اللَّهُ وَرَسُولُهُ، يَفْتَحُ اللَّهُ عَلَى يَدَيْهِ"،
                                 فَاِقْتَحَمَ الْحِصْنَ وَحَقَّقَ النَّصْرَ.
                                كَمَا اِشْتَهَرَ عَلِيٌّ بِسَيْفِهِ ذِي الْفَقَارِ الَّذِي أَهْدَاهُ لَهُ الرَّسُولُ.
                                لَمْ تَكُنْ بَطُولَةُ عَلِيٍّ مُقْتَصِرَةً عَلَى الْقِتَالِ،
                                 بَلْ كَانَ مِنْ أَغْزَرِ الصَّحَابَةِ عِلْمًا وَفِقْهًا. وَهُوَ أَحَدُ الصَّحَابَةِ الَّذِينَ أَفْتَوْا فِي حَيَاةِ النَّبِيِّ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ).
                                  قَالَ عُمَرُ بْنُ الْخَطَّابِ (رَضِيَ اللَّهُ عَنْهُ): "أَقْرَؤُنَا أُبَيٌّ وَأَقْضَانَا عَلِيٌّ".
                                  
                                • عِلْمُهُ: عُرِفَ بِإِتْقَانِهِ لِلْقُرْآنِ وَتَفْسِيرِهِ.
                                 وَكَانَ مُتَفَرِّدًا فِي الْقَضَاءِ وَحَلِّ الْمَسَائِلِ الْمُعَقَّدَةِ، حَتَّى أَرْسَلَهُ النَّبِيُّ إِلَى الْيَمَنِ قَاضِيًا وَدَاعِيًا.
                                
                                • فَصَاحَتُهُ: اِشْتُهِرَ بِالْفَصَاحَةِ وَالْبَلَاغَةِ، 
                                وَتُنْسَبُ إِلَيْهِ حِكَمٌ وَأَقْوَالٌ مَأْثُورَةٌ جُمِعَتْ فِي كُتُبٍ مِثْلَ "نَهْجِ الْبَلَاغَةِ".
                                
                                • زُهْدُهُ: كَانَ مَثَلًا لِلزُّهْدِ وَالتَّقَشُّفِ،
                                 فَكَانَتْ خِلَافَتُهُ اِمْتِدَادًا لِسِيرَةِ النَّبِيِّ وَأَبِي بَكْرٍ وَعُمَرَ فِي الْبُعْدِ عَنْ مَتَاعِ الدُّنْيَا.
                                تُوُلِّيَ عَلِيٌّ خِلَافَةَ الْمُسْلِمِينَ فِي ظُرُوفٍ عَصِيبَةٍ جِدًّا،
                                 بَعْدَ اِسْتِشْهَادِ الْخَلِيفَةِ عُثْمَانَ بْنِ عَفَّانَ (سَنَةَ 35 هـ).
                                  اِتَّسَمَتْ فَتْرَةُ خِلَافَتِهِ (خَمْسَ سَنَوَاتٍ) بِالْفِتَنِ الدَّاخِلِيَّةِ 
                                  وَالْخِلَافَاتِ السِّيَاسِيَّةِ الَّتِي شَغَلَتْهُ عَنْ اِسْتِكْمَالِ الْفُتُوحَاتِ الْخَارِجِيَّةِ، وَمِنْ أَبْرَزِ هَذِهِ الْأَحْدَاثِ:
                                
                                1. مَعْرَكَةُ الْجَمَلِ (36 هـ): دَارَتْ بَيْنَهُ وَبَيْنَ جَيْشِ الْمُطَالِبِينَ بِالْقِصَاصِ لِدَمِ عُثْمَانَ،
                                 وَكَانَتْ عَلَى رَأْسِهِمْ عَائِشَةُ أُمُّ الْمُؤْمِنِينَ.
                                
                                2. مَعْرَكَةُ صِفِّينَ (37 هـ): دَارَتْ بَيْنَهُ وَبَيْنَ مُعَاوِيَةَ بْنِ أَبِي سُفْيَانَ (وَالِي الشَّامِ) حَوْلَ قَضِيَّةِ الْقِصَاصِ.
                                 وَاِنْتَهَتْ بِالتَّحْكِيمِ الْمَعْرُوفِ.
                                
                                3. مَعْرَكَةُ النَّهْرَوَانِ (38 هـ): قَاتَلَ فِيهَا عَلِيٌّ فِرْقَةَ الْخَوَارِجِ الَّتِي اِعْتَزَلَتْهُ وَكَفَّرَتْهُ بِسَبَبِ قَبُولِهِ التَّحْكِيمَ.
                                نَقَلَ عَلِيٌّ عَاصِمَةَ الْخِلَافَةِ إِلَى الْكُوفَةِ فِي الْعِرَاقِ لِتَكُونَ أَقْرَبَ إِلَى مُوَاقِعِ الصِّرَاعِ. 
                                وَاِخْتُتِمَتْ سِيرَتُهُ بِاِسْتِشْهَادِهِ فِي رَمَضَانَ سَنَةَ 40 لِلْهِجْرَةِ عَلَى يَدِ عَبْدِ الرَّحْمَنِ بْنِ مُلْجَمٍ أَحَدِ الْخَوَارِجِ،
                                 لِيَكُونَ بِذَلِكَ آخِرَ الْخُلَفَاءِ الرَّاشِدِينَ.
                        """
                    },
                ]
            },
            "6": {
                "title": "السَّيِّدةُ خَدِيجَةُ بِنْتُ خُوَيْلِدٍ (رضي الله عنها)",
                "body":
                [
                    {
                        "text":"""        
                                هي خَدِيجَةُ بنتُ خُوَيْلِدِ بنِ أسدٍ القرشِيَّةُ، زَوْجَةُ نبيِّنَا الكريمِ مُحَمَّدٍ صلى الله عليه وسلم
                                 وأوَّلُ أُمَّهاتِ المُؤمنينَ. كانَتْ خَدِيجَةُ ذاتَ حَسَبٍ ونَسَبٍ وشَرَفٍ في قُرَيْشٍ.
                                كانتْ خديجةُ تَاجِرَةً غنيَّةً وناجِحَةً، ولها مالٌ كثيرٌ تُرْسِلُهُ في القوافِلِ التِّجاريةِ.
                                 وقد عُرِفَتْ في قَومِها بِعِفَّتِها ورَجَاحَةِ عَقْلِها وكَرَمِها.
                                  لُقِّبَتْ قبلَ الإسلامِ بـ "الطَّاهِرَةِ"، لِطِيبِ أَخلاقِها ونَزاهتِها.

                                عندما سَمِعَتْ عن أمانَةِ نبيِّنَا مُحَمَّدٍ صلى الله عليه وسلم وصدقِهِ،
                                 اسْتَأْجَرَتْهُ ليَخْرُجَ في تِجارتِها إلى الشَّامِ. بعدَ عودَتِهِ، أعجَبَتْ بِأمانَتِهِ وبركَةِ عملِهِ،
                                  فتقدَّمتْ إليهِ وطَلَبَتِ الزواجَ منهُ.
                                كانت خديجةُ أوَّلَ مَنْ آمَنَ بالرَّسولِ صلى الله عليه وسلم،
                                 فقد كانَتْ السَّنَدَ والعَوْنَ لَهُ في أَصْعَبِ الأوقاتِ.
                                عندما عادَ النَّبيُّ صلى الله عليه وسلم إلى بَيْتِهِ مرعوبًا بعدَ نزولِ الوحيِ لأوَّلِ مرَّةٍ في غارِ حِراءَ،
                                 قالتْ لهُ خديجةُ كلماتِها المَشْهُورَةَ التي تَدُلُّ على عقلِها الحكيمِ وإيمانِها القويِّ:
                                  "كَلَّا واللهِ! مَا يُخْزِيكَ اللهُ أَبَدًا، إِنَّكَ لَتَصِلُ الرَّحِمَ، وتَحْمِلُ الْكَلَّ، وتَكْسِبُ الْمَعْدُومَ،
                                   وَتَقْرِي الضَّيْفَ، وتُعينُ على نوائبِ الحقِّ".

                                وهي أمُّ جميعِ أولادِ النَّبيِّ صلى الله عليه وسلم، ما عدا إبراهيمَ.
                                 وظلَّتْ تُساندُهُ بِمالِها وكَلِمَتِها حتَّى تُوُفِّيَتْ رضي الله عنها قبلَ الهجرةِ بِثلاثِ سنينَ،
                                  وقد سَمَّى النبيُّ صلى الله عليه وسلم تلكَ السَّنةَ بِـ "عامِ الحُزْنِ".
                        """
                    },
                ]
            },
            "7": {
                "title": "أُمُّ اَلْمُؤْمِنِينَ حَفْصَةُ بِنْتُ عُمَرَ رَضِيَ اَللَّهُ عَنْهُمَا",
                "body":
                [
                    {
                        "text":"""        
                               حَفْصَة{رَضِيَ اَللَّهُ عَنْهَا} هِيَ إِحْدَى زَوْجَاتِ اَلنَّبِيِّ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ}،
                                وَهِيَ شَخْصِيَّةٌ عَظِيمَةٌ يُمْكِنُ لَنَا أَنْ نَتَعَلَّمَ مِنْهَا اَلْكَثِيرَ.

                                • هِيَ حَفْصَةُ بِنْتُ عُمَرَ بْنِ اَلْخَطَّابِ {رَضِيَ اَللَّهُ عَنْهُ}، اَلْخَلِيفَةِ اَلثَّانِي وَ "اَلْفَارُوقِ".
                                أَسْلَمَتْ حَفْصَةُ {رَضِيَ اَللَّهُ عَنْهَا} فِي مَكَّةَ مَعَ أَبِيهَا، ثُمَّ هَاجَرَتْ إِلَى اَلْمَدِينَةِ.
                                تَزَوَّجَتْ قَبْلَ اَلنَّبِيِّ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ} مِنْ اَلصَّحَابِيِّ خُنَيْسِ بْنِ حُذَافَةَ
                                 اَلَّذِي اِسْتُشْهِدَ مُتَأَثِّرًا بِجِرَاحِهِ بَعْدَ غَزْوَةِ بَدْرٍ.
                                وبَعْدَ وَفَاةِ زَوْجِهَا، اِقْتَرَحَ عُمَرُ عَلَى أَبِي بَكْرٍ وَعُثْمَانَ زَوَاجَهُمَا مِنْهَا،
                                 ثُمَّ بَعْدَ ذَلِكَ، خَطَبَهَا اَلنَّبِيُّ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ} لِنَفْسِهِ فِي شَعْبَانَ سَنَةَ 3 هـ،
                                  وَبِذَلِكَ حَظِيَتْ بِشَرَفِ أَنْ تَكُونَ أُمَّ اَلْمُؤْمِنِينَ.

                                لُقِّبَتْ حَفْصَةُ {رَضِيَ اَللَّهُ عَنْهَا} بِـ "اَلصَّوَّامَةِ اَلْقَوَّامَةِ" (كَثِيرَةِ اَلصِّيَامِ وَاَلْقِيَامِ)
                                 بِشَهَادَةِ اَلْمَلَكِ جِبْرِيلَ {عَلَيْهِ اَلسَّلَامُ} لِلنَّبِيِّ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ}
                                كَانَتْ حَفْصَةُ {رَضِيَ اَللَّهُ عَنْهَا} تُعْرَفُ بِقُوَّةِ اَلْحِفْظِ وَ اَلْعِلْمِ.
                                 وَاَلْمَنْقَبَةُ اَلْأَهَمُّ لَهَا هِيَ أَنَّ اَلْخَلِيفَةَ أَبَا بَكْرٍ {رَضِيَ اَللَّهُ عَنْهُ}
                                  جَعَلَهَا اَلْأَمِينَةَ عَلَى اَلصُّحُفِ اَلْأُولَى لِلْقُرْآنِ اَلْكَرِيمِ اَلَّتِي جُمِعَتْ بَعْدَ وَفَاةِ اَلنَّبِيِّ {صَلَّى اَللَّهُ عَلَيْهِ وَسَلَّمَ}
                                هَذِهِ اَلصُّحُفُ هِيَ اَلَّتِي اِعْتَمَدَ عَلَيْهَا اَلْخَلِيفَةُ عُثْمَانُ بْنُ عَفَّانَ لِنَسْخِ "اَلْمُصْحَفِ اَلْإِمَامِ" وَتَوْزِيعِهِ عَلَى اَلْأَمْصَارِ.
                                 وَهَذَا يَدُلُّ عَلَى عِظَمِ مَكَانَتِهَا وَأَمَانَتِهَا اَلْعِلْمِيَّةِ.
                                كَانَتْ حَفْصَةُ مِنْ اَلنِّسَاءِ اَلْقَلَائِلِ اَللَّاتِي أَتْقَنَّ اَلْكِتَابَةَ فِي ذَلِكَ اَلْوَقْتِ،
                                 مِمَّا يَدُلُّ عَلَى اِهْتِمَامِهَا بِاَلْعِلْمِ.
                        """
                    },
                ]
            },
            "8": {
                "title": "زَيْنَبُ بِنْتُ الرَّسُولِ (رضي الله عنها)",
                "body":
                [
                    {
                        "text":"""        
                               كانَتْ زَيْنَبُ هِيَ أَكْبَرُ بَنَاتِ النَّبِيِّ مُحَمَّدٍ صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ مِنْ زَوْجَتِهِ خَدِيجَةَ رَضِيَ اللهُ عَنْهَا.
                                وُلِدَتْ زَيْنَبُ فِي مَكَّةَ قَبْلَ البِعْثَةِ بِعَشْرِ سَنَوَاتٍ تَقْرِيبًا.
                                عَاشَتْ زَيْنَبُ فِي كَنَفِ أَبَوَيْنِ كَرِيمَيْنِ،
                                 وتَزَوَّجَتْ مِنْ أَبِي العَاصِ بنِ الرَّبِيعِ، وَهُوَ ابْنُ خَالَتِهَا. كانَتْ حَيَاتُهُمَا سَعِيدَةً وَهَادِئَةً.

                                عِنْدَمَا أُنْزِلَ الوَحْيُ عَلَى النَّبِيِّ مُحَمَّدٍ، أَسْلَمَتْ زَيْنَبُ مُبَاشَرَةً،
                                 لَكِنَّ زَوْجَهَا أَبَا العَاصِ ظَلَّ عَلَى دِينِ قَوْمِهِ مُشْرِكاً، فَلَمْ يُسْلِمْ فِي بِدَايَةِ الأَمْرِ.
                                  وَبِسَبَبِ اخْتِلَافِ الدِّينِ، فَرَّقَ الإِسْلَامُ بَيْنَهُمَا وَلَمْ يَكُنْ يَجُوزُ لِلْمُسْلِمَةِ البَقَاءُ فِي عِصْمَةِ مُشْرِكٍ.
                                ظَلَّتْ زَيْنَبُ فِي مَكَّةَ مَعَ بَنَاتِهَا وَابْنِهَا بَعْدَ هِجْرَةِ النَّبِيِّ إِلَى المَدِينَةِ.

                                 وَكَانَ لَهَا مَوْقِفٌ بَطُولِيٌّ فِي الهِجْرَةِ؛ فَعِنْدَمَا خَرَجَتْ مُهَاجِرَةً،
                                  تَعَرَّضَتْ لِلأَذَى مِنْ قُرَيْشٍ. وَبَعْدَ مَشَقَّةٍ وَصُعُوبَةٍ، وَصَلَتْ إِلَى المَدِينَةِ.
                                أَمَّا أَبُو العَاصِ، فَقَدْ وَقَعَ أَسِيراً فِي يَدِ المُسْلِمِينَ فِي غَزْوَةِ بَدْرٍ.
                                 وَقْتَئِذٍ، بَعَثَتْ زَيْنَبُ بِـ قِلَادَةٍ لِفِدَائِهِ (لإِطْلاقِ سَرَاحِهِ).
                                 وَهَذِهِ القِلَادَةُ كَانَتْ هَدِيَّةً قَدَّمَتْهَا لَهَا أُمُّهَا خَدِيجَةُ يَوْمَ زِفَافِهَا.
                                  عِنْدَمَا رَأَى النَّبِيُّ مُحَمَّدٌ القِلَادَةَ، رَقَّ قَلْبُهُ لِذِكْرَى خَدِيجَةَ،
                                   فَأَمَرَ بِإِطْلَاقِ سَرَاحِ أَبِي العَاصِ، عَلَى شَرْطِ أَنْ يُطْلِقَ سَرَاحَ زَيْنَبَ لِتَلْحَقَ بِأَبِيهَا.
                                بَعْدَ سِنِينَ، أَسْلَمَ أَبُو العَاصِ وَجَاءَ مُهَاجِراً إِلَى المَدِينَةِ، 
                                وَجَمَعَهُمَا النَّبِيُّ مُحَمَّدٌ مَرَّةً أُخْرَى، فَعَادَتْ زَيْنَبُ إِلَى زَوْجِهَا الذِي أَحَبَّتْ.


                                <span style="color:green; font-weight:bold;"> أَبْنَاءُ زَيْنَبَ بِنْتِ الرَّسُولِ (رضي الله عنها)</span><br>        
                                أَنْجَبَتِ السَّيِّدَةُ زَيْنَبُ بِنْتُ الرَّسُولِ صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ مِنْ زَوْجِهَا أَبِي الْعَاصِ بْنِ الرَّبِيعِ
                                 وَلَدَيْنِ هُمَا:
                                1. اِبْنٌ اِسْمُهُ: عَلِيٌّ.
                                2. اِبْنَةٌ اِسْمُهَا: أُمَامَةُ.

                                • عَلِيُّ بْنُ أَبِي الْعَاصِ: يُذْكَرُ أَنَّهُ أَدْرَكَ الْإِسْلَامَ وَرَكِبَ خَلْفَ النَّبِيِّ صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ 
                                عَلَى نَاقَتِهِ يَوْمَ فَتْحِ مَكَّةَ، وَتُوُفِّيَ فِي صِغَرِهِ.
                                • أُمَامَةُ بِنْتُ أَبِي الْعَاصِ: هِيَ أَشْهَرُ أَوْلَادِ زَيْنَبَ.
                                 كَانَ النَّبِيُّ صَلَّى اللهُ عَلَيْهِ وَسَلَّمَ يُحِبُّهَا وَيَحْمِلُهَا وَهُوَ يُصَلِّي بِالنَّاسِ،
                                 فَإِذَا سَجَدَ وَضَعَهَا، وَإِذَا قَامَ حَمَلَهَا.
                                  تَزَوَّجَتْ فِيمَا بَعْدُ مِنْ عَلِيِّ بْنِ أَبِي طَالِبٍ (رَضِيَ اللهُ عَنْهُ)
                                   بَعْدَ وَفَاةِ خَالتِها فَاطِمَةَ الزَّهْرَاءِ، ثُمَّ تَزَوَّجَتْ مِنْ الْمُغِيرَةِ بْنِ نَوْفَلٍ بَعْدَ وَفَاةِ عَلِيٍّ. 
                                تُوُفِّيَتْ زَيْنَبُ فِي السَّنَةِ الثَّامِنَةِ لِلْهِجْرَةِ.
                        """
                    },
                ]
            },
            "9": {
                "title": "فَاطِمَةُ الزَّهْرَاءُ بِنْتُ مُحَمَّدٍ (رَضِيَ اللَّهُ عَنْهَا)",
                "body":
                [
                    {
                        "text":"""  
                                هِيَ فَاطِمَةُ بِنْتُ مُحَمَّدٍ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ)،
                                 وَأُمُّهَا هِيَ خَدِيجَةُ بِنْتُ خُوَيْلِدٍ (رَضِيَ اللَّهُ عَنْهَا)، 
                                أَوَّلُ زَوْجَاتِ النَّبِيِّ. وُلِدَتْ فَاطِمَةُ فِي مَكَّةَ الْمُكَرَّمَةِ قَبْلَ الْبِتْعَةِ النَّبَوِيَّةِ بِقَلِيلٍ.
                                عَاشَتْ فَاطِمَةُ طُفُولَتَهَا وَفَتَاهَتَهَا فِي بَيْتِ النُّبُوَّةِ،
                                 وَشَهِدَتْ مُنْذُ صِغَرِهَا الْأَذَى الَّذِي كَانَ يَلْحَقُ بِأَبِيهَا مِنْ كُفَّارِ قُرَيْشٍ،
                                  فَكَانَتْ سَنَدًا لَهُ. وَعِنْدَمَا تُوُفِّيَتْ أُمُّهَا خَدِيجَةُ،
                                   اِزْدَادَ تَعَلُّقُهَا بِأَبِيهَا وَرِعَايَتُهَا لَهُ.

                                <span style="color:green; font-weight:bold;">لُقِّبَتْ فَاطِمَةُ بِلَقَبَيْنِ مُهِمَّيْنِ:</span><br> 
                                1. الزَّهْرَاءُ: لِجَمَالِهَا وَإِشْرَاقِ وَجْهِهَا، وَنَقَاءِ سِيرَتِهَا.
                                2. أُمُّ أَبِيهَا: وَهُوَ لَقَبٌ عَزِيزٌ دَلِيلٌ عَلَى شِدَّةِ حُبِّهَا لِلنَّبِيِّ 
                                وَقِيَامِهَا بِرِعَايَتِهِ وَالْوُقُوفِ إِلَى جَانِبِهِ كَالْأُمِّ لِوَلَدِهَا.

                                <span style="color:green; font-weight:bold;"> الْحَيَاةُ الزَّوْجِيَّةُ وَالْعَائِلَةُ</span><br> 
                                هَاجَرَتْ فَاطِمَةُ إِلَى الْمَدِينَةِ الْمُنَوَّرَةِ مَعَ الْمُسْلِمِينَ.
                                 وَفِي الْمَدِينَةِ، تَزَوَّجَتْ مِنْ عَلِيِّ بْنِ أَبِي طَالِبٍ (رَضِيَ اللَّهُ عَنْهُ)،
                                  وَهُوَ اِبْنُ عَمِّ النَّبِيِّ وَرَابِعُ الْخُلَفَاءِ الرَّاشِدِينَ. وَكَانَ زَوَاجُهُمَا بَسِيطًا وَزَاهِدًا.

                                أَنْجَبَتْ فَاطِمَةُ لِعَلِيٍّ:
                                • الْحَسَنَ وَ الْحُسَيْنَ (رَضِيَ اللَّهُ عَنْهُمَا)،
                                 وَهُمَا سَيِّدَا شَبَابِ أَهْلِ الْجَنَّةِ.
                                • وَبَنَاتٍ مِثْلَ زَيْنَبَ وَ أُمِّ كُلْثُومٍ.
                                كَانَتْ حَيَاتُهَا الزَّوْجِيَّةُ مِثَالًا لِلْصَّبْرِ وَالْزُّهْدِ وَالْعَفَافِ.
                                 وَعَلَى الرَّغْمِ مِنْ أَنَّهَا بِنْتُ سَيِّدِ الْقَوْمِ، إِلَّا أَنَّهَا كَانَتْ تَقُومُ بِأَعْمَالِ مَنْزِلِهَا بِنَفْسِهَا
                                  وَتَطْحَنُ الْقَمْحَ، وَكَانَتْ قُدْوَةً لِجَمِيعِ النِّسَاءِ فِي بَسَاطَةِ الْعَيْشِ وَالْإِيمَانِ الْقَوِيِّ

                                <span style="color:green; font-weight:bold;">وَفَاتُهَا وَمَكَانَتُهَا</span><br> 
                                لِفَاطِمَةَ مَكَانَةٌ عَظِيمَةٌ، فَقَدْ قَالَ عَنْهَا الرَّسُولُ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ):
                                 "فَاطِمَةُ سَيِّدَةُ نِسَاءِ أَهْلِ الْجَنَّةِ".
                                  وَكَانَتْ أَشْبَهَ النَّاسِ بِأَبِيهَا فِي هَيْئَتِهِ وَطَرِيقَةِ كَلَامِهِ وَمَشْيِهِ.
                                تُوُفِّيَتْ فَاطِمَةُ (رَضِيَ اللَّهُ عَنْهَا) بَعْدَ وَفَاةِ أَبِيهَا النَّبِيِّ (صَلَّى اللَّهُ عَلَيْهِ وَسَلَّمَ) بِفَتْرَةٍ قَصِيرَةٍ (حَوَالِي سِتَّةِ أَشْهُرٍ).
                                 وَدُفِنَتْ فِي الْمَدِينَةِ الْمُنَوَّرَةِ.
                                  وَتَبْقَى سِيرَتُهَا دَرْسًا فِي الْإِيمَانِ، وَالْبِرِّ بِالْوَالِدَيْنِ، وَالصَّبْرِ عَلَى الْحَيَاةِ.
                        """
                    },
                ]
            },
            
        }
    }
    if not level:
        return render(request, "core/library.html", {"level": None})

    if level not in valid_levels:
        return redirect(reverse("library"))

    if sid:
        story_map = STORIES.get(level, {})
        story = story_map.get(sid)
        if not story:
            return redirect(f"{reverse('library')}?level={level}")
        

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
        })

    sentences = []
    for s_id, s_data in STORIES.get(level, {}).items():
        href = f"{reverse('library')}?level={level}&sid={s_id}"   # <<--- NICHT "#"
        sentences.append({"title": s_data["title"], "href": href})

    return render(request, "core/library.html", {
        "level": level,
        "level_title": valid_levels[level],
        "sentences": sentences,
    })