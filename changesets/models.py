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
    suspicion_score = models.IntegerField(null=True) # 0-100, rule-based (computed at ingestion)
    suspicion_flags = models.JSONField(null=True, default=list) # names of the triggered rules
    ml_score = models.FloatField(null=True) # 0-100 percentile of Isolation Forest anomaly score

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at']),
            models.Index(fields=['closed_at']),
            models.Index(fields=['user']),
            models.Index(fields=['created_by']),
            models.Index(fields=['changes_count']),
            models.Index(fields=['sequence_from']),
            models.Index(fields=['suspicion_score']),
            models.Index(fields=['ml_score']),
        ]

    def __str__(self):
        return str(self.changeset_id)