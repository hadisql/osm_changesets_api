from os import path, makedirs
import requests
import xml.etree.ElementTree as ET
import gzip
from datetime import datetime
from django.utils import timezone
from .models import Changeset

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

def changeset_check_if_updates(changeset, changeset_to_add, sequence_number, save_db):
    changeset_id = int(changeset.attrib['id'])

    if save_db and Changeset.objects.filter(changeset_id=changeset_id).exists():
        # Retrieve the existing Changeset object from the database
        db_changeset = Changeset.objects.get(changeset_id=changeset_id)
        
        # Track if any changes were made
        changes_made = False

        # a snapshot of the current state before making updates
        current_sequence_from = db_changeset.sequence_from
        current_state = {
            'sequence_from': current_sequence_from,
            'created_at': db_changeset.created_at.isoformat() if db_changeset.created_at else None,
            'closed_at': db_changeset.closed_at.isoformat() if db_changeset.closed_at else None,
            'open': db_changeset.open,
            'changes_count': db_changeset.changes_count,
            'user': db_changeset.user,
            'user_id': db_changeset.user_id,
            'min_lat': db_changeset.min_lat,
            'max_lat': db_changeset.max_lat,
            'min_lon': db_changeset.min_lon,
            'max_lon': db_changeset.max_lon,
            'comments_count': db_changeset.comments_count,
            'tags': db_changeset.tags,
            # 'timestamp': timezone.now().isoformat()  # Record the time of this snapshot
        }
        
        # Check if current sequence is later than the one processed to populate the changeset data
        if sequence_number >= current_sequence_from:
            for attribute, value in changeset_to_add.items():
                # Check if any of the attributes have changed
                db_value = getattr(db_changeset, attribute)
                if not compare_attributes(value, db_value):
                    print(f"Attribute {attribute} has changed: {db_value} -> {value}")
            
                    # Update the attribute in the db (using custom save method)
                    setattr(db_changeset, attribute, value)
                    changes_made = True
        # if the changeset has data from a later sequence -> no changeset data update, but append its history attribute
        else:
            print(f"Changeset {changeset_id} has data from a later sequence ({current_sequence_from}) than the one being processed ({sequence_number})")
            # if the history doesn't contain the current (older) sequence, append it
            if not sequence_number in [dict['sequence_from'] for dict in db_changeset.history]:
                # making changeset_to_add datetime attributes JSON serializable 
                if 'created_at' in changeset_to_add:
                    changeset_to_add['created_at'] = changeset_to_add['created_at'].isoformat()
                if 'closed_at' in changeset_to_add:
                    changeset_to_add['closed_at'] = changeset_to_add['closed_at'].isoformat()

                db_changeset.history.append(changeset_to_add)
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
        Changeset.objects.create(**changeset_to_add)

    return changeset_to_add



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
    changeset_to_add = {}
    changeset_to_add["tags"] = {}

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

    changeset_to_add['sequence_from'] = sequence_number
    return changeset_to_add