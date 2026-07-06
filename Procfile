web: gunicorn osm_changeset_api.wsgi:application

worker: python manage.py ingest_changesets --follow --retention-days 7

release: django-admin migrate --no-input && django-admin collectstatic --no-input