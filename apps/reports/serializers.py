"""Response shapes of the report endpoints.

The views return plain dicts built by the services; these serializers exist to
document those shapes in the OpenAPI schema, and a test keeps them in step
with the real responses.
"""
from rest_framework import serializers

from apps.issues.models import Issue


class ReportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField()


class ProjectOverviewSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    project_key = serializers.CharField()
    total_issues = serializers.IntegerField(
        help_text='Non-archived issues in the project.',
    )
    open_issues = serializers.IntegerField(
        help_text='Issues not started yet (status TODO).',
    )
    in_progress_issues = serializers.IntegerField(
        help_text='Issues being worked on (status IN_PROGRESS or IN_REVIEW).',
    )
    completed_issues = serializers.IntegerField(
        help_text='Issues with status DONE.',
    )
    overdue_issues = serializers.IntegerField(
        help_text='Issues that are not DONE and whose due date is before '
                  'today. An issue due today is not overdue.',
    )
    unassigned_issues = serializers.IntegerField(
        help_text='Issues with no assignee.',
    )
    completion_rate = serializers.FloatField(
        help_text='completed_issues / total_issues * 100, rounded half-up '
                  'to one decimal place; 0.0 when the project has no issues.',
    )


class StatusCountSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Issue.Status.choices)
    label = serializers.CharField()
    count = serializers.IntegerField()


class StatusDistributionSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    results = StatusCountSerializer(many=True)
    other_count = serializers.IntegerField(
        help_text='Issues whose status is not one of the declared choices '
                  '(legacy data). Normally 0.',
    )
    total_issues = serializers.IntegerField(
        help_text='Sum of every count in `results` plus `other_count`.',
    )


class PriorityCountSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=Issue.Priority.choices)
    label = serializers.CharField()
    count = serializers.IntegerField()


class PriorityDistributionSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    results = PriorityCountSerializer(many=True)
    other_count = serializers.IntegerField(
        help_text='Issues whose priority is not one of the declared choices '
                  '(legacy data). Normally 0.',
    )
    total_issues = serializers.IntegerField(
        help_text='Sum of every count in `results` plus `other_count`.',
    )


class AssigneeWorkloadItemSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(
        allow_null=True,
        help_text='`null` for the group of unassigned issues.',
    )
    username = serializers.CharField(allow_null=True)
    full_name = serializers.CharField(allow_null=True)
    assigned_issues = serializers.IntegerField()
    open_issues = serializers.IntegerField()
    in_progress_issues = serializers.IntegerField()
    completed_issues = serializers.IntegerField()
    overdue_issues = serializers.IntegerField()


class AssigneeWorkloadSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    results = AssigneeWorkloadItemSerializer(many=True)
    total_issues = serializers.IntegerField(
        help_text='Sum of `assigned_issues` over all groups.',
    )


class TrendPointSerializer(serializers.Serializer):
    period = serializers.DateField(
        help_text='The day, or the Monday that starts the week.',
    )
    created_count = serializers.IntegerField()
    completed_count = serializers.IntegerField()


class TrendsSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    interval = serializers.ChoiceField(choices=['day', 'week'])
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    results = TrendPointSerializer(many=True)
