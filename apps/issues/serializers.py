import re

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.projects.models import ProjectMember

from .models import Comment, Issue


class IssueSerializer(serializers.ModelSerializer):
    issue_key = serializers.CharField(read_only=True)

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

    reporter_detail = serializers.SerializerMethodField()
    assignee_detail = serializers.SerializerMethodField()

    def _user_brief(self, user):
        if user is None:
            return None

        return {'id': user.id, 'username': user.username}

    @extend_schema_field({'type': 'object', 'nullable': True, 'properties': {'id': {'type': 'integer'}, 'username': {'type': 'string'}}})
    def get_reporter_detail(self, obj):
        return self._user_brief(obj.reporter)

    @extend_schema_field({'type': 'object', 'nullable': True, 'properties': {'id': {'type': 'integer'}, 'username': {'type': 'string'}}})
    def get_assignee_detail(self, obj):
        return self._user_brief(obj.assignee)

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
            'reporter_detail',
            'assignee_detail',
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


class CommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id',
            'issue',
            'author',
            'body',
            'created_at',
            'updated_at',
            'is_deleted',
            'deleted_at',
        ]
        read_only_fields = [
            'id',
            'issue',
            'author',
            'created_at',
            'updated_at',
            'is_deleted',
            'deleted_at',
        ]

    @extend_schema_field({
        'type': 'object',
        'properties': {
            'id': {'type': 'integer'},
            'username': {'type': 'string'},
        },
        'required': ['id', 'username'],
    })
    def get_author(self, comment):
        return {
            'id': comment.author_id,
            'username': comment.author.username,
        }

    def validate_body(self, value):
        body = value.strip()
        if not body:
            raise serializers.ValidationError(
                'Comment cannot be empty.'
            )

        issue = self.context['issue']
        usernames = set(re.findall(r'(?<![\w@])@([\w.-]+)', body))
        if usernames:
            valid_usernames = set(
                ProjectMember.objects.filter(
                    project=issue.project,
                    user__username__in=usernames,
                ).values_list('user__username', flat=True)
            )
            unknown = usernames - valid_usernames
            if unknown:
                raise serializers.ValidationError(
                    'Mentions must refer to members of this project.'
                )

        return body
