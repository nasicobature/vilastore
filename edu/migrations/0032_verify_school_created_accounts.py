from django.db import migrations

# Profiles the school itself created (a creator role is recorded in created_via and
# an approver is set). The school vouches for these email addresses, so they no
# longer need to click a verification link before their first login.
SELF_SERVICE_SOURCES = ['', 'self', 'school-register', 'repaired-login']


def verify_school_created_accounts(apps, schema_editor):
    Profile = apps.get_model('edu', 'Profile')
    (
        Profile.objects.filter(email_verified=False, approved_by__isnull=False)
        .exclude(created_via__in=SELF_SERVICE_SOURCES)
        .update(email_verified=True)
    )


class Migration(migrations.Migration):

    dependencies = [
        ('edu', '0031_alter_edumembership_role_alter_profile_role_and_more'),
    ]

    operations = [
        migrations.RunPython(verify_school_created_accounts, migrations.RunPython.noop),
    ]
