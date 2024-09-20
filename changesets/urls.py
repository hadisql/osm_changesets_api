from django.urls import path
from .views import ChangesetListView, redirect_to_landing_page, update_changeset_view


urlpatterns = [
    path('sequence/<int:seq_start>/<int:seq_end>/', ChangesetListView.as_view(), name='changeset-list'),
    path('update/', update_changeset_view, name='update_changeset_view'),
    path('sequence/', redirect_to_landing_page),
    path('', redirect_to_landing_page),
]
