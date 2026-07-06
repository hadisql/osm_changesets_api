"""
Continuous / one-shot ingestion of OSM changeset replication sequences.

Usage examples:
    python manage.py ingest_changesets                       # ingest the latest sequence once
    python manage.py ingest_changesets --start 6200000 --end 6200050   # backfill a range
    python manage.py ingest_changesets --follow              # run forever, polling state.yaml
"""
import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max
from django.utils import timezone

from changesets.models import Changeset
from changesets.osm_fetcher import process_sequence
from changesets.osm_utils import SequenceFetchError, get_last_sequence

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ingests OSM changeset replication sequences into the database."

    def add_arguments(self, parser):
        parser.add_argument("--start", type=int, help="First sequence of a backfill range.")
        parser.add_argument("--end", type=int, help="Last sequence of a backfill range (inclusive).")
        parser.add_argument("--follow", action="store_true",
                            help="Keep running: poll state.yaml and ingest new sequences as they appear.")
        parser.add_argument("--interval", type=int, default=60,
                            help="Polling interval in seconds for --follow (default: 60, the replication cadence).")
        parser.add_argument("--max-catchup", type=int, default=120,
                            help="In --follow mode, maximum number of past sequences to catch up on start (default: 120).")
        parser.add_argument("--retention-days", type=int, default=None,
                            help="If set, delete changesets created more than N days ago "
                                 "(keeps the database bounded on long-running deployments).")

    def handle(self, *args, **options):
        if options["follow"]:
            self.run_follow(options["interval"], options["max_catchup"], options["retention_days"])
            return

        if (options["start"] is None) != (options["end"] is None):
            raise CommandError("--start and --end must be used together.")

        if options["start"] is not None:
            seq_start, seq_end = sorted((options["start"], options["end"]))
        else:
            latest = get_last_sequence()
            seq_start = seq_end = latest
            self.stdout.write(f"No range given, ingesting latest sequence {latest}.")

        ok, failed = self.ingest_range(seq_start, seq_end)
        self.prune(options["retention_days"])
        self.stdout.write(self.style.SUCCESS(f"Done: {ok} sequence(s) ingested, {failed} failed."))
        if failed:
            raise CommandError(f"{failed} sequence(s) could not be ingested.")

    def prune(self, retention_days):
        """Deletes changesets whose OSM creation date is older than the retention window."""
        if not retention_days:
            return
        cutoff = timezone.now() - timedelta(days=retention_days)
        deleted_count, _ = Changeset.objects.filter(created_at__lt=cutoff).delete()
        if deleted_count:
            self.stdout.write(f"Pruned {deleted_count} changeset(s) older than {retention_days} day(s).")

    def ingest_range(self, seq_start, seq_end):
        """Processes sequences seq_start..seq_end (inclusive). Returns (ok_count, failed_count)."""
        ok = failed = 0
        for sequence_number in range(seq_start, seq_end + 1):
            try:
                changesets = process_sequence(sequence_number, save_db=True, cache_locally=False)
            except SequenceFetchError as exc:
                failed += 1
                self.stderr.write(self.style.WARNING(f"Skipping sequence {sequence_number}: {exc}"))
                continue
            ok += 1
            self.stdout.write(f"Sequence {sequence_number}: {len(changesets)} changeset(s) processed.")
        return ok, failed

    def run_follow(self, interval, max_catchup, retention_days=None):
        """Polls state.yaml forever and ingests every sequence not yet in the database."""
        self.stdout.write(f"Following replication stream (polling every {interval}s). Ctrl+C to stop.")
        try:
            while True:
                try:
                    remote_latest = get_last_sequence()
                except SequenceFetchError as exc:
                    self.stderr.write(self.style.WARNING(f"Could not read state.yaml, retrying: {exc}"))
                    time.sleep(interval)
                    continue

                local_latest = Changeset.objects.aggregate(latest=Max("sequence_from"))["latest"]
                if local_latest is None:
                    next_sequence = remote_latest - max_catchup + 1
                else:
                    # never go further back than max_catchup, even after a long downtime
                    next_sequence = max(local_latest + 1, remote_latest - max_catchup + 1)

                if next_sequence <= remote_latest:
                    self.ingest_range(next_sequence, remote_latest)
                else:
                    self.stdout.write(f"Up to date (sequence {remote_latest}).")

                self.prune(retention_days)

                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("\nStopped.")
