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

        # Fetch and process changesets
        min_changeset, max_changeset = fetch_and_process_changesets(seq_start, seq_end, save_locally=False)

        # Filter changesets within the requested range
        changesets = Changeset.objects.filter(changeset_id__gte=min_changeset, changeset_id__lte=max_changeset)
        serializer = ChangesetSerializer(changesets, many=True)
        
        return Response(serializer.data)

