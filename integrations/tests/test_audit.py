from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from integrations.models import IntegrationAuditLog, STATUS_ACTIVE, TossInvestCredential
from integrations.services.audit import record_integration_audit
from integrations.services.credential_crypto import CredentialCryptoConfigurationError


class IntegrationAuditServiceTests(TestCase):
    def create_user(self, username: str):
        return get_user_model().objects.create_user(username=username, password="unused")

    def create_credential(self, username: str, **kwargs) -> TossInvestCredential:
        user = self.create_user(username)
        defaults = {"user": user, "status": STATUS_ACTIVE}
        defaults.update(kwargs)
        return TossInvestCredential.objects.create(**defaults)

    @override_settings(CREDENTIAL_HASH_PEPPER="dummy-pepper")
    def test_record_integration_audit_creates_log(self):
        actor = self.create_user("actor-alpha")
        target = self.create_user("target-alpha")

        log = record_integration_audit(
            action=IntegrationAuditLog.ACTION_CREDENTIAL_CREATE,
            actor=actor,
            target_user=target,
            safe_summary="safe event",
            safe_metadata={"result": "created"},
        )

        self.assertEqual(log.action, IntegrationAuditLog.ACTION_CREDENTIAL_CREATE)
        self.assertEqual(log.actor, actor)
        self.assertEqual(log.target_user, target)
        self.assertTrue(log.actor_ref_hash)
        self.assertTrue(log.target_user_ref_hash)
        self.assertEqual(log.safe_metadata, {"result": "created"})

    @override_settings(CREDENTIAL_HASH_PEPPER="dummy-pepper")
    def test_credential_sets_target_user_and_account_hash(self):
        credential = self.create_credential("target-alpha", account_hash="hash-account")

        log = record_integration_audit(
            action=IntegrationAuditLog.ACTION_STAFF_MASKED_VIEW,
            credential=credential,
        )

        self.assertEqual(log.credential, credential)
        self.assertEqual(log.target_user, credential.user)
        self.assertEqual(log.account_hash, "hash-account")
        self.assertTrue(log.target_user_ref_hash)

    @override_settings(CREDENTIAL_HASH_PEPPER="dummy-pepper")
    def test_safe_metadata_none_defaults_to_empty_dict(self):
        log = record_integration_audit(action=IntegrationAuditLog.ACTION_CREDENTIAL_RESET, safe_metadata=None)

        self.assertEqual(log.safe_metadata, {})

    @override_settings(CREDENTIAL_HASH_PEPPER="dummy-pepper")
    def test_dangerous_metadata_keys_raise_value_error(self):
        for unsafe_key in ["token", "secret", "authorization", "accountNo", "accountSeq", "raw_response"]:
            with self.subTest(unsafe_key=unsafe_key):
                with self.assertRaises(ValueError):
                    record_integration_audit(
                        action=IntegrationAuditLog.ACTION_CREDENTIAL_RESET,
                        safe_metadata={unsafe_key: "blocked"},
                    )

    @override_settings(CREDENTIAL_HASH_PEPPER="dummy-pepper")
    def test_audit_str_does_not_include_sensitive_values(self):
        log = record_integration_audit(
            action=IntegrationAuditLog.ACTION_CREDENTIAL_RESET,
            safe_summary="safe summary",
            safe_metadata={"status": "reset"},
        )

        rendered = str(log)

        self.assertNotIn("secret", rendered.lower())
        self.assertNotIn("token", rendered.lower())
        self.assertNotIn("dummy-account-alpha", rendered)

    @override_settings(CREDENTIAL_HASH_PEPPER="")
    def test_missing_pepper_raises_when_hash_needed(self):
        actor = self.create_user("actor-alpha")

        with self.assertRaises(CredentialCryptoConfigurationError):
            record_integration_audit(action=IntegrationAuditLog.ACTION_PERMISSION_DENIED, actor=actor)
