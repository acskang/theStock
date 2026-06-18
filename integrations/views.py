from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST

from holdings.models import UserHolding
from stocks.models import Stock

from integrations.forms import (
    ConfirmActionForm,
    LocalStockSearchForm,
    RevealCredentialForm,
    TossAccountSelectionForm,
    TossAccountTradingInfoForm,
    TossCandleForm,
    TossCredentialForm,
    TossCredentialVerificationForm,
    TossDashboardHoldingsForm,
    TossDashboardOrdersForm,
    TossExchangeRateForm,
    TossHoldingsApplyForm,
    TossHoldingsDryRunForm,
    TossOrderHistoryFilterForm,
    TossSellableQuantityForm,
    TossStockQuotesForm,
    TossSymbolDetailForm,
    TossTradeSyncForm,
)
from integrations.models import IntegrationAuditLog
from integrations.services.credential_crypto import CredentialCryptoConfigurationError
from integrations.services.credential_lifecycle import (
    CredentialDuplicateError,
    CredentialLifecycleError,
    CredentialNotFoundError,
    CredentialRevealError,
    disconnect_credential,
    get_credential_safe_status,
    register_or_replace_pending_credential,
    reset_credential,
    reveal_client_credentials,
)
from integrations.services.toss_readonly_verification import (
    TossReadonlyVerificationAccountNotFound,
    TossReadonlyVerificationAccountSelectionRequired,
    TossReadonlyVerificationAuthError,
    TossReadonlyVerificationConfigurationError,
    TossReadonlyVerificationError,
    TossReadonlyVerificationStateError,
    TossReadonlyVerificationTransientError,
    verify_user_toss_credential_readonly,
)
from integrations.services.toss_holdings_readonly import (
    TossHoldingsReadonlyAuthError,
    TossHoldingsReadonlyError,
    TossHoldingsReadonlyParseError,
    TossHoldingsReadonlyStateError,
    TossHoldingsReadonlyTransientError,
    TossHoldingsReadonlyValidationError,
    fetch_user_toss_holdings_preview,
)
from integrations.services.toss_holdings_sync_plan import (
    ACTION_CREATE,
    ACTION_REMOVE_CANDIDATE,
    ACTION_SKIPPED,
    ACTION_UNCHANGED,
    ACTION_UPDATE,
    HoldingSyncPlanError,
    HoldingSyncPlanMappingError,
    HoldingSyncPlanValidationError,
    fetch_and_build_holdings_sync_plan,
)
from integrations.services.toss_holdings_apply import (
    HoldingApplyDatabaseError,
    HoldingApplyError,
    HoldingApplyFeatureDisabledError,
    HoldingApplyPermissionError,
    HoldingApplyPreflightError,
    HoldingApplyStalePlanError,
    HoldingApplyTokenExpiredError,
    HoldingApplyTokenInvalidError,
    apply_holdings_sync_plan,
    create_apply_confirmation_context,
    is_holdings_apply_enabled,
    load_apply_confirmation_token,
)
from integrations.services.toss_order_history_readonly import (
    TossOrderHistoryAuthError,
    TossOrderHistoryError,
    TossOrderHistoryParseError,
    TossOrderHistoryStateError,
    TossOrderHistoryTransientError,
    TossOrderHistoryValidationError,
    fetch_user_toss_order_history,
)
from integrations.services.toss_trading_info_readonly import (
    TossTradingInfoAuthError,
    TossTradingInfoError,
    TossTradingInfoParseError,
    TossTradingInfoStateError,
    TossTradingInfoTransientError,
    TossTradingInfoValidationError,
    fetch_user_toss_account_trading_info,
    fetch_user_toss_sellable_quantity,
)
from integrations.services.toss_market_explorer_readonly import (
    TossMarketAuthError,
    TossMarketExplorerError,
    TossMarketNotFoundError,
    TossMarketParseError,
    TossMarketStateError,
    TossMarketTransientError,
    TossMarketValidationError,
    fetch_user_toss_candles,
    fetch_user_toss_stock_quotes,
    fetch_user_toss_symbol_market_detail,
    fetch_user_toss_usd_krw_exchange_rate,
)
from integrations.services.toss_trade_sync import (
    TossTradeSyncError,
    TossTradeSyncStateError,
    get_or_create_sync_state,
    get_recent_import_records,
    run_incremental_trade_sync,
    run_initial_trade_sync,
)


FULL_TEMPLATE = "integrations/toss_credential_settings.html"
PANEL_TEMPLATE = "integrations/partials/toss_credential_panel.html"
REVEAL_TEMPLATE = "integrations/partials/toss_credential_reveal.html"
HOLDINGS_DRY_RUN_PANEL_TEMPLATE = "integrations/partials/toss_holdings_dry_run_panel.html"
ORDER_HISTORY_TEMPLATE = "integrations/toss_order_history.html"
ORDER_HISTORY_PANEL_TEMPLATE = "integrations/partials/toss_order_history_panel.html"
DASHBOARD_TEMPLATE = "integrations/toss_dashboard.html"
DASHBOARD_LIVE_HOLDINGS_TEMPLATE = "integrations/partials/toss_dashboard_live_holdings.html"
DASHBOARD_RECENT_ORDERS_TEMPLATE = "integrations/partials/toss_dashboard_recent_orders.html"
TRADING_INFO_TEMPLATE = "integrations/toss_trading_info.html"
TRADING_INFO_ACCOUNT_PANEL_TEMPLATE = "integrations/partials/toss_trading_info_account_panel.html"
SELLABLE_QUANTITY_PANEL_TEMPLATE = "integrations/partials/toss_sellable_quantity_panel.html"
MARKET_EXPLORER_TEMPLATE = "integrations/toss_market_explorer.html"
MARKET_LOCAL_SEARCH_TEMPLATE = "integrations/partials/toss_market_local_search.html"
MARKET_QUOTES_PANEL_TEMPLATE = "integrations/partials/toss_market_quotes_panel.html"
MARKET_SYMBOL_DETAIL_PANEL_TEMPLATE = "integrations/partials/toss_market_symbol_detail_panel.html"
MARKET_CANDLES_PANEL_TEMPLATE = "integrations/partials/toss_market_candles_panel.html"
MARKET_EXCHANGE_RATE_TEMPLATE = "integrations/partials/toss_market_exchange_rate.html"
TRADE_SYNC_TEMPLATE = "integrations/toss_trade_sync.html"
TRADE_SYNC_PANEL_TEMPLATE = "integrations/partials/toss_trade_sync_panel.html"


@login_required
@require_GET
def toss_dashboard(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    context = _build_dashboard_context(request)
    return _no_store(render(request, DASHBOARD_TEMPLATE, context))


@login_required
@require_GET
def toss_credential_settings(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    context = _build_context(request)
    return _no_store(render(request, FULL_TEMPLATE, context))


@login_required
@require_POST
@sensitive_post_parameters("client_secret")
def toss_credential_save(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossCredentialForm(request.POST)
    feedback: list[tuple[str, str]] = []

    if form.is_valid():
        try:
            register_or_replace_pending_credential(
                user=request.user,
                client_id=form.cleaned_data["client_id"],
                client_secret=form.cleaned_data["client_secret"],
                scopes=[],
                actor=request.user,
            )
        except CredentialDuplicateError:
            form.add_error(None, "이미 등록된 credential입니다.")
        except CredentialCryptoConfigurationError:
            form.add_error(None, "Credential 암호화 설정을 확인해야 합니다.")
        except CredentialLifecycleError:
            form.add_error(None, "Credential 저장에 실패했습니다.")
        else:
            success = "Toss credential이 암호화 저장되었습니다. 실제 연결 검증은 후속 단계에서 진행됩니다."
            if _is_htmx(request):
                feedback.append(("success", success))
                context = _build_context(request, credential_form=TossCredentialForm(), feedback=feedback)
                return _no_store(render(request, PANEL_TEMPLATE, context))
            messages.success(request, success)
            return redirect("integrations:toss_credential_settings")

    if _is_htmx(request):
        context = _build_context(request, credential_form=form)
        return _no_store(render(request, PANEL_TEMPLATE, context, status=400))
    context = _build_context(request, credential_form=form)
    return _no_store(render(request, FULL_TEMPLATE, context, status=400))


@login_required
@require_POST
@sensitive_post_parameters("password")
def toss_credential_reveal(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = RevealCredentialForm(request.POST)
    reveal_payload = None
    reveal_error = ""

    if form.is_valid():
        try:
            reveal_payload = reveal_client_credentials(
                user=request.user,
                request_user=request.user,
                password=form.cleaned_data["password"],
            )
        except (CredentialRevealError, CredentialLifecycleError):
            reveal_error = "Credential을 표시할 수 없습니다. 비밀번호와 credential 상태를 확인해 주세요."
    else:
        reveal_error = "비밀번호를 입력해 주세요."

    context = _build_context(
        request,
        reveal_form=RevealCredentialForm(),
        reveal_payload=reveal_payload,
        reveal_error=reveal_error,
    )
    template = REVEAL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
    response_status = 200 if reveal_payload else 400
    return _no_store(render(request, template, context, status=response_status))


@login_required
@require_POST
def toss_credential_reset(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = ConfirmActionForm(request.POST, prefix="reset")
    feedback: list[tuple[str, str]] = []

    if form.is_valid():
        try:
            reset_credential(
                user=request.user,
                actor=request.user,
                reason_code="user_reset",
                safe_summary="user requested credential reset",
            )
        except CredentialNotFoundError:
            feedback.append(("warning", "초기화할 Toss credential이 없습니다."))
        except CredentialLifecycleError:
            feedback.append(("danger", "Credential 초기화에 실패했습니다."))
        else:
            success = "Credential이 초기화되었습니다. 다시 등록해 주세요."
            if _is_htmx(request):
                feedback.append(("success", success))
            else:
                messages.success(request, success)
                return redirect("integrations:toss_credential_settings")
    else:
        feedback.append(("danger", "초기화를 확인해 주세요."))

    if _is_htmx(request):
        context = _build_context(request, reset_form=form, feedback=feedback)
        return _no_store(render(request, PANEL_TEMPLATE, context, status=400 if form.errors else 200))
    context = _build_context(request, reset_form=form, feedback=feedback)
    return _no_store(render(request, FULL_TEMPLATE, context, status=400 if form.errors else 200))


@login_required
@require_POST
def toss_credential_disconnect(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = ConfirmActionForm(request.POST, prefix="disconnect")
    feedback: list[tuple[str, str]] = []

    if form.is_valid():
        try:
            disconnect_credential(
                user=request.user,
                actor=request.user,
                reason_code="user_disconnect",
                safe_summary="user disconnected Toss integration",
            )
        except CredentialNotFoundError:
            feedback.append(("warning", "해제할 Toss 연동이 없습니다."))
        except CredentialLifecycleError:
            feedback.append(("danger", "Toss 연동 해제에 실패했습니다."))
        else:
            success = "Toss 연동이 해제되었습니다."
            if _is_htmx(request):
                feedback.append(("success", success))
            else:
                messages.success(request, success)
                return redirect("integrations:toss_credential_settings")
    else:
        feedback.append(("danger", "연동 해제를 확인해 주세요."))

    if _is_htmx(request):
        context = _build_context(request, disconnect_form=form, feedback=feedback)
        return _no_store(render(request, PANEL_TEMPLATE, context, status=400 if form.errors else 200))
    context = _build_context(request, disconnect_form=form, feedback=feedback)
    return _no_store(render(request, FULL_TEMPLATE, context, status=400 if form.errors else 200))


@login_required
@require_POST
def toss_credential_verify(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    feedback: list[tuple[str, str]] = []
    account_candidates = []
    verification_level = ""
    verification_message = ""

    if not _api_calls_enabled():
        verification_level = "warning"
        verification_message = "현재 Toss 연결 확인 기능이 활성화되지 않았습니다."
        feedback.append((verification_level, verification_message))
        context = _build_context(request, feedback=feedback, verification_level=verification_level, verification_message=verification_message)
        template = PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=403))

    selected_account_hash = str(request.POST.get("selected_account_hash", "") or "").strip()
    if selected_account_hash:
        form = TossAccountSelectionForm(request.POST)
        verification_form = TossCredentialVerificationForm()
        account_selection_form = form
    else:
        form = TossCredentialVerificationForm(request.POST)
        verification_form = form
        account_selection_form = TossAccountSelectionForm()

    if not form.is_valid():
        verification_level = "danger"
        verification_message = "연결 확인을 실행하려면 확인 항목을 선택해 주세요."
        feedback.append((verification_level, verification_message))
        context = _build_context(
            request,
            verification_form=verification_form,
            account_selection_form=account_selection_form,
            feedback=feedback,
            verification_level=verification_level,
            verification_message=verification_message,
        )
        template = PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=400))

    try:
        result = verify_user_toss_credential_readonly(
            user=request.user,
            actor=request.user,
            selected_account_hash=form.cleaned_data.get("selected_account_hash"),
        )
    except TossReadonlyVerificationAccountSelectionRequired as exc:
        account_candidates = exc.candidates
        verification_level = "info"
        verification_message = "여러 계좌가 확인되었습니다. 대표 계좌를 선택해 주세요."
        feedback.append((verification_level, verification_message))
        context = _build_context(
            request,
            account_candidates=account_candidates,
            feedback=feedback,
            verification_level=verification_level,
            verification_message=verification_message,
        )
        template = PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=200))
    except TossReadonlyVerificationAuthError:
        verification_level = "danger"
        verification_message = "Toss 인증에 실패했습니다. Credential을 다시 등록해 주세요."
        feedback.append((verification_level, verification_message))
    except TossReadonlyVerificationTransientError:
        verification_level = "warning"
        verification_message = "일시적인 오류로 연결 확인을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
        feedback.append((verification_level, verification_message))
    except TossReadonlyVerificationAccountNotFound:
        verification_level = "warning"
        verification_message = "선택 가능한 Toss 계좌를 찾지 못했습니다."
        feedback.append((verification_level, verification_message))
    except TossReadonlyVerificationConfigurationError:
        verification_level = "warning"
        verification_message = "현재 Toss 연결 확인 기능이 활성화되지 않았습니다."
        feedback.append((verification_level, verification_message))
    except TossReadonlyVerificationStateError:
        verification_level = "danger"
        verification_message = "현재 상태에서는 연결 확인을 실행할 수 없습니다."
        feedback.append((verification_level, verification_message))
    except TossReadonlyVerificationError:
        verification_level = "danger"
        verification_message = "Toss 연결 확인에 실패했습니다."
        feedback.append((verification_level, verification_message))
    else:
        verification_level = "success"
        verification_message = "Toss read-only 연결 확인이 완료되었습니다."
        feedback.append((verification_level, verification_message))
        context = _build_context(
            request,
            verification_result=result,
            feedback=feedback,
            verification_level=verification_level,
            verification_message=verification_message,
        )
        if _is_htmx(request):
            return _no_store(render(request, PANEL_TEMPLATE, context))
        return _no_store(render(request, FULL_TEMPLATE, context))

    context = _build_context(request, feedback=feedback, verification_level=verification_level, verification_message=verification_message)
    template = PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
    return _no_store(render(request, template, context, status=400))


@login_required
@require_POST
def toss_holdings_dry_run(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossHoldingsDryRunForm(request.POST)
    feedback: list[tuple[str, str]] = []
    safe_status = get_credential_safe_status(request.user)

    if not _api_calls_enabled():
        feedback.append(("warning", "현재 Toss API 호출 기능이 비활성화되어 있어 보유종목 미리보기를 실행할 수 없습니다."))
        context = _build_context(request, holdings_dry_run_form=form, feedback=feedback)
        template = HOLDINGS_DRY_RUN_PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=403))

    if safe_status.get("status") != "active":
        feedback.append(("warning", "Toss credential 연결 확인을 먼저 완료해 주세요."))
        context = _build_context(request, holdings_dry_run_form=form, feedback=feedback)
        template = HOLDINGS_DRY_RUN_PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=400))

    if not form.is_valid():
        context = _build_context(
            request,
            holdings_dry_run_form=TossHoldingsDryRunForm(),
            holdings_dry_run_error="입력값을 확인해 주세요.",
        )
        template = HOLDINGS_DRY_RUN_PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=400))

    try:
        plan = fetch_and_build_holdings_sync_plan(
            user=request.user,
            actor=request.user,
            symbol=form.cleaned_data.get("symbol") or None,
            transport=None,
            record_audit=True,
        )
    except Exception as exc:
        context = _build_context(
            request,
            holdings_dry_run_form=form,
            holdings_dry_run_error=_map_holdings_dry_run_exception_to_safe_message(exc),
        )
        template = HOLDINGS_DRY_RUN_PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
        return _no_store(render(request, template, context, status=400))

    context = _build_context(
        request,
        holdings_dry_run_form=TossHoldingsDryRunForm(),
        holdings_dry_run_plan=plan,
        holdings_apply_form=_build_holdings_apply_form(request.user, plan),
        holdings_dry_run_message="보유종목 동기화 dry-run plan이 생성되었습니다. 실제 DB에는 반영되지 않았습니다.",
        feedback=feedback,
    )
    template = HOLDINGS_DRY_RUN_PANEL_TEMPLATE if _is_htmx(request) else FULL_TEMPLATE
    return _no_store(render(request, template, context))


@login_required
@require_POST
@sensitive_post_parameters("password", "confirmation_token")
def toss_holdings_apply(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossHoldingsApplyForm(request.POST)

    if not (_api_calls_enabled() and _holdings_apply_enabled()):
        context = _build_context(
            request,
            holdings_apply_form=TossHoldingsApplyForm(),
            holdings_apply_error="현재 보유종목 실제 반영 기능이 활성화되지 않았습니다.",
        )
        return _no_store(render(request, HOLDINGS_DRY_RUN_PANEL_TEMPLATE, context, status=403))

    if not form.is_valid():
        context = _build_context(
            request,
            holdings_apply_form=TossHoldingsApplyForm(),
            holdings_apply_error="반영 확인 입력값을 확인해 주세요.",
        )
        return _no_store(render(request, HOLDINGS_DRY_RUN_PANEL_TEMPLATE, context, status=400))

    if not request.user.check_password(form.cleaned_data["password"]):
        context = _build_context(
            request,
            holdings_apply_form=TossHoldingsApplyForm(),
            holdings_apply_error="비밀번호가 올바르지 않습니다.",
        )
        return _no_store(render(request, HOLDINGS_DRY_RUN_PANEL_TEMPLATE, context, status=400))

    try:
        payload = load_apply_confirmation_token(
            token=form.cleaned_data["confirmation_token"],
            user=request.user,
        )
        fresh_plan = fetch_and_build_holdings_sync_plan(
            user=request.user,
            actor=request.user,
            symbol=payload.get("symbol_filter") or None,
            transport=None,
            record_audit=False,
        )
        result = apply_holdings_sync_plan(
            user=request.user,
            actor=request.user,
            plan=fresh_plan,
            confirmation_payload=payload,
        )
    except Exception as exc:
        context = _build_context(
            request,
            holdings_apply_form=TossHoldingsApplyForm(),
            holdings_apply_error=_map_holdings_apply_exception_to_safe_message(exc),
        )
        return _no_store(render(request, HOLDINGS_DRY_RUN_PANEL_TEMPLATE, context, status=400))

    context = _build_context(
        request,
        holdings_apply_form=TossHoldingsApplyForm(),
        holdings_apply_result=result,
        holdings_apply_message="UserHolding create/update 반영이 완료되었습니다.",
    )
    return _no_store(render(request, HOLDINGS_DRY_RUN_PANEL_TEMPLATE, context))


@login_required
def toss_order_history(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    order_history_page = None
    order_history_error = ""
    order_history_message = ""

    if request.method == "POST":
        form = TossOrderHistoryFilterForm(request.POST)
        if not _api_calls_enabled():
            order_history_error = "현재 Toss API 호출 기능이 비활성화되어 주문 내역을 조회할 수 없습니다."
        elif form.is_valid():
            try:
                order_history_page = fetch_user_toss_order_history(
                    user=request.user,
                    actor=request.user,
                    status=form.cleaned_data["status"],
                    symbol=form.cleaned_data.get("symbol") or None,
                    from_date=form.cleaned_data.get("from_date"),
                    to_date=form.cleaned_data.get("to_date"),
                    cursor=form.cleaned_data.get("cursor") or None,
                    limit=form.cleaned_data.get("limit") or 20,
                    transport=None,
                )
            except Exception as exc:
                order_history_error = _map_order_history_exception_to_safe_message(exc)
            else:
                order_history_message = "Toss 주문·체결 내역을 조회했습니다."
        else:
            order_history_error = "조회 조건을 확인해 주세요."
        status_code = 400 if order_history_error else 200
    else:
        form = TossOrderHistoryFilterForm(initial={"status": "CLOSED", "limit": "20"})
        status_code = 200

    context = _build_order_history_context(
        request,
        order_history_form=form,
        order_history_page=order_history_page,
        order_history_error=order_history_error,
        order_history_message=order_history_message,
    )
    template = ORDER_HISTORY_PANEL_TEMPLATE if _is_htmx(request) else ORDER_HISTORY_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_GET
def toss_trading_info(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    context = _build_trading_info_context(request)
    return _no_store(render(request, TRADING_INFO_TEMPLATE, context))


@login_required
@require_POST
def toss_account_trading_info(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossAccountTradingInfoForm(request.POST)
    account_trading_info = None
    account_trading_info_error = ""
    account_trading_info_message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)

    if not _api_calls_enabled():
        account_trading_info_error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        account_trading_info_error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            account_trading_info = fetch_user_toss_account_trading_info(
                user=request.user,
                actor=request.user,
                transport=None,
            )
        except Exception as exc:
            account_trading_info_error = _map_trading_info_exception_to_safe_message(exc)
            status_code = 400
        else:
            account_trading_info_message = "Toss 계좌 거래 가능 정보를 조회했습니다."
    else:
        account_trading_info_error = "조회 조건을 확인해 주세요."
        status_code = 400

    context = _build_trading_info_context(
        request,
        account_form=form,
        account_trading_info=account_trading_info,
        account_trading_info_error=account_trading_info_error,
        account_trading_info_message=account_trading_info_message,
    )
    template = TRADING_INFO_ACCOUNT_PANEL_TEMPLATE if _is_htmx(request) else TRADING_INFO_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_POST
def toss_sellable_quantity(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossSellableQuantityForm(request.POST)
    sellable_quantity = None
    sellable_quantity_error = ""
    sellable_quantity_message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)

    if not _api_calls_enabled():
        sellable_quantity_error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        sellable_quantity_error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            sellable_quantity = fetch_user_toss_sellable_quantity(
                user=request.user,
                actor=request.user,
                symbol=form.cleaned_data["symbol"],
                transport=None,
            )
        except Exception as exc:
            sellable_quantity_error = _map_trading_info_exception_to_safe_message(exc)
            status_code = 400
        else:
            sellable_quantity_message = "Toss 매도 가능 수량을 조회했습니다."
    else:
        sellable_quantity_error = "조회 조건을 확인해 주세요."
        status_code = 400

    context = _build_trading_info_context(
        request,
        sellable_form=form,
        sellable_quantity=sellable_quantity,
        sellable_quantity_error=sellable_quantity_error,
        sellable_quantity_message=sellable_quantity_message,
    )
    template = SELLABLE_QUANTITY_PANEL_TEMPLATE if _is_htmx(request) else TRADING_INFO_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_GET
def toss_market_explorer(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    return _no_store(render(request, MARKET_EXPLORER_TEMPLATE, _build_market_context(request)))


@login_required
@require_POST
def toss_market_local_search(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = LocalStockSearchForm(request.POST)
    results = []
    error = ""
    status_code = 200
    if form.is_valid():
        query = form.cleaned_data["query"]
        results = list(
            Stock.objects.filter(Q(code__icontains=query) | Q(name__icontains=query), is_active=True)
            .order_by("code")[:20]
        )
    else:
        error = "검색어를 확인해 주세요."
        status_code = 400
    context = _build_market_context(request, local_search_form=form, local_search_results=results, local_search_error=error)
    template = MARKET_LOCAL_SEARCH_TEMPLATE if _is_htmx(request) else MARKET_EXPLORER_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_POST
def toss_market_quotes(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossStockQuotesForm(request.POST)
    quote_batch = None
    error = ""
    message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)
    if not _api_calls_enabled():
        error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            quote_batch = fetch_user_toss_stock_quotes(
                user=request.user,
                actor=request.user,
                symbols=form.cleaned_data["symbols"],
                transport=None,
            )
        except Exception as exc:
            error = _map_market_exception_to_safe_message(exc)
            status_code = 400
        else:
            message = "현재가와 종목 기본정보를 조회했습니다."
    else:
        error = "조회 조건을 확인해 주세요."
        status_code = 400
    context = _build_market_context(request, quotes_form=form, quote_batch=quote_batch, quotes_error=error, quotes_message=message)
    template = MARKET_QUOTES_PANEL_TEMPLATE if _is_htmx(request) else MARKET_EXPLORER_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_POST
def toss_market_symbol_detail(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossSymbolDetailForm(request.POST)
    symbol_detail = None
    error = ""
    message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)
    if not _api_calls_enabled():
        error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            symbol_detail = fetch_user_toss_symbol_market_detail(
                user=request.user,
                actor=request.user,
                symbol=form.cleaned_data["symbol"],
                trades_count=form.cleaned_data["trades_count"],
                transport=None,
            )
        except Exception as exc:
            error = _map_market_exception_to_safe_message(exc)
            status_code = 400
        else:
            message = "종목 상세 시세를 조회했습니다."
    else:
        error = "조회 조건을 확인해 주세요."
        status_code = 400
    context = _build_market_context(request, detail_form=form, symbol_detail=symbol_detail, detail_error=error, detail_message=message)
    template = MARKET_SYMBOL_DETAIL_PANEL_TEMPLATE if _is_htmx(request) else MARKET_EXPLORER_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_POST
def toss_market_candles(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossCandleForm(request.POST)
    candle_page = None
    error = ""
    message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)
    if not _api_calls_enabled():
        error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            candle_page = fetch_user_toss_candles(
                user=request.user,
                actor=request.user,
                symbol=form.cleaned_data["symbol"],
                interval=form.cleaned_data["interval"],
                count=form.cleaned_data["count"],
                adjusted=form.cleaned_data.get("adjusted"),
                before=form.cleaned_data.get("before") or None,
                transport=None,
            )
        except Exception as exc:
            error = _map_market_exception_to_safe_message(exc)
            status_code = 400
        else:
            message = "캔들 데이터를 조회했습니다."
    else:
        error = "조회 조건을 확인해 주세요."
        status_code = 400
    context = _build_market_context(request, candle_form=form, candle_page=candle_page, candles_error=error, candles_message=message)
    template = MARKET_CANDLES_PANEL_TEMPLATE if _is_htmx(request) else MARKET_EXPLORER_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_POST
def toss_market_exchange_rate(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossExchangeRateForm(request.POST)
    exchange_rate = None
    error = ""
    message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)
    if not _api_calls_enabled():
        error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            exchange_rate = fetch_user_toss_usd_krw_exchange_rate(user=request.user, actor=request.user, transport=None)
        except Exception as exc:
            error = _map_market_exception_to_safe_message(exc)
            status_code = 400
        else:
            message = "USD/KRW 참고 환율을 조회했습니다."
    else:
        error = "조회 조건을 확인해 주세요."
        status_code = 400
    context = _build_market_context(request, exchange_rate_form=form, exchange_rate=exchange_rate, exchange_rate_error=error, exchange_rate_message=message)
    template = MARKET_EXCHANGE_RATE_TEMPLATE if _is_htmx(request) else MARKET_EXPLORER_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_GET
def toss_trade_sync_page(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    context = _build_trade_sync_context(request)
    return _no_store(render(request, TRADE_SYNC_TEMPLATE, context))


@login_required
@require_POST
def toss_trade_sync_run(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossTradeSyncForm(request.POST)
    sync_result = None
    sync_error = ""
    sync_message = ""

    if not _api_calls_enabled():
        sync_error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
    elif get_credential_safe_status(request.user).get("status") != "active":
        sync_error = "Toss credential 연결 확인을 먼저 완료해 주세요."
    elif not form.is_valid():
        sync_error = "거래 동기화를 실행하려면 확인 항목을 선택해 주세요."
    else:
        try:
            if form.cleaned_data["mode"] == "initial":
                sync_result = run_initial_trade_sync(user=request.user, actor=request.user)
            else:
                sync_result = run_incremental_trade_sync(user=request.user, actor=request.user)
        except TossTradeSyncError as exc:
            sync_error = _map_trade_sync_exception_to_safe_message(exc)
        else:
            sync_message = "Toss 체결 거래 동기화가 완료되었습니다."

    context = _build_trade_sync_context(
        request,
        initial_form=TossTradeSyncForm(mode="initial"),
        incremental_form=TossTradeSyncForm(mode="incremental"),
        sync_result=sync_result,
        sync_error=sync_error,
        sync_message=sync_message,
    )
    template = TRADE_SYNC_PANEL_TEMPLATE if _is_htmx(request) else TRADE_SYNC_TEMPLATE
    return _no_store(render(request, template, context, status=400 if sync_error else 200))


@login_required
@require_POST
def toss_dashboard_holdings(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossDashboardHoldingsForm(request.POST)
    live_holdings_preview = None
    live_holdings_error = ""
    live_holdings_message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)

    if not _api_calls_enabled():
        live_holdings_error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        live_holdings_error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            live_holdings_preview = fetch_user_toss_holdings_preview(
                user=request.user,
                actor=request.user,
                symbol=form.cleaned_data.get("symbol") or None,
                transport=None,
            )
        except Exception as exc:
            live_holdings_error = _map_dashboard_data_exception_to_safe_message(exc)
            status_code = 400
        else:
            live_holdings_message = "Toss 실시간 보유종목을 조회했습니다."
    else:
        live_holdings_error = "조회 조건을 확인해 주세요."
        status_code = 400

    context = _build_dashboard_context(
        request,
        holdings_form=form,
        live_holdings_preview=live_holdings_preview,
        live_holdings_error=live_holdings_error,
        live_holdings_message=live_holdings_message,
    )
    template = DASHBOARD_LIVE_HOLDINGS_TEMPLATE if _is_htmx(request) else DASHBOARD_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


@login_required
@require_POST
def toss_dashboard_orders(request: HttpRequest) -> HttpResponse:
    _feature_enabled_or_404()
    form = TossDashboardOrdersForm(request.POST)
    recent_orders_page = None
    recent_orders_error = ""
    recent_orders_message = ""
    status_code = 200
    safe_status = get_credential_safe_status(request.user)

    if not _api_calls_enabled():
        recent_orders_error = "현재 Toss API 조회 기능이 비활성화되어 있습니다."
        status_code = 403
    elif safe_status.get("status") != "active":
        recent_orders_error = "Toss credential 연결 확인을 먼저 완료해 주세요."
        status_code = 400
    elif form.is_valid():
        try:
            recent_orders_page = fetch_user_toss_order_history(
                user=request.user,
                actor=request.user,
                status=form.cleaned_data["status"],
                symbol=form.cleaned_data.get("symbol") or None,
                limit=form.cleaned_data.get("limit") or 10,
                transport=None,
            )
        except Exception as exc:
            recent_orders_error = _map_dashboard_data_exception_to_safe_message(exc)
            status_code = 400
        else:
            recent_orders_message = "최근 Toss 주문·체결 내역을 조회했습니다."
    else:
        recent_orders_error = "조회 조건을 확인해 주세요."
        status_code = 400

    context = _build_dashboard_context(
        request,
        orders_form=form,
        recent_orders_page=recent_orders_page,
        recent_orders_error=recent_orders_error,
        recent_orders_message=recent_orders_message,
    )
    template = DASHBOARD_RECENT_ORDERS_TEMPLATE if _is_htmx(request) else DASHBOARD_TEMPLATE
    return _no_store(render(request, template, context, status=status_code))


def _feature_enabled_or_404() -> None:
    if not bool(getattr(settings, "TOSS_USER_CREDENTIAL_UI_ENABLED", False)):
        raise Http404("Toss credential UI is disabled.")


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _api_calls_enabled() -> bool:
    return bool(getattr(settings, "TOSS_USER_TOSS_API_CALLS_ENABLED", False))


def _holdings_apply_enabled() -> bool:
    return bool(getattr(settings, "TOSS_USER_HOLDINGS_APPLY_ENABLED", False))


def _no_store(response: HttpResponse) -> HttpResponse:
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def _map_holdings_dry_run_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, (HoldingSyncPlanValidationError, TossHoldingsReadonlyValidationError)):
        return "입력값을 확인해 주세요."
    if isinstance(exc, HoldingSyncPlanMappingError):
        return "현재 보유종목 모델과 매핑할 수 없습니다."
    if isinstance(exc, TossHoldingsReadonlyAuthError):
        return "Toss 인증 상태를 확인해 주세요. 필요하면 credential을 다시 등록해 주세요."
    if isinstance(exc, TossHoldingsReadonlyTransientError):
        return "일시적인 오류로 보유종목 미리보기를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
    if isinstance(exc, TossHoldingsReadonlyStateError):
        return "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, TossHoldingsReadonlyParseError):
        return "Toss 응답을 해석하지 못했습니다."
    if isinstance(exc, (HoldingSyncPlanError, TossHoldingsReadonlyError)):
        return "보유종목 미리보기를 완료하지 못했습니다."
    return "보유종목 미리보기를 완료하지 못했습니다."


def _map_holdings_apply_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, HoldingApplyTokenExpiredError):
        return "확인 시간이 만료되었습니다. dry-run을 다시 실행해 주세요."
    if isinstance(exc, HoldingApplyTokenInvalidError):
        return "유효하지 않은 반영 요청입니다. dry-run을 다시 실행해 주세요."
    if isinstance(exc, HoldingApplyStalePlanError):
        return "보유종목 데이터가 변경되었습니다. dry-run을 다시 실행해 주세요."
    if isinstance(exc, HoldingApplyPreflightError):
        return "일부 종목을 Stock master와 매핑할 수 없어 반영하지 않았습니다."
    if isinstance(exc, HoldingApplyPermissionError):
        return "이 반영 작업을 수행할 권한이 없습니다."
    if isinstance(exc, HoldingApplyDatabaseError):
        return "보유종목 반영 중 오류가 발생해 전체 작업이 취소되었습니다."
    if isinstance(exc, HoldingApplyFeatureDisabledError):
        return "현재 보유종목 실제 반영 기능이 활성화되지 않았습니다."
    if isinstance(exc, HoldingApplyError):
        return "보유종목을 반영하지 못했습니다."
    if isinstance(exc, TossHoldingsReadonlyAuthError):
        return "Toss 인증 상태를 확인해 주세요. 필요하면 credential을 다시 등록해 주세요."
    if isinstance(exc, TossHoldingsReadonlyTransientError):
        return "일시적인 오류로 보유종목 반영 준비를 완료하지 못했습니다. 잠시 후 다시 시도해 주세요."
    if isinstance(exc, TossHoldingsReadonlyStateError):
        return "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, TossHoldingsReadonlyParseError):
        return "Toss 응답을 해석하지 못했습니다."
    return "보유종목을 반영하지 못했습니다."


def _map_order_history_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, TossOrderHistoryValidationError):
        return "조회 조건을 확인해 주세요."
    if isinstance(exc, TossOrderHistoryAuthError):
        return "Toss 인증 상태를 확인해 주세요."
    if isinstance(exc, TossOrderHistoryTransientError):
        return "일시적인 오류로 주문 내역을 조회하지 못했습니다."
    if isinstance(exc, TossOrderHistoryStateError):
        return "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, TossOrderHistoryParseError):
        return "주문 내역 응답을 해석하지 못했습니다."
    if isinstance(exc, TossOrderHistoryError):
        return "주문 내역을 조회하지 못했습니다."
    return "주문 내역을 조회하지 못했습니다."


def _map_trade_sync_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, TossTradeSyncStateError):
        return str(exc) or "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, TossTradeSyncError):
        return "일시적인 오류로 거래 동기화를 완료하지 못했습니다. 다시 실행하면 중복 없이 이어서 처리됩니다."
    return "거래 동기화를 완료하지 못했습니다."


def _map_dashboard_data_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, (TossHoldingsReadonlyAuthError, TossOrderHistoryAuthError)):
        return "Toss 인증 상태를 확인해 주세요."
    if isinstance(exc, (TossHoldingsReadonlyTransientError, TossOrderHistoryTransientError)):
        return "일시적인 오류로 데이터를 불러오지 못했습니다."
    if isinstance(exc, (TossHoldingsReadonlyStateError, TossOrderHistoryStateError)):
        return "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, (TossHoldingsReadonlyParseError, TossOrderHistoryParseError)):
        return "Toss 응답을 해석하지 못했습니다."
    if isinstance(exc, (TossHoldingsReadonlyValidationError, TossOrderHistoryValidationError)):
        return "조회 조건을 확인해 주세요."
    if isinstance(exc, (TossHoldingsReadonlyError, TossOrderHistoryError)):
        return "데이터를 불러오지 못했습니다."
    return "데이터를 불러오지 못했습니다."


def _map_trading_info_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, TossTradingInfoValidationError):
        return "조회 조건을 확인해 주세요."
    if isinstance(exc, TossTradingInfoAuthError):
        return "Toss 인증 상태를 확인해 주세요."
    if isinstance(exc, TossTradingInfoTransientError):
        return "일시적인 오류로 거래 가능 정보를 불러오지 못했습니다."
    if isinstance(exc, TossTradingInfoStateError):
        return "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, TossTradingInfoParseError):
        return "Toss 응답을 해석하지 못했습니다."
    if isinstance(exc, TossTradingInfoError):
        return "거래 가능 정보를 불러오지 못했습니다."
    return "거래 가능 정보를 불러오지 못했습니다."


def _map_market_exception_to_safe_message(exc: Exception) -> str:
    if isinstance(exc, TossMarketValidationError):
        return "조회 조건을 확인해 주세요."
    if isinstance(exc, TossMarketNotFoundError):
        return "해당 종목 정보를 찾지 못했습니다."
    if isinstance(exc, TossMarketAuthError):
        return "Toss 인증 상태를 확인해 주세요."
    if isinstance(exc, TossMarketTransientError):
        return "일시적인 오류로 시장 데이터를 불러오지 못했습니다."
    if isinstance(exc, TossMarketStateError):
        return "Toss credential 연결 확인을 먼저 완료해 주세요."
    if isinstance(exc, TossMarketParseError):
        return "시장 데이터 응답을 해석하지 못했습니다."
    if isinstance(exc, TossMarketExplorerError):
        return "시장 데이터를 불러오지 못했습니다."
    return "시장 데이터를 불러오지 못했습니다."


def _build_holdings_apply_form(user, plan) -> TossHoldingsApplyForm | None:
    if not _holdings_apply_enabled():
        return None
    if not plan or plan.create_count + plan.update_count <= 0:
        return None
    context = create_apply_confirmation_context(user=user, plan=plan)
    return TossHoldingsApplyForm(initial={"confirmation_token": context["confirmation_token"]})


def _group_holdings_plan_items(plan) -> dict[str, list]:
    grouped = {
        ACTION_CREATE: [],
        ACTION_UPDATE: [],
        ACTION_UNCHANGED: [],
        ACTION_REMOVE_CANDIDATE: [],
        ACTION_SKIPPED: [],
    }
    if not plan:
        return grouped
    for item in plan.items:
        grouped.setdefault(item.action, []).append(item)
    return grouped


def _build_context(
    request: HttpRequest,
    *,
    credential_form: TossCredentialForm | None = None,
    reveal_form: RevealCredentialForm | None = None,
    reset_form: ConfirmActionForm | None = None,
    disconnect_form: ConfirmActionForm | None = None,
    verification_form: TossCredentialVerificationForm | None = None,
    account_selection_form: TossAccountSelectionForm | None = None,
    account_candidates: list | None = None,
    verification_result=None,
    verification_level: str = "",
    verification_message: str = "",
    holdings_dry_run_form: TossHoldingsDryRunForm | None = None,
    holdings_dry_run_plan=None,
    holdings_dry_run_error: str = "",
    holdings_dry_run_message: str = "",
    holdings_apply_form: TossHoldingsApplyForm | None = None,
    holdings_apply_result=None,
    holdings_apply_error: str = "",
    holdings_apply_message: str = "",
    reveal_payload: dict | None = None,
    reveal_error: str = "",
    feedback: list[tuple[str, str]] | None = None,
) -> dict:
    holdings_items_by_action = _group_holdings_plan_items(holdings_dry_run_plan)
    return {
        "credential_form": credential_form or TossCredentialForm(),
        "reveal_form": reveal_form or RevealCredentialForm(),
        "reset_form": reset_form or ConfirmActionForm(prefix="reset"),
        "disconnect_form": disconnect_form or ConfirmActionForm(prefix="disconnect"),
        "verification_form": verification_form or TossCredentialVerificationForm(),
        "account_selection_form": account_selection_form or TossAccountSelectionForm(),
        "holdings_dry_run_form": holdings_dry_run_form or TossHoldingsDryRunForm(),
        "holdings_dry_run_plan": holdings_dry_run_plan,
        "holdings_dry_run_items_by_action": holdings_items_by_action,
        "holdings_dry_run_error": holdings_dry_run_error,
        "holdings_dry_run_message": holdings_dry_run_message,
        "holdings_apply_form": holdings_apply_form,
        "holdings_apply_result": holdings_apply_result,
        "holdings_apply_error": holdings_apply_error,
        "holdings_apply_message": holdings_apply_message,
        "holdings_apply_enabled": _holdings_apply_enabled(),
        "account_candidates": account_candidates or [],
        "verification_result": verification_result,
        "verification_level": verification_level,
        "verification_message": verification_message,
        "safe_status": get_credential_safe_status(request.user),
        "reveal_payload": reveal_payload,
        "reveal_error": reveal_error,
        "feedback": feedback or [],
        "toss_api_calls_enabled": _api_calls_enabled(),
        "settings_url": reverse("integrations:toss_credential_settings"),
        "public_rollout_warning": "public 운영 전 토스증권 약관/승인 범위 확인이 필요합니다.",
        "verification_notice": "Toss read-only 연결 확인은 token 발급과 계좌 목록 조회만 수행합니다. 보유종목/주문내역 동기화는 후속 단계에서 진행됩니다.",
    }


def _build_order_history_context(
    request: HttpRequest,
    *,
    order_history_form: TossOrderHistoryFilterForm | None = None,
    order_history_page=None,
    order_history_error: str = "",
    order_history_message: str = "",
) -> dict:
    return {
        "order_history_form": order_history_form or TossOrderHistoryFilterForm(initial={"status": "CLOSED", "limit": "20"}),
        "order_history_page": order_history_page,
        "order_history_error": order_history_error,
        "order_history_message": order_history_message,
        "safe_status": get_credential_safe_status(request.user),
        "toss_api_calls_enabled": _api_calls_enabled(),
        "settings_url": reverse("integrations:toss_credential_settings"),
        "orders_url": reverse("integrations:toss_order_history"),
    }


def _build_dashboard_context(
    request: HttpRequest,
    *,
    holdings_form: TossDashboardHoldingsForm | None = None,
    orders_form: TossDashboardOrdersForm | None = None,
    live_holdings_preview=None,
    live_holdings_error: str = "",
    live_holdings_message: str = "",
    recent_orders_page=None,
    recent_orders_error: str = "",
    recent_orders_message: str = "",
) -> dict:
    local_summary = _build_local_holdings_summary(request.user)
    return {
        "safe_status": get_credential_safe_status(request.user),
        "local_holdings_summary": local_summary,
        "local_holdings_items": local_summary["items"],
        "recent_activity": _recent_integration_activity(request.user),
        "holdings_form": holdings_form or TossDashboardHoldingsForm(),
        "orders_form": orders_form or TossDashboardOrdersForm(initial={"status": "CLOSED", "limit": "10"}),
        "live_holdings_preview": live_holdings_preview,
        "live_holdings_error": live_holdings_error,
        "live_holdings_message": live_holdings_message,
        "recent_orders_page": recent_orders_page,
        "recent_orders_error": recent_orders_error,
        "recent_orders_message": recent_orders_message,
        "toss_api_calls_enabled": _api_calls_enabled(),
        "holdings_apply_enabled": _holdings_apply_enabled(),
        "dashboard_url": reverse("integrations:toss_dashboard"),
        "settings_url": reverse("integrations:toss_credential_settings"),
        "orders_url": reverse("integrations:toss_order_history"),
        "dashboard_holdings_url": reverse("integrations:toss_dashboard_holdings"),
        "dashboard_orders_url": reverse("integrations:toss_dashboard_orders"),
        "portfolio_summary_url": reverse("portfolio_summary_page"),
        "trading_info_url": reverse("integrations:toss_trading_info"),
        "market_url": reverse("integrations:toss_market_explorer"),
    }


def _build_trading_info_context(
    request: HttpRequest,
    *,
    account_form: TossAccountTradingInfoForm | None = None,
    sellable_form: TossSellableQuantityForm | None = None,
    account_trading_info=None,
    account_trading_info_error: str = "",
    account_trading_info_message: str = "",
    sellable_quantity=None,
    sellable_quantity_error: str = "",
    sellable_quantity_message: str = "",
) -> dict:
    return {
        "account_form": account_form or TossAccountTradingInfoForm(),
        "sellable_form": sellable_form or TossSellableQuantityForm(),
        "account_trading_info": account_trading_info,
        "account_trading_info_error": account_trading_info_error,
        "account_trading_info_message": account_trading_info_message,
        "sellable_quantity": sellable_quantity,
        "sellable_quantity_error": sellable_quantity_error,
        "sellable_quantity_message": sellable_quantity_message,
        "safe_status": get_credential_safe_status(request.user),
        "toss_api_calls_enabled": _api_calls_enabled(),
        "dashboard_url": reverse("integrations:toss_dashboard"),
        "settings_url": reverse("integrations:toss_credential_settings"),
        "orders_url": reverse("integrations:toss_order_history"),
        "account_trading_info_url": reverse("integrations:toss_account_trading_info"),
        "sellable_quantity_url": reverse("integrations:toss_sellable_quantity"),
        "market_url": reverse("integrations:toss_market_explorer"),
    }


def _build_market_context(
    request: HttpRequest,
    *,
    local_search_form: LocalStockSearchForm | None = None,
    local_search_results=None,
    local_search_error: str = "",
    quotes_form: TossStockQuotesForm | None = None,
    quote_batch=None,
    quotes_error: str = "",
    quotes_message: str = "",
    detail_form: TossSymbolDetailForm | None = None,
    symbol_detail=None,
    detail_error: str = "",
    detail_message: str = "",
    candle_form: TossCandleForm | None = None,
    candle_page=None,
    candles_error: str = "",
    candles_message: str = "",
    exchange_rate_form: TossExchangeRateForm | None = None,
    exchange_rate=None,
    exchange_rate_error: str = "",
    exchange_rate_message: str = "",
) -> dict:
    return {
        "local_search_form": local_search_form or LocalStockSearchForm(),
        "local_search_results": local_search_results or [],
        "local_search_error": local_search_error,
        "quotes_form": quotes_form or TossStockQuotesForm(),
        "quote_batch": quote_batch,
        "quotes_error": quotes_error,
        "quotes_message": quotes_message,
        "detail_form": detail_form or TossSymbolDetailForm(initial={"trades_count": "20"}),
        "symbol_detail": symbol_detail,
        "detail_error": detail_error,
        "detail_message": detail_message,
        "candle_form": candle_form or TossCandleForm(initial={"interval": "1d", "count": "50", "adjusted": True}),
        "candle_page": candle_page,
        "candles_error": candles_error,
        "candles_message": candles_message,
        "exchange_rate_form": exchange_rate_form or TossExchangeRateForm(),
        "exchange_rate": exchange_rate,
        "exchange_rate_error": exchange_rate_error,
        "exchange_rate_message": exchange_rate_message,
        "safe_status": get_credential_safe_status(request.user),
        "toss_api_calls_enabled": _api_calls_enabled(),
        "dashboard_url": reverse("integrations:toss_dashboard"),
        "settings_url": reverse("integrations:toss_credential_settings"),
        "orders_url": reverse("integrations:toss_order_history"),
        "trading_info_url": reverse("integrations:toss_trading_info"),
        "market_url": reverse("integrations:toss_market_explorer"),
        "portfolio_summary_url": reverse("portfolio_summary_page"),
        "local_search_url": reverse("integrations:toss_market_local_search"),
        "quotes_url": reverse("integrations:toss_market_quotes"),
        "detail_url": reverse("integrations:toss_market_symbol_detail"),
        "candles_url": reverse("integrations:toss_market_candles"),
        "exchange_rate_url": reverse("integrations:toss_market_exchange_rate"),
    }


def _build_trade_sync_context(
    request: HttpRequest,
    *,
    initial_form: TossTradeSyncForm | None = None,
    incremental_form: TossTradeSyncForm | None = None,
    sync_result=None,
    sync_error: str = "",
    sync_message: str = "",
) -> dict:
    sync_state = None
    state_error = ""
    try:
        if get_credential_safe_status(request.user).get("status") == "active":
            sync_state = get_or_create_sync_state(request.user)
    except TossTradeSyncError:
        state_error = "거래 동기화 상태를 불러오지 못했습니다."
    return {
        "safe_status": get_credential_safe_status(request.user),
        "sync_state": sync_state,
        "state_error": state_error,
        "initial_form": initial_form or TossTradeSyncForm(mode="initial"),
        "incremental_form": incremental_form or TossTradeSyncForm(mode="incremental"),
        "sync_result": sync_result,
        "sync_error": sync_error,
        "sync_message": sync_message,
        "recent_import_records": get_recent_import_records(request.user),
        "toss_api_calls_enabled": _api_calls_enabled(),
        "trade_sync_url": reverse("integrations:toss_trade_sync"),
        "trade_sync_run_url": reverse("integrations:toss_trade_sync_run"),
        "dashboard_url": reverse("integrations:toss_dashboard"),
        "orders_url": reverse("integrations:toss_order_history"),
        "transaction_list_url": reverse("transaction_list"),
        "upload_csv_url": reverse("upload_csv"),
        "settings_url": reverse("integrations:toss_credential_settings"),
    }


def _build_local_holdings_summary(user) -> dict[str, object]:
    holdings = list(
        UserHolding.objects.filter(user=user, is_active=True)
        .select_related("stock")
        .order_by("-updated_at", "-id")[:10]
    )
    total_count = UserHolding.objects.filter(user=user, is_active=True).count()
    total_purchase_basis = Decimal("0")
    items = []
    for holding in holdings:
        invested = holding.total_invested_amount
        total_purchase_basis += invested
        items.append(
            {
                "code": holding.stock.code,
                "name": holding.stock.name,
                "quantity": holding.quantity,
                "average_price": holding.average_price,
                "purchase_basis": invested,
                "updated_at": holding.updated_at,
            }
        )
    if total_count > len(holdings):
        for holding in UserHolding.objects.filter(user=user, is_active=True).select_related("stock")[10:]:
            total_purchase_basis += holding.total_invested_amount
    return {
        "count": total_count,
        "total_purchase_basis": total_purchase_basis,
        "items": items,
    }


def _recent_integration_activity(user):
    return list(
        IntegrationAuditLog.objects.filter(Q(target_user=user) | Q(actor=user))
        .order_by("-created_at")[:10]
    )
