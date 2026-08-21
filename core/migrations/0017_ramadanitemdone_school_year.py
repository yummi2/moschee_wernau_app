from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_checklistitem_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="ramadanitemdone",
            name="school_year",
            field=models.CharField(default="2026", max_length=4),
        ),
        migrations.AlterUniqueTogether(
            name="ramadanitemdone",
            unique_together={("user", "day", "item_key", "school_year")},
        ),
    ]
