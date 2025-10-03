#!/usr/bin/env bash
set -e
python manage.py collectstatic --noinput
python manage.py migrate --noinput
gunicorn config.wsgi --bind 0.0.0.0:$PORT --access-logfile - --error-logfile -
