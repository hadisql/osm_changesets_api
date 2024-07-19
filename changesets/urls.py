from django.urls import path
from .views import ChangesetListView

urlpatterns = [
    path('changesets/<int:seq_start>/<int:seq_end>/', ChangesetListView.as_view(), name='changeset-list'),
]
