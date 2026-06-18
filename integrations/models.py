from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


PROVIDER_TOSS_INVEST = "toss_invest"

STATUS_PENDING_VERIFICATION = "pending_verification"
STATUS_ACTIVE = "active"
STATUS_DISCONNECTED = "disconnected"
STATUS_REVOKED = "revoked"
STATUS_RESET_REQUIRED = "reset_required"
STATUS_ERROR = "error"

TOSS_CREDENTIAL_STATUSES = [
    (STATUS_PENDING_VERIFICATION, "Pending verification"),
    (STATUS_ACTIVE, "Active"),
    (STATUS_DISCONNECTED, "Disconnected"),
    (STATUS_REVOKED, "Revoked"),
    (STATUS_RESET_REQUIRED, "Reset required"),
    (STATUS_ERROR, "Error"),
]


class TossInvestCredential(models.Model):
    """User-owned Toss credential metadata.

    Ciphertext fields are never decrypted by model methods, admin, forms, or serializers.
    Reset/recovery flows must not store raw Toss responses, tokens, headers, accounts, or order ids.
    """

    PROVIDER_TOSS_INVEST = PROVIDER_TOSS_INVEST

    STATUS_PENDING_VERIFICATION = STATUS_PENDING_VERIFICATION
    STATUS_ACTIVE = STATUS_ACTIVE
    STATUS_DISCONNECTED = STATUS_DISCONNECTED
    STATUS_REVOKED = STATUS_REVOKED
    STATUS_RESET_REQUIRED = STATUS_RESET_REQUIRED
    STATUS_ERROR = STATUS_ERROR
    STATUS_CHOICES = TOSS_CREDENTIAL_STATUSES

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="toss_invest_credential",
    )
    provider = models.CharField(max_length=32, default=PROVIDER_TOSS_INVEST, db_index=True)
    client_id_ciphertext = models.TextField(null=True, blank=True)
    client_secret_ciphertext = models.TextField(null=True, blank=True)
    access_token_ciphertext = models.TextField(null=True, blank=True)
    # Toss OpenAPI currently does not provide refresh tokens; this field remains for future/provider compatibility.
    refresh_token_ciphertext = models.TextField(null=True, blank=True)
    account_ref_ciphertext = models.TextField(null=True, blank=True)
    client_id_key_version = models.CharField(max_length=32, blank=True, default="")
    client_secret_key_version = models.CharField(max_length=32, blank=True, default="")
    access_token_key_version = models.CharField(max_length=32, blank=True, default="")
    refresh_token_key_version = models.CharField(max_length=32, blank=True, default="")
    account_ref_key_version = models.CharField(max_length=32, blank=True, default="")
    client_id_fingerprint = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    account_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    account_masked = models.CharField(max_length=80, blank=True, default="")
    external_user_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    scopes = models.JSONField(default=list, blank=True)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    access_token_issued_at = models.DateTimeField(null=True, blank=True)
    access_token_type = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING_VERIFICATION,
        db_index=True,
    )
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=120, blank=True, default="")
    error_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(
                    status__in=[
                        STATUS_PENDING_VERIFICATION,
                        STATUS_ACTIVE,
                        STATUS_DISCONNECTED,
                        STATUS_REVOKED,
                        STATUS_RESET_REQUIRED,
                        STATUS_ERROR,
                    ]
                ),
                name="ck_int_toss_cred_status",
            ),
            models.UniqueConstraint(
                fields=["provider", "client_id_fingerprint"],
                condition=Q(
                    status__in=[STATUS_PENDING_VERIFICATION, STATUS_ACTIVE],
                    client_id_fingerprint__isnull=False,
                ),
                name="uniq_int_active_pending_client_fp",
            ),
            models.UniqueConstraint(
                fields=["provider", "account_hash"],
                condition=Q(status=STATUS_ACTIVE, account_hash__isnull=False),
                name="uniq_int_active_account_hash",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "status"], name="idx_int_cred_provider_status"),
            models.Index(fields=["status", "updated_at"], name="idx_int_cred_status_updated"),
            models.Index(fields=["user", "status"], name="idx_int_cred_user_status"),
            models.Index(fields=["account_hash"], name="idx_int_cred_account_hash"),
            models.Index(fields=["client_id_fingerprint"], name="idx_int_cred_client_fp"),
        ]

    def __str__(self) -> str:
        return f"TossInvestCredential(user_id={self.user_id}, status={self.status})"

    def has_client_credentials(self) -> bool:
        return bool(self.client_id_ciphertext and self.client_secret_ciphertext)

    def has_tokens(self) -> bool:
        return bool(self.access_token_ciphertext or self.refresh_token_ciphertext)

    def has_account(self) -> bool:
        return bool(self.account_hash or self.account_masked or self.account_ref_ciphertext)

    def has_account_ref(self) -> bool:
        return bool(self.account_ref_ciphertext)

    def clear_ciphertexts(self) -> None:
        self.client_id_ciphertext = None
        self.client_secret_ciphertext = None
        self.access_token_ciphertext = None
        self.refresh_token_ciphertext = None
        self.account_ref_ciphertext = None
        self.client_id_key_version = ""
        self.client_secret_key_version = ""
        self.access_token_key_version = ""
        self.refresh_token_key_version = ""
        self.account_ref_key_version = ""
        self.access_token_expires_at = None
        self.access_token_issued_at = None
        self.access_token_type = ""

    def mark_reset_required(self, *, error_code: str = "", error_summary: str = "") -> None:
        """Clear encrypted values and mark the credential as requiring reset.

        Only safe error code/summary text may be stored. Do not pass raw Toss responses,
        tokens, headers, account identifiers, order identifiers, or request bodies.
        """

        self.clear_ciphertexts()
        self.status = STATUS_RESET_REQUIRED
        self.error_code = error_code[:120]
        self.error_summary = error_summary

    def mark_disconnected(self) -> None:
        self.clear_ciphertexts()
        self.status = STATUS_DISCONNECTED
        self.disconnected_at = timezone.now()

    def safe_display_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "provider": self.provider,
            "status": self.status,
            "account_masked": self.account_masked,
            "account_ref_stored": self.has_account_ref(),
            "token_stored": self.has_tokens(),
            "access_token_expires_at": self.access_token_expires_at,
            "last_verified_at": self.last_verified_at,
            "last_used_at": self.last_used_at,
            "disconnected_at": self.disconnected_at,
        }


class IntegrationAuditLog(models.Model):
    """Safe audit event for external integrations.

    Do not store raw credentials, tokens, account identifiers, order identifiers,
    Authorization headers, request bodies, or raw Toss responses.
    """

    ACTION_CREDENTIAL_CREATE = "credential_create"
    ACTION_CREDENTIAL_UPDATE = "credential_update"
    ACTION_CREDENTIAL_RESET = "credential_reset"
    ACTION_CREDENTIAL_DISCONNECT = "credential_disconnect"
    ACTION_CREDENTIAL_REVEAL_ATTEMPT = "credential_reveal_attempt"
    ACTION_CREDENTIAL_REVEAL_SUCCESS = "credential_reveal_success"
    ACTION_CREDENTIAL_REVEAL_FAILURE = "credential_reveal_failure"
    ACTION_CREDENTIAL_VERIFICATION_SUCCESS = "credential_verification_success"
    ACTION_CREDENTIAL_VERIFICATION_FAILURE = "credential_verification_failure"
    ACTION_TOKEN_REFRESH = "token_refresh"
    ACTION_HOLDINGS_SYNC = "holdings_sync"
    ACTION_ORDER_HISTORY_SYNC = "order_history_sync"
    ACTION_STAFF_MASKED_VIEW = "staff_masked_view"
    ACTION_PERMISSION_DENIED = "permission_denied"
    ACTION_DECRYPTION_FAILURE = "decryption_failure"

    ACTION_CHOICES = [
        (ACTION_CREDENTIAL_CREATE, "Credential create"),
        (ACTION_CREDENTIAL_UPDATE, "Credential update"),
        (ACTION_CREDENTIAL_RESET, "Credential reset"),
        (ACTION_CREDENTIAL_DISCONNECT, "Credential disconnect"),
        (ACTION_CREDENTIAL_REVEAL_ATTEMPT, "Credential reveal attempt"),
        (ACTION_CREDENTIAL_REVEAL_SUCCESS, "Credential reveal success"),
        (ACTION_CREDENTIAL_REVEAL_FAILURE, "Credential reveal failure"),
        (ACTION_CREDENTIAL_VERIFICATION_SUCCESS, "Credential verification success"),
        (ACTION_CREDENTIAL_VERIFICATION_FAILURE, "Credential verification failure"),
        (ACTION_TOKEN_REFRESH, "Token refresh"),
        (ACTION_HOLDINGS_SYNC, "Holdings sync"),
        (ACTION_ORDER_HISTORY_SYNC, "Order history sync"),
        (ACTION_STAFF_MASKED_VIEW, "Staff masked view"),
        (ACTION_PERMISSION_DENIED, "Permission denied"),
        (ACTION_DECRYPTION_FAILURE, "Decryption failure"),
    ]

    provider = models.CharField(max_length=32, default=PROVIDER_TOSS_INVEST, db_index=True)
    credential = models.ForeignKey(
        "integrations.TossInvestCredential",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="integration_audit_events",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="targeted_integration_audit_events",
    )
    actor_ref_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    target_user_ref_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    action = models.CharField(max_length=64, choices=ACTION_CHOICES, db_index=True)
    account_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    success = models.BooleanField(default=True, db_index=True)
    reason_code = models.CharField(max_length=120, blank=True, default="")
    error_code = models.CharField(max_length=120, blank=True, default="")
    safe_summary = models.TextField(blank=True, default="")
    safe_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "action", "created_at"], name="idx_int_audit_provider_action"),
            models.Index(fields=["actor_ref_hash", "created_at"], name="idx_int_audit_actor_hash"),
            models.Index(fields=["target_user_ref_hash", "created_at"], name="idx_int_audit_target_hash"),
            models.Index(fields=["account_hash", "created_at"], name="idx_int_audit_account_hash"),
            models.Index(fields=["success", "created_at"], name="idx_int_audit_success"),
        ]

    def __str__(self) -> str:
        return f"IntegrationAuditLog(action={self.action}, success={self.success}, created_at={self.created_at})"


class TossTradeSyncState(models.Model):
    """Per-user checkpoint for importing filled Toss orders into legacy Transaction rows."""

    MODE_INITIAL = "initial"
    MODE_INCREMENTAL = "incremental"
    STATUS_NEVER = "never"
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_PARTIAL = "partial"
    STATUS_ERROR = "error"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="toss_trade_sync_state",
    )
    credential = models.OneToOneField(
        "integrations.TossInvestCredential",
        on_delete=models.CASCADE,
        related_name="trade_sync_state",
    )
    provider = models.CharField(max_length=32, default=PROVIDER_TOSS_INVEST, db_index=True)
    initial_sync_completed = models.BooleanField(default=False)
    last_successful_sync_at = models.DateTimeField(null=True, blank=True)
    last_successful_ordered_at = models.DateTimeField(null=True, blank=True)
    last_successful_filled_at = models.DateTimeField(null=True, blank=True)
    last_run_started_at = models.DateTimeField(null=True, blank=True)
    last_run_completed_at = models.DateTimeField(null=True, blank=True)
    last_run_mode = models.CharField(max_length=32, blank=True, default="")
    last_run_status = models.CharField(max_length=32, default=STATUS_NEVER, db_index=True)
    last_run_counts = models.JSONField(default=dict, blank=True)
    last_error_code = models.CharField(max_length=120, blank=True, default="")
    last_error_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "last_run_status"], name="idx_int_trade_state_status"),
            models.Index(fields=["last_successful_sync_at"], name="idx_int_trade_state_success"),
        ]

    def __str__(self) -> str:
        return f"TossTradeSyncState(user_id={self.user_id}, status={self.last_run_status})"


class TossTradeImportRecord(models.Model):
    """Safe provenance for a Toss filled order imported into portfolio.Transaction."""

    RESULT_CREATED = "created"
    RESULT_MATCHED_EXISTING = "matched_existing"
    RESULT_UPDATED = "updated"
    RESULT_DUPLICATE = "duplicate"
    RESULT_SKIPPED_NO_FILL = "skipped_no_fill"
    RESULT_SKIPPED_MISSING_STOCK = "skipped_missing_stock"
    RESULT_CONFLICT = "conflict"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="toss_trade_import_records",
    )
    credential = models.ForeignKey(
        "integrations.TossInvestCredential",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trade_import_records",
    )
    transaction = models.ForeignKey(
        "portfolio.Transaction",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="toss_import_records",
    )
    provider = models.CharField(max_length=32, default=PROVIDER_TOSS_INVEST, db_index=True)
    account_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    order_id_hash = models.CharField(max_length=64, db_index=True)
    execution_digest = models.CharField(max_length=64, db_index=True)
    symbol = models.CharField(max_length=32, db_index=True)
    side = models.CharField(max_length=16, db_index=True)
    source_status = models.CharField(max_length=48, blank=True, default="")
    currency = models.CharField(max_length=16, blank=True, default="")
    ordered_at = models.DateTimeField(null=True, blank=True, db_index=True)
    filled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    filled_quantity = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    average_filled_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    filled_amount = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    commission = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    tax = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    settlement_date = models.CharField(max_length=32, blank=True, default="")
    import_result = models.CharField(max_length=48, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "provider", "account_hash", "order_id_hash"],
                name="uniq_int_toss_trade_order",
            )
        ]
        indexes = [
            models.Index(fields=["user", "filled_at"], name="idx_int_trade_import_user_fill"),
            models.Index(fields=["import_result", "created_at"], name="idx_int_trade_import_result"),
            models.Index(fields=["symbol", "filled_at"], name="idx_int_trade_import_symbol"),
        ]

    def __str__(self) -> str:
        return f"TossTradeImportRecord(user_id={self.user_id}, symbol={self.symbol}, result={self.import_result})"
