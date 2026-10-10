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

    def get_user(self, activity):
        return {
            'id': activity.user_id,
            'username': activity.user.username,
        }


class ActivityFilterSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=Activity.Action.choices,
        required=False,
    )
    entity_type = serializers.ChoiceField(
        choices=Activity.EntityType.choices,
        required=False,
    )
    entity_id = serializers.IntegerField(
        min_value=1,
        required=False,
    )
