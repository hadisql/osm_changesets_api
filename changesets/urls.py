from django.urls import path
from .views import ChangesetListView, CountView

urlpatterns = [
    path('changesets/<int:seq_start>/<int:seq_end>/', ChangesetListView.as_view(), name='changeset-list'),
    path('count/', CountView.as_view(), name='count'),
]
