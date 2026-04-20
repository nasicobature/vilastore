from django.apps import AppConfig


class EduConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "edu"
    verbose_name = "Education Portal"

    def ready(self):
        import edu.signals  # noqa: F401

