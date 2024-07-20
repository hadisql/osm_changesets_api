web: gunicorn osm_changeset_api.wsgi:application

release: django-admin migrate --no-input && django-admin collectstatic --no-input