from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from .models import Changeset
from .serializers import ChangesetSerializer
from .osm_fetcher import fetch_and_process_changesets
from django.views.generic import TemplateView
from django.http import JsonResponse, HttpResponseRedirect
import yaml, requests
from django.urls import reverse

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


def get_last_sequence():
    """Fetches the latest sequence from the state.yaml file."""
    response = requests.get("https://planet.osm.org/replication/changesets/state.yaml", stream=True)
    last_sequence = int(yaml.load(response.raw.read(), Loader=yaml.FullLoader)["sequence"])
    return last_sequence


class APILandingPageView(TemplateView):
    template_name = 'changesets/landing_page.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['last_changeset_id'] = get_last_sequence()
        return context

## Redirect to landing page

def redirect_to_landing_page(request):
    return HttpResponseRedirect(reverse('api-landing-page'))


##############################################
### Changeset livestream plot

# def get_changeset_count(sequence):
#     """Fetches changesets using the provided sequence from the API."""
#     url = f"http://localhost:8000/api/sequence/{sequence}/{sequence}/"
#     response = requests.get(url)
#     if response.status_code == 200:
#         changesets = response.json()
#         return len(changesets)  # Return the number of changesets fetched
#     return 0
import xml.etree.ElementTree as ET
import gzip
from .osm_utils import urlized_sequence_number
from bs4 import BeautifulSoup


def scrape_timestamps(sequence, n=10):
    """Scrapes the timestamps of the last n changesets"""
    sequence_adjusted = str(sequence).rjust(9, "0")
    url = f"https://planet.osm.org/replication/changesets/{sequence_adjusted[0:3]}/{sequence_adjusted[3:6]}/"
    response = requests.get(url)
    html_content = response.text
    soup = BeautifulSoup(html_content, 'html.parser')
    timestamps = {}

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if href.endswith('.state.txt'):
            number = int(href.split('.')[0])
            seq_last_3_digits = int(str(sequence)[-3:])
            if number in range(seq_last_3_digits - n  +1, seq_last_3_digits + 1):
                timestamp = a_tag.find_next_sibling(string=True).strip().split()[:2]
                timestamps[number] = timestamp

    return timestamps

def get_changeset_count(sequence):
    """ Fetches changesets using urlized sequence number and extract the length of the xml tree <=> nb of changesets """
    url_sequence = urlized_sequence_number(sequence)
    xml_sequence_request = requests.get(url_sequence, stream=True).raw.read()
    xml_sequence = ET.fromstring(gzip.decompress(xml_sequence_request))
    return len(xml_sequence)
    
def get_last_n_sequences(n=10):
    """Fetches the last N changeset counts starting from the latest sequence"""
    last_sequence = get_last_sequence()  # Get the latest sequence from the state.yaml file
    sequence_data = []
    
    timestamps = scrape_timestamps(last_sequence, n=n) # we scrape the last n_sequences' timestamps

    for i in range(n):
        sequence_number = last_sequence - i
        count = get_changeset_count(sequence_number)
        seq_last_3_digits = int(str(sequence_number)[-3:])
        sequence_data.append({"sequence": sequence_number, "changeset_count": count, "timestamp": timestamps[seq_last_3_digits][1]})
    
    sequence_data.reverse()  # To show the oldest data first
    return sequence_data

# Store the previous sequence to compare with the new one
last_fetched_sequence = None

def update_changeset_view(request):
    global last_fetched_sequence
    if request.GET.get('initial') == 'true':
        # If it's the first request, fetch the last 10 sequences
        last_10_data = get_last_n_sequences(10)
        last_fetched_sequence = last_10_data[-1]["sequence"]  # The latest sequence
        last_10_timestamps = scrape_timestamps(last_fetched_sequence, 10)
        return JsonResponse({"initial_data": last_10_data})

    # Real-time updating logic (after the initial load)
    new_sequence = get_last_sequence()

    # Check if the new sequence is different from the previous one
    if new_sequence != last_fetched_sequence:
        changeset_count = get_changeset_count(new_sequence)
        last_fetched_sequence = new_sequence  # Update the last fetched sequence
        return JsonResponse({"sequence": new_sequence, "changeset_count": changeset_count})
    
    # If there's no new sequence, return an empty response to avoid updating
    return JsonResponse({"sequence": last_fetched_sequence, "changeset_count": None})
