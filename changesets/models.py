from django.db import models
from django.utils import timezone

class Changeset(models.Model):
    changeset_id = models.BigIntegerField(unique=True)
    created_at = models.DateTimeField(null=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    open = models.BooleanField(null=True)
    changes_count = models.IntegerField(null=True)
    user = models.CharField(max_length=100, null=True)
    user_id = models.IntegerField(null=True)
    min_lat = models.FloatField(null=True)
    max_lat = models.FloatField(null=True)
    min_lon = models.FloatField(null=True)
    max_lon = models.FloatField(null=True)
    comments_count = models.IntegerField(null=True)
    comment = models.TextField(null=True)
    created_by = models.CharField(max_length=100, null=True) # editor name
    locale = models.CharField(max_length=100, null=True) # language code
    source = models.CharField(max_length=100, null=True) # used only with JOSM and Streetcomplete apps
    hashtags = models.JSONField(null=True, default=list) # list of hashtags
    imagery_used = models.CharField(max_length=100, null=True) # iD dedicated tag
    host = models.CharField(max_length=100, null=True) # iD dedicated tag
    additional_tags = models.JSONField(null=True)
    sequence_from = models.IntegerField(null=True) # Sequence from which the changeset was fetched
    history = models.JSONField(null=True, default=list) # Stores the history of the changeset

    def __str__(self):
        return str(self.changeset_id)