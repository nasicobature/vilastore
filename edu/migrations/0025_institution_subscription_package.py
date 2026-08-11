from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('edu', '0024_edu_subscription_pricing'),
    ]

    operations = [
        migrations.AddField(
            model_name='institution',
            name='subscription_package',
            field=models.CharField(default='starter', max_length=40),
        ),
        migrations.AlterField(
            model_name='institution',
            name='subscription_billing_cycle',
            field=models.CharField(
                choices=[('termly', 'Per Term'), ('session', 'Per Session')],
                default='termly',
                max_length=20,
            ),
        ),
    ]
