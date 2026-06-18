from unittest.mock import patch
from decimal import Decimal

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

import integrations.views as credential_views
from integrations.models import (
    STATUS_ACTIVE,
    STATUS_DISCONNECTED,
    STATUS_PENDING_VERIFICATION,
    STATUS_RESET_REQUIRED,
    IntegrationAuditLog,
    TossInvestCredential,
)
from integrations.services.credential_lifecycle import register_or_replace_pending_credential
from integrations.services.toss_readonly_verification import (
    TossAccountCandidate,
    TossReadonlyVerificationAccountNotFound,
    TossReadonlyVerificationAccountSelectionRequired,
    TossReadonlyVerificationAuthError,
    TossReadonlyVerificationConfigurationError,
    TossReadonlyVerificationStateError,
    TossReadonlyVerificationTransientError,
    TossVerificationResult,
)
from integrations.services.toss_holdings_readonly import (
    TossHoldingsReadonlyAuthError,
    TossHoldingsReadonlyParseError,
    TossHoldingsReadonlyStateError,
    TossHoldingsReadonlyTransientError,
)
from integrations.services.toss_holdings_sync_plan import (
    ACTION_CREATE,
    ACTION_REMOVE_CANDIDATE,
    ACTION_SKIPPED,
    ACTION_UNCHANGED,
    ACTION_UPDATE,
    HoldingFieldDiff,
    HoldingSnapshotValue,
    HoldingSyncDryRunPlan,
    HoldingSyncPlanItem,
    HoldingSyncPlanMappingError,
    HoldingSyncPlanValidationError,
)


def view_settings(enabled: bool = True, api_enabled: bool = True):
    return override_settings(
        TOSS_USER_CREDENTIAL_UI_ENABLED=enabled,
        TOSS_USER_TOSS_API_CALLS_ENABLED=api_enabled,
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
        CREDENTIAL_REVEAL_TIMEOUT_SECONDS=300,
    )


class TossCredentialViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="user-alpha",
            password="dummy-password",
        )
        self.urls = {
            "settings": reverse("integrations:toss_credential_settings"),
            "save": reverse("integrations:toss_credential_save"),
            "reveal": reverse("integrations:toss_credential_reveal"),
            "verify": reverse("integrations:toss_credential_verify"),
            "holdings_dry_run": reverse("integrations:toss_holdings_dry_run"),
            "reset": reverse("integrations:toss_credential_reset"),
            "disconnect": reverse("integrations:toss_credential_disconnect"),
        }

    def login(self):
        self.client.login(username="user-alpha", password="dummy-password")

    def create_active_credential(self):
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.status = STATUS_ACTIVE
        credential.account_masked = "acct_****1111"
        credential.account_hash = "a" * 64
        credential.save()
        return credential

    def fake_holdings_plan(self, *, symbol_filter=None):
        current = HoldingSnapshotValue(
            symbol="005930",
            comparison_key="005930",
            name="Samsung",
            quantity=Decimal("10"),
            average_purchase_price=Decimal("70000"),
            source="current",
            object_id=1,
        )
        updated = HoldingSnapshotValue(
            symbol="005930",
            comparison_key="005930",
            name="Samsung",
            quantity=Decimal("12"),
            average_purchase_price=Decimal("70000"),
            last_price=Decimal("71000"),
            source="toss",
        )
        create_target = HoldingSnapshotValue(
            symbol="AAPL",
            comparison_key="AAPL",
            name="Apple",
            quantity=Decimal("2"),
            average_purchase_price=Decimal("180"),
            source="toss",
        )
        unchanged_current = HoldingSnapshotValue(
            symbol="MSFT",
            comparison_key="MSFT",
            name="Microsoft",
            quantity=Decimal("1"),
            average_purchase_price=Decimal("300"),
            source="current",
            object_id=2,
        )
        remove_current = HoldingSnapshotValue(
            symbol="TSLA",
            comparison_key="TSLA",
            name="Tesla",
            quantity=Decimal("3"),
            average_purchase_price=Decimal("200"),
            source="current",
            object_id=3,
        )
        skipped_target = HoldingSnapshotValue(
            symbol="BAD",
            comparison_key="BAD",
            name="Needs review",
            source="toss",
        )
        remove_items = []
        if symbol_filter is None:
            remove_items = [
                HoldingSyncPlanItem(
                    action=ACTION_REMOVE_CANDIDATE,
                    symbol="TSLA",
                    comparison_key="TSLA",
                    current=remove_current,
                    warnings=["remove_candidate requires explicit confirmation in a later phase"],
                )
            ]
        items = [
            HoldingSyncPlanItem(action=ACTION_CREATE, symbol="AAPL", comparison_key="AAPL", target=create_target),
            HoldingSyncPlanItem(
                action=ACTION_UPDATE,
                symbol="005930",
                comparison_key="005930",
                current=current,
                target=updated,
                diffs=[
                    HoldingFieldDiff(
                        field="quantity",
                        current="10",
                        target="12",
                        severity="update",
                    ),
                    HoldingFieldDiff(
                        field="last_price",
                        current=None,
                        target="71000",
                        severity="info",
                        reason="price is informational",
                    ),
                ],
            ),
            HoldingSyncPlanItem(
                action=ACTION_UNCHANGED,
                symbol="MSFT",
                comparison_key="MSFT",
                current=unchanged_current,
                target=unchanged_current,
            ),
            *remove_items,
            HoldingSyncPlanItem(
                action=ACTION_SKIPPED,
                symbol="BAD",
                comparison_key="BAD",
                target=skipped_target,
                warnings=["target holding skipped because symbol is invalid"],
            ),
        ]
        return HoldingSyncDryRunPlan(
            user_id=self.user.pk,
            provider="toss_invest",
            source="toss_holdings_preview",
            generated_at=timezone.now(),
            symbol_filter=symbol_filter,
            current_count=3,
            target_count=3,
            create_count=1,
            update_count=1,
            unchanged_count=1,
            remove_candidate_count=0 if symbol_filter else 1,
            skipped_count=1,
            items=items,
            warnings=[],
        )

    @view_settings(enabled=False)
    def test_feature_flag_disabled_blocks_all_routes(self):
        self.login()

        self.assertEqual(self.client.get(self.urls["settings"]).status_code, 404)
        for name in ["save", "reveal", "verify", "reset", "disconnect"]:
            self.assertEqual(self.client.post(self.urls[name]).status_code, 404)

    @view_settings()
    def test_login_required(self):
        response = self.client.get(self.urls["settings"])

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    @view_settings()
    def test_get_settings_safe_page(self):
        self.login()

        response = self.client.get(self.urls["settings"])
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Toss증권 연동")
        self.assertContains(response, "연결 확인")
        self.assertContains(response, "read-only")
        self.assertContains(response, "public 운영 전 토스증권 약관/승인 범위 확인이 필요합니다.")
        self.assertNotIn("client_id_ciphertext", body)
        self.assertNotIn("client_secret_ciphertext", body)
        self.assertNotIn("access_token_ciphertext", body)
        self.assertNotIn("refresh_token_ciphertext", body)
        self.assertNotIn("Authorization", body)
        self.assertNotIn("X-Tossinvest-Account", body)
        self.assertNotIn("raw_response", body)

    @view_settings()
    def test_holdings_dry_run_url_reverse(self):
        self.assertEqual(self.urls["holdings_dry_run"], "/integrations/toss/holdings/dry-run/")

    @view_settings(api_enabled=False)
    def test_api_calls_disabled_shows_notice_and_blocks_holdings_dry_run(self):
        self.login()

        get_response = self.client.get(self.urls["settings"])
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "보유종목 미리보기")
        self.assertContains(get_response, "현재 Toss API 호출 기능이 비활성화")

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as dry_run_mock:
            response = self.client.post(self.urls["holdings_dry_run"], {"confirm": "on"})

        self.assertEqual(response.status_code, 403)
        dry_run_mock.assert_not_called()
        self.assertContains(response, "보유종목 미리보기를 실행할 수 없습니다", status_code=403)

    @view_settings()
    def test_holdings_dry_run_requires_login(self):
        response = self.client.post(self.urls["holdings_dry_run"], {"confirm": "on"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    @view_settings()
    def test_get_settings_shows_holdings_dry_run_section(self):
        self.login()

        response = self.client.get(self.urls["settings"])
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("보유종목 미리보기", body)
        self.assertIn("실제 UserHolding DB를 변경하지 않는 dry-run preview", body)
        self.assertNotIn("dummy-access-token-alpha", body)
        self.assertNotIn("dummy-account-ref-alpha", body)
        self.assertNotIn("Authorization", body)
        self.assertNotIn("accountSeq", body)

    @view_settings()
    def test_holdings_dry_run_requires_active_credential(self):
        self.login()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as dry_run_mock:
            response = self.client.post(self.urls["holdings_dry_run"], {"confirm": "on"})

        self.assertEqual(response.status_code, 400)
        dry_run_mock.assert_not_called()
        self.assertContains(response, "연결 확인을 먼저 완료", status_code=400)

    @view_settings()
    def test_holdings_dry_run_requires_confirm(self):
        self.login()
        self.create_active_credential()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as dry_run_mock:
            response = self.client.post(self.urls["holdings_dry_run"], {})

        self.assertEqual(response.status_code, 400)
        dry_run_mock.assert_not_called()
        self.assertContains(response, "입력값을 확인해 주세요.", status_code=400)
        self.assertNotContains(response, "dummy-secret-alpha", status_code=400)

    @view_settings()
    def test_holdings_dry_run_success_safe_response(self):
        self.login()
        self.create_active_credential()
        plan = self.fake_holdings_plan()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan", return_value=plan) as dry_run_mock:
            response = self.client.post(self.urls["holdings_dry_run"], {"confirm": "on"})

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        dry_run_mock.assert_called_once()
        _, kwargs = dry_run_mock.call_args
        self.assertEqual(kwargs["user"], self.user)
        self.assertEqual(kwargs["actor"], self.user)
        self.assertIsNone(kwargs["symbol"])
        self.assertTrue(kwargs["record_audit"])
        self.assertIn("보유종목 동기화 dry-run plan이 생성되었습니다", body)
        self.assertIn("create", body)
        self.assertIn("update", body)
        self.assertIn("삭제 후보", body)
        self.assertIn("검토 필요", body)
        self.assertIn("005930", body)
        self.assertIn("AAPL", body)
        self.assertIn("실제 DB에는 반영되지 않았습니다", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("dummy-access-token-alpha", body)
        self.assertNotIn("dummy-secret-alpha", body)
        self.assertNotIn("dummy-account-ref-alpha", body)
        self.assertNotIn("Authorization", body)
        self.assertNotIn("accountSeq", body)
        self.assertNotIn("accountNo", body)
        self.assertNotIn("client_secret_ciphertext", body)
        self.assertNotIn("access_token_ciphertext", body)

    @view_settings()
    def test_holdings_dry_run_with_symbol_passes_filter(self):
        self.login()
        self.create_active_credential()
        plan = self.fake_holdings_plan(symbol_filter="005930")

        with patch("integrations.views.fetch_and_build_holdings_sync_plan", return_value=plan) as dry_run_mock:
            response = self.client.post(
                self.urls["holdings_dry_run"],
                {"symbol": "005930", "confirm": "on"},
            )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        _, kwargs = dry_run_mock.call_args
        self.assertEqual(kwargs["symbol"], "005930")
        self.assertIn("symbol_filter: 005930", body)
        self.assertIn("부분 조회 dry-run", body)
        self.assertNotIn("dummy-secret-alpha", body)

    @view_settings()
    def test_htmx_holdings_dry_run_success_returns_panel(self):
        self.login()
        self.create_active_credential()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan", return_value=self.fake_holdings_plan()):
            response = self.client.post(
                self.urls["holdings_dry_run"],
                {"confirm": "on"},
                HTTP_HX_REQUEST="true",
            )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("toss-holdings-dry-run-panel", body)
        self.assertNotIn("toss-credential-panel", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("dummy-secret-alpha", body)

    @view_settings()
    def test_holdings_dry_run_invalid_symbol_is_safe(self):
        self.login()
        self.create_active_credential()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as dry_run_mock:
            response = self.client.post(
                self.urls["holdings_dry_run"],
                {"symbol": "005930 accountSeq dummy-secret-alpha", "confirm": "on"},
            )

        body = response.content.decode()
        self.assertEqual(response.status_code, 400)
        dry_run_mock.assert_not_called()
        self.assertIn("입력값을 확인해 주세요.", body)
        self.assertNotIn("dummy-secret-alpha", body)
        self.assertNotIn("accountSeq", body)

    @view_settings()
    def test_holdings_dry_run_error_mapping_is_safe(self):
        cases = [
            (HoldingSyncPlanValidationError("raw dummy-secret-alpha"), "입력값을 확인"),
            (HoldingSyncPlanMappingError("raw mapping dummy-account-ref-alpha"), "보유종목 모델"),
            (TossHoldingsReadonlyAuthError("raw dummy-secret-alpha"), "Toss 인증 상태"),
            (TossHoldingsReadonlyTransientError("raw dummy-access-token-alpha"), "잠시 후 다시 시도"),
            (TossHoldingsReadonlyStateError("raw dummy-account-ref-alpha"), "연결 확인을 먼저"),
            (TossHoldingsReadonlyParseError("raw raw_response accountNo"), "응답을 해석"),
        ]
        self.login()
        self.create_active_credential()

        for exc, expected in cases:
            with self.subTest(exc=exc.__class__.__name__):
                with patch("integrations.views.fetch_and_build_holdings_sync_plan", side_effect=exc):
                    response = self.client.post(self.urls["holdings_dry_run"], {"confirm": "on"})
                body = response.content.decode()
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, body)
                self.assertNotIn("dummy-secret-alpha", body)
                self.assertNotIn("dummy-access-token-alpha", body)
                self.assertNotIn("dummy-account-ref-alpha", body)
                self.assertNotIn("raw_response", body)

    @view_settings()
    def test_post_save_valid_creates_pending_credential(self):
        self.login()

        response = self.client.post(
            self.urls["save"],
            {
                "client_id": "dummy-client-alpha",
                "client_secret": "dummy-secret-alpha",
                "confirm_terms_ack": "on",
            },
            follow=True,
        )
        credential = TossInvestCredential.objects.get(user=self.user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertTrue(credential.client_id_ciphertext)
        self.assertTrue(credential.client_secret_ciphertext)
        self.assertNotEqual(credential.client_id_ciphertext, "dummy-client-alpha")
        self.assertNotEqual(credential.client_secret_ciphertext, "dummy-secret-alpha")
        self.assertNotContains(response, "dummy-secret-alpha")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_CREATE,
            ).exists()
        )

    @view_settings()
    def test_post_save_update_same_row(self):
        self.login()
        self.client.post(
            self.urls["save"],
            {
                "client_id": "dummy-client-alpha",
                "client_secret": "dummy-secret-alpha",
                "confirm_terms_ack": "on",
            },
        )
        credential = TossInvestCredential.objects.get(user=self.user)

        response = self.client.post(
            self.urls["save"],
            {
                "client_id": "dummy-client-beta",
                "client_secret": "dummy-secret-beta",
                "confirm_terms_ack": "on",
            },
            follow=True,
        )
        credential.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(TossInvestCredential.objects.filter(user=self.user).count(), 1)
        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertNotContains(response, "dummy-secret-alpha")
        self.assertNotContains(response, "dummy-secret-beta")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_UPDATE,
            ).exists()
        )

    @view_settings()
    def test_post_save_duplicate_is_safe(self):
        other = get_user_model().objects.create_user(username="user-beta", password="dummy-password")
        register_or_replace_pending_credential(
            user=other,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-beta",
        )
        self.login()

        response = self.client.post(
            self.urls["save"],
            {
                "client_id": "dummy-client-alpha",
                "client_secret": "dummy-secret-alpha",
                "confirm_terms_ack": "on",
            },
        )
        body = response.content.decode()

        self.assertEqual(response.status_code, 400)
        self.assertIn("이미 등록된 credential입니다.", body)
        self.assertNotIn("dummy-secret-alpha", body)
        self.assertFalse(TossInvestCredential.objects.filter(user=self.user).exists())

    @view_settings()
    def test_reveal_success_no_store_and_no_token(self):
        self.login()
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.access_token_ciphertext = "cipher-access"
        credential.refresh_token_ciphertext = "cipher-refresh"
        credential.save()

        response = self.client.post(self.urls["reveal"], {"password": "dummy-password"})
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("dummy-client-alpha", body)

    @view_settings(api_enabled=False)
    def test_api_calls_disabled_shows_notice_and_blocks_verify(self):
        self.login()

        get_response = self.client.get(self.urls["settings"])
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "현재 연결 확인 기능은 비활성화되어 있습니다.")

        with patch("integrations.views.verify_user_toss_credential_readonly") as verify_mock:
            response = self.client.post(self.urls["verify"], {"confirm": "on"})

        self.assertEqual(response.status_code, 403)
        verify_mock.assert_not_called()
        self.assertContains(response, "현재 Toss 연결 확인 기능이 활성화되지 않았습니다.", status_code=403)

    @view_settings()
    def test_verify_requires_login(self):
        response = self.client.post(self.urls["verify"], {"confirm": "on"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    @view_settings()
    def test_verify_requires_confirm(self):
        self.login()

        with patch("integrations.views.verify_user_toss_credential_readonly") as verify_mock:
            response = self.client.post(self.urls["verify"], {})

        self.assertEqual(response.status_code, 400)
        verify_mock.assert_not_called()
        self.assertContains(response, "연결 확인을 실행하려면 확인 항목을 선택해 주세요.", status_code=400)

    @view_settings()
    def test_verify_single_account_success_safe_response(self):
        self.login()
        result = TossVerificationResult(
            credential_id=1,
            status=STATUS_ACTIVE,
            success=True,
            selected_account_hash="a" * 64,
            account_candidates=[],
            reason_code="",
            safe_summary="verification succeeded",
        )

        with patch("integrations.views.verify_user_toss_credential_readonly", return_value=result) as verify_mock:
            response = self.client.post(self.urls["verify"], {"confirm": "on"}, follow=True)

        self.assertEqual(response.status_code, 200)
        verify_mock.assert_called_once()
        _, kwargs = verify_mock.call_args
        self.assertEqual(kwargs["user"], self.user)
        self.assertEqual(kwargs["actor"], self.user)
        self.assertIsNone(kwargs["selected_account_hash"])
        self.assertContains(response, "Toss read-only 연결 확인이 완료되었습니다.")
        body = response.content.decode()
        self.assertNotIn("dummy-access-token-alpha", body)
        self.assertNotIn("dummy-secret-alpha", body)
        self.assertNotIn("dummy-account-seq-alpha", body)
        self.assertNotIn("dummy-account-no-alpha", body)
        self.assertIn("no-store", response["Cache-Control"])

    @view_settings()
    def test_verify_multiple_accounts_selection_required_safe_ui(self):
        self.login()
        candidates = [
            TossAccountCandidate(account_hash="a" * 64, account_masked="acct_****1111", account_type="BROKERAGE"),
            TossAccountCandidate(account_hash="b" * 64, account_masked="acct_****2222", account_type="BROKERAGE"),
        ]

        with patch(
            "integrations.views.verify_user_toss_credential_readonly",
            side_effect=TossReadonlyVerificationAccountSelectionRequired(candidates),
        ):
            response = self.client.post(self.urls["verify"], {"confirm": "on"})

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("여러 계좌가 확인되었습니다. 대표 계좌를 선택해 주세요.", body)
        self.assertIn("acct_****1111", body)
        self.assertIn("acct_****2222", body)
        self.assertIn('value="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"', body)
        self.assertNotIn("dummy-account-seq-alpha", body)
        self.assertNotIn("dummy-account-no-alpha", body)
        self.assertNotIn("dummy-access-token-alpha", body)
        self.assertIn("no-store", response["Cache-Control"])

    @view_settings()
    def test_verify_selected_account_hash_posts_to_service(self):
        self.login()
        result = TossVerificationResult(
            credential_id=1,
            status=STATUS_ACTIVE,
            success=True,
            selected_account_hash="b" * 64,
            account_candidates=[],
            reason_code="",
            safe_summary="verification succeeded",
        )

        with patch("integrations.views.verify_user_toss_credential_readonly", return_value=result) as verify_mock:
            response = self.client.post(
                self.urls["verify"],
                {"selected_account_hash": "b" * 64, "confirm": "on"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        _, kwargs = verify_mock.call_args
        self.assertEqual(kwargs["selected_account_hash"], "b" * 64)
        self.assertContains(response, "Toss read-only 연결 확인이 완료되었습니다.")

    @view_settings()
    def test_verify_error_mapping_is_safe(self):
        cases = [
            (TossReadonlyVerificationAuthError("raw invalid_client dummy-secret-alpha"), "다시 등록"),
            (TossReadonlyVerificationTransientError("raw timeout dummy-access-token-alpha"), "잠시 후 다시 시도"),
            (TossReadonlyVerificationAccountNotFound("raw dummy-account-seq-alpha"), "선택 가능한 Toss 계좌"),
            (TossReadonlyVerificationConfigurationError("raw config key"), "활성화되지 않았습니다"),
            (TossReadonlyVerificationStateError("raw state dummy-secret-alpha"), "현재 상태"),
        ]
        self.login()

        for exc, expected in cases:
            with self.subTest(exc=exc.__class__.__name__):
                with patch("integrations.views.verify_user_toss_credential_readonly", side_effect=exc):
                    response = self.client.post(self.urls["verify"], {"confirm": "on"})
                body = response.content.decode()
                self.assertEqual(response.status_code, 400)
                self.assertIn(expected, body)
                self.assertNotIn("dummy-secret-alpha", body)
                self.assertNotIn("dummy-access-token-alpha", body)
                self.assertNotIn("dummy-account-seq-alpha", body)

    @view_settings()
    def test_htmx_verify_success_returns_panel_no_store(self):
        self.login()
        result = TossVerificationResult(
            credential_id=1,
            status=STATUS_ACTIVE,
            success=True,
            selected_account_hash="a" * 64,
            account_candidates=[],
            reason_code="",
            safe_summary="verification succeeded",
        )

        with patch("integrations.views.verify_user_toss_credential_readonly", return_value=result):
            response = self.client.post(
                self.urls["verify"],
                {"confirm": "on"},
                HTTP_HX_REQUEST="true",
            )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("toss-credential-panel", body)
        self.assertIn("Toss read-only 연결 확인이 완료되었습니다.", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("dummy-secret-alpha", body)

    @view_settings()
    def test_htmx_account_selection_returns_safe_panel(self):
        self.login()
        candidates = [
            TossAccountCandidate(account_hash="a" * 64, account_masked="acct_****1111", account_type="BROKERAGE"),
        ]

        with patch(
            "integrations.views.verify_user_toss_credential_readonly",
            side_effect=TossReadonlyVerificationAccountSelectionRequired(candidates),
        ):
            response = self.client.post(
                self.urls["verify"],
                {"confirm": "on"},
                HTTP_HX_REQUEST="true",
            )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("toss-credential-panel", body)
        self.assertIn("acct_****1111", body)
        self.assertNotIn("dummy-account-seq-alpha", body)
        self.assertNotIn("dummy-secret-alpha", body)

    @view_settings()
    def test_views_do_not_import_toss_provider_modules(self):
        source = credential_views.__loader__.get_source(credential_views.__name__)

        self.assertNotIn("data_pipeline.providers", source)
        self.assertNotIn("toss_auth", source)
        self.assertNotIn("toss_client", source)
        self.assertNotIn("requests.", source)
        self.assertNotIn("urllib", source)

    @view_settings()
    def test_normal_status_response_safety_after_save(self):
        self.login()
        self.client.post(
            self.urls["save"],
            {
                "client_id": "dummy-client-alpha",
                "client_secret": "dummy-secret-alpha",
                "confirm_terms_ack": "on",
            },
        )

        response = self.client.get(self.urls["settings"])
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("dummy-client-alpha", body)
        self.assertNotIn("dummy-secret-alpha", body)
        self.assertNotIn("client_id_ciphertext", body)
        self.assertNotIn("client_secret_ciphertext", body)
        self.assertNotIn("access_token_ciphertext", body)
        self.assertNotIn("refresh_token_ciphertext", body)
        self.assertNotIn("Authorization", body)
        self.assertNotIn("X-Tossinvest-Account", body)
        self.assertNotIn("raw_response", body)
        self.assertIn("no-store", response["Cache-Control"])

    @view_settings()
    def test_reveal_wrong_password_safe_failure(self):
        self.login()
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        response = self.client.post(self.urls["reveal"], {"password": "wrong-password"})
        body = response.content.decode()

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("dummy-client-alpha", body)
        self.assertNotIn("dummy-secret-alpha", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_FAILURE,
            ).exists()
        )

    @view_settings()
    def test_reveal_not_configured_safe_failure(self):
        self.login()

        response = self.client.post(self.urls["reveal"], {"password": "dummy-password"})

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "dummy-secret-alpha", status_code=400)

    @view_settings()
    def test_reveal_reset_required_and_disconnected_forbidden(self):
        self.login()
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.mark_reset_required(error_code="safe")
        credential.save()

        reset_response = self.client.post(self.urls["reveal"], {"password": "dummy-password"})
        self.assertEqual(reset_response.status_code, 400)
        self.assertNotContains(reset_response, "dummy-secret-alpha", status_code=400)

        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.mark_disconnected()
        credential.save()
        disconnected_response = self.client.post(self.urls["reveal"], {"password": "dummy-password"})
        self.assertEqual(disconnected_response.status_code, 400)
        self.assertNotContains(disconnected_response, "dummy-secret-alpha", status_code=400)

    @view_settings()
    def test_reset_clears_ciphertext_and_audits(self):
        self.login()
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        response = self.client.post(self.urls["reset"], {"reset-confirm": "on"}, follow=True)
        credential.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertNotContains(response, "dummy-secret-alpha")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_RESET,
            ).exists()
        )

    @view_settings()
    def test_disconnect_clears_ciphertext_and_audits(self):
        self.login()
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        response = self.client.post(self.urls["disconnect"], {"disconnect-confirm": "on"}, follow=True)
        credential.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(credential.status, STATUS_DISCONNECTED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertIsNotNone(credential.disconnected_at)
        self.assertNotContains(response, "dummy-secret-alpha")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_DISCONNECT,
            ).exists()
        )

    @view_settings()
    def test_htmx_save_returns_partial_without_secret(self):
        self.login()

        response = self.client.post(
            self.urls["save"],
            {
                "client_id": "dummy-client-alpha",
                "client_secret": "dummy-secret-alpha",
                "confirm_terms_ack": "on",
            },
            HTTP_HX_REQUEST="true",
        )
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("toss-credential-panel", body)
        self.assertNotIn("dummy-secret-alpha", body)

    @view_settings()
    def test_htmx_reveal_returns_partial_no_store(self):
        self.login()
        credential = register_or_replace_pending_credential(
            user=self.user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        response = self.client.post(
            self.urls["reveal"],
            {"password": "dummy-password"},
            HTTP_HX_REQUEST="true",
        )
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("dummy-client-alpha", body)
        self.assertIn("dummy-secret-alpha", body)
        self.assertNotIn("access_token", body)
        self.assertNotIn("refresh_token", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_SUCCESS,
            ).exists()
        )
