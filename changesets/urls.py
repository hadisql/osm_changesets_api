from django.urls import path
from .views import ChangesetListView, redirect_to_landing_page


urlpatterns = [
    path('changesets/<int:seq_start>/<int:seq_end>/', ChangesetListView.as_view(), name='changeset-list'),
    path('changesets/', redirect_to_landing_page),
    path('', redirect_to_landing_page),
]
