import datetime as dt
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import Assignment, AssignmentCompletion, AssignmentReminderDelivery


class Command(BaseCommand):
    help = "Send one bundled reminder per email address for assignments due tomorrow."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Local send date in YYYY-MM-DD format (for testing).")

    def handle(self, *args, **options):
        send_date = dt.date.fromisoformat(options["date"]) if options["date"] else timezone.localdate()
        due_date = send_date + dt.timedelta(days=1)
        assignments = Assignment.objects.filter(due_at__isnull=False, due_at__date=due_date).select_related("classroom")
        grouped = defaultdict(list)
        User = get_user_model()

        for assignment in assignments:
            students = User.objects.filter(
                Q(classes_as_student=assignment.classroom) | Q(profile__classroom=assignment.classroom),
                is_active=True,
            ).exclude(email="").distinct()
            completed_ids = set(AssignmentCompletion.objects.filter(
                assignment=assignment, user__in=students,
            ).values_list("user_id", flat=True))
            sent_ids = set(AssignmentReminderDelivery.objects.filter(
                assignment=assignment, due_at=assignment.due_at, user__in=students,
            ).values_list("user_id", flat=True))

            for student in students:
                if student.pk not in completed_ids and student.pk not in sent_ids:
                    grouped[student.email.strip().casefold()].append((student, assignment))

        sent_messages = 0
        for recipient, entries in grouped.items():
            lines_de, lines_ar = [], []
            for student, assignment in entries:
                deadline = timezone.localtime(assignment.due_at).strftime("%d.%m.%Y, %H:%M")
                account = student.get_full_name().strip() or student.username
                lines_de.append(f"• {account}: {assignment.title} ({assignment.classroom.name}) – fällig {deadline}")
                lines_ar.append(f"• {account}: {assignment.title} ({assignment.classroom.name}) – موعد التسليم {deadline}")

            body = (
                "Hausaufgaben-Erinnerung\n\nFolgende Hausaufgaben sind morgen fällig:\n"
                + "\n".join(lines_de)
                + "\n\nيرجى الانتباه: الواجبات التالية موعد تسليمها غدًا:\n"
                + "\n".join(lines_ar)
                + "\n\nDar Al Farah | دار الفرح"
            )
            EmailMessage(
                subject="Hausaufgaben morgen fällig | تذكير بالواجبات",
                body=body,
                to=[recipient],
            ).send(fail_silently=False)

            with transaction.atomic():
                AssignmentReminderDelivery.objects.bulk_create([
                    AssignmentReminderDelivery(
                        user=student, assignment=assignment,
                        recipient_email=recipient, due_at=assignment.due_at,
                    ) for student, assignment in entries
                ], ignore_conflicts=True)
            sent_messages += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent_messages} reminder email(s) for {due_date}."))
