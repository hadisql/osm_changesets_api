from os import path, makedirs
import requests
import xml.etree.ElementTree as ET
import gzip
from .models import Changeset
from datetime import datetime
from django.utils import timezone
import json
from django.conf import settings
from .osm_utils import urlized_sequence_number, changeset_formatting, use_local_data_or_fetch, changeset_check_if_updates


def process_sequence(sequence_number, save_db=True):
    
    # fetch and process changesets (locally or online)
    xml_sequence, sequence_was_fetched = use_local_data_or_fetch(sequence_number)

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
        
        # formatting changeset
        changeset_to_add = changeset_formatting(changeset, sequence_number, save_db)

        # check if changeset has been updated for the given sequence
        changeset_updated = changeset_check_if_updates(changeset, changeset_to_add, sequence_number, save_db)
        changesets_processed.append(changeset_updated)

    if sequence_was_fetched:
        print("Processed " + str(sequence_number) + ", data fetched from planet.osm.org")
    else:
        print("Processed " + str(sequence_number) + ", data fetched locally")
    
    return changesets_processed


def fetch_and_process_changesets(seq_start, seq_end, save_locally=False):

    if seq_start > seq_end:
        seq_start, seq_end = seq_end, seq_start

    all_changesets = []
    for i, sequence_number in enumerate(range(seq_start, seq_end + 1)):
        if save_locally:
            output_dir = './output'
            output_path = path.join(output_dir, str(sequence_number) + ".jsonl")

            # Ensure the output directory exists
            if not path.exists(output_dir):
                makedirs(output_dir)

            # If the output file doesn't exist, process the sequence
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

        all_changesets.extend(output_changesets)

    return all_changesets



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