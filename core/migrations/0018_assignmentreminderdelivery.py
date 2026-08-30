import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_ramadanitemdone_school_year"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AssignmentReminderDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recipient_email", models.EmailField(max_length=254)),
                ("due_at", models.DateTimeField()),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                ("assignment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reminder_deliveries", to="core.assignment")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignment_reminders", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="assignmentreminderdelivery",
            constraint=models.UniqueConstraint(fields=("user", "assignment", "due_at"), name="unique_assignment_due_reminder"),
        ),
    ]
