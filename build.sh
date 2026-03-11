#!/usr/bin/env bash
set -o errexit

mkdir -p "${MEDIA_ROOT:-media}"
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py check_static_assets
python manage.py migrate
