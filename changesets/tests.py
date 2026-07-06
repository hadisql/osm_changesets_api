import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Changeset
from .osm_utils import (
    SequenceFetchError,
    changeset_formatting,
    fetch_sequence_xml,
    urlized_sequence_number,
)

SAMPLE_CHANGESET_XML = """
<changeset id="113928427" created_at="2021-11-18T06:17:42Z" open="false" comments_count="0"
           num_changes="6" closed_at="2021-11-18T06:17:44Z" min_lat="15.3384649"
           min_lon="-91.8697209" max_lat="15.3386183" max_lon="-91.8694203"
           uid="12026398" user="mapper_one">
    <tag k="comment" v="Add some buildings #hotosm-project-1 #missingmaps"/>
    <tag k="created_by" v="iD 2.27.3"/>
    <tag k="hashtags" v="#hotosm-project-1;#missingmaps"/>
    <tag k="locale" v="en-US"/>
    <tag k="changesets_count" v="73"/>
</changeset>
"""

SAMPLE_SEQUENCE_XML = f'<osm version="0.6">{SAMPLE_CHANGESET_XML}</osm>'


class ChangesetFormattingTests(TestCase):

    def setUp(self):
        self.element = ET.fromstring(SAMPLE_CHANGESET_XML)

    def test_attributes_are_mapped_and_typed(self):
        formatted = changeset_formatting(self.element, sequence_number=6200000, save_db=True)
        self.assertEqual(formatted['changeset_id'], '113928427')
        self.assertEqual(formatted['changes_count'], 6)
        self.assertEqual(formatted['user'], 'mapper_one')
        self.assertEqual(formatted['user_id'], 12026398)
        self.assertAlmostEqual(formatted['min_lat'], 15.3384649)
        self.assertFalse(formatted['open'])
        self.assertEqual(
            formatted['created_at'],
            datetime(2021, 11, 18, 6, 17, 42, tzinfo=dt_timezone.utc),
        )
        self.assertEqual(formatted['sequence_from'], 6200000)

    def test_special_tags_and_additional_tags(self):
        formatted = changeset_formatting(self.element, sequence_number=6200000, save_db=True)
        self.assertEqual(formatted['created_by'], 'iD 2.27.3')
        self.assertEqual(formatted['hashtags'], ['#hotosm-project-1', '#missingmaps'])
        self.assertEqual(formatted['additional_tags'], {'changesets_count': '73'})


class OsmUtilsTests(TestCase):

    def test_urlized_sequence_number(self):
        self.assertEqual(
            urlized_sequence_number(6200000),
            "https://planet.osm.org/replication/changesets/006/200/000.osm.gz",
        )

    def test_fetch_sequence_xml_network_error_raises(self):
        with mock.patch('changesets.osm_utils.requests.get', side_effect=ConnectionError):
            # requests exceptions inherit from OSError, so ConnectionError is representative
            with self.assertRaises(SequenceFetchError):
                fetch_sequence_xml(6200000)

    def test_fetch_sequence_xml_decompresses_and_parses(self):
        fake_response = mock.Mock(content=gzip.compress(SAMPLE_SEQUENCE_XML.encode()))
        fake_response.raise_for_status = mock.Mock()
        with mock.patch('changesets.osm_utils.requests.get', return_value=fake_response):
            xml_root, raw = fetch_sequence_xml(6200000)
        self.assertEqual(len(xml_root), 1)
        self.assertEqual(xml_root[0].attrib['id'], '113928427')


def create_changeset(**overrides):
    defaults = dict(
        changeset_id=1,
        created_at=datetime(2026, 7, 1, 12, 0, tzinfo=dt_timezone.utc),
        closed_at=datetime(2026, 7, 1, 12, 5, tzinfo=dt_timezone.utc),
        open=False,
        changes_count=10,
        user='alice',
        user_id=1,
        min_lat=48.8, max_lat=48.9, min_lon=2.2, max_lon=2.4,  # Paris-ish
        comments_count=0,
        created_by='iD 2.27.3',
        hashtags=[],
        additional_tags={},
        history=[],
        sequence_from=6200000,
    )
    defaults.update(overrides)
    return Changeset.objects.create(**defaults)


class ChangesetQueryAPITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        create_changeset(changeset_id=1, user='alice', created_by='iD 2.27.3',
                         hashtags=['#hotosm-project-1'], changes_count=10)
        create_changeset(changeset_id=2, user='bob', created_by='JOSM/1.5 (18969 en)',
                         changes_count=200,
                         created_at=datetime(2026, 7, 2, 9, 0, tzinfo=dt_timezone.utc),
                         min_lat=-34.7, max_lat=-34.5, min_lon=-58.5, max_lon=-58.3)  # Buenos Aires-ish
        create_changeset(changeset_id=3, user='alice', created_by='StreetComplete 50.2',
                         hashtags=['#hotosm-project-1', '#missingmaps'], changes_count=3,
                         created_at=datetime(2026, 7, 3, 15, 0, tzinfo=dt_timezone.utc))

    def test_list_is_paginated_and_ordered(self):
        response = self.client.get('/api/changesets/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 3)
        results = response.data['results']
        # newest first
        self.assertEqual([row['changeset_id'] for row in results], [3, 2, 1])
        # compact serializer omits heavy fields
        self.assertNotIn('history', results[0])

    def test_filter_by_user(self):
        response = self.client.get('/api/changesets/', {'user': 'ALICE'})
        self.assertEqual(response.data['count'], 2)

    def test_filter_by_editor(self):
        response = self.client.get('/api/changesets/', {'editor': 'JOSM'})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['changeset_id'], 2)

    def test_filter_by_hashtag_with_or_without_hash(self):
        for value in ('#missingmaps', 'missingmaps'):
            response = self.client.get('/api/changesets/', {'hashtag': value})
            self.assertEqual(response.data['count'], 1, value)
            self.assertEqual(response.data['results'][0]['changeset_id'], 3)

    def test_filter_by_created_range(self):
        response = self.client.get('/api/changesets/', {
            'created_after': '2026-07-02T00:00:00Z',
            'created_before': '2026-07-02T23:59:59Z',
        })
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['changeset_id'], 2)

    def test_filter_by_bbox_intersection(self):
        response = self.client.get('/api/changesets/', {'bbox': '2.0,48.0,3.0,49.0'})
        self.assertEqual(response.data['count'], 2)  # the two Paris-ish ones

    def test_filter_by_bbox_invalid_returns_400(self):
        response = self.client.get('/api/changesets/', {'bbox': 'not-a-bbox'})
        self.assertEqual(response.status_code, 400)

    def test_filter_by_min_changes(self):
        response = self.client.get('/api/changesets/', {'min_changes': 100})
        self.assertEqual(response.data['count'], 1)

    def test_detail_returns_full_record(self):
        response = self.client.get('/api/changesets/2/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('history', response.data)
        self.assertEqual(response.data['user'], 'bob')

    def test_detail_unknown_id_returns_404(self):
        response = self.client.get('/api/changesets/999999/')
        self.assertEqual(response.status_code, 404)

    def test_page_size_is_client_adjustable(self):
        response = self.client.get('/api/changesets/', {'page_size': 2})
        self.assertEqual(len(response.data['results']), 2)
        self.assertIsNotNone(response.data['next'])


class SuspicionRulesTests(TestCase):

    def test_benign_changeset_gets_low_score(self):
        from .anomaly import compute_suspicion
        score, flags = compute_suspicion({
            'changes_count': 12, 'comment': 'Added a bench and a bin',
            'min_lat': 48.85, 'max_lat': 48.86, 'min_lon': 2.34, 'max_lon': 2.35,
            'additional_tags': {'changesets_count': '250'},
        })
        self.assertEqual(score, 0)
        self.assertEqual(flags, [])

    def test_suspicious_changeset_accumulates_flags(self):
        from .anomaly import compute_suspicion
        score, flags = compute_suspicion({
            'changes_count': 4000, 'comment': '',
            'min_lat': -50, 'max_lat': 50, 'min_lon': -100, 'max_lon': 100,  # continental bbox
            'additional_tags': {'changesets_count': '2', 'review_requested': 'yes'},
        })
        self.assertCountEqual(
            flags, ['huge_bbox', 'high_change_count', 'no_comment', 'new_mapper', 'review_requested'])
        self.assertEqual(score, 100)  # capped

    def test_missing_metadata_is_not_flagged_as_new_mapper(self):
        from .anomaly import compute_suspicion
        score, flags = compute_suspicion({'changes_count': 5, 'comment': 'fix typo',
                                          'additional_tags': {}})
        self.assertNotIn('new_mapper', flags)

    def test_scoring_happens_at_ingestion(self):
        element = ET.fromstring(SAMPLE_CHANGESET_XML)
        formatted = changeset_formatting(element, sequence_number=6200000, save_db=True)
        self.assertIn('suspicion_score', formatted)
        self.assertIn('suspicion_flags', formatted)


class SuspicionAPITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        create_changeset(changeset_id=1, suspicion_score=0, suspicion_flags=[], ml_score=10.0)
        create_changeset(changeset_id=2, suspicion_score=55,
                         suspicion_flags=['huge_bbox', 'high_change_count', 'no_comment'],
                         ml_score=99.5)
        create_changeset(changeset_id=3, suspicion_score=30,
                         suspicion_flags=['new_mapper', 'no_comment'], ml_score=None)

    def test_filter_by_min_suspicion(self):
        response = self.client.get('/api/changesets/', {'min_suspicion': 50})
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['changeset_id'], 2)

    def test_filter_by_flag(self):
        response = self.client.get('/api/changesets/', {'flag': 'no_comment'})
        self.assertEqual(response.data['count'], 2)

    def test_filter_by_min_ml_score(self):
        response = self.client.get('/api/changesets/', {'min_ml_score': 90})
        self.assertEqual(response.data['count'], 1)

    def test_ordering_by_suspicion(self):
        response = self.client.get('/api/changesets/', {'ordering': '-suspicion_score'})
        self.assertEqual([row['changeset_id'] for row in response.data['results']], [2, 3, 1])

    def test_suspicion_stats(self):
        response = self.client.get(reverse('stats-suspicion'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['flag_counts']['no_comment'], 2)
        self.assertEqual(response.data['suspicion_gte_50'], 1)
        self.assertEqual(response.data['ml_scored'], 2)
        self.assertEqual(response.data['ml_gte_99'], 1)


class ScoreAnomaliesCommandTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        # 59 ordinary changesets + 1 glaring outlier
        for i in range(59):
            create_changeset(changeset_id=i + 1, changes_count=5 + (i % 20),
                             comment='small fix', additional_tags={'changesets_count': '300'})
        create_changeset(changeset_id=1000, changes_count=90000, comment='',
                         min_lat=-60, max_lat=70, min_lon=-170, max_lon=170,
                         additional_tags={})

    def test_outlier_gets_top_percentile(self):
        out = StringIO()
        call_command('score_anomalies', stdout=out)
        outlier = Changeset.objects.get(changeset_id=1000)
        self.assertIsNotNone(outlier.ml_score)
        self.assertGreaterEqual(outlier.ml_score, 95.0)
        self.assertEqual(Changeset.objects.filter(ml_score__isnull=True).count(), 0)
        self.assertIn('60 score(s) written', out.getvalue())

    def test_only_unscored_rows_updated_by_default(self):
        Changeset.objects.filter(changeset_id=1).update(ml_score=42.0)
        call_command('score_anomalies', stdout=StringIO())
        self.assertEqual(Changeset.objects.get(changeset_id=1).ml_score, 42.0)

    def test_refuses_to_train_on_tiny_dataset(self):
        from django.core.management.base import CommandError
        Changeset.objects.exclude(changeset_id__lte=10).delete()
        with self.assertRaises(CommandError):
            call_command('score_anomalies', stdout=StringIO())


class GeoTests(TestCase):

    def test_country_for_known_coordinates(self):
        from .geo import country_for
        self.assertEqual(country_for(48.8566, 2.3522), 'FR')

    def test_country_for_missing_coordinates(self):
        from .geo import country_for
        self.assertIsNone(country_for(None, 2.35))

    def test_formatting_sets_country_from_bbox_center(self):
        element = ET.fromstring(SAMPLE_CHANGESET_XML)
        formatted = changeset_formatting(element, sequence_number=6200000, save_db=True)
        self.assertEqual(formatted['country_code'], 'GT')  # sample bbox is in Guatemala


class CountryAPITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        create_changeset(changeset_id=1, country_code='FR', changes_count=10)
        create_changeset(changeset_id=2, country_code='FR', changes_count=5)
        create_changeset(changeset_id=3, country_code='AR', changes_count=100)
        create_changeset(changeset_id=4, country_code=None)

    def test_filter_by_country_case_insensitive(self):
        response = self.client.get('/api/changesets/', {'country': 'fr'})
        self.assertEqual(response.data['count'], 2)

    def test_top_countries(self):
        response = self.client.get(reverse('stats-countries'))
        self.assertEqual(response.data[0], {'country_code': 'FR', 'changesets': 2, 'edits': 15})
        self.assertEqual(response.data[1], {'country_code': 'AR', 'changesets': 1, 'edits': 100})


class ScoreSchedulingTests(TestCase):

    def make_command(self):
        from changesets.management.commands.ingest_changesets import Command
        command = Command()
        command._last_scored_at = None
        command.stderr = StringIO()
        return command

    def test_disabled_by_default(self):
        command = self.make_command()
        with mock.patch('changesets.management.commands.ingest_changesets.call_command') as scored:
            command.maybe_score(None)
        scored.assert_not_called()

    def test_scores_once_per_interval(self):
        command = self.make_command()
        command.stdout = StringIO()
        with mock.patch('changesets.management.commands.ingest_changesets.call_command') as scored:
            command.maybe_score(15)
            command.maybe_score(15)  # immediately after: within the interval
        scored.assert_called_once()


class LiveMapPageTests(TestCase):

    def test_map_page_renders(self):
        response = self.client.get(reverse('live-map'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'leaflet')
        self.assertContains(response, '/api/changesets/')


class StatsAPITests(APITestCase):

    @classmethod
    def setUpTestData(cls):
        create_changeset(changeset_id=1, user='alice', created_by='iD 2.27.3',
                         hashtags=['#hotosm-project-1'], changes_count=10)
        create_changeset(changeset_id=2, user='bob', created_by='JOSM/1.5 (18969 en)',
                         changes_count=200,
                         created_at=datetime(2026, 7, 2, 9, 0, tzinfo=dt_timezone.utc))
        create_changeset(changeset_id=3, user='alice', created_by='iD 2.30.0',
                         hashtags=['#hotosm-project-1', '#missingmaps'], changes_count=3,
                         created_at=datetime(2026, 7, 2, 15, 0, tzinfo=dt_timezone.utc))

    def test_summary(self):
        response = self.client.get(reverse('stats-summary'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total_changesets'], 3)
        self.assertEqual(response.data['total_edits'], 213)
        self.assertEqual(response.data['unique_users'], 2)

    def test_summary_respects_filters(self):
        response = self.client.get(reverse('stats-summary'), {'user': 'alice'})
        self.assertEqual(response.data['total_changesets'], 2)
        self.assertEqual(response.data['total_edits'], 13)

    def test_top_contributors(self):
        response = self.client.get(reverse('stats-contributors'))
        self.assertEqual(response.data[0], {'user': 'alice', 'changesets': 2, 'edits': 13})

    def test_top_editors_strips_versions(self):
        response = self.client.get(reverse('stats-editors'))
        self.assertEqual(response.data[0], {'editor': 'iD', 'changesets': 2})
        self.assertEqual(response.data[1], {'editor': 'JOSM', 'changesets': 1})

    def test_top_hashtags(self):
        response = self.client.get(reverse('stats-hashtags'))
        self.assertEqual(response.data[0], {'hashtag': '#hotosm-project-1', 'changesets': 2})

    def test_timeline_by_day(self):
        response = self.client.get(reverse('stats-timeline'), {'interval': 'day'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)  # July 1st and July 2nd
        self.assertEqual(response.data[1]['changesets'], 2)

    def test_timeline_rejects_bad_interval(self):
        response = self.client.get(reverse('stats-timeline'), {'interval': 'century'})
        self.assertEqual(response.status_code, 400)


class IngestCommandTests(TestCase):

    def fake_fetch(self, sequence_number):
        xml = SAMPLE_SEQUENCE_XML.replace('113928427', str(113928000 + sequence_number))
        return ET.fromstring(xml), b''

    def test_ingest_range_saves_changesets(self):
        out = StringIO()
        with mock.patch('changesets.osm_utils.fetch_sequence_xml', side_effect=self.fake_fetch):
            call_command('ingest_changesets', start=6200001, end=6200003, stdout=out)
        self.assertEqual(Changeset.objects.count(), 3)
        self.assertIn('3 sequence(s) ingested', out.getvalue())
        changeset = Changeset.objects.get(changeset_id=113928000 + 6200001)
        self.assertEqual(changeset.user, 'mapper_one')
        self.assertEqual(changeset.sequence_from, 6200001)

    def test_ingest_is_idempotent(self):
        with mock.patch('changesets.osm_utils.fetch_sequence_xml', side_effect=self.fake_fetch):
            call_command('ingest_changesets', start=6200001, end=6200001, stdout=StringIO())
            call_command('ingest_changesets', start=6200001, end=6200001, stdout=StringIO())
        self.assertEqual(Changeset.objects.count(), 1)

    def test_failed_sequence_is_reported(self):
        from django.core.management.base import CommandError
        with mock.patch('changesets.osm_utils.fetch_sequence_xml',
                        side_effect=SequenceFetchError('boom')):
            with self.assertRaises(CommandError):
                call_command('ingest_changesets', start=6200001, end=6200001,
                             stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Changeset.objects.count(), 0)

    def test_retention_prunes_old_changesets(self):
        from django.utils import timezone
        create_changeset(changeset_id=100, created_at=timezone.now() - timedelta(days=30))
        create_changeset(changeset_id=200, created_at=timezone.now() - timedelta(days=1))
        out = StringIO()
        with mock.patch('changesets.osm_utils.fetch_sequence_xml', side_effect=self.fake_fetch):
            call_command('ingest_changesets', start=6200001, end=6200001,
                         retention_days=7, stdout=out)
        remaining_ids = set(Changeset.objects.values_list('changeset_id', flat=True))
        self.assertNotIn(100, remaining_ids)
        self.assertIn(200, remaining_ids)
        # both the 30-day-old fixture and the freshly ingested 2021 sample get pruned
        self.assertIn('Pruned 2 changeset(s)', out.getvalue())

    def test_no_retention_by_default(self):
        from django.utils import timezone
        create_changeset(changeset_id=100, created_at=timezone.now() - timedelta(days=365))
        with mock.patch('changesets.osm_utils.fetch_sequence_xml', side_effect=self.fake_fetch):
            call_command('ingest_changesets', start=6200001, end=6200001, stdout=StringIO())
        self.assertTrue(Changeset.objects.filter(changeset_id=100).exists())


class LegacyEndpointTests(APITestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()  # reset throttle counters between tests

    def test_does_not_cache_files_on_disk(self):
        with mock.patch('changesets.views.fetch_and_process_changesets', return_value=[]) as fetch_mock:
            response = self.client.get('/api/sequence/6200001/6200001/')
        self.assertEqual(response.status_code, 200)
        fetch_mock.assert_called_once_with(6200001, 6200001, save_locally=False, cache_locally=False)

    def test_range_too_large_returns_400(self):
        response = self.client.get('/api/sequence/1/999/')
        self.assertEqual(response.status_code, 400)

    def test_upstream_failure_returns_502(self):
        with mock.patch('changesets.views.fetch_and_process_changesets',
                        side_effect=SequenceFetchError('planet.osm.org unreachable')):
            response = self.client.get('/api/sequence/6200001/6200001/')
        self.assertEqual(response.status_code, 502)

    def test_rate_limit_returns_429(self):
        from rest_framework.throttling import ScopedRateThrottle
        with mock.patch.dict(ScopedRateThrottle.THROTTLE_RATES, {'on_demand_ingest': '1/hour'}):
            with mock.patch('changesets.views.fetch_and_process_changesets', return_value=[]):
                first = self.client.get('/api/sequence/6200001/6200001/')
                second = self.client.get('/api/sequence/6200001/6200001/')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
