from django.db import migrations, models


def create_attendance_api_control(apps, schema_editor):
    AttendanceApiControl = apps.get_model("core", "AttendanceApiControl")
    AttendanceApiControl.objects.create(enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0026_teachernote_link"),
    ]

    operations = [
        migrations.CreateModel(
            name="AttendanceApiControl",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="AttendanceApiLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("remote_address", models.GenericIPAddressField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("status_code", models.PositiveSmallIntegerField()),
                ("successful", models.BooleanField(default=False)),
                ("message", models.CharField(blank=True, max_length=240)),
            ],
            options={"ordering": ("-requested_at", "-id")},
        ),
        migrations.RunPython(create_attendance_api_control, migrations.RunPython.noop),
    ]
