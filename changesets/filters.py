import django_filters
from django.db.models import TextField
from django.db.models.functions import Cast
from rest_framework.exceptions import ValidationError

from .models import Changeset


class ChangesetFilter(django_filters.FilterSet):
    """
    Query filters for the /api/changesets/ endpoint.

    Examples:
        ?user=JohnDoe
        ?editor=JOSM
        ?hashtag=hotosm-project-123
        ?created_after=2026-07-01T00:00:00Z&created_before=2026-07-02T00:00:00Z
        ?bbox=2.2,48.8,2.5,48.9   (min_lon,min_lat,max_lon,max_lat)
        ?min_changes=100
    """
    user = django_filters.CharFilter(field_name='user', lookup_expr='iexact')
    uid = django_filters.NumberFilter(field_name='user_id')
    editor = django_filters.CharFilter(
        field_name='created_by', lookup_expr='icontains',
        help_text="Editor name, e.g. 'iD', 'JOSM', 'StreetComplete' (matched inside created_by).",
    )
    hashtag = django_filters.CharFilter(method='filter_hashtag',
                                        help_text="Hashtag with or without leading '#'.")
    comment_contains = django_filters.CharFilter(field_name='comment', lookup_expr='icontains')
    created_after = django_filters.IsoDateTimeFilter(field_name='created_at', lookup_expr='gte')
    created_before = django_filters.IsoDateTimeFilter(field_name='created_at', lookup_expr='lte')
    open = django_filters.BooleanFilter(field_name='open')
    min_changes = django_filters.NumberFilter(field_name='changes_count', lookup_expr='gte')
    max_changes = django_filters.NumberFilter(field_name='changes_count', lookup_expr='lte')
    sequence = django_filters.NumberFilter(field_name='sequence_from')
    bbox = django_filters.CharFilter(method='filter_bbox',
                                     help_text="min_lon,min_lat,max_lon,max_lat — changesets intersecting this box.")
    country = django_filters.CharFilter(field_name='country_code', lookup_expr='iexact',
                                        help_text="ISO 3166-1 alpha-2 country code, e.g. FR.")
    min_suspicion = django_filters.NumberFilter(field_name='suspicion_score', lookup_expr='gte',
                                                help_text="Rule-based suspicion score threshold (0-100).")
    min_ml_score = django_filters.NumberFilter(field_name='ml_score', lookup_expr='gte',
                                               help_text="Isolation Forest anomaly percentile threshold (0-100).")
    flag = django_filters.CharFilter(method='filter_flag',
                                     help_text="Changesets carrying this suspicion flag "
                                               "(e.g. huge_bbox, high_change_count, new_mapper, review_requested, no_comment).")

    class Meta:
        model = Changeset
        fields = []

    def filter_hashtag(self, queryset, name, value):
        hashtag = value if value.startswith('#') else f'#{value}'
        # hashtags is a JSON list; casting to text lets the exact '"#tag"' token be
        # matched on both SQLite and PostgreSQL
        return queryset.annotate(
            hashtags_text=Cast('hashtags', TextField())
        ).filter(hashtags_text__icontains=f'"{hashtag}"')

    def filter_flag(self, queryset, name, value):
        # same JSON-list-as-text trick as filter_hashtag
        return queryset.annotate(
            flags_text=Cast('suspicion_flags', TextField())
        ).filter(flags_text__icontains=f'"{value}"')

    def filter_bbox(self, queryset, name, value):
        try:
            min_lon, min_lat, max_lon, max_lat = (float(part) for part in value.split(','))
        except ValueError:
            raise ValidationError({'bbox': "Expected format: min_lon,min_lat,max_lon,max_lat (four floats)."})
        # keep changesets whose bounding box intersects the requested one
        return queryset.filter(
            min_lon__lte=max_lon, max_lon__gte=min_lon,
            min_lat__lte=max_lat, max_lat__gte=min_lat,
        )
