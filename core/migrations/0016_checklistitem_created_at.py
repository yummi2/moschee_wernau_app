import datetime

from django.db import migrations, models


def date_existing_checklist_items(apps, schema_editor):
    ChecklistItem = apps.get_model("core", "ChecklistItem")
    existing_date = datetime.datetime(
        2026, 8, 20, 12, 0, tzinfo=datetime.timezone.utc
    )
    ChecklistItem.objects.filter(created_at__isnull=True).update(created_at=existing_date)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_assignmentcompletion"),
    ]

    operations = [
        migrations.AddField(
            model_name="checklistitem",
            name="created_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(
            date_existing_checklist_items,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="checklistitem",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
