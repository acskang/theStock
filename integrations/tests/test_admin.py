from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from unittest.mock import patch

from integrations.admin import IntegrationAuditLogAdmin, TossInvestCredentialAdmin
from integrations.models import IntegrationAuditLog, STATUS_ACTIVE, TossInvestCredential


class IntegrationsAdminTests(TestCase):
    def setUp(self):
        self.site = admin.site
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="admin-alpha",
            password="unused",
        )
        self.request = self.factory.get("/")
        self.request.user = self.user

    def create_credential(self) -> TossInvestCredential:
        owner = get_user_model().objects.create_user(username="owner-alpha", password="unused")
        return TossInvestCredential.objects.create(
            user=owner,
            status=STATUS_ACTIVE,
            client_id_ciphertext="cipher-client-value",
            client_secret_ciphertext="cipher-secret-value",
            access_token_ciphertext="cipher-access-value",
            account_ref_ciphertext="cipher-account-ref-value",
            access_token_expires_at=timezone.now(),
            account_hash="a" * 64,
            account_masked="acct_****1234",
        )

    def test_admins_are_registered(self):
        self.assertIsInstance(self.site._registry[TossInvestCredential], TossInvestCredentialAdmin)
        self.assertIsInstance(self.site._registry[IntegrationAuditLog], IntegrationAuditLogAdmin)

    def test_credential_admin_list_display_uses_safe_methods(self):
        model_admin = self.site._registry[TossInvestCredential]

        self.assertIn("client_id_stored", model_admin.list_display)
        self.assertIn("secret_stored", model_admin.list_display)
        self.assertIn("token_stored", model_admin.list_display)
        self.assertIn("account_ref_stored", model_admin.list_display)
        self.assertIn("access_token_expires_at_display", model_admin.list_display)

    def test_credential_admin_fieldsets_do_not_expose_ciphertext_fields(self):
        model_admin = self.site._registry[TossInvestCredential]
        rendered = str(model_admin.fieldsets)

        self.assertNotIn("client_id_ciphertext", rendered)
        self.assertNotIn("client_secret_ciphertext", rendered)
        self.assertNotIn("access_token_ciphertext", rendered)
        self.assertNotIn("refresh_token_ciphertext", rendered)
        self.assertNotIn("account_ref_ciphertext", rendered)

    def test_credential_admin_methods_do_not_return_ciphertexts(self):
        credential = self.create_credential()
        model_admin = self.site._registry[TossInvestCredential]

        outputs = [
            model_admin.client_id_stored(credential),
            model_admin.secret_stored(credential),
            model_admin.token_stored(credential),
            model_admin.account_ref_stored(credential),
            model_admin.access_token_expires_at_display(credential),
            model_admin.account_masked_display(credential),
            model_admin.account_hash_short(credential),
            model_admin.client_id_fingerprint_short(credential),
        ]
        rendered = " ".join(outputs)

        self.assertNotIn("cipher-client-value", rendered)
        self.assertNotIn("cipher-secret-value", rendered)
        self.assertNotIn("cipher-access-value", rendered)
        self.assertNotIn("cipher-account-ref-value", rendered)

    def test_credential_admin_methods_do_not_decrypt(self):
        credential = self.create_credential()
        model_admin = self.site._registry[TossInvestCredential]

        with patch("integrations.services.credential_crypto.decrypt_text") as decrypt_mock:
            model_admin.client_id_stored(credential)
            model_admin.secret_stored(credential)
            model_admin.token_stored(credential)
            model_admin.account_ref_stored(credential)
            model_admin.access_token_expires_at_display(credential)

        decrypt_mock.assert_not_called()

    def test_credential_admin_search_fields_do_not_include_account_ref_ciphertext(self):
        model_admin = self.site._registry[TossInvestCredential]

        self.assertNotIn("account_ref_ciphertext", model_admin.search_fields)

    def test_audit_admin_is_view_only(self):
        model_admin = self.site._registry[IntegrationAuditLog]

        self.assertFalse(model_admin.has_add_permission(self.request))
        self.assertFalse(model_admin.has_change_permission(self.request))
        self.assertFalse(model_admin.has_delete_permission(self.request))

    def test_audit_admin_methods_do_not_return_raw_values(self):
        log = IntegrationAuditLog.objects.create(
            action=IntegrationAuditLog.ACTION_STAFF_MASKED_VIEW,
            actor_ref_hash="b" * 64,
            target_user_ref_hash="c" * 64,
            account_hash="d" * 64,
            safe_summary="safe summary",
        )
        model_admin = self.site._registry[IntegrationAuditLog]

        rendered = " ".join(
            [
                model_admin.actor_ref_hash_short(log),
                model_admin.target_user_ref_hash_short(log),
                model_admin.account_hash_short(log),
            ]
        )

        self.assertNotIn("dummy-secret", rendered)
        self.assertNotIn("dummy-token", rendered)
        self.assertNotIn("dummy-account-alpha", rendered)
