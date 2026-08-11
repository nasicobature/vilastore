"""
WSGI config for VilaStore project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'VilaStore.settings')

if settings.STATIC_ROOT:
    os.makedirs(settings.STATIC_ROOT, exist_ok=True)

application = get_wsgi_application()
