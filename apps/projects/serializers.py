from rest_framework import serializers

from .models import Project


class ProjectSerializer(serializers.ModelSerializer):
    created_by = serializers.ReadOnlyField(
        source='created_by.username'
    )

    class Meta:
        model = Project
        fields = [
            'id',
            'key',
            'name',
            'description',
            'start_date',
            'end_date',
            'created_by',
            'created_at',
            'updated_at',
            'is_archived',
        ]

        read_only_fields = [
            'id',
            'created_by',
            'created_at',
            'updated_at',
        ]

    def validate(self, attrs):
        start_date = attrs.get('start_date')
        end_date = attrs.get('end_date')

        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {
                    'end_date': (
                        'End date must be greater than or equal '
                        'to the start date.'
                    )
                }
            )

        return attrs