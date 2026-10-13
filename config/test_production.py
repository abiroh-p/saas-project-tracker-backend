from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.throttling import ScopedRateThrottle


class HealthCheckTests(TestCase):
    def test_liveness_ignores_host_validation(self):
        response = self.client.get("/api/healthz", HTTP_HOST="10.0.0.5:8000")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readiness_checks_database(self):
        response = self.client.get("/api/readyz", HTTP_HOST="10.0.0.5:8000")
        self.assertEqual(response.status_code, 200)

    def test_readiness_reports_unavailable_database(self):
        with mock.patch("config.middleware.connection.cursor", side_effect=Exception("db down")):
            response = self.client.get("/api/readyz", HTTP_HOST="10.0.0.5:8000")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_probe_does_not_accept_writes(self):
        response = self.client.post("/api/healthz")
        self.assertNotEqual(response.status_code, 200)


class AuthThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_login_is_rate_limited(self):
        rates = {**ScopedRateThrottle.THROTTLE_RATES, "login": "3/min"}
        with mock.patch.object(ScopedRateThrottle, "THROTTLE_RATES", rates):
            statuses = [
                self.client.post(
                    "/api/v1/accounts/login/",
                    {"identifier": "nobody@example.com", "password": "wrong-password"},
                    content_type="application/json",
                ).status_code
                for _ in range(4)
            ]
        self.assertNotIn(429, statuses[:3])
        self.assertEqual(statuses[3], 429)


class ApiDocsSwitchTests(SimpleTestCase):
    def test_docs_are_off_by_default_outside_debug(self):
        from django.conf import settings

        self.assertEqual(settings.ENABLE_API_DOCS, settings.DEBUG)
