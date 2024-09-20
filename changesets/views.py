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

        ## Fetch and process changesets
        changesets_processed = fetch_and_process_changesets(seq_start, seq_end, save_locally=False)
        # get the list of processed changeset ids
        changesets_processed_list = [changeset['changeset_id'] for changeset in changesets_processed]

        ## Filter changesets within list of processed changesets
        changesets = Changeset.objects.filter(changeset_id__in=changesets_processed_list)
        serializer = ChangesetSerializer(changesets, many=True)
        
        return Response(serializer.data)

from django.views.generic import TemplateView

def get_last_sequence():
    import yaml, requests
    """Fetches the latest sequence from the state.yaml file."""
    response = requests.get("https://planet.osm.org/replication/changesets/state.yaml", stream=True)
    last_sequence = int(yaml.load(response.raw.read(), Loader=yaml.FullLoader)["sequence"])
    return last_sequence

def get_changeset_count(sequence):
    """Fetches changesets using the provided sequence from the API."""
    url = f"http://localhost:8000/api/sequence/{sequence}/{sequence}/"
    response = requests.get(url)
    if response.status_code == 200:
        changesets = response.json()
        return len(changesets)  # Return the number of changesets fetched
    return 0

class APILandingPageView(TemplateView):
    template_name = 'changesets/landing_page.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['last_changeset_id'] = get_last_sequence()
        return context

## Redirect to landing page
from django.http import HttpResponseRedirect
from django.urls import reverse

def redirect_to_landing_page(request):
    return HttpResponseRedirect(reverse('api-landing-page'))


##############################################
### Changeset livestream plot

from django.http import JsonResponse
import requests

# Store the previous sequence to compare with the new one
last_fetched_sequence = None

def update_changeset_view(request):
    global last_fetched_sequence
    new_sequence = get_last_sequence()

    # Check if the new sequence is different from the previous one
    if new_sequence != last_fetched_sequence:
        changeset_count = get_changeset_count(new_sequence)
        last_fetched_sequence = new_sequence  # Update the last fetched sequence
        return JsonResponse({"sequence": new_sequence, "changeset_count": changeset_count})
    
    # If there's no new sequence, return an empty response to avoid updating
    return JsonResponse({"sequence": last_fetched_sequence, "changeset_count": None})
