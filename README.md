# OSM Changesets API

### This is a Django Rest Framwork API for Open Street Map changesets.

### It is based on the work made [here](https://github.com/johanmorganti/osm-monitor/tree/main)

API ideas : 
* graph changesets between 2 periods
    * `api/count`
        * This API will be used to power graphs : it will return about 300 data points for each query : each data point representing a `time-bucket` or `interval`
        * Parameters : 
            * `from`
            * `to`
            * `type` : what we want to count
                * default : `changesets`
                * Other possible values : [`users`, `objects`]
            * `group_by` : return results split by an attribute
                * default : `none`, return each time bucket
                * possible values : [`user`, `editor`, `language`]
        * Response :
            * Total count for the whole interval
            * Total count for each time bucket + group_by value


When executing 
```python manage.py runserver``` 
on localhost, in your browser go to `http://127.0.0.1/api/changesets/<start_sequence>/<end_sequence>`
where **start_sequence** and **end_sequence** correspond to the [replication changesets](https://planet.osm.org/replication/changesets/). The last one can be found [here](https://planet.osm.org/replication/changesets/state.yaml) (it is a .yaml file, updating very regularly)

### More to come..! 