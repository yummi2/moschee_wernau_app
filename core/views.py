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
        "advanced": {"1": {"title": "نص متقدم 1", "body": ["…"]}},
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