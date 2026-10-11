from rest_framework import serializers

from apps.issues.models import Issue


class DashboardIssueSerializer(serializers.ModelSerializer):
    """The few issue fields a dashboard row needs."""

    issue_key = serializers.CharField(read_only=True)
    project_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Issue
        fields = [
            'id',
            'issue_key',
            'title',
            'status',
            'priority',
            'project_id',
            'due_date',
            'updated_at',
        ]
        read_only_fields = fields


class DashboardSummarySerializer(serializers.Serializer):
    projects_count = serializers.IntegerField(
        help_text='Non-archived projects the user is a member of.',
    )
    assigned_issues_count = serializers.IntegerField(
        help_text='Non-archived issues assigned to the user in projects '
                  'they can access. Normally equals the sum of '
                  'issues_by_status; it also counts any issue whose status '
                  'is not one of the declared choices.',
    )
    in_progress_count = serializers.IntegerField(
        help_text='Assigned issues with status IN_PROGRESS.',
    )
    completed_count = serializers.IntegerField(
        help_text='Assigned issues with status DONE.',
    )
    overdue_count = serializers.IntegerField(
        help_text='Assigned, incomplete issues with a due date before today.',
    )


# One integer field per declared status, so the documented keys can never
# drift from Issue.Status.
IssuesByStatusSerializer = type(
    'IssuesByStatusSerializer',
    (serializers.Serializer,),
    {value: serializers.IntegerField() for value in Issue.Status.values},
)


class DashboardSerializer(serializers.Serializer):
    summary = DashboardSummarySerializer()
    issues_by_status = IssuesByStatusSerializer()
    recent_issues = DashboardIssueSerializer(many=True)
