"""
Offline country resolution for changesets, using reverse_geocoder
(nearest populated place from the bundled GeoNames dataset — no network calls).

Caveat: nearest-neighbor lookup means points in open water resolve to the
closest coastal country; good enough for contribution statistics.
"""
import logging

logger = logging.getLogger(__name__)

_geocoder_search = None  # lazy: the dataset takes ~1s to load on first use


def country_for(lat, lon):
    """ISO 3166-1 alpha-2 country code for a coordinate, or None."""
    global _geocoder_search
    if lat is None or lon is None:
        return None
    if _geocoder_search is None:
        import reverse_geocoder
        _geocoder_search = reverse_geocoder.search
    try:
        # mode=1: single-process (the default multiprocess mode is wasteful per-call)
        results = _geocoder_search([(float(lat), float(lon))], mode=1)
        return results[0]['cc'] if results else None
    except Exception:
        logger.warning("Reverse geocoding failed for (%s, %s)", lat, lon, exc_info=True)
        return None


def changeset_country(changeset):
    """Country of a changeset's bounding-box center, from a formatted dict."""
    try:
        lat = (float(changeset['min_lat']) + float(changeset['max_lat'])) / 2
        lon = (float(changeset['min_lon']) + float(changeset['max_lon'])) / 2
    except (KeyError, TypeError, ValueError):
        return None
    return country_for(lat, lon)
