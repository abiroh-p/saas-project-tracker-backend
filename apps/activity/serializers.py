from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Activity


class ActivitySerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = (
            'id',
            'user',
            'action',
            'entity_type',
            'entity_id',
            'description',
            'metadata',
            'created_at',
        )

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'id': {'type': 'integer'},
            'username': {'type': 'string'},
        },
        'required': ['id', 'username'],
    })
    def get_user(self, activity):
        return {
            'id': activity.user_id,
            'username': activity.user.username,
        }


class IssueActivityFilterSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=Activity.Action.choices,
        required=False,
    )
    user = serializers.IntegerField(
        min_value=1,
        required=False,
    )


class ActivityFilterSerializer(IssueActivityFilterSerializer):
    entity_type = serializers.ChoiceField(
        choices=Activity.EntityType.choices,
        required=False,
    )
    entity_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )

    def validate(self, attrs):
        # Ids are only unique within an entity type (issue 5 and membership 5
        # can both exist), so an id alone would mix unrelated events.
        if 'entity_id' in attrs and 'entity_type' not in attrs:
            raise serializers.ValidationError({
                'entity_type': 'This field is required when filtering '
                               'by entity_id.',
            })

        return attrs
