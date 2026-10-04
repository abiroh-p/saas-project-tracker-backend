from rest_framework import serializers

from .models import Issue


class IssueSerializer(serializers.ModelSerializer):
    issue_key = serializers.ReadOnlyField()

    reporter = serializers.ReadOnlyField(
        source='reporter.username',
    )

    assignee = serializers.PrimaryKeyRelatedField(
        queryset=Issue._meta.get_field(
            'assignee'
        ).remote_field.model.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Issue
        fields = [
            'id',
            'issue_key',
            'issue_number',
            'project',
            'title',
            'description',
            'issue_type',
            'priority',
            'status',
            'reporter',
            'assignee',
            'due_date',
            'created_at',
            'updated_at',
            'is_archived',
        ]
        read_only_fields = [
            'id',
            'issue_key',
            'issue_number',
            'project',
            'reporter',
            'status',
            'created_at',
            'updated_at',
            'is_archived',
        ]

    def validate(self, attrs):
        start_date = None
        end_date = None

        if self.instance:
            project = self.instance.project
        else:
            project = self.context.get('project')

        if project:
            start_date = project.start_date
            end_date = project.end_date

        due_date = attrs.get(
            'due_date',
            self.instance.due_date if self.instance else None,
        )

        if (
            due_date
            and start_date
            and due_date < start_date
        ):
            raise serializers.ValidationError(
                {
                    'due_date': (
                        'Due date cannot be before '
                        'the project start date.'
                    )
                }
            )

        if (
            due_date
            and end_date
            and due_date > end_date
        ):
            raise serializers.ValidationError(
                {
                    'due_date': (
                        'Due date cannot be after '
                        'the project end date.'
                    )
                }
            )

        return attrs

class IssueTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=Issue.Status.choices,
    )