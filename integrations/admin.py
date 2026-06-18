from __future__ import annotations

from django.contrib import admin

from integrations.models import IntegrationAuditLog, TossInvestCredential, TossTradeImportRecord, TossTradeSyncState


def _short_hash(value: str | None) -> str:
    if not value:
        return ""
    return f"{value[:8]}...{value[-6:]}" if len(value) > 18 else value


@admin.register(TossInvestCredential)
class TossInvestCredentialAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_id_display",
        "provider",
        "status",
        "client_id_stored",
        "secret_stored",
        "token_stored",
        "account_ref_stored",
        "account_masked_display",
        "access_token_expires_at_display",
        "last_verified_at",
        "last_used_at",
        "updated_at",
    )
    list_filter = ("provider", "status", "created_at", "updated_at")
    search_fields = ("id", "user__id", "client_id_fingerprint", "account_hash", "account_masked")
    readonly_fields = (
        "id",
        "user_id_display",
        "provider",
        "status",
        "client_id_stored",
        "secret_stored",
        "token_stored",
        "account_ref_stored",
        "client_id_fingerprint_short",
        "account_hash_short",
        "account_masked_display",
        "external_user_hash_short",
        "scopes",
        "last_verified_at",
        "last_used_at",
        "access_token_expires_at_display",
        "disconnected_at",
        "error_code",
        "error_summary",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Safe metadata",
            {
                "fields": (
                    "id",
                    "user_id_display",
                    "provider",
                    "status",
                    "client_id_stored",
                    "secret_stored",
                    "token_stored",
                    "account_ref_stored",
                    "account_masked_display",
                    "client_id_fingerprint_short",
                    "account_hash_short",
                    "external_user_hash_short",
                    "scopes",
                )
            },
        ),
        (
            "Lifecycle",
            {
                "fields": (
                    "last_verified_at",
                    "last_used_at",
                    "access_token_expires_at_display",
                    "disconnected_at",
                    "error_code",
                    "error_summary",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def has_view_permission(self, request, obj=None) -> bool:
        return super().has_view_permission(request, obj)

    @admin.display(description="User ID")
    def user_id_display(self, obj: TossInvestCredential) -> str:
        return str(obj.user_id)

    @admin.display(description="Client ID")
    def client_id_stored(self, obj: TossInvestCredential) -> str:
        return "stored" if obj.client_id_ciphertext else "empty"

    @admin.display(description="Client secret")
    def secret_stored(self, obj: TossInvestCredential) -> str:
        return "stored" if obj.client_secret_ciphertext else "empty"

    @admin.display(description="Token")
    def token_stored(self, obj: TossInvestCredential) -> str:
        return "stored" if obj.has_tokens() else "empty"

    @admin.display(description="Account ref")
    def account_ref_stored(self, obj: TossInvestCredential) -> str:
        return "stored" if obj.has_account_ref() else "empty"

    @admin.display(description="Access token expires at")
    def access_token_expires_at_display(self, obj: TossInvestCredential) -> str:
        return obj.access_token_expires_at.isoformat() if obj.access_token_expires_at else ""

    @admin.display(description="Account")
    def account_masked_display(self, obj: TossInvestCredential) -> str:
        return obj.account_masked or ""

    @admin.display(description="Account hash")
    def account_hash_short(self, obj: TossInvestCredential) -> str:
        return _short_hash(obj.account_hash)

    @admin.display(description="Client fingerprint")
    def client_id_fingerprint_short(self, obj: TossInvestCredential) -> str:
        return _short_hash(obj.client_id_fingerprint)

    @admin.display(description="External user hash")
    def external_user_hash_short(self, obj: TossInvestCredential) -> str:
        return _short_hash(obj.external_user_hash)


@admin.register(TossTradeSyncState)
class TossTradeSyncStateAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_id",
        "initial_sync_completed",
        "last_successful_sync_at",
        "last_run_status",
        "last_run_mode",
        "updated_at",
    )
    list_filter = ("provider", "initial_sync_completed", "last_run_status", "last_run_mode")
    readonly_fields = [field.name for field in TossTradeSyncState._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(TossTradeImportRecord)
class TossTradeImportRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user_id",
        "symbol",
        "side",
        "source_status",
        "import_result",
        "filled_at",
        "transaction_id",
    )
    list_filter = ("provider", "side", "source_status", "import_result", "currency")
    search_fields = ("symbol", "order_id_hash", "execution_digest")
    readonly_fields = [field.name for field in TossTradeImportRecord._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description="External user hash")
    def external_user_hash_short(self, obj: TossInvestCredential) -> str:
        return _short_hash(obj.external_user_hash)


@admin.register(IntegrationAuditLog)
class IntegrationAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider",
        "action",
        "success",
        "actor_ref_hash_short",
        "target_user_ref_hash_short",
        "account_hash_short",
        "reason_code",
        "error_code",
        "created_at",
    )
    list_filter = ("provider", "action", "success", "created_at")
    search_fields = ("actor_ref_hash", "target_user_ref_hash", "account_hash", "reason_code", "error_code")
    readonly_fields = (
        "id",
        "provider",
        "credential",
        "actor_ref_hash_short",
        "target_user_ref_hash_short",
        "action",
        "account_hash_short",
        "success",
        "reason_code",
        "error_code",
        "safe_summary",
        "safe_metadata",
        "created_at",
    )
    fieldsets = (
        (
            "Safe event",
            {
                "fields": (
                    "id",
                    "provider",
                    "credential",
                    "action",
                    "success",
                    "reason_code",
                    "error_code",
                    "safe_summary",
                    "safe_metadata",
                    "created_at",
                )
            },
        ),
        (
            "References",
            {
                "fields": (
                    "actor_ref_hash_short",
                    "target_user_ref_hash_short",
                    "account_hash_short",
                )
            },
        ),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    def has_view_permission(self, request, obj=None) -> bool:
        return super().has_view_permission(request, obj)

    @admin.display(description="Actor hash")
    def actor_ref_hash_short(self, obj: IntegrationAuditLog) -> str:
        return _short_hash(obj.actor_ref_hash)

    @admin.display(description="Target user hash")
    def target_user_ref_hash_short(self, obj: IntegrationAuditLog) -> str:
        return _short_hash(obj.target_user_ref_hash)

    @admin.display(description="Account hash")
    def account_hash_short(self, obj: IntegrationAuditLog) -> str:
        return _short_hash(obj.account_hash)
