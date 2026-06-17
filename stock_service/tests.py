from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse


User = get_user_model()


class MonitoringEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()

    @override_settings(APP_VERSION="test-version", APP_BUILD_SHA="abc123")
    def test_healthz_returns_public_ok_payload(self):
        response = self.client.get("/healthz/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["service"], "stock-workbench")
        self.assertEqual(response.json()["version"], "test-version")
        self.assertEqual(response.json()["build_sha"], "abc123")

    def test_readyz_returns_ready_payload(self):
        response = self.client.get("/readyz/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ready")
        self.assertTrue(payload["checks"]["database"]["ok"])
        self.assertTrue(payload["checks"]["migrations"]["ok"])

    @patch(
        "stock_service.monitoring._check_default_database",
        return_value={"ok": False, "alias": "default", "error_type": "OperationalError"},
    )
    def test_readyz_returns_503_when_database_check_fails(self, _mock_database_check):
        response = self.client.get("/readyz/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["checks"]["database"]["ok"])
        self.assertTrue(payload["checks"]["migrations"]["skipped"])

    @patch(
        "stock_service.monitoring._check_pending_migrations",
        return_value={"ok": False, "pending_count": 2},
    )
    def test_readyz_returns_503_when_pending_migrations_exist(self, _mock_migration_check):
        response = self.client.get("/readyz/", HTTP_HOST="localhost")

        self.assertEqual(response.status_code, 503)
        payload = response.json()
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(payload["checks"]["migrations"]["pending_count"], 2)


class PublicLandingAndAuthGateTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_landing_page_is_public(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "theStock")
        self.assertContains(response, "theStock 자체 계정")

    def test_internal_page_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("analysis_view"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertIn("next=/analysis/", response["Location"])

    def test_authenticated_user_can_access_workspace_dashboard(self):
        user = User.objects.create_user(username="workspace_user", password="pw12345")
        self.client.force_login(user)

        response = self.client.get(reverse("workspace_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "월별 매수/매도")
