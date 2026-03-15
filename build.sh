#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
mkdir -p "${MEDIA_ROOT:-media}"
python manage.py collectstatic --no-input
python manage.py check_static_assets
python manage.py migrate
