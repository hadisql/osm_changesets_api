"""
Suspicion scoring for changesets, working on replication *metadata* only
(the actual edited geometries are not in the changeset replication stream).

Two complementary layers:
- rule-based flags (this module, applied at ingestion time), inspired by the
  heuristics of OSMCha (https://github.com/OSMCha/osmcha) adapted to metadata;
- an unsupervised Isolation Forest (see the score_anomalies command) that
  ranks changesets by how atypical their metadata is.
"""
import math

# each rule: (flag name, weight, predicate over the formatted changeset dict)
HUGE_BBOX_DEG2 = 25.0        # a 5°x5° box spans several countries
HIGH_CHANGES_COUNT = 1500    # hand edits rarely reach this; imports/bulk edits do
NEW_MAPPER_CHANGESETS = 5    # user's total changesets at upload time (editor-provided tag)


def bbox_area(changeset):
    try:
        width = float(changeset.get('max_lon')) - float(changeset.get('min_lon'))
        height = float(changeset.get('max_lat')) - float(changeset.get('min_lat'))
    except (TypeError, ValueError):
        return None
    return max(width, 0.0) * max(height, 0.0)


def user_experience(changeset):
    """The user's total changeset count at upload time, when the editor provided it."""
    try:
        return int((changeset.get('additional_tags') or {}).get('changesets_count'))
    except (TypeError, ValueError):
        return None


def compute_suspicion(changeset):
    """
    Returns (score 0-100, list of flag names) for a formatted changeset dict.
    Flags are cumulative; the score is the capped sum of their weights.
    """
    flags = []

    area = bbox_area(changeset)
    if area is not None and area > HUGE_BBOX_DEG2:
        flags.append(('huge_bbox', 25))

    changes_count = changeset.get('changes_count')
    if changes_count is not None and changes_count >= HIGH_CHANGES_COUNT:
        flags.append(('high_change_count', 20))

    comment = (changeset.get('comment') or '').strip()
    if len(comment) < 3:
        flags.append(('no_comment', 10))

    experience = user_experience(changeset)
    if experience is not None and experience < NEW_MAPPER_CHANGESETS:
        flags.append(('new_mapper', 20))

    if (changeset.get('additional_tags') or {}).get('review_requested') == 'yes':
        flags.append(('review_requested', 30))

    score = min(100, sum(weight for _, weight in flags))
    return score, [name for name, _ in flags]


def ml_features(changeset):
    """
    Numeric feature vector for the Isolation Forest, from a Changeset-like dict.
    All features are log-scaled counts or bounded quantities, robust to missing values.
    """
    area = bbox_area(changeset) or 0.0
    experience = user_experience(changeset)
    comment = (changeset.get('comment') or '').strip()
    return [
        math.log1p(changeset.get('changes_count') or 0),
        math.log1p(area * 1000),          # keeps tiny (common) areas discriminable
        math.log1p(len(comment)),
        math.log1p(experience if experience is not None else 0),
        1.0 if experience is None else 0.0,   # editor did not report experience
    ]
