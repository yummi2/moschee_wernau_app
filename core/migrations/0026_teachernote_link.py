from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_alter_studentchecklist_unique_together_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="teachernote",
            name="link",
            field=models.URLField(blank=True, null=True, verbose_name="Link"),
        ),
    ]
