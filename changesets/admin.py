from django.contrib import admin

from .models import Changeset

class ChangesetAdmin(admin.ModelAdmin):
    list_display = ('changeset_id', 'created_at', 'closed_at', 'open', 'changes_count', 'user', 'user_id', 'min_lat', 'max_lat', 'min_lon', 'max_lon', 'comments_count', 'tags')
    search_fields  = ['changeset_id']

admin.site.register(Changeset, ChangesetAdmin)
