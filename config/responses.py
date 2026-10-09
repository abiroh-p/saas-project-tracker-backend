from rest_framework.response import Response


def api_error(detail, code, http_status):
    return Response(
        {'detail': detail, 'code': code},
        status=http_status,
    )
