from django.db import connection
from django.http import JsonResponse


class HealthCheckMiddleware:
    """Liveness and readiness endpoints for container probes.

    Handled before the rest of the stack because probes call the container by IP, which would
    otherwise be rejected by ALLOWED_HOSTS validation (and bounced by the HTTPS redirect).

    /api/healthz  process is up (no dependencies touched)
    /api/readyz   process is up and the database answers
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in ("GET", "HEAD"):
            if request.path == "/api/healthz":
                return JsonResponse({"status": "ok"})
            if request.path == "/api/readyz":
                return self._readiness()
        return self.get_response(request)

    @staticmethod
    def _readiness():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return JsonResponse({"status": "unavailable"}, status=503)
        return JsonResponse({"status": "ok"})
