"""
Unsupervised anomaly scoring of ingested changesets with an Isolation Forest.

The model is (re)trained on the current database content each run — the
population drifts as data comes and goes (retention), so a fresh fit on
recent data is both simpler and more accurate than persisting a model.

Scores are stored on Changeset.ml_score as a 0-100 percentile: 100 = the
most atypical changeset of the batch. Run it periodically (e.g. hourly)
alongside the ingestion worker.

    python manage.py score_anomalies
    python manage.py score_anomalies --rescore-all   # also rescore rows that already have a score
"""
import numpy as np
from django.core.management.base import BaseCommand, CommandError
from sklearn.ensemble import IsolationForest

from changesets.anomaly import ml_features
from changesets.models import Changeset

MIN_TRAINING_ROWS = 50
FIELDS = ['changes_count', 'min_lat', 'max_lat', 'min_lon', 'max_lon',
          'comment', 'additional_tags']


class Command(BaseCommand):
    help = "Trains an Isolation Forest on the ingested changesets and stores a 0-100 anomaly percentile."

    def add_arguments(self, parser):
        parser.add_argument("--rescore-all", action="store_true",
                            help="Rescore every changeset (default: only those without a score).")
        parser.add_argument("--n-estimators", type=int, default=200)

    def handle(self, *args, **options):
        queryset = Changeset.objects.all().only('id', *FIELDS)
        total = queryset.count()
        if total < MIN_TRAINING_ROWS:
            raise CommandError(f"Need at least {MIN_TRAINING_ROWS} changesets to train (found {total}).")

        self.stdout.write(f"Extracting features from {total} changeset(s)…")
        ids, rows = [], []
        for changeset in queryset.iterator(chunk_size=2000):
            ids.append(changeset.id)
            rows.append(ml_features({field: getattr(changeset, field) for field in FIELDS}))
        features = np.asarray(rows)

        self.stdout.write("Training Isolation Forest…")
        model = IsolationForest(n_estimators=options["n_estimators"], random_state=42, n_jobs=-1)
        model.fit(features)

        # score_samples: the lower, the more abnormal -> invert, then rank into a 0-100 percentile
        raw_scores = -model.score_samples(features)
        percentiles = 100.0 * np.argsort(np.argsort(raw_scores)) / max(len(raw_scores) - 1, 1)

        if options["rescore_all"]:
            to_update_ids = set(ids)
        else:
            to_update_ids = set(
                Changeset.objects.filter(ml_score__isnull=True).values_list('id', flat=True))

        updates = [
            Changeset(id=changeset_id, ml_score=round(float(percentile), 2))
            for changeset_id, percentile in zip(ids, percentiles)
            if changeset_id in to_update_ids
        ]
        Changeset.objects.bulk_update(updates, ['ml_score'], batch_size=1000)

        self.stdout.write(self.style.SUCCESS(
            f"Done: trained on {total} changeset(s), {len(updates)} score(s) written."))
