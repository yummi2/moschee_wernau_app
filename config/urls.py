"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from core.views import home, profile_view
from django.conf import settings
from django.conf.urls.static import static
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home, name='home'),
    path('accounts/', include('django.contrib.auth.urls')),  # Login/Logout/Passwort
    path('profile/', profile_view, name='profile'),
    path("absences/mark/", views.mark_absence, name="mark_absence"),
    path("assignments/<int:pk>/", views.assignment_detail, name="assignment_detail"),
    path("checklist/toggle/", views.toggle_check, name="toggle_check"),
    path("admin/banner/", views.set_banner, name="set_banner"),
    path('library/', views.library, name='library'),
    path("ajax/mark-story-read/", views.mark_story_read, name="mark_story_read"),
    path("prayer/toggle/", views.toggle_prayer, name="toggle_prayer"),
    path("ramadan-plan/", views.ramadan_plan, name="ramadan_plan"),
    path("ramadan/<int:day>/", views.ramadan_day, name="ramadan_day"),
    path("ramadan/mark-done/", views.mark_ramadan_item_done, name="mark_ramadan_item_done"),

]
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
