import re

from rest_framework import serializers

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field

from .models import Project, ProjectMember

User = get_user_model()

# Jira-style: 2-10 characters, starts with a letter, letters and digits only.
PROJECT_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9]{1,9}$')


class ProjectSerializer(serializers.ModelSerializer):
    created_by = serializers.ReadOnlyField(
        source='created_by.username'
    )

    my_role = serializers.SerializerMethodField()

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
            'my_role',
        ]

        read_only_fields = [
            'id',
            'created_by',
            'created_at',
            'updated_at',
        ]

    @extend_schema_field(
        serializers.ChoiceField(
            choices=ProjectMember.Role.choices,
            allow_null=True,
        )
    )
    def get_my_role(self, obj):
        request = self.context.get('request')

        if request is None or not request.user.is_authenticated:
            return None

        for member in obj.members.all():
            if member.user_id == request.user.id:
                return member.role

        return None

    def validate_key(self, value):
        value = value.strip().upper()

        if not PROJECT_KEY_PATTERN.match(value):
            raise serializers.ValidationError(
                'Use 2 to 10 letters or digits, starting with a letter.'
            )

        # The unique validator ran on the raw input, so check the normalised
        # value too ('demo' must not slip past an existing 'DEMO').
        taken = Project.objects.filter(key=value)

        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)

        if taken.exists():
            raise serializers.ValidationError(
                'A project with this key already exists.'
            )

        return value

    def validate(self, attrs):
        if (
            self.instance
            and 'key' in attrs
            and attrs['key'] != self.instance.key
        ):
            raise serializers.ValidationError(
                {
                    'key': 'Project key cannot be changed.'
                }
            )

        start_date = attrs.get(
            'start_date',
            self.instance.start_date if self.instance else None,
        )

        end_date = attrs.get(
            'end_date',
            self.instance.end_date if self.instance else None,
        )

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


class ProjectMemberSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    full_name = serializers.CharField(source='user.full_name', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = ProjectMember
        fields = [
            'id',
            'user_id',
            'username',
            'full_name',
            'email',
            'role',
            'created_at',
        ]
        read_only_fields = fields


class AddProjectMemberSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    role = serializers.ChoiceField(
        choices=ProjectMember.Role.choices,
        default=ProjectMember.Role.TEAM_MEMBER,
    )

    def validate_user_id(self, value):
        if not User.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError('User not found.')

        return value


class UpdateProjectMemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ProjectMember.Role.choices)
