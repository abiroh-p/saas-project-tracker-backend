from rest_framework.exceptions import ValidationError
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return None

    if isinstance(exc, ValidationError):
        data = response.data

        if isinstance(data, dict):
            errors = dict(data)
        else:
            errors = {'non_field_errors': list(data)}

        response.data = {
            'detail': 'Validation failed.',
            'code': 'validation_error',
            'errors': errors,
        }
        return response

    data = response.data if isinstance(response.data, dict) else {}
    codes = exc.get_codes() if hasattr(exc, 'get_codes') else 'error'

    response.data = {
        'detail': str(data.get('detail', exc)),
        'code': data.get('code') or (codes if isinstance(codes, str) else 'error'),
    }
    return response
