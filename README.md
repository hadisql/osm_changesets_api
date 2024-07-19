# OSM Changesets API

### This is a Django Rest Framwork API for Open Street Map changesets.

### It is based on the work made [here](https://github.com/johanmorganti/osm-monitor/tree/main)

When executing 
```python manage.py runserver``` 
on localhost, in your browser go to `http://127.0.0.1/api/changesets/<start_sequence>/<end_sequence>`
where **start_sequence** and **end_sequence** correspond to the [replication changesets](https://planet.osm.org/replication/changesets/). The last one can be found [here](https://planet.osm.org/replication/changesets/state.yaml) (it is a .yaml file, updating very regularly)

### More to come..! 