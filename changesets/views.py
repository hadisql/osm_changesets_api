import logging
import re
from collections import Counter

from django.db.models import Count, Max, Min, Sum
from django.db.models.functions import TruncDay, TruncHour
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.views.generic import TemplateView
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .filters import ChangesetFilter
from .models import Changeset
from .osm_fetcher import fetch_and_process_changesets
from .osm_utils import SequenceFetchError, fetch_sequence_xml, get_last_sequence
from .serializers import ChangesetListSerializer, ChangesetSerializer

logger = logging.getLogger(__name__)


##############################################
### Query API: read the ingested database

@extend_schema(
    summary="List ingested changesets",
    description="Paginated list of changesets stored in the database, "
                "filterable by user, editor, hashtag, date range, bounding box…",
)
class ChangesetQueryView(generics.ListAPIView):
    queryset = Changeset.objects.all()
    serializer_class = ChangesetListSerializer
    filterset_class = ChangesetFilter
    ordering_fields = ['created_at', 'closed_at', 'changes_count', 'comments_count',
                       'suspicion_score', 'ml_score']
    ordering = ['-created_at']


@extend_schema(
    summary="Retrieve one changeset",
    description="Full record (including history and additional tags) for a given OSM changeset id.",
)
class ChangesetDetailView(generics.RetrieveAPIView):
    queryset = Changeset.objects.all()
    serializer_class = ChangesetSerializer
    lookup_field = 'changeset_id'


##############################################
### Stats API: aggregates over the ingested database
### All endpoints accept the same filters as /api/changesets/ (user, hashtag, bbox, dates, ...)

def filtered_changesets(request):
    """Applies the ChangesetFilter query params to the full queryset."""
    return ChangesetFilter(request.GET, queryset=Changeset.objects.all()).qs


def get_limit(request, default=10, maximum=100):
    try:
        return min(max(int(request.GET.get('limit', default)), 1), maximum)
    except ValueError:
        return default


# strips version suffixes: "iD 2.27.3" -> "iD", "JOSM/1.5 (18969 en)" -> "JOSM"
EDITOR_VERSION_PATTERN = re.compile(r'[/ ]+v?\d.*$')


LIMIT_PARAMETER = OpenApiParameter('limit', int, description="Number of rows to return (default 10, max 100).")


@extend_schema(
    summary="Global summary",
    description="Totals over the ingested changesets. Accepts the same filters as /api/changesets/.",
)
class StatsSummaryView(APIView):
    def get(self, request):
        aggregates = filtered_changesets(request).aggregate(
            total_changesets=Count('id'),
            total_edits=Sum('changes_count'),
            unique_users=Count('user', distinct=True),
            first_created_at=Min('created_at'),
            last_created_at=Max('created_at'),
            first_sequence=Min('sequence_from'),
            last_sequence=Max('sequence_from'),
        )
        return Response(aggregates)


@extend_schema(
    summary="Top contributors",
    parameters=[LIMIT_PARAMETER],
    description="Users ranked by number of changesets. Accepts the same filters as /api/changesets/.",
)
class TopContributorsView(APIView):
    def get(self, request):
        rows = (
            filtered_changesets(request)
            .exclude(user__isnull=True)
            .values('user')
            .annotate(changesets=Count('id'), edits=Sum('changes_count'))
            .order_by('-changesets')[:get_limit(request)]
        )
        return Response(list(rows))


@extend_schema(
    summary="Top editors",
    parameters=[LIMIT_PARAMETER],
    description="Editing software ranked by number of changesets (versions are stripped, "
                "e.g. 'iD 2.27.3' counts as 'iD'). Accepts the same filters as /api/changesets/.",
)
class TopEditorsView(APIView):
    def get(self, request):
        created_by_values = (
            filtered_changesets(request)
            .exclude(created_by__isnull=True)
            .values_list('created_by', flat=True)
        )
        counter = Counter(EDITOR_VERSION_PATTERN.sub('', value).strip() for value in created_by_values)
        return Response([
            {'editor': editor, 'changesets': count}
            for editor, count in counter.most_common(get_limit(request))
        ])


@extend_schema(
    summary="Top hashtags",
    parameters=[LIMIT_PARAMETER],
    description="Hashtags ranked by number of changesets mentioning them. "
                "Accepts the same filters as /api/changesets/.",
)
class TopHashtagsView(APIView):
    def get(self, request):
        hashtag_lists = (
            filtered_changesets(request)
            .exclude(hashtags=[])
            .exclude(hashtags__isnull=True)
            .values_list('hashtags', flat=True)
        )
        counter = Counter(hashtag for hashtags in hashtag_lists for hashtag in hashtags)
        return Response([
            {'hashtag': hashtag, 'changesets': count}
            for hashtag, count in counter.most_common(get_limit(request))
        ])


@extend_schema(
    summary="Suspicion overview",
    description="Distribution of the rule-based suspicion flags and score levels "
                "(see /api/changesets/?flag=... to drill down). "
                "Accepts the same filters as /api/changesets/.",
)
class SuspicionStatsView(APIView):
    def get(self, request):
        queryset = filtered_changesets(request)
        flag_lists = (
            queryset
            .exclude(suspicion_flags=[])
            .exclude(suspicion_flags__isnull=True)
            .values_list('suspicion_flags', flat=True)
        )
        flag_counter = Counter(flag for flags in flag_lists for flag in flags)
        return Response({
            'flag_counts': dict(flag_counter.most_common()),
            'suspicion_gte_50': queryset.filter(suspicion_score__gte=50).count(),
            'ml_scored': queryset.exclude(ml_score__isnull=True).count(),
            'ml_gte_99': queryset.filter(ml_score__gte=99).count(),
        })


@extend_schema(
    summary="Contribution timeline",
    parameters=[OpenApiParameter('interval', str, enum=['hour', 'day'],
                                 description="Bucket size (default: hour).")],
    description="Changesets and edits bucketed by hour or day of creation. "
                "Accepts the same filters as /api/changesets/.",
)
class TimelineView(APIView):
    def get(self, request):
        interval = request.GET.get('interval', 'hour')
        if interval not in ('hour', 'day'):
            return Response({'error': "interval must be 'hour' or 'day'."},
                            status=status.HTTP_400_BAD_REQUEST)
        trunc = TruncHour if interval == 'hour' else TruncDay
        rows = (
            filtered_changesets(request)
            .exclude(created_at__isnull=True)
            .annotate(bucket=trunc('created_at'))
            .values('bucket')
            .annotate(changesets=Count('id'), edits=Sum('changes_count'))
            .order_by('bucket')
        )
        return Response(list(rows))


##############################################
### On-demand ingestion (legacy endpoint): fetches sequences from
### planet.osm.org synchronously, then returns them.
### Prefer `python manage.py ingest_changesets` + /api/changesets/.

@extend_schema(
    summary="Fetch a sequence range on demand (legacy)",
    description="Synchronously downloads the given replication sequences from planet.osm.org, "
                "stores them, and returns the changesets. Limited to 10 sequences per call "
                "and rate-limited; prefer the ingestion worker and /api/changesets/ for real usage.",
)
class ChangesetListView(APIView):
    # this endpoint triggers downloads and DB writes, so it gets a strict rate limit
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'on_demand_ingest'

    def get(self, request, seq_start, seq_end):
        seq_start = int(seq_start)
        seq_end = int(seq_end)

        max_range = 10
        # Check if the range is too large
        if abs(seq_end - seq_start) > max_range:
            return Response(
                {"error": f"The range between seq_start and seq_end should not exceed {max_range}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ## Fetch and process changesets (no .osm.gz file caching on the server)
        try:
            changesets_processed = fetch_and_process_changesets(seq_start, seq_end,
                                                                save_locally=False, cache_locally=False)
        except SequenceFetchError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        # get the list of processed changeset ids
        changesets_processed_list = [changeset['changeset_id'] for changeset in changesets_processed]

        ## Filter changesets within list of processed changesets
        changesets = Changeset.objects.filter(changeset_id__in=changesets_processed_list)
        serializer = ChangesetSerializer(changesets, many=True)

        return Response(serializer.data)


##############################################
### Landing page & live chart

class APILandingPageView(TemplateView):
    template_name = 'changesets/landing_page.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['last_changeset_id'] = get_last_sequence()
        except SequenceFetchError:
            logger.warning("Could not fetch last sequence for the landing page", exc_info=True)
            context['last_changeset_id'] = None
        return context


class LiveMapView(TemplateView):
    """World map of the latest ingested changesets, refreshed by polling /api/changesets/."""
    template_name = 'changesets/map_page.html'


## Redirect to landing page

def redirect_to_landing_page(request):
    return HttpResponseRedirect(reverse('api-landing-page'))


import gzip
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

from .osm_utils import REQUEST_TIMEOUT


def scrape_timestamps(sequence, n=10):
    """Scrapes the timestamps of the last n changesets"""
    sequence_adjusted = str(sequence).rjust(9, "0")
    url = f"https://planet.osm.org/replication/changesets/{sequence_adjusted[0:3]}/{sequence_adjusted[3:6]}/"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    html_content = response.text
    soup = BeautifulSoup(html_content, 'html.parser')
    timestamps = {}

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if href.endswith('.state.txt'):
            number = int(href.split('.')[0])
            seq_last_3_digits = int(str(sequence)[-3:])
            if number in range(seq_last_3_digits - n  +1, seq_last_3_digits + 1):
                timestamp = a_tag.find_next_sibling(string=True).strip().split()[:2]
                timestamps[number] = timestamp

    return timestamps

def get_changeset_count(sequence):
    """ Fetches one sequence and returns the number of changesets it contains """
    xml_sequence, _ = fetch_sequence_xml(sequence)
    return len(xml_sequence)

def get_last_n_sequences(n=10):
    """Fetches the last N changeset counts starting from the latest sequence"""
    last_sequence = get_last_sequence()  # Get the latest sequence from the state.yaml file
    sequence_data = []

    timestamps = scrape_timestamps(last_sequence, n=n) # we scrape the last n_sequences' timestamps

    for i in range(n):
        sequence_number = last_sequence - i
        count = get_changeset_count(sequence_number)
        seq_last_3_digits = int(str(sequence_number)[-3:])
        sequence_data.append({"sequence": sequence_number, "changeset_count": count, "timestamp": timestamps[seq_last_3_digits][1]})

    sequence_data.reverse()  # To show the oldest data first
    return sequence_data

# Store the previous sequence to compare with the new one
last_fetched_sequence = None

def update_changeset_view(request):
    global last_fetched_sequence
    try:
        if request.GET.get('initial') == 'true':
            # If it's the first request, fetch the last 10 sequences
            last_10_data = get_last_n_sequences(10)
            last_fetched_sequence = last_10_data[-1]["sequence"]  # The latest sequence
            return JsonResponse({"initial_data": last_10_data})

        # Real-time updating logic (after the initial load)
        new_sequence = get_last_sequence()

        # Check if the new sequence is different from the previous one
        if new_sequence != last_fetched_sequence:
            changeset_count = get_changeset_count(new_sequence)
            last_fetched_sequence = new_sequence  # Update the last fetched sequence
            return JsonResponse({"sequence": new_sequence, "changeset_count": changeset_count})
    except SequenceFetchError as exc:
        logger.warning("Live chart update failed: %s", exc)
        return JsonResponse({"error": str(exc)}, status=502)

    # If there's no new sequence, return an empty response to avoid updating
    return JsonResponse({"sequence": last_fetched_sequence, "changeset_count": None})
