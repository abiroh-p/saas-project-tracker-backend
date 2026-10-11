from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import MAX_COMMENT_LENGTH, Comment
from .services.mentions import extract_mentioned_usernames


class CommentInputSerializer(serializers.Serializer):
    """Only the text can be written. The author is always the request user
    and the issue comes from the URL, so neither is accepted from the client.
    """

    body = serializers.CharField(max_length=MAX_COMMENT_LENGTH)


class CommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    mentions = serializers.SerializerMethodField()
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Comment
        fields = (
            'id',
            'issue',
            'author',
            'body',
            'mentions',
            'created_at',
            'updated_at',
            'edited_at',
            'is_deleted',
            'deleted_at',
        )
        read_only_fields = fields

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

    @extend_schema_field({'type': 'string', 'nullable': True})
    def get_body(self, comment):
        # A deleted comment keeps its place in the discussion but not its text.
        return None if comment.is_deleted else comment.body

    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'id': {'type': 'integer'},
                'username': {'type': 'string'},
            },
            'required': ['id', 'username'],
        },
    })
    def get_mentions(self, comment):
        """Members mentioned in the text, in order of appearance, so the
        client can turn "@name" into a link. Deleted comments mention no
        one."""
        if comment.is_deleted:
            return []

        users = {
            user.username.lower(): user
            for user in comment.mentions.all()
        }

        return [
            {'id': users[name].id, 'username': users[name].username}
            for name in extract_mentioned_usernames(comment.body)
            if name in users
        ]
