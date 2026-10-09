from drf_spectacular.utils import inline_serializer
from rest_framework import serializers


def paginated(serializer_class):
    return inline_serializer(
        name=f'Paginated{serializer_class.__name__}',
        fields={
            'count': serializers.IntegerField(),
            'next': serializers.URLField(allow_null=True),
            'previous': serializers.URLField(allow_null=True),
            'results': serializer_class(many=True),
        },
    )
