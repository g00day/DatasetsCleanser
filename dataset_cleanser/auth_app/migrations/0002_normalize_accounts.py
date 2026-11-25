from django.db import migrations, models


def normalize_accounts(apps, schema_editor):
    accounts = apps.get_model("auth_app", "Account").objects.using(schema_editor.connection.alias)
    usernames = set()
    emails = set()
    for account in accounts.order_by("id").iterator():
        username_key = account.username.strip().casefold()
        email = account.email.strip().casefold()
        if username_key in usernames or email in emails or len(email) > 256:
            raise RuntimeError("Resolve conflicting legacy account identifiers before migrating.")
        usernames.add(username_key)
        emails.add(email)

    for account in accounts.order_by("id").iterator():
        account.username_key = account.username.strip().casefold()
        account.email = account.email.strip().casefold()
        account.updated_at = account.updated_at or account.created_at
        account.save(update_fields=["username_key", "email", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("auth_app", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="account", name="username_key",
            field=models.TextField(null=True, editable=False),
        ),
        migrations.RunPython(normalize_accounts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="account", name="username_key",
            field=models.TextField(unique=True, editable=False),
        ),
    ]
