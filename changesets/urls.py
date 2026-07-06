from django.urls import path

from .views import (
    ChangesetDetailView,
    ChangesetListView,
    ChangesetQueryView,
    StatsSummaryView,
    TimelineView,
    TopContributorsView,
    TopEditorsView,
    TopHashtagsView,
    redirect_to_landing_page,
    update_changeset_view,
)

urlpatterns = [
    # Query API (reads the ingested database)
    path('changesets/', ChangesetQueryView.as_view(), name='changeset-query'),
    path('changesets/<int:changeset_id>/', ChangesetDetailView.as_view(), name='changeset-detail'),

    # Stats API (aggregates, accepts the same filters as /changesets/)
    path('stats/summary/', StatsSummaryView.as_view(), name='stats-summary'),
    path('stats/contributors/', TopContributorsView.as_view(), name='stats-contributors'),
    path('stats/editors/', TopEditorsView.as_view(), name='stats-editors'),
    path('stats/hashtags/', TopHashtagsView.as_view(), name='stats-hashtags'),
    path('stats/timeline/', TimelineView.as_view(), name='stats-timeline'),

    # On-demand ingestion (legacy) + landing page live chart
    path('sequence/<int:seq_start>/<int:seq_end>/', ChangesetListView.as_view(), name='changeset-list'),
    path('update/', update_changeset_view, name='update_changeset_view'),
    path('sequence/', redirect_to_landing_page),
    path('', redirect_to_landing_page),
]
