from rest_framework import serializers

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_field

from .models import Project, ProjectMember

User = get_user_model()


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
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = ProjectMember
        fields = [
            'id',
            'user_id',
            'username',
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
