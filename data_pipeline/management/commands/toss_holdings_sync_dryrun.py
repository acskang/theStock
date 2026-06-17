import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from data_pipeline.providers import get_provider
from data_pipeline.providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossProviderDisabled,
    TossRateLimitError,
)
from data_pipeline.providers.toss_masking import is_configured, mask_account_id
from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log
from holdings.models import UserHolding
from stocks.models import Stock


SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
ACCOUNTS_ENDPOINT = "/api/v1/accounts"
ACCOUNTS_LOG_ENDPOINT = "acct_list"
HOLDINGS_ENDPOINT = "/api/v1/holdings"
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch Toss holdings candidates without saving them."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", default=None)
        parser.add_argument("--account", default=None)
        parser.add_argument("--no-network", action="store_true")
        parser.add_argument(
            "--diagnose-account",
            action="store_true",
            help="Diagnose Toss account selection via /api/v1/accounts without querying holdings.",
        )
        parser.add_argument("--raw", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--confirm-save", action="store_true")
        parser.add_argument("--map-user-holdings", action="store_true")
        parser.add_argument("--user-id", type=int, default=None)
        parser.add_argument("--username", default=None)
        parser.add_argument("--update-existing", action="store_true")

    def handle(self, *args, **options):
        symbol = _validate_optional_symbol(options.get("symbol"))
        account = (options.get("account") or "").strip() or None
        commit_requested = bool(options.get("commit"))
        confirm_save = bool(options.get("confirm_save"))
        diagnose_account = bool(options.get("diagnose_account"))
        map_user_holdings = bool(options.get("map_user_holdings"))
        update_existing = bool(options.get("update_existing"))
        endpoint_name = ACCOUNTS_LOG_ENDPOINT if diagnose_account else HOLDINGS_ENDPOINT

        if commit_requested and not confirm_save:
            self._write_status(
                "FAILED",
                reason="confirm_save_required",
                symbol=symbol,
                network_call=False,
                commit_requested=commit_requested,
                commit_mode="confirm_required",
                endpoint_name=endpoint_name,
            )
            return
        if commit_requested and not map_user_holdings:
            self._write_status(
                "FAILED",
                reason="map_user_holdings_required",
                symbol=symbol,
                network_call=False,
                commit_requested=commit_requested,
                commit_mode="map_user_holdings_required",
                endpoint_name=endpoint_name,
            )
            return

        if options["no_network"]:
            self._write_status(
                "SKIPPED",
                reason="--no-network was provided",
                symbol=symbol,
                network_call=False,
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                endpoint_name=endpoint_name,
                diagnostics=_safe_diagnostics(None, account=account, accounts_api_called=False),
            )
            return

        owner_context = _resolve_owner_context(
            user_id=options.get("user_id"),
            username=options.get("username"),
        )
        if commit_requested and owner_context.get("status") != "configured":
            self._write_status(
                "FAILED",
                reason=str(owner_context.get("status") or "owner_required"),
                symbol=symbol,
                network_call=False,
                commit_requested=commit_requested,
                commit_mode="confirmed",
                endpoint_name=endpoint_name,
            )
            return

        try:
            provider = _get_toss_provider_from_registry()
        except ValueError:
            self._write_status(
                "FAILED",
                reason="provider not registered",
                symbol=symbol,
                network_call=False,
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                endpoint_name=endpoint_name,
            )
            return
        except Exception:
            self._write_status(
                "FAILED",
                reason="provider error",
                symbol=symbol,
                network_call=False,
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                endpoint_name=endpoint_name,
            )
            return

        if diagnose_account:
            self._handle_account_diagnostic(
                provider,
                symbol=symbol,
                account=account,
                commit_requested=commit_requested,
                confirm_save=confirm_save,
                raw=bool(options["raw"]),
            )
            return

        try:
            result = provider.get_holdings_candidates(account_id=account, symbol=symbol or None)
        except (
            TossProviderDisabled,
            TossConfigurationError,
            TossAuthError,
            TossRateLimitError,
            TossOpenApiError,
        ) as exc:
            reason = _safe_reason(exc)
            diagnostics = _safe_diagnostics(exc, account=account)
            self._write_status(
                "FAILED",
                reason=reason,
                symbol=symbol,
                network_call=_network_call_for_reason(reason),
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                diagnostics=diagnostics,
                endpoint_name=HOLDINGS_ENDPOINT,
            )
            return
        except Exception:
            self._write_status(
                "FAILED",
                reason="provider_error",
                symbol=symbol,
                network_call=True,
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                diagnostics=_safe_diagnostics(None, account=account),
                endpoint_name=HOLDINGS_ENDPOINT,
            )
            return

        candidates = result.get("candidates") if isinstance(result, Mapping) else []
        if not isinstance(candidates, list):
            candidates = []
        summary = result.get("summary") if isinstance(result, Mapping) else {}
        if not isinstance(summary, Mapping):
            summary = {}
        account_summary = result.get("account") if isinstance(result, Mapping) else {}
        if not isinstance(account_summary, Mapping):
            account_summary = {}
        account_diagnostic = summary.get("account_diagnostic") if isinstance(summary, Mapping) else {}
        if not isinstance(account_diagnostic, Mapping):
            account_diagnostic = {}

        self.stdout.write("Toss holdings sync dry-run: OK")
        self.stdout.write("provider: toss")
        self.stdout.write(f"endpoint: {result.get('endpoint', HOLDINGS_ENDPOINT) if isinstance(result, Mapping) else HOLDINGS_ENDPOINT}")
        self.stdout.write(f"dry_run: {_bool_text(not commit_requested)}")
        self.stdout.write("network_call: true")
        self.stdout.write("account: configured")
        self.stdout.write(f"account_source: {account_summary.get('source', 'unknown')}")
        self.stdout.write(f"account_fallback_used: {_bool_text(bool(account_diagnostic.get('account_fallback_used')))}")
        if symbol:
            self.stdout.write(f"symbol: {symbol}")
        if commit_requested:
            self.stdout.write("commit: confirmed")
        self.stdout.write(f"item_count: {summary.get('item_count', len(candidates))}")
        self.stdout.write("candidates:")
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            self.stdout.write(f"  - symbol: {candidate.get('symbol')}")
            self.stdout.write(f"    name: {candidate.get('name')}")
            self.stdout.write(f"    market_country: {candidate.get('market_country')}")
            self.stdout.write(f"    currency: {candidate.get('currency')}")
            self.stdout.write(f"    quantity: {candidate.get('quantity')}")
            self.stdout.write(f"    average_purchase_price: {candidate.get('average_purchase_price')}")
            self.stdout.write(f"    last_price: {candidate.get('last_price')}")
            self.stdout.write(f"    profit_loss_rate: {candidate.get('profit_loss_rate')}")
            self.stdout.write(f"    source: {candidate.get('source')}")
        if options["raw"]:
            raw = result.get("raw") if isinstance(result, Mapping) else None
            self.stdout.write(f"raw_summary: {_format_raw_summary(raw)}")

        mapping_summary = None
        commit_result = _empty_commit_result()
        if map_user_holdings:
            mapping_summary = _build_user_holding_mapping(
                candidates,
                owner_context=owner_context,
                update_existing=update_existing,
            )
            self._write_user_holding_mapping(mapping_summary)
            if commit_requested:
                commit_result = _commit_user_holding_mapping(mapping_summary, owner_context=owner_context)
                self._write_user_holding_commit_result(commit_result)

        skipped_count = 0
        saved_count = 0
        updated_count = 0
        failed_count = 0
        if mapping_summary:
            skipped_count = int(mapping_summary.get("skipped_count", 0)) + int(mapping_summary.get("existing_skip_count", 0))
        if commit_requested:
            saved_count = int(commit_result.get("saved_count", 0))
            updated_count = int(commit_result.get("updated_count", 0))
            skipped_count = int(commit_result.get("skipped_count", skipped_count))
            failed_count = int(commit_result.get("failed_count", 0))

        record_data_ingestion_log(
            provider_name="toss",
            job_type="toss_holdings_sync_dryrun",
            target_type="holdings",
            target_symbol=symbol,
            endpoint_name=HOLDINGS_ENDPOINT,
            status="partial" if failed_count else "success",
            safe_reason="holdings_received",
            network_call=True,
            dry_run=not commit_requested,
            commit_mode="confirmed" if commit_requested else "not_requested",
            candidate_count=len(candidates),
            saved_count=saved_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            metadata={
                "command": "toss_holdings_sync_dryrun",
                "provider": "toss",
                "symbol": symbol,
                "endpoint_name": HOLDINGS_ENDPOINT,
                "network_call": True,
                "dry_run": not commit_requested,
                "commit_mode": "confirmed" if commit_requested else "not_requested",
                "candidate_count": len(candidates),
                "saved_count": saved_count,
                "updated_count": updated_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
                "params_shape": "symbol" if symbol else "",
                "update_existing": update_existing,
            },
        )
        logger.info(
            "toss_holdings_sync_dryrun_result command=%s status=ok provider=toss symbol=%s "
            "endpoint=%s candidate_count=%s network_call=true dry_run=%s commit=%s",
            "toss_holdings_sync_dryrun",
            symbol,
            HOLDINGS_ENDPOINT,
            len(candidates),
            _bool_text(not commit_requested),
            "confirmed" if commit_requested else "not_requested",
        )

    def _write_user_holding_mapping(self, summary: Mapping[str, Any]) -> None:
        self.stdout.write("user_holding_mapping:")
        self.stdout.write(f"  owner_status: {summary.get('owner_status')}")
        self.stdout.write(f"  update_existing: {_bool_text(bool(summary.get('update_existing')))}")
        self.stdout.write(f"  candidate_count: {summary.get('candidate_count', 0)}")
        self.stdout.write(f"  would_create_count: {summary.get('would_create_count', 0)}")
        self.stdout.write(f"  would_update_count: {summary.get('would_update_count', 0)}")
        self.stdout.write(f"  existing_skip_count: {summary.get('existing_skip_count', 0)}")
        self.stdout.write(f"  skipped_count: {summary.get('skipped_count', 0)}")
        self.stdout.write("  candidates:")
        for item in summary.get("items", []):
            if not isinstance(item, Mapping):
                continue
            self.stdout.write(f"    - symbol: {item.get('symbol')}")
            self.stdout.write(f"      mapping_status: {item.get('mapping_status')}")
            self.stdout.write(f"      reason: {item.get('reason')}")
            self.stdout.write(f"      stock_found: {_bool_text(bool(item.get('stock_found')))}")
            if item.get("stock_code"):
                self.stdout.write(f"      stock_code: {item.get('stock_code')}")
            if item.get("quantity") not in {None, ""}:
                self.stdout.write(f"      quantity: {item.get('quantity')}")
            if item.get("average_price") not in {None, ""}:
                self.stdout.write(f"      average_price: {item.get('average_price')}")

    def _write_user_holding_commit_result(self, result: Mapping[str, Any]) -> None:
        self.stdout.write("user_holding_commit:")
        self.stdout.write("  commit: confirmed")
        self.stdout.write("  dry_run: false")
        self.stdout.write(f"  saved_count: {result.get('saved_count', 0)}")
        self.stdout.write(f"  updated_count: {result.get('updated_count', 0)}")
        self.stdout.write(f"  skipped_count: {result.get('skipped_count', 0)}")
        self.stdout.write(f"  failed_count: {result.get('failed_count', 0)}")

    def _handle_account_diagnostic(
        self,
        provider: Any,
        *,
        symbol: str,
        account: str | None,
        commit_requested: bool,
        confirm_save: bool,
        raw: bool,
    ) -> None:
        try:
            result = provider.get_accounts()
        except (
            TossProviderDisabled,
            TossConfigurationError,
            TossAuthError,
            TossRateLimitError,
            TossOpenApiError,
        ) as exc:
            reason = _safe_reason(exc, diagnostic=True)
            diagnostics = _safe_diagnostics(exc, account=account, accounts_api_called=True)
            self._write_status(
                "FAILED",
                reason=reason,
                symbol=symbol,
                network_call=_network_call_for_reason(reason),
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                diagnostics=diagnostics,
                endpoint_name=ACCOUNTS_LOG_ENDPOINT,
            )
            return
        except Exception:
            self._write_status(
                "FAILED",
                reason="provider_error",
                symbol=symbol,
                network_call=True,
                commit_requested=commit_requested,
                commit_mode="confirmed" if commit_requested and confirm_save else "not_requested",
                diagnostics=_safe_diagnostics(None, account=account, accounts_api_called=True),
                endpoint_name=ACCOUNTS_LOG_ENDPOINT,
            )
            return

        accounts = result.get("accounts") if isinstance(result, Mapping) else []
        if not isinstance(accounts, list):
            accounts = []
        account_count = _safe_int(result.get("account_count") if isinstance(result, Mapping) else None, len(accounts))
        account_types = result.get("account_types") if isinstance(result, Mapping) else []
        if not isinstance(account_types, list):
            account_types = []
        account_seq_usable_count = _safe_int(
            result.get("account_seq_usable_count") if isinstance(result, Mapping) else None,
            sum(1 for account_entry in accounts if isinstance(account_entry, Mapping) and account_entry.get("account_seq_usable")),
        )
        env_account = getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")

        self.stdout.write("Toss holdings account diagnostic: OK")
        self.stdout.write(f"endpoint: {result.get('endpoint', ACCOUNTS_ENDPOINT) if isinstance(result, Mapping) else ACCOUNTS_ENDPOINT}")
        self.stdout.write("dry_run: true")
        self.stdout.write("network_call: true")
        self.stdout.write("provider: toss")
        if commit_requested:
            self.stdout.write("commit: confirmed")
        self.stdout.write(f"account_env_configured: {_bool_text(is_configured(env_account))}")
        self.stdout.write(f"account_env_shape: {_classify_account_value(env_account)}")
        self.stdout.write("accounts_api_called: true")
        self.stdout.write(f"account_count: {account_count}")
        self.stdout.write(f"account_types: {_format_account_types(account_types)}")
        self.stdout.write(f"account_seq_usable_count: {account_seq_usable_count}")
        self.stdout.write(f"account_seq_usable: {_bool_text(account_seq_usable_count > 0)}")
        if raw:
            raw_summary = result.get("raw") if isinstance(result, Mapping) else None
            self.stdout.write(f"raw_summary: {_format_raw_summary(raw_summary)}")

        record_data_ingestion_log(
            provider_name="toss",
            job_type="toss_holdings_sync_dryrun",
            target_type="holdings",
            target_symbol=symbol,
            endpoint_name=ACCOUNTS_LOG_ENDPOINT,
            status="success",
            safe_reason="acct_received",
            network_call=True,
            dry_run=True,
            commit_mode="confirmed" if commit_requested else "not_requested",
            candidate_count=account_count,
            saved_count=0,
            updated_count=0,
            skipped_count=0,
            failed_count=0,
            metadata={
                "command": "toss_holdings_sync_dryrun",
                "provider": "toss",
                "diagnostic": "account",
                "endpoint_name": ACCOUNTS_LOG_ENDPOINT,
                "network_call": True,
                "dry_run": True,
                "commit_mode": "confirmed" if commit_requested else "not_requested",
                "candidate_count": account_count,
                "account_env_configured": _bool_text(is_configured(env_account)),
                "account_env_shape": _classify_account_value(env_account),
                "accounts_api_called": True,
                "account_count": account_count,
                "account_types": _safe_account_types(account_types),
                "account_seq_usable_count": account_seq_usable_count,
                "account_seq_usable": account_seq_usable_count > 0,
            },
        )
        logger.info(
            "toss_holdings_sync_dryrun_result command=%s status=ok provider=toss endpoint=%s "
            "network_call=true dry_run=true diagnostic=account account_count=%s account_types=%s",
            "toss_holdings_sync_dryrun",
            ACCOUNTS_ENDPOINT,
            account_count,
            _format_account_types(account_types),
        )

    def _write_status(
        self,
        status: str,
        *,
        reason: str,
        symbol: str,
        network_call: bool,
        commit_requested: bool,
        commit_mode: str | None = None,
        diagnostics: Mapping[str, Any] | None = None,
        endpoint_name: str = HOLDINGS_ENDPOINT,
    ) -> None:
        diagnostics = dict(diagnostics or _safe_diagnostics(None))
        clean_commit_mode = commit_mode or ("requested" if commit_requested else "not_requested")
        self.stdout.write(f"Toss holdings sync dry-run: {status}")
        if symbol:
            self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"reason: {reason}")
        self.stdout.write("dry_run: true")
        if commit_requested:
            self.stdout.write(f"commit: {clean_commit_mode}")
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        self.stdout.write("provider: toss")
        for key in (
            "http_status_code",
            "error_code",
            "error_field",
            "safe_message",
            "account_env_configured",
            "account_env_shape",
            "accounts_api_called",
            "selected_account_source",
            "selected_account_masked",
            "account_arg_shape",
            "account_count",
            "account_types",
            "account_fallback_used",
            "account_header_configured",
        ):
            value = diagnostics.get(key)
            if value not in {None, ""}:
                self.stdout.write(f"{key}: {value}")

        log_status = "skipped" if status == "SKIPPED" else "failed"
        log_reason = _log_safe_reason(reason)
        http_status_code = _diagnostic_int(diagnostics.get("http_status_code"))
        error_code = _log_safe_error_code(diagnostics.get("error_code"))
        record_data_ingestion_log(
            provider_name="toss",
            job_type="toss_holdings_sync_dryrun",
            target_type="holdings",
            target_symbol=symbol,
            endpoint_name=endpoint_name,
            status=log_status,
            safe_reason=log_reason,
            error_code=error_code,
            http_status_code=http_status_code,
            network_call=network_call,
            dry_run=True,
            commit_mode=clean_commit_mode,
            candidate_count=0,
            saved_count=0,
            updated_count=0,
            skipped_count=0,
            failed_count=1 if status == "FAILED" else 0,
            metadata={
                "command": "toss_holdings_sync_dryrun",
                "provider": "toss",
                "symbol": symbol,
                "endpoint_name": endpoint_name,
                "network_call": network_call,
                "dry_run": True,
                "commit_mode": clean_commit_mode,
                "candidate_count": 0,
                "saved_count": 0,
                "updated_count": 0,
                "skipped_count": 0,
                "failed_count": 1 if status == "FAILED" else 0,
                "http_status_code": http_status_code,
                "error_code": error_code,
                "error_field": diagnostics.get("error_field", ""),
                "safe_message": diagnostics.get("safe_message", ""),
                "params_shape": diagnostics.get("params_shape", ""),
                "account_env_configured": diagnostics.get("account_env_configured", ""),
                "account_env_shape": diagnostics.get("account_env_shape", ""),
                "accounts_api_called": diagnostics.get("accounts_api_called", ""),
                "selected_account_source": diagnostics.get("selected_account_source", ""),
                "account_arg_shape": diagnostics.get("account_arg_shape", ""),
                "account_count": diagnostics.get("account_count", ""),
                "account_types": _safe_account_types(diagnostics.get("account_types", [])),
                "account_fallback_used": diagnostics.get("account_fallback_used", ""),
                "account_header_configured": diagnostics.get("account_header_configured", ""),
            },
        )
        diagnostic_text = _format_diagnostics_for_log(diagnostics)
        log_method = logger.warning if status == "FAILED" else logger.info
        log_method(
            "toss_holdings_sync_dryrun_result command=%s status=%s provider=toss reason=%s symbol=%s "
            "endpoint=%s network_call=%s dry_run=true commit=%s diagnostics=%s",
            "toss_holdings_sync_dryrun",
            status.lower(),
            log_reason,
            symbol,
            endpoint_name,
            _bool_text(network_call),
            clean_commit_mode,
            diagnostic_text,
        )


def _get_toss_provider_from_registry():
    provider = get_provider("toss")
    if isinstance(provider, type):
        return provider()
    return provider


def _resolve_owner_context(*, user_id: int | None, username: str | None) -> dict[str, Any]:
    clean_username = str(username or "").strip()
    if user_id is not None and clean_username:
        return {"status": "owner_ambiguous", "user": None}
    if user_id is None and not clean_username:
        return {"status": "owner_required", "user": None}

    user_model = get_user_model()
    try:
        if user_id is not None:
            user = user_model.objects.filter(id=user_id).first()
        else:
            user = user_model.objects.filter(username=clean_username).first()
    except Exception:
        return {"status": "owner_not_found", "user": None}

    if user is None:
        return {"status": "owner_not_found", "user": None}
    return {"status": "configured", "user": user}


def _build_user_holding_mapping(
    candidates: list[Any],
    *,
    owner_context: Mapping[str, Any],
    update_existing: bool,
) -> dict[str, Any]:
    owner_status = str(owner_context.get("status") or "owner_required")
    owner = owner_context.get("user")
    items = []
    counts = {
        "would_create_count": 0,
        "would_update_count": 0,
        "existing_skip_count": 0,
        "skipped_count": 0,
    }

    for candidate in candidates:
        item = _map_user_holding_candidate(
            candidate if isinstance(candidate, Mapping) else {},
            owner=owner,
            owner_status=owner_status,
            update_existing=update_existing,
        )
        items.append(item)
        status = item["mapping_status"]
        if status == "would_create":
            counts["would_create_count"] += 1
        elif status == "would_update":
            counts["would_update_count"] += 1
        elif status == "existing_skip":
            counts["existing_skip_count"] += 1
        else:
            counts["skipped_count"] += 1

    return {
        "owner_status": owner_status,
        "update_existing": bool(update_existing),
        "candidate_count": len(candidates),
        **counts,
        "items": items,
    }


def _empty_commit_result() -> dict[str, int]:
    return {
        "saved_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
    }


def _commit_user_holding_mapping(
    mapping_summary: Mapping[str, Any],
    *,
    owner_context: Mapping[str, Any],
) -> dict[str, int]:
    result = _empty_commit_result()
    owner = owner_context.get("user")
    if owner_context.get("status") != "configured" or owner is None:
        result["failed_count"] = 1
        return result

    for item in mapping_summary.get("items", []):
        if not isinstance(item, Mapping):
            result["failed_count"] += 1
            continue
        mapping_status = item.get("mapping_status")
        if mapping_status not in {"would_create", "would_update"}:
            result["skipped_count"] += 1
            continue

        stock_code = str(item.get("stock_code") or "").strip()
        try:
            stock = Stock.objects.get(code=stock_code, is_active=True)
            quantity = int(str(item.get("quantity") or "0"))
            average_price = Decimal(str(item.get("average_price") or "0")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        except (Stock.DoesNotExist, InvalidOperation, ValueError):
            result["failed_count"] += 1
            continue

        with transaction.atomic():
            existing = UserHolding.objects.select_for_update().filter(user=owner, stock=stock).first()
            if mapping_status == "would_create":
                if existing is None:
                    UserHolding.objects.create(
                        user=owner,
                        stock=stock,
                        average_price=average_price,
                        quantity=quantity,
                    )
                    result["saved_count"] += 1
                else:
                    result["skipped_count"] += 1
                continue

            if existing is not None and existing.is_active:
                existing.average_price = average_price
                existing.quantity = quantity
                existing.save(update_fields=["average_price", "quantity", "updated_at"])
                result["updated_count"] += 1
            else:
                result["skipped_count"] += 1

    return result


def _map_user_holding_candidate(
    candidate: Mapping[str, Any],
    *,
    owner: Any,
    owner_status: str,
    update_existing: bool,
) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "").strip()
    base = {
        "symbol": symbol,
        "mapping_status": "skipped",
        "reason": "",
        "stock_found": False,
        "stock_code": "",
        "quantity": "",
        "average_price": "",
    }
    if not symbol or not SYMBOL_PATTERN.match(symbol):
        return {**base, "reason": "invalid_symbol"}
    if owner_status != "configured":
        return {**base, "reason": owner_status}

    market_country = str(candidate.get("market_country") or "").strip().upper()
    currency = str(candidate.get("currency") or "").strip().upper()
    if market_country and market_country != "KR":
        return {**base, "reason": "unsupported_market_country"}
    if currency and currency != "KRW":
        return {**base, "reason": "unsupported_currency"}

    quantity_result = _normalize_user_holding_quantity(candidate.get("quantity"))
    if not quantity_result["ok"]:
        return {**base, "reason": quantity_result["reason"]}
    average_price_result = _normalize_user_holding_average_price(candidate.get("average_purchase_price"))
    if not average_price_result["ok"]:
        return {**base, "reason": average_price_result["reason"], "quantity": quantity_result["display"]}

    stock = Stock.objects.filter(code=symbol).first()
    if stock is None:
        return {
            **base,
            "reason": "stock_not_found",
            "quantity": quantity_result["display"],
            "average_price": average_price_result["display"],
        }
    if not stock.is_active:
        return {
            **base,
            "reason": "stock_inactive",
            "stock_found": True,
            "stock_code": stock.code,
            "quantity": quantity_result["display"],
            "average_price": average_price_result["display"],
        }

    existing = UserHolding.objects.filter(user=owner, stock=stock).first()
    mapped = {
        **base,
        "stock_found": True,
        "stock_code": stock.code,
        "quantity": quantity_result["display"],
        "average_price": average_price_result["display"],
    }
    if existing is None:
        return {**mapped, "mapping_status": "would_create", "reason": "new_holding"}
    if not existing.is_active:
        return {**mapped, "reason": "inactive_existing"}
    if update_existing:
        return {**mapped, "mapping_status": "would_update", "reason": "update_existing"}
    return {**mapped, "mapping_status": "existing_skip", "reason": "existing_holding"}


def _normalize_user_holding_quantity(value: Any) -> dict[str, Any]:
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return {"ok": False, "reason": "invalid_quantity", "display": ""}
    if quantity <= 0:
        return {"ok": False, "reason": "invalid_quantity", "display": str(quantity)}
    if quantity != quantity.to_integral_value():
        return {"ok": False, "reason": "unsupported_fractional_quantity", "display": str(quantity)}
    return {"ok": True, "reason": "", "value": int(quantity), "display": str(int(quantity))}


def _normalize_user_holding_average_price(value: Any) -> dict[str, Any]:
    try:
        average_price = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return {"ok": False, "reason": "invalid_average_price", "display": ""}
    if average_price < 0:
        return {"ok": False, "reason": "invalid_average_price", "display": str(average_price)}
    return {"ok": True, "reason": "", "value": average_price, "display": f"{average_price:.2f}"}


def _validate_optional_symbol(symbol: Any) -> str:
    clean_symbol = str(symbol or "").strip()
    if not clean_symbol:
        return ""
    if "," in clean_symbol:
        raise CommandError("Only one Toss holdings symbol is supported.")
    if not SYMBOL_PATTERN.match(clean_symbol):
        raise CommandError("Invalid Toss holdings symbol.")
    return clean_symbol


def _safe_reason(exc: Exception, *, diagnostic: bool = False) -> str:
    explicit_reason = getattr(exc, "safe_reason", "")
    if explicit_reason:
        return str(explicit_reason)
    if isinstance(exc, TossProviderDisabled):
        return "provider_disabled"
    if isinstance(exc, TossConfigurationError):
        return "credentials_missing"
    if isinstance(exc, TossAuthError):
        return "authentication_failed"
    if isinstance(exc, TossRateLimitError):
        return "rate_limit_exceeded"
    if isinstance(exc, TossOpenApiError):
        if diagnostic:
            return "accounts_request_failed"
        return "holdings_request_failed"
    return "provider_error"


def _safe_diagnostics(
    exc: Exception | None,
    *,
    account: str | None = None,
    accounts_api_called: bool | None = None,
) -> dict[str, Any]:
    env_account = getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")
    diagnostic = getattr(exc, "account_diagnostic", {}) if exc is not None else {}
    diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else {}
    selected_source = (
        str(diagnostic.get("selected_account_source") or "")
        or ("cli" if is_configured(account) else ("env" if is_configured(env_account) else "accounts_api_single"))
    )
    selected_value = account if is_configured(account) else env_account
    diagnostics = {
        "account_env_configured": _bool_text(is_configured(env_account)),
        "account_env_shape": diagnostic.get("account_env_shape") or _classify_account_value(env_account),
        "accounts_api_called": _bool_text(
            bool(diagnostic.get("accounts_api_called"))
            if accounts_api_called is None
            else bool(accounts_api_called)
        ),
        "selected_account_source": selected_source,
        "account_header_configured": _bool_text(bool(diagnostic.get("account_header_configured", is_configured(selected_value)))),
        "params_shape": "symbol" if selected_source else "",
    }
    for key in ("account_arg_shape", "account_count", "account_types", "account_fallback_used"):
        if key in diagnostic:
            diagnostics[key] = diagnostic[key]
    if is_configured(selected_value) and selected_source not in {"cli_invalid", "none", "ambiguous"}:
        diagnostics["selected_account_masked"] = mask_account_id(selected_value)

    if exc is not None:
        status_code = getattr(exc, "http_status_code", None)
        if status_code is not None:
            diagnostics["http_status_code"] = status_code
        for attr in ("error_code", "error_field", "safe_message"):
            value = _safe_diagnostic_text(getattr(exc, attr, ""))
            if value:
                diagnostics[attr] = value
    return diagnostics


def _classify_account_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "missing"
    if not text.isdigit():
        return "non_integer"
    if len(text) > 20:
        return "too_long"
    return "integer_like"


def _safe_diagnostic_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        return ""
    lowered = text.lower()
    forbidden = (
        "authorization",
        "bearer ",
        "access_token",
        "client_secret",
        "x-tossinvest-account",
        "accountno",
        "accountseq",
    )
    if any(part in lowered for part in forbidden):
        return ""
    return text


def _diagnostic_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_account_types(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    safe_values = []
    for value in values:
        text = _safe_diagnostic_text(value)
        if text:
            safe_values.append(text)
    return safe_values[:20]


def _format_account_types(values: Any) -> str:
    safe_values = _safe_account_types(values)
    return ",".join(safe_values) if safe_values else "none"


def _format_diagnostics_for_log(diagnostics: Mapping[str, Any]) -> str:
    parts = []
    for key in (
        "http_status_code",
        "error_code",
        "error_field",
        "account_env_configured",
        "account_env_shape",
        "accounts_api_called",
        "selected_account_source",
        "account_header_configured",
        "params_shape",
    ):
        value = diagnostics.get(key)
        if value not in {None, ""}:
            parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "none"


def _network_call_for_reason(reason: str) -> bool:
    return reason not in {
        "provider_not_registered",
        "provider_disabled",
        "credentials_missing",
        "account_required",
        "account_seq_required",
        "invalid_account_identifier",
        "invalid_symbol",
        "no_network",
    }


def _log_safe_reason(reason: str) -> str:
    return {
        "--no-network was provided": "no_network",
        "provider not registered": "provider_not_registered",
        "provider error": "provider_error",
        "account_required": "holdings_request_failed",
        "account_not_found": "holdings_request_failed",
        "ambiguous_account": "holdings_request_failed",
        "account_seq_required": "holdings_request_failed",
        "invalid_account_identifier": "holdings_request_failed",
        "confirm_save_required": "confirm_save_required",
        "map_user_holdings_required": "map_user_holdings_required",
        "owner_required": "owner_required",
        "owner_not_found": "owner_not_found",
        "owner_ambiguous": "owner_ambiguous",
    }.get(reason, reason)


def _log_safe_error_code(value: Any) -> str:
    code = str(value or "").strip()
    if code == "account-not-found":
        return "not_found"
    return code


def _format_raw_summary(raw: Any) -> str:
    if not isinstance(raw, Mapping):
        return "none"
    allowed_keys = ("result_count",)
    parts = [f"{key}={raw[key]}" for key in allowed_keys if key in raw]
    return " ".join(parts) if parts else "none"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
