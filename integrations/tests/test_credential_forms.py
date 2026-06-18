from django.test import SimpleTestCase

from integrations.forms import (
    ConfirmActionForm,
    RevealCredentialForm,
    TossAccountSelectionForm,
    TossCredentialForm,
    TossCredentialVerificationForm,
    TossHoldingsDryRunForm,
)


class TossCredentialFormTests(SimpleTestCase):
    def test_toss_credential_form_valid_input(self):
        form = TossCredentialForm(
            data={
                "client_id": "dummy-client-alpha",
                "client_secret": "dummy-secret-alpha",
                "confirm_terms_ack": "on",
            }
        )

        self.assertTrue(form.is_valid())

    def test_toss_credential_form_requires_client_id(self):
        form = TossCredentialForm(
            data={"client_secret": "dummy-secret-alpha", "confirm_terms_ack": "on"}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("client_id", form.errors)

    def test_toss_credential_form_requires_client_secret(self):
        form = TossCredentialForm(
            data={"client_id": "dummy-client-alpha", "confirm_terms_ack": "on"}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("client_secret", form.errors)

    def test_toss_credential_form_requires_terms_ack(self):
        form = TossCredentialForm(
            data={"client_id": "dummy-client-alpha", "client_secret": "dummy-secret-alpha"}
        )

        self.assertFalse(form.is_valid())
        self.assertIn("confirm_terms_ack", form.errors)

    def test_toss_credential_form_rejects_too_long_input_without_echoing_value(self):
        long_value = "x" * 513
        form = TossCredentialForm(
            data={
                "client_id": long_value,
                "client_secret": long_value,
                "confirm_terms_ack": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertNotIn(long_value, form.errors.as_text())

    def test_reveal_form_requires_password(self):
        form = RevealCredentialForm(data={})

        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_confirm_action_form_requires_confirm(self):
        form = ConfirmActionForm(data={})

        self.assertFalse(form.is_valid())
        self.assertIn("confirm", form.errors)

    def test_verification_form_requires_confirm(self):
        form = TossCredentialVerificationForm(data={})

        self.assertFalse(form.is_valid())
        self.assertIn("confirm", form.errors)

    def test_verification_form_valid_confirm(self):
        form = TossCredentialVerificationForm(data={"confirm": "on"})

        self.assertTrue(form.is_valid())

    def test_account_selection_form_requires_hash_and_confirm(self):
        form = TossAccountSelectionForm(data={})

        self.assertFalse(form.is_valid())
        self.assertIn("selected_account_hash", form.errors)
        self.assertIn("confirm", form.errors)

    def test_account_selection_form_valid_hash(self):
        form = TossAccountSelectionForm(data={"selected_account_hash": "a" * 64, "confirm": "on"})

        self.assertTrue(form.is_valid())

    def test_account_selection_form_rejects_invalid_hash_without_raw_echo(self):
        raw_value = "dummy-account-seq-alpha"
        form = TossAccountSelectionForm(data={"selected_account_hash": raw_value, "confirm": "on"})

        self.assertFalse(form.is_valid())
        self.assertNotIn(raw_value, form.errors.as_text())

    def test_holdings_dry_run_form_valid_with_empty_symbol(self):
        form = TossHoldingsDryRunForm(data={"confirm": "on"})

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["symbol"], "")

    def test_holdings_dry_run_form_valid_with_symbol(self):
        form = TossHoldingsDryRunForm(data={"symbol": "005930", "confirm": "on"})

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["symbol"], "005930")

    def test_holdings_dry_run_form_rejects_invalid_symbol_without_raw_echo(self):
        raw_value = "005930 accountSeq dummy-secret-alpha"
        form = TossHoldingsDryRunForm(data={"symbol": raw_value, "confirm": "on"})

        self.assertFalse(form.is_valid())
        self.assertNotIn(raw_value, form.errors.as_text())

    def test_holdings_dry_run_form_rejects_too_long_symbol_without_raw_echo(self):
        raw_value = "A" * 33
        form = TossHoldingsDryRunForm(data={"symbol": raw_value, "confirm": "on"})

        self.assertFalse(form.is_valid())
        self.assertNotIn(raw_value, form.errors.as_text())

    def test_holdings_dry_run_form_requires_confirm(self):
        form = TossHoldingsDryRunForm(data={"symbol": "AAPL"})

        self.assertFalse(form.is_valid())
        self.assertIn("confirm", form.errors)
