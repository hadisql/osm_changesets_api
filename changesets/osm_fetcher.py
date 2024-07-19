from os import path
import requests
import xml.etree.ElementTree as ET
import gzip
from .models import Changeset
from datetime import datetime
from django.utils import timezone
import json
import copy

COLUMNS_MAPPING = {
    "id": "changeset_id",
    "created_at": "created_at",
    "closed_at": "closed_at",
    "open": "open",
    "num_changes": "changes_count",
    "user": "user",
    "uid": "user_id",
    "min_lat": "min_lat",
    "max_lat": "max_lat",
    "min_lon": "min_lon",
    "max_lon": "max_lon",
    "comments_count": "comments_count"
}


def urlized_sequence_number(sequence_number):
    
    # returns url of the form https://planet.osm.org/replication/changesets/123/456/789.osm.gz
    sequence_number_adjusted = str(sequence_number).rjust(9, "0")
    return f"https://planet.osm.org/replication/changesets/{sequence_number_adjusted[0:3]}/{sequence_number_adjusted[3:6]}/{sequence_number_adjusted[6:9]}.osm.gz"


def get_sequence_min_max_changeset_id(sequence_number, locally=False):
    # returns min and max values of changeset ids 
    if locally:
        sequence_path = "./source/" + str(sequence_number) + ".osm.gz"
        with open(sequence_path, 'rb') as sequence_file:
            xml_sequence = ET.fromstring(gzip.decompress(sequence_file.read()))
    else:
        url_sequence = urlized_sequence_number(sequence_number)
        xml_sequence_request = requests.get(url_sequence, stream=True).raw.read()
        xml_sequence = ET.fromstring(gzip.decompress(xml_sequence_request))
    return min(xml_sequence, key=lambda x: x.attrib['id']).attrib['id'], max(xml_sequence, key=lambda x: x.attrib['id']).attrib['id']


def process_sequence(sequence_number, save_db=True):
    
    sequence_path = "./source/" + str(sequence_number) + ".osm.gz"
    if not path.isfile(sequence_path):
        url_sequence = urlized_sequence_number(sequence_number)
        xml_sequence_request = requests.get(url_sequence, stream=True).raw.read()
        xml_sequence = ET.fromstring(gzip.decompress(xml_sequence_request))
        with open(sequence_path, 'wb') as sequence_file:
            sequence_file.write(xml_sequence_request)
    else:
        with open(sequence_path, 'rb') as sequence_file:
            xml_sequence = ET.fromstring(gzip.decompress(sequence_file.read()))

    changesets_processed = []

    for changeset in xml_sequence:
        """
        Changeset overview :
            <changeset [...] attribute_key="attribute_value" [...]>
                [...]
                # list of elements, in OSM there is moslty tag elements, with k/v attributes for key/values
                <tag k="key" v="value"/>
                [...]
            </changeset>
            <osm>
            <changeset id="113928427" created_at="2021-11-18T06:17:42Z" open="false" comments_count="0" changes_count="6" closed_at="2021-11-18T06:17:44Z" min_lat="15.3384649" min_lon="-91.8697209" max_lat="15.3386183" max_lon="-91.8694203" uid="12026398" user="<redacted>">
            <tag k="changesets_count" v="73"/>
            [...] # More k,v tags
            </changeset>
            <changeset id="113928426" created_at="2021-11-18T06:17:42Z" open="false" comments_count="0" changes_count="11" closed_at="2021-11-18T06:17:43Z" min_lat="-23.6402734" min_lon="47.3068178" max_lat="-23.6387451" max_lon="47.3096663" uid="13571396" user="<redated>">
            <tag k="changesets_count" v="2200"/>
            [...] # More k,v tags
            </changeset>
            [...] # more changesets
            </osm>
        """
        changeset_to_add = {}
        changeset_to_add["tags"] = {}

        changeset_id = int(changeset.attrib['id'])

        for attribute, value in changeset.attrib.items():
            if attribute in COLUMNS_MAPPING:
                if attribute == "open":
                    value = value.lower() == 'true'
                elif attribute in ["changes_count", "comments_count", "user_id"]:
                    value = int(value)
                elif attribute in ["min_lat", "max_lat", "min_lon", "max_lon"]:
                    value = float(value)
                elif attribute in ["created_at", "closed_at"] and save_db: # when save_db = False, don't convert to datetime object
                    naive_datetime = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                    value = timezone.make_aware(naive_datetime, timezone.utc) # prevents from RuntimeWarning about time zone

                changeset_to_add[COLUMNS_MAPPING[attribute]] = value

            else :
                print("Sequence number : " + sequence_number)
                print("Changeset " + changeset.attrib["id"])
                print("Changeset attribute not known : " + attribute)
                    
        for element in changeset:
            if 'tag' in element.tag:
                if 'k' in element.attrib:
                    changeset_to_add["tags"][element.attrib["k"]] = element.attrib["v"]
            elif 'discussion' in element.tag:
                ## TODO : implement
                continue
            else:
                print("Sequence number : " + str(sequence_number))
                print("Changeset : " + changeset.attrib["id"])
                print("Element of XML not being a <tag> nor <discussion> : " + element.tag)

        if save_db and not Changeset.objects.filter(changeset_id=changeset_id).exists():
            Changeset.objects.create(**changeset_to_add)

        changesets_processed.append(changeset_to_add)

    print("Processed " + str(sequence_number))
    
    return changesets_processed


def fetch_and_process_changesets(seq_start, seq_end, save_locally=False):

    if seq_start > seq_end:
        seq_start, seq_end = seq_end, seq_start

    for i, sequence_number in enumerate(range(seq_start, seq_end + 1)):
        if save_locally:
            output_path = "./output/" + str(sequence_number) + ".jsonl"
            if not path.isfile(output_path):
                output_changesets = process_sequence(sequence_number, save_db=False) # if user saves locally, don't save in db
                with open(output_path, 'w') as output_file:
                    for output_changeset in output_changesets:
                        json.dump(output_changeset, output_file)
                        output_file.write('\n')
            else:
                print("Sequence " + str(sequence_number) + " already processed.")
                
        
        else:
            # If user doesn't want to save locally, save in db
            output_changesets = process_sequence(sequence_number, save_db=True)

    # get min and max values of changeset ids
    min_changesets = get_sequence_min_max_changeset_id(seq_start, locally=save_locally)[0]
    max_changesets = get_sequence_min_max_changeset_id(seq_end, locally=save_locally)[1]
            
    return min_changesets, max_changesets




###### TESTING ######
# this is for debugging/testing
def duration_info(sequence_number):
    data = process_sequence(sequence_number, False)
    min_created_at = min(data, key=lambda x: x['created_at'])['created_at']
    max_created_at = max(data, key=lambda x: x['created_at'])['created_at']
    duration = max_created_at - min_created_at
    print('max created at : ' + str(max_created_at))
    print('min created at : ' + str(min_created_at))
    print("Duration : " + str(duration))
    return duration