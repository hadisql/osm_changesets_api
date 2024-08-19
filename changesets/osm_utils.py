from os import path, makedirs
import requests
import xml.etree.ElementTree as ET
import gzip
from datetime import datetime
from django.utils import timezone
from .models import Changeset
from django.forms.models import model_to_dict

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
    "comments_count": "comments_count",
}

SPECIAL_TAGS = ["comment","created_by","locale","source","hashtags","imagery_used","host"]

def compare_attributes(value, db_value):
    """
    Compare the given value with the database value.
    Handles special cases like datetime objects and NoneType. 
    (used in changeset_check_if_updates)
    """
    # Handle NoneType: if db_value is None, just compare it directly
    if db_value is None:
        return value == db_value

    # Handle datetime comparison separately
    if isinstance(value, datetime):
        return value == db_value
    
    # Handle dictionary comparison (e.g., for 'tags' attribute)
    if isinstance(value, dict):
        return value == db_value
    
    # Apply type conversion for other types
    return value == type(value)(db_value)

def changeset_snapshot(db_changeset):
    '''
    Create a snapshot of the changeset object.
    '''
    # Convert model instance to dictionary, excluding unnecessary fields
    current_state = model_to_dict(db_changeset, exclude=['id', 'changeset_id', 'history'])

    # Convert datetime fields to ISO format
    for field in ['created_at', 'closed_at']:
        if current_state.get(field):
            current_state[field] = current_state[field].isoformat()

    return current_state

def changeset_update_and_process(formatted_changeset, sequence_number, save_db):
    '''
    For each fetched changeset in the sequence, check if it exists in the database. 
    If it does, check if there are any updates to the changeset. 
    If there are, update the database with the new values and keep track of previous values by appending the history list (attribute) of the Changeset object.
    '''
    changeset_id = int(formatted_changeset['changeset_id'])

    if save_db and Changeset.objects.filter(changeset_id=changeset_id).exists():
        # Retrieve the existing Changeset object from the database
        db_changeset = Changeset.objects.get(changeset_id=changeset_id)
        
        # Track if any changes were made
        changes_made = False

        # a snapshot of the current state before making updates
        current_state = changeset_snapshot(db_changeset)
        
        # Check if current sequence is later than the one processed to populate the changeset data
        if int(sequence_number) >= int(current_state['sequence_from']):
            for attribute, value in formatted_changeset.items():
                # Check if any of the attributes have changed
                db_value = getattr(db_changeset, attribute)
                if not compare_attributes(value, db_value):
                    print(f"Attribute {attribute} has changed: {db_value} -> {value}")
            
                    # Update the attribute in the db (using custom save method)
                    setattr(db_changeset, attribute, value)
                    changes_made = True
        # if the changeset has data from a later sequence -> no changeset data update, but append its history attribute
        else:
            print(f"Changeset {changeset_id} has data from a later sequence ({current_state['sequence_from']}) than the one being processed ({sequence_number})")
            # if the history doesn't contain the current (older) sequence, append it
            if not sequence_number in [dict['sequence_from'] for dict in db_changeset.history]:
                # making formatted_changeset datetime attributes JSON serializable 
                if 'created_at' in formatted_changeset:
                    formatted_changeset['created_at'] = formatted_changeset['created_at'].isoformat()
                if 'closed_at' in formatted_changeset:
                    formatted_changeset['closed_at'] = formatted_changeset['closed_at'].isoformat()

                db_changeset.history.append(formatted_changeset)
                db_changeset.save()
                print(f"History appended for Changeset {db_changeset.changeset_id} for 'earlier' than this sequence ({sequence_number})")
            else:
                print(f"History already contains the current sequence ({sequence_number}) for Changeset {db_changeset.changeset_id}")

        if changes_made:
            # Append the previous state to the history list
            db_changeset.history.append(current_state)
            
            # Save the updated Changeset object
            db_changeset.save()
            print(f"History saved for Changeset {db_changeset.changeset_id}")

    elif save_db and not Changeset.objects.filter(changeset_id=changeset_id).exists():
        # Create a new Changeset object if it doesn't already exist
        Changeset.objects.create(**formatted_changeset)

    return formatted_changeset



def use_local_data_or_fetch(sequence_number):
    source_dir = "./source"
    sequence_path = path.join(source_dir, str(sequence_number) + ".osm.gz")
    
    # Ensure the source directory exists
    if not path.exists(source_dir):
        makedirs(source_dir)

    if not path.isfile(sequence_path):
        sequence_was_fetched = True
        url_sequence = urlized_sequence_number(sequence_number)
        xml_sequence_request = requests.get(url_sequence, stream=True).raw.read()
        xml_sequence = ET.fromstring(gzip.decompress(xml_sequence_request))
        with open(sequence_path, 'wb') as sequence_file:
            sequence_file.write(xml_sequence_request)
    else:
        sequence_was_fetched = False
        with open(sequence_path, 'rb') as sequence_file:
            xml_sequence = ET.fromstring(gzip.decompress(sequence_file.read()))

    return xml_sequence, sequence_was_fetched

def urlized_sequence_number(sequence_number):
    # returns url of the form https://planet.osm.org/replication/changesets/123/456/789.osm.gz
    sequence_number_adjusted = str(sequence_number).rjust(9, "0")
    return f"https://planet.osm.org/replication/changesets/{sequence_number_adjusted[0:3]}/{sequence_number_adjusted[3:6]}/{sequence_number_adjusted[6:9]}.osm.gz"


def changeset_formatting(changeset, sequence_number, save_db):
    formatted_changeset = {}
    formatted_changeset["additional_tags"] = {}
    formatted_changeset["hashtags"] = []

    # formatting changeset data
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

            formatted_changeset[COLUMNS_MAPPING[attribute]] = value

        else :
            print("Sequence number : " + sequence_number)
            print("Changeset " + changeset.attrib["id"])
            print("Changeset attribute not known : " + attribute)

    # Process tags elements
    for tag in changeset.findall('tag'):
        # if tag in SPECIAL_TAGS then add these tag keys to the Changeset object:
        if tag.attrib["k"] in SPECIAL_TAGS:
            if tag.attrib["k"] == "hashtags":
                formatted_changeset[tag.attrib["k"]].extend(tag.attrib["v"].split(";"))
            else:
                formatted_changeset[tag.attrib["k"]] = tag.attrib["v"]
        # otherwise, add the tag to the Changeset object's additional tags list:
        else:
            formatted_changeset["additional_tags"][tag.attrib["k"]] = tag.attrib["v"]

    formatted_changeset['sequence_from'] = sequence_number
    return formatted_changeset
