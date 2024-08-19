from rest_framework import serializers
from .models import Changeset



class ChangesetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Changeset
        fields = '__all__'
        hide_fields = ['id'] # fields to hide from the serializer (corresponds to the Changeset model's id field in the database -> useless)

    # overriding the get_field_names method to remove the fields defined in hide_fields
    def get_field_names(self, declared_fields, info):
        diminished_fields = super(ChangesetSerializer, self).get_field_names(declared_fields, info)
        return [field for field in diminished_fields if field not in self.Meta.hide_fields]