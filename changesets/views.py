from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import Changeset
from .serializers import ChangesetSerializer
from .osm_fetcher import fetch_and_process_changesets

class ChangesetListView(APIView):

    def get(self, request, seq_start, seq_end):
        seq_start = int(seq_start)
        seq_end = int(seq_end)
        
        max_range = 10
        # Check if the range is too large
        if seq_end - seq_start > max_range:
            return Response(
                {"error": f"The range between seq_start and seq_end should not exceed {max_range}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch and process changesets
        min_changeset, max_changeset = fetch_and_process_changesets(seq_start, seq_end, save_locally=False)

        # Filter changesets within the requested range
        changesets = Changeset.objects.filter(changeset_id__gte=min_changeset, changeset_id__lte=max_changeset)
        serializer = ChangesetSerializer(changesets, many=True)
        
        return Response(serializer.data)

from django.views.generic import TemplateView

class APILandingPageView(TemplateView):
    template_name = 'changesets/landing_page.html'

    def get_context_data(self, **kwargs):
        import yaml, requests
        context = super().get_context_data(**kwargs)
        context['last_changeset_id'] = int(yaml.load(requests.get("https://planet.osm.org/replication/changesets/state.yaml", stream=True).raw.read(),Loader=yaml.FullLoader)["sequence"])
        return context