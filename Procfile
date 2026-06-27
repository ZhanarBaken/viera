web: python manage.py migrate && python manage.py collectstatic --noinput && python manage.py create_admin && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 30 --graceful-timeout 30
worker: celery -A config worker -l info -Ofair
