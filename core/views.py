from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from .models import Profile, Assignment
from .forms import ProfileForm
from django.contrib import messages
import calendar
import datetime as dt

def home(request):
    assignments = []
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

        #  Mini-Kalender (immer berechnen – unabhängig von Klassen)
        today = dt.date.today()
        y = int(request.GET.get("y", today.year))
        m = int(request.GET.get("m", today.month))

        # Monat in 1..12 halten
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1

        special_dates = {
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

        special_map = {
            d.day: cls
            for d, cls in special_dates.items()
            if d.year == y and d.month == m
        }


    def month_neighbors(year, month):
        first = dt.date(year, month, 1)
        prev_last = first - dt.timedelta(days=1)
        next_first = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return (prev_last.year, prev_last.month), (next_first.year, next_first.month)

    (py, pm), (ny, nm) = month_neighbors(y, m)
    weeks = calendar.monthcalendar(y, m)
    
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
