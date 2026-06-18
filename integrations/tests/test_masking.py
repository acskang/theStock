from django.test import SimpleTestCase

from integrations.services.masking import mask_account, mask_client_id, mask_secret, mask_token


class MaskingTests(SimpleTestCase):
    def test_client_id_partial_masking(self):
        self.assertEqual(mask_client_id("client-identifier-1234"), "clie****1234")

    def test_short_client_id_is_mostly_masked(self):
        masked = mask_client_id("abc")

        self.assertNotEqual(masked, "abc")
        self.assertIn("*", masked)

    def test_secret_and_token_are_fixed_masks(self):
        self.assertEqual(mask_secret("dummy-secret"), "********")
        self.assertEqual(mask_secret("another-secret"), "********")
        self.assertEqual(mask_token("dummy-token"), "********")
        self.assertEqual(mask_token("another-token"), "********")

    def test_none_and_empty_values_are_safe(self):
        self.assertEqual(mask_client_id(None), "Not configured")
        self.assertEqual(mask_client_id(" "), "Not configured")
        self.assertEqual(mask_secret(None), "Not configured")
        self.assertEqual(mask_token(""), "Not configured")
        self.assertEqual(mask_account(None), "Not configured")

    def test_account_masking_limits_exposure(self):
        self.assertEqual(mask_account("ACCT-12 34"), "acct_****1234")
        self.assertEqual(mask_account("acct_****1234"), "acct_****1234")
        self.assertEqual(mask_account("123"), "acct_****")
