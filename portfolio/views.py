import csv
import json
import re
from urllib.parse import urlencode
from decimal import Decimal
from pathlib import Path
from statistics import mean

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from data_pipeline.models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot
from holdings.models import UserHolding
from data_pipeline.services.summary_service import build_data_pipeline_summary
from holdings.services.sync_service import sync_all_holdings_for_legacy_user
from marketdata.models import StockDataCollectionStatus
from marketdata.services.collection_status_service import get_collection_status_snapshot
from marketdata.services.price_service import get_latest_price
from stocks.models import FinancialSnapshot, Stock

from .forms import CSVUploadForm, StockSymbolForm, SymbolResolveForm, TransactionForm
from .models import StockSymbol, Transaction
from .services import (
    build_historical_buy_timing_analysis,
    build_historical_buy_timing_rankings,
    build_holdings_analysis,
    build_portfolio_summary,
    build_realized_profit_analysis,
    get_price_board,
    get_symbol_usage,
    get_unmapped_stock_names,
    load_csv_file,
    seed_default_symbols,
    summarize_transactions,
    upsert_symbol_mapping,
)
from .serializers import PortfolioSummarySerializer


RETROSPECTIVE_FILTER_OPTIONS = [
    ("all", "전체"),
    ("good", "잘한 매수"),
    ("neutral", "보통 매수"),
    ("bad", "아쉬운 매수"),
    ("pending", "판단 보류"),
]

RETROSPECTIVE_RANKING_SORT_OPTIONS = [
    ("score", "평균 회고 점수"),
    ("consistency", "실행 일관성"),
    ("good_ratio", "좋은 매수 비율"),
    ("return_20", "평균 20일 성과"),
]

MANUAL_DOC_ROOT = Path(settings.BASE_DIR) / "docs"
MANUAL_GROUPS = [
    ("current", "Current State", ("26_", "37_", "38_", "39_", "42_", "44_", "46_", "47_", "49_", "50_", "51_", "52_", "53_")),
    ("portfolio", "Portfolio / Simulation", ("31_", "33_", "34_", "35_", "36_", "40_", "41_", "43_")),
    ("operations", "Operations / Data", ("22_", "23_", "27_", "28_", "29_", "45_", "48_")),
    ("design", "Design Docs", ("01_", "02_", "03_", "04_", "05_", "06_", "07_", "08_", "09_", "10_", "11_", "13_", "14_", "16_", "18_", "20_")),
    ("prompts", "Codex Prompts", ("codex_prompts/",)),
]


def _is_truthy_query_param(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _manual_document_options():
    if not MANUAL_DOC_ROOT.exists():
        return []

    options = []
    for path in sorted(MANUAL_DOC_ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        relative = path.relative_to(MANUAL_DOC_ROOT).as_posix()
        if relative.startswith("toss_OpenAPI_guide/"):
            continue
        title = _manual_title(path, relative)
        group = _manual_group_for(relative)
        options.append(
            {
                "value": relative,
                "label": title,
                "stage": group["value"],
                "stage_label": group["label"],
                "path": path,
            }
        )
    return options


def _manual_group_for(relative_path):
    for value, label, prefixes in MANUAL_GROUPS:
        if any(relative_path.startswith(prefix) for prefix in prefixes):
            return {"value": value, "label": label}
    return {"value": "other", "label": "Other Docs"}


def _manual_title(path, relative_path):
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            clean = line.strip()
            if clean.startswith("#"):
                return clean.lstrip("#").strip() or path.stem
            if clean:
                break
    except OSError:
        pass
    return Path(relative_path).stem.replace("_", " ")


def _manual_grouped_options(options):
    groups = []
    all_groups = [(value, label) for value, label, _prefixes in MANUAL_GROUPS] + [("other", "Other Docs")]
    for value, label in all_groups:
        files = [option for option in options if option["stage"] == value]
        if files:
            groups.append({"value": value, "label": label, "files": files})
    return groups


def _manual_read_doc(relative_path):
    clean = str(relative_path or "").strip()
    if not clean:
        raise Http404("Manual document not found.")
    candidate = (MANUAL_DOC_ROOT / clean).resolve()
    try:
        candidate.relative_to(MANUAL_DOC_ROOT.resolve())
    except ValueError as exc:
        raise Http404("Manual document not found.") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in {".md", ".txt"}:
        raise Http404("Manual document not found.")
    if candidate.relative_to(MANUAL_DOC_ROOT).as_posix().startswith("toss_OpenAPI_guide/"):
        raise Http404("Manual document not found.")
    return candidate.read_text(encoding="utf-8", errors="replace")


def _manual_markdown_to_html(text):
    html_parts = []
    in_list = False
    in_code = False
    code_lines = []

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                html_parts.append(f'<pre class="manual-pre"><code>{escape(chr(10).join(code_lines))}</code></pre>')
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            close_list()
            continue
        if stripped.startswith("#"):
            close_list()
            level = min(3, len(stripped) - len(stripped.lstrip("#")))
            title = stripped.lstrip("#").strip()
            html_parts.append(f"<h{level}>{escape(title)}</h{level}>")
            continue
        if stripped.startswith(("- ", "* ")):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_manual_inline(stripped[2:].strip())}</li>")
            continue
        close_list()
        html_parts.append(f"<p>{_manual_inline(stripped)}</p>")

    if in_code:
        html_parts.append(f'<pre class="manual-pre"><code>{escape(chr(10).join(code_lines))}</code></pre>')
    close_list()
    return mark_safe("\n".join(html_parts))


def _manual_inline(text):
    safe = escape(text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)


def _manual_search(options, query):
    clean_query = str(query or "").strip().lower()
    if not clean_query:
        return []
    results = []
    for option in options:
        try:
            text = option["path"].read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lower = text.lower()
        index = lower.find(clean_query)
        if index == -1 and clean_query not in option["label"].lower():
            continue
        start = max(0, index - 80) if index >= 0 else 0
        end = min(len(text), index + len(clean_query) + 160) if index >= 0 else 180
        excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
        results.append(
            {
                "title": option["label"],
                "relative_path": option["value"],
                "stage_label": option["stage_label"],
                "excerpt": excerpt,
            }
        )
        if len(results) >= 30:
            break
    return results


class PortfolioSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        include_inactive = _is_truthy_query_param(request.query_params.get("include_inactive"))
        summary = build_portfolio_summary(request.user, include_inactive=include_inactive)
        serializer = PortfolioSummarySerializer(summary)
        return Response(serializer.data)


@login_required
def portfolio_summary_page(request):
    include_inactive = _is_truthy_query_param(request.GET.get("include_inactive"))
    summary = build_portfolio_summary(request.user, include_inactive=include_inactive)
    return render(
        request,
        "portfolio/summary.html",
        {
            "summary": summary,
            "include_inactive": include_inactive,
        },
    )


@login_required
def manual_page(request, doc_path=None):
    options = _manual_document_options()
    selected_path = doc_path or request.GET.get("doc") or (options[0]["value"] if options else "")
    current_stage = request.GET.get("stage") or ""
    search_query = request.GET.get("q", "")

    current_doc = None
    if selected_path:
        option = next((item for item in options if item["value"] == selected_path), None)
        if option is None:
            raise Http404("Manual document not found.")
        raw_text = _manual_read_doc(selected_path)
        current_doc = {
            "title": option["label"],
            "relative_path": option["value"],
            "stage_label": option["stage_label"],
            "html_content": _manual_markdown_to_html(raw_text),
        }
        current_stage = current_stage or option["stage"]

    grouped = _manual_grouped_options(options)
    stage_options = [{"value": "", "label": "All Groups"}] + [
        {"value": group["value"], "label": group["label"]} for group in grouped
    ]
    current_stage_files = [
        option for option in options if not current_stage or option["stage"] == current_stage
    ] or options

    return render(
        request,
        "portfolio/manual.html",
        {
            "manual_stats": {"document_count": len(options), "stage_count": len(grouped)},
            "manual_stage_options": stage_options,
            "manual_stage_groups": grouped,
            "current_stage": current_stage,
            "current_stage_files": current_stage_files,
            "selected_doc_path": selected_path,
            "current_doc": current_doc,
            "search_query": search_query,
            "search_results": _manual_search(options, search_query),
        },
    )


@login_required
def manual_raw(request, doc_path):
    return HttpResponse(_manual_read_doc(doc_path), content_type="text/plain; charset=utf-8")


def _notify_holding_sync_result(request, report):
    summary_parts = []
    if report.created_count:
        summary_parts.append(f'생성 {report.created_count}건')
    if report.updated_count:
        summary_parts.append(f'갱신 {report.updated_count}건')
    if report.deactivated_count:
        summary_parts.append(f'비활성화 {report.deactivated_count}건')
    if summary_parts:
        messages.info(request, f'보유 원장 동기화: {", ".join(summary_parts)}')
    if report.unresolved_names:
        names = ", ".join(sorted(set(report.unresolved_names))[:5])
        suffix = "" if len(set(report.unresolved_names)) <= 5 else " 외"
        messages.warning(request, f'보유 원장 동기화에서 종목 매핑 실패: {names}{suffix}')
    if report.warnings:
        messages.warning(request, report.warnings[0])


def _format_currency(value):
    if value is None:
        return "데이터 없음"
    return f"{value:,.0f}원"


def _format_percent(value):
    if value is None:
        return "데이터 없음"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _format_day_average(value):
    if value is None:
        return "-"
    return f"{value:.1f}일"


def _calculate_loss_rate(average_price, current_price):
    if current_price is None or not average_price:
        return None
    return (((current_price - average_price) / average_price) * Decimal("100")).quantize(Decimal("0.01"))


def _build_retrospective_insights(filtered_evaluations, selected_filter):
    if not filtered_evaluations:
        return {
            "headline": "현재 필터에서는 해석할 매수 사례가 없습니다.",
            "average_return_20_display": "-",
            "average_max_drawdown_20_display": "-",
            "dominant_entry_context": "-",
            "best_case_summary": "",
            "worst_case_summary": "",
        }

    return_20_values = [row["return_20"] for row in filtered_evaluations if row["return_20"] is not None]
    drawdown_values = [
        row["max_drawdown_20"] for row in filtered_evaluations
        if row["max_drawdown_20"] is not None
    ]
    context_counts = {}
    for row in filtered_evaluations:
        context_counts[row["entry_context"]] = context_counts.get(row["entry_context"], 0) + 1
    dominant_entry_context = max(context_counts.items(), key=lambda item: (item[1], item[0]))[0]

    average_return_20 = round(mean(return_20_values), 2) if return_20_values else None
    average_max_drawdown_20 = round(mean(drawdown_values), 2) if drawdown_values else None
    best_case = max(
        filtered_evaluations,
        key=lambda row: row["return_20"] if row["return_20"] is not None else float("-inf"),
    )
    worst_case = min(
        filtered_evaluations,
        key=lambda row: row["max_drawdown_20"] if row["max_drawdown_20"] is not None else float("inf"),
    )

    if selected_filter == "good":
        headline = "좋았던 추가 매수는 반등 초입이나 눌림 구간에서 이뤄진 경우가 많았습니다."
    elif selected_filter == "bad":
        headline = "아쉬운 추가 매수는 이후 20거래일 동안 약세가 이어진 사례가 많았습니다."
    elif selected_filter == "pending":
        headline = "판단 보류 매수는 아직 후행 가격 이력이 부족해 성급한 해석을 피해야 합니다."
    elif average_return_20 is not None and average_return_20 >= 3:
        headline = "전체적으로는 추가 매수 타이밍이 나쁘지 않았고, 평균적으로 20거래일 후 성과가 플러스였습니다."
    elif average_return_20 is not None and average_return_20 <= -3:
        headline = "전체적으로는 추가 매수 타이밍을 더 보수적으로 잡을 필요가 있습니다."
    else:
        headline = "추가 매수 성과가 엇갈려서 구간별 패턴을 함께 보는 것이 좋습니다."

    best_case_summary = (
        f"가장 좋았던 사례는 {best_case['traded_at']} {best_case['entry_context']}로 "
        f"20거래일 후 {best_case['return_20_display']}였습니다."
        if best_case["return_20"] is not None
        else ""
    )
    worst_case_summary = (
        f"가장 힘들었던 사례는 {worst_case['traded_at']} {worst_case['entry_context']}로 "
        f"20일 최대 낙폭이 {worst_case['max_drawdown_20_display']}였습니다."
        if worst_case["max_drawdown_20"] is not None
        else ""
    )

    return {
        "headline": headline,
        "average_return_20_display": _format_percent(average_return_20),
        "average_max_drawdown_20_display": _format_percent(average_max_drawdown_20),
        "dominant_entry_context": dominant_entry_context,
        "best_case_summary": best_case_summary,
        "worst_case_summary": worst_case_summary,
    }


def _build_retrospective_reason_breakdown(filtered_evaluations):
    if not filtered_evaluations:
        return []

    reason_groups = {}
    total_count = len(filtered_evaluations)
    for row in filtered_evaluations:
        key = row["evaluation_reason_key"]
        group = reason_groups.setdefault(
            key,
            {
                "label": row["evaluation_reason_label"],
                "count": 0,
                "examples": [],
            },
        )
        group["count"] += 1
        if len(group["examples"]) < 2:
            group["examples"].append(
                f"{row['traded_at']} {row['entry_context']} / 20일 {row['return_20_display']}"
            )

    breakdown_rows = []
    for group in reason_groups.values():
        ratio = round((group["count"] / total_count) * 100, 1) if total_count else 0
        breakdown_rows.append(
            {
                "label": group["label"],
                "count": group["count"],
                "ratio_display": _format_percent(ratio),
                "examples": group["examples"],
            }
        )

    return sorted(breakdown_rows, key=lambda row: (-row["count"], row["label"]))


def _build_retrospective_execution_quality(filtered_evaluations):
    if not filtered_evaluations:
        return {
            "headline": "현재 필터에서는 실행 품질을 계산할 매수 사례가 없습니다.",
            "average_pre_avg_gap_display": "-",
            "average_break_even_display": "-",
            "average_peak_display": "-",
        }

    pre_avg_gap_values = [
        row["pre_avg_gap_pct"] for row in filtered_evaluations
        if row["pre_avg_gap_pct"] is not None
    ]
    break_even_values = [
        row["days_to_break_even_20"] for row in filtered_evaluations
        if row["days_to_break_even_20"] is not None
    ]
    peak_values = [
        row["days_to_peak_20"] for row in filtered_evaluations
        if row["days_to_peak_20"] is not None
    ]
    trough_values = [
        row["days_to_trough_20"] for row in filtered_evaluations
        if row["days_to_trough_20"] is not None
    ]
    trough_gap_values = [
        row["distance_to_trough_20"] for row in filtered_evaluations
        if row["distance_to_trough_20"] is not None
    ]
    pre_buy_decline_values = [
        row["pre_buy_return_5"] for row in filtered_evaluations
        if row["pre_buy_return_5"] is not None
    ]
    timing_score_values = [row["timing_score"] for row in filtered_evaluations if row["timing_score"] is not None]

    average_pre_avg_gap = round(mean(pre_avg_gap_values), 2) if pre_avg_gap_values else None
    average_break_even = round(mean(break_even_values), 1) if break_even_values else None
    average_peak = round(mean(peak_values), 1) if peak_values else None
    average_trough = round(mean(trough_values), 1) if trough_values else None
    average_trough_gap = round(mean(trough_gap_values), 2) if trough_gap_values else None
    average_pre_buy_decline = round(mean(pre_buy_decline_values), 2) if pre_buy_decline_values else None
    average_timing_score = round(mean(timing_score_values), 1) if timing_score_values else None

    if average_timing_score is not None and average_timing_score >= 75:
        headline = "종합 회고 점수가 높아, 전체적으로는 진입 가격과 회복 속도가 모두 양호했습니다."
    elif average_trough_gap is not None and average_trough_gap <= 3 and average_break_even is not None and average_break_even <= 7:
        headline = "대체로 저점에 가깝게 들어갔고, 이후 회복 속도도 빨랐습니다."
    elif average_pre_avg_gap is not None and average_pre_avg_gap <= -5 and average_break_even is not None and average_break_even <= 7:
        headline = "대체로 이전 평단보다 충분히 낮은 가격에서 매수했고, 손익분기 회복도 빨랐습니다."
    elif average_timing_score is not None and average_timing_score <= 45:
        headline = "종합 회고 점수가 낮아, 진입 시점과 회복 속도를 모두 더 보수적으로 볼 필요가 있습니다."
    elif average_pre_avg_gap is not None and average_pre_avg_gap > 0 and average_break_even is None:
        headline = "이전 평단보다 높은 추격 매수가 많았고, 20거래일 안에 손익분기를 회복하지 못한 사례가 많았습니다."
    elif average_trough_gap is not None and average_trough_gap >= 10:
        headline = "매수 후에도 저점까지 추가 하락 여지가 컸던 편이라, 너무 이른 진입이 반복됐을 가능성이 있습니다."
    elif average_break_even is not None and average_break_even <= 5:
        headline = "매수 후 반등 속도가 빨라 단기 회복이 양호했습니다."
    elif average_break_even is not None and average_break_even >= 12:
        headline = "매수 후 손익분기 회복까지 시간이 오래 걸려 진입 타이밍을 더 보수적으로 볼 필요가 있습니다."
    else:
        headline = "실행 품질은 구간마다 달랐고, 평단 대비 진입 가격과 회복 속도를 함께 보는 것이 좋습니다."

    return {
        "headline": headline,
        "average_timing_score_display": "-" if average_timing_score is None else f"{average_timing_score:.1f}점",
        "average_pre_buy_decline_display": _format_percent(average_pre_buy_decline),
        "average_pre_avg_gap_display": _format_percent(average_pre_avg_gap),
        "average_trough_gap_display": _format_percent(average_trough_gap),
        "average_trough_display": _format_day_average(average_trough),
        "average_break_even_display": _format_day_average(average_break_even),
        "average_peak_display": _format_day_average(average_peak),
    }


def _decorate_retrospective_scores(filtered_evaluations):
    decorated_rows = []
    for row in filtered_evaluations:
        if row["timing_score"] >= 80:
            score_bar_class = "bg-success"
        elif row["timing_score"] >= 65:
            score_bar_class = "bg-info"
        elif row["timing_score"] >= 45:
            score_bar_class = "bg-warning"
        else:
            score_bar_class = "bg-danger"
        decorated_rows.append(
            {
                **row,
                "score_bar_width": max(4, row["timing_score"]),
                "score_bar_class": score_bar_class,
            }
        )
    return decorated_rows


def _build_retrospective_score_comparison(filtered_evaluations):
    if not filtered_evaluations:
        return {"best_case": None, "worst_case": None}

    best_case = max(filtered_evaluations, key=lambda row: (row["timing_score"], row["traded_at"]))
    worst_case = min(filtered_evaluations, key=lambda row: (row["timing_score"], row["traded_at"]))
    return {
        "best_case": best_case,
        "worst_case": worst_case,
    }


def _build_retrospective_ranking_highlights(rankings):
    if not rankings:
        return []

    scored_rankings = [row for row in rankings if row["average_timing_score"] is not None]
    if not scored_rankings:
        return []

    fastest_recovery_candidates = [
        row for row in scored_rankings
        if row["average_break_even_days"] is not None
    ]
    trough_gap_candidates = [
        row for row in scored_rankings
        if row["average_trough_gap"] is not None
    ]
    consistency_candidates = [
        row for row in scored_rankings
        if row["timing_score_stddev"] is not None
    ]
    caution_candidates = [
        row for row in scored_rankings
        if row["bad_count"] > 0 or (row["average_timing_score"] is not None and row["average_timing_score"] < 50)
    ]

    top_score = max(scored_rankings, key=lambda row: (row["average_timing_score"], row["good_count"], -row["bad_count"]))
    fastest_recovery = (
        min(fastest_recovery_candidates, key=lambda row: (row["average_break_even_days"], -row["average_timing_score"]))
        if fastest_recovery_candidates else None
    )
    trough_leader = (
        min(trough_gap_candidates, key=lambda row: (row["average_trough_gap"], -row["average_timing_score"]))
        if trough_gap_candidates else None
    )
    consistency_leader = (
        min(consistency_candidates, key=lambda row: (row["timing_score_stddev"], -row["average_timing_score"]))
        if consistency_candidates else None
    )
    caution_stock = (
        max(caution_candidates, key=lambda row: (row["bad_count"], -(row["average_timing_score"] or 0), row["stock_name"]))
        if caution_candidates else None
    )

    highlights = [
        {
            "title": "평균 점수 최고",
            "stock_name": top_score["stock_name"],
            "metric": top_score["average_timing_score_display"],
            "detail": f"평균 20일 성과 {top_score['average_return_20_display']} / 잘한 매수 {top_score['good_count']}건 / 신뢰도 {top_score['confidence_label']}",
            "tone_class": "text-success",
        }
    ]
    if fastest_recovery:
        highlights.append(
            {
                "title": "회복이 가장 빨랐던 종목",
                "stock_name": fastest_recovery["stock_name"],
                "metric": fastest_recovery["average_break_even_days_display"],
                "detail": f"평균 회고 점수 {fastest_recovery['average_timing_score_display']} / 평가 완료 {fastest_recovery['scored_buy_count']}건 / 신뢰도 {fastest_recovery['confidence_label']}",
                "tone_class": "text-primary",
            }
        )
    if trough_leader:
        highlights.append(
            {
                "title": "저점 근접도가 좋았던 종목",
                "stock_name": trough_leader["stock_name"],
                "metric": trough_leader["average_trough_gap_display"],
                "detail": f"매수 후 평균 추가 하락폭 / 평균 점수 {trough_leader['average_timing_score_display']} / 신뢰도 {trough_leader['confidence_label']}",
                "tone_class": "text-info",
            }
        )
    if consistency_leader:
        highlights.append(
            {
                "title": "실행 일관성이 좋았던 종목",
                "stock_name": consistency_leader["stock_name"],
                "metric": consistency_leader["timing_score_stddev_display"],
                "detail": f"점수 편차가 작았던 종목 / 평균 점수 {consistency_leader['average_timing_score_display']} / 일관성 {consistency_leader['consistency_label']}",
                "tone_class": "text-dark",
            }
        )
    if caution_stock:
        highlights.append(
            {
                "title": "가장 어려웠던 종목",
                "stock_name": caution_stock["stock_name"],
                "metric": caution_stock["average_timing_score_display"],
                "detail": f"아쉬운 매수 {caution_stock['bad_count']}건 / 평균 20일 성과 {caution_stock['average_return_20_display']} / 신뢰도 {caution_stock['confidence_label']}",
                "tone_class": "text-danger",
            }
        )
    return highlights


def _sort_retrospective_rankings(rankings, selected_sort):
    allowed_sorts = {value for value, _label in RETROSPECTIVE_RANKING_SORT_OPTIONS}
    effective_sort = selected_sort if selected_sort in allowed_sorts else "score"

    def _score_sort_key(row):
        return (
            row["average_timing_score"] is None,
            -(row["average_timing_score"] if row["average_timing_score"] is not None else -1),
            -row["good_count"],
            row["bad_count"],
            row["stock_name"],
        )

    def _consistency_sort_key(row):
        return (
            row["timing_score_stddev"] is None,
            row["timing_score_stddev"] if row["timing_score_stddev"] is not None else float("inf"),
            -(row["average_timing_score"] if row["average_timing_score"] is not None else -1),
            row["stock_name"],
        )

    def _good_ratio_sort_key(row):
        return (
            row["good_ratio"] is None,
            -(row["good_ratio"] if row["good_ratio"] is not None else -1),
            -(row["average_timing_score"] if row["average_timing_score"] is not None else -1),
            row["stock_name"],
        )

    def _return_20_sort_key(row):
        return (
            row["average_return_20"] is None,
            -(row["average_return_20"] if row["average_return_20"] is not None else -9999),
            -(row["average_timing_score"] if row["average_timing_score"] is not None else -1),
            row["stock_name"],
        )

    sort_key_map = {
        "score": _score_sort_key,
        "consistency": _consistency_sort_key,
        "good_ratio": _good_ratio_sort_key,
        "return_20": _return_20_sort_key,
    }
    return sorted(rankings, key=sort_key_map[effective_sort]), effective_sort


def _build_retrospective_ranking_comparison(rankings, selected_sort):
    if not rankings or selected_sort == "score":
        return None

    current_top = rankings[0]
    score_rankings, _effective_sort = _sort_retrospective_rankings(list(rankings), "score")
    if not score_rankings:
        return None
    score_top = score_rankings[0]
    if current_top["stock_name"] == score_top["stock_name"]:
        return None

    detail_map = {
        "consistency": (
            f"{current_top['stock_name']}는 점수 편차가 {current_top['timing_score_stddev_display']}로 더 작아 "
            f"실행 품질이 더 안정적이었습니다. 반면 평균 점수 자체는 {score_top['stock_name']}가 "
            f"{score_top['average_timing_score_display']}로 가장 높았습니다."
        ),
        "good_ratio": (
            f"{current_top['stock_name']}는 좋은 매수 비율이 {current_top['good_ratio_display']}로 더 높았습니다. "
            f"반면 평균 회고 점수 자체는 {score_top['stock_name']}가 {score_top['average_timing_score_display']}로 앞섰습니다."
        ),
        "return_20": (
            f"{current_top['stock_name']}는 평균 20거래일 성과가 {current_top['average_return_20_display']}로 더 좋았습니다. "
            f"반면 평균 회고 점수 자체는 {score_top['stock_name']}가 {score_top['average_timing_score_display']}로 가장 높았습니다."
        ),
    }

    title_map = {
        "consistency": "일관성 1위와 평균 점수 1위가 다릅니다.",
        "good_ratio": "좋은 매수 비율 1위와 평균 점수 1위가 다릅니다.",
        "return_20": "평균 20일 성과 1위와 평균 점수 1위가 다릅니다.",
    }

    return {
        "title": title_map[selected_sort],
        "current_top_name": current_top["stock_name"],
        "current_top_metric": {
            "consistency": current_top["timing_score_stddev_display"],
            "good_ratio": current_top["good_ratio_display"],
            "return_20": current_top["average_return_20_display"],
        }[selected_sort],
        "score_top_name": score_top["stock_name"],
        "score_top_metric": score_top["average_timing_score_display"],
        "detail": detail_map[selected_sort],
    }


def _build_retrospective_ranking_leader_names(rankings):
    if not rankings:
        return {}

    scored_rankings = [row for row in rankings if row["average_timing_score"] is not None]
    if not scored_rankings:
        return {}

    def _pick_max(rows, field_name, tie_field="average_timing_score"):
        candidates = [row for row in rows if row[field_name] is not None]
        if not candidates:
            return ""
        return max(
            candidates,
            key=lambda row: (
                row[field_name],
                row[tie_field] if row[tie_field] is not None else -1,
                row["stock_name"],
            ),
        )["stock_name"]

    def _pick_min(rows, field_name, tie_field="average_timing_score"):
        candidates = [row for row in rows if row[field_name] is not None]
        if not candidates:
            return ""
        return min(
            candidates,
            key=lambda row: (
                row[field_name],
                -(row[tie_field] if row[tie_field] is not None else -1),
                row["stock_name"],
            ),
        )["stock_name"]

    return {
        "score_top": _pick_max(scored_rankings, "average_timing_score"),
        "consistency_top": _pick_min(scored_rankings, "timing_score_stddev"),
        "good_ratio_top": _pick_max(scored_rankings, "good_ratio"),
        "return_20_top": _pick_max(scored_rankings, "average_return_20"),
        "recovery_top": _pick_min(scored_rankings, "average_break_even_days"),
        "trough_top": _pick_min(scored_rankings, "average_trough_gap"),
    }


def _export_retrospective_rankings_csv(rankings, selected_sort):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="retrospective_rankings_{selected_sort}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "순위",
            "종목",
            "종목코드",
            "시장",
            "평균 회고 점수",
            "좋은 매수 비율",
            "평균 20일 성과",
            "평균 손익분기 도달일",
            "평균 저점 대비 추가 하락",
            "점수 편차",
            "신뢰도",
            "일관성",
            "잘한 매수",
            "아쉬운 매수",
            "평가 완료",
            "전체 매수",
            "정렬 기준",
        ]
    )
    for index, row in enumerate(rankings, start=1):
        writer.writerow(
            [
                index,
                row["stock_name"],
                row["stock_code"],
                row["stock_market"],
                row["average_timing_score_display"],
                row["good_ratio_display"],
                row["average_return_20_display"],
                row["average_break_even_days_display"],
                row["average_trough_gap_display"],
                row["timing_score_stddev_display"],
                row["confidence_label"],
                row["consistency_label"],
                row["good_count"],
                row["bad_count"],
                row["scored_buy_count"],
                row["buy_count"],
                selected_sort,
            ]
        )
    return response


def _export_retrospective_details_csv(retrospective, selected_filter):
    stock_name = retrospective.get("stock_name", "retrospective")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="retrospective_details_{stock_name}_{selected_filter}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(
        [
            "매수시각",
            "매수 구분",
            "판정",
            "판정 사유",
            "타이밍 점수",
            "점수 등급",
            "수량",
            "매수가",
            "매수 전 평단",
            "매수 후 평단",
            "매수 직전 5일 등락률",
            "5일 후 수익률",
            "20일 후 수익률",
            "60일 후 수익률",
            "20일 최대상승",
            "20일 최대하락",
            "저점까지 추가 하락",
            "저점 도달일",
            "손익분기 도달일",
            "최고점 도달일",
            "데이터 비고",
            "필터",
        ]
    )
    for row in retrospective["filtered_evaluations"]:
        writer.writerow(
            [
                row["traded_at"],
                row["entry_context"],
                row["evaluation_label"],
                row["evaluation_reason_label"],
                row["timing_score_display"],
                row["timing_score_label"],
                row["quantity"],
                row["unit_price_display"],
                row["pre_avg_price_display"],
                row["post_avg_price_display"],
                row["pre_buy_return_5_display"],
                row["return_5_display"],
                row["return_20_display"],
                row["return_60_display"],
                row["max_gain_20_display"],
                row["max_drawdown_20_display"],
                row["distance_to_trough_20_display"],
                row["days_to_trough_20_display"],
                row["days_to_break_even_20_display"],
                row["days_to_peak_20_display"],
                row["data_note"],
                selected_filter,
            ]
        )
    return response


def _apply_retrospective_filter(retrospective, selected_filter):
    allowed_filters = {value for value, _label in RETROSPECTIVE_FILTER_OPTIONS}
    effective_filter = selected_filter if selected_filter in allowed_filters else "all"
    filtered_evaluations = retrospective["evaluations"]
    if effective_filter != "all":
        filtered_evaluations = [
            row for row in retrospective["evaluations"]
            if row["evaluation_category"] == effective_filter
        ]

    overview_chart = dict(retrospective["overview_chart"])
    if overview_chart.get("available"):
        overview_chart["markers"] = [
            marker for marker in overview_chart["markers"]
            if effective_filter == "all" or marker["category"] == effective_filter
        ]

    decorated_rows = _decorate_retrospective_scores(filtered_evaluations)

    return {
        **retrospective,
        "selected_filter": effective_filter,
        "filter_options": RETROSPECTIVE_FILTER_OPTIONS,
        "filtered_count": len(decorated_rows),
        "filtered_evaluations": decorated_rows,
        "overview_chart": overview_chart,
        "insights": _build_retrospective_insights(decorated_rows, effective_filter),
        "reason_breakdown": _build_retrospective_reason_breakdown(decorated_rows),
        "execution_quality": _build_retrospective_execution_quality(decorated_rows),
        "score_comparison": _build_retrospective_score_comparison(decorated_rows),
    }


def _build_holding_consult_summary(holding):
    latest_price = get_latest_price(holding.stock)
    current_price = getattr(latest_price, "close_price", None)
    current_price_date = getattr(latest_price, "date", None)
    loss_rate = _calculate_loss_rate(holding.average_price, current_price)
    is_consultable = holding.is_active and holding.quantity > 0
    return {
        "holding": holding,
        "current_price": current_price,
        "current_price_date": current_price_date,
        "loss_rate": loss_rate,
        "is_consultable": is_consultable,
        "average_price_display": _format_currency(holding.average_price),
        "current_price_display": _format_currency(current_price),
        "loss_rate_display": _format_percent(loss_rate),
        "max_additional_budget_display": _format_currency(holding.max_additional_budget),
        "total_invested_amount_display": _format_currency(holding.total_invested_amount),
    }


def landing_page(request):
    return render(request, "portfolio/landing.html")


def dashboard(request):
    seed_default_symbols()
    stats = summarize_transactions()
    recent = Transaction.objects.all()[:10]
    context = {
        'tx_count': Transaction.objects.count(),
        'stock_count': Transaction.objects.values('stock_name').distinct().count(),
        'symbol_count': StockSymbol.objects.count(),
        'unmapped_count': len(get_unmapped_stock_names()),
        'recent': recent,
        'stats_json': json.dumps(stats, ensure_ascii=False),
    }
    return render(request, 'portfolio/dashboard.html', context)


def transaction_list(request):
    qs = Transaction.objects.all()
    q = request.GET.get('q', '').strip()
    trade_type = request.GET.get('trade_type', '').strip()
    year = request.GET.get('year', '').strip()

    if q:
        qs = qs.filter(stock_name__icontains=q)
    if trade_type:
        qs = qs.filter(trade_type=trade_type)
    if year:
        try:
            qs = qs.filter(year=int(year))
        except ValueError:
            messages.error(request, '년 필터가 올바르지 않습니다.')

    paginator = Paginator(qs, 30)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'portfolio/transaction_list.html', {
        'page_obj': page_obj,
        'q': q,
        'trade_type': trade_type,
        'year': year,
    })


def upload_csv(request):
    if request.method == 'POST':
        form = CSVUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    count = load_csv_file(form.cleaned_data['csv_file'])
                    report = sync_all_holdings_for_legacy_user()
                messages.success(request, f'{count}건을 업로드했습니다.')
                _notify_holding_sync_result(request, report)
                return redirect('transaction_list')
            except Exception as exc:
                messages.error(request, f'업로드 실패: {exc}')
    else:
        form = CSVUploadForm()
    return render(request, 'portfolio/upload.html', {'form': form})


def transaction_create(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                    report = sync_all_holdings_for_legacy_user()
                messages.success(request, '거래를 등록했습니다.')
                _notify_holding_sync_result(request, report)
                return redirect('transaction_list')
            except Exception as exc:
                messages.error(request, f'거래 등록 실패: {exc}')
    else:
        form = TransactionForm()
    return render(request, 'portfolio/transaction_create.html', {'form': form})


def transaction_edit(request, pk):
    tx = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=tx)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                    report = sync_all_holdings_for_legacy_user()
                messages.success(request, '거래를 수정했습니다.')
                _notify_holding_sync_result(request, report)
                return redirect('transaction_list')
            except Exception as exc:
                messages.error(request, f'거래 수정 실패: {exc}')
    else:
        form = TransactionForm(instance=tx)
    return render(request, 'portfolio/transaction_edit.html', {'form': form, 'tx': tx})


def transaction_delete(request, pk):
    tx = get_object_or_404(Transaction, pk=pk)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                tx.delete()
                report = sync_all_holdings_for_legacy_user()
            messages.success(request, '거래를 삭제했습니다.')
            _notify_holding_sync_result(request, report)
            return redirect('transaction_list')
        except Exception as exc:
            messages.error(request, f'거래 삭제 실패: {exc}')
    return render(request, 'portfolio/transaction_delete.html', {'tx': tx})


def symbol_list(request):
    seed_default_symbols()
    query = request.GET.get('q', '').strip()
    rows = get_symbol_usage()
    if query:
        rows = [row for row in rows if query.lower() in row['stock_name'].lower() or query.lower() in row['ticker'].lower()]
    context = {
        'rows': rows,
        'q': query,
        'create_form': StockSymbolForm(),
        'unmapped_names': get_unmapped_stock_names(),
    }
    return render(request, 'portfolio/symbol_list.html', context)


def symbol_create(request):
    if request.method != 'POST':
        return redirect('symbol_list')
    form = StockSymbolForm(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():
                form.save()
                report = sync_all_holdings_for_legacy_user()
            messages.success(request, '종목명↔티커 매핑을 추가했습니다.')
            _notify_holding_sync_result(request, report)
        except Exception as exc:
            messages.error(request, f'티커 매핑 추가 실패: {exc}')
    else:
        messages.error(request, form.errors.as_text())
    return redirect('symbol_list')


def symbol_edit(request, pk):
    symbol = get_object_or_404(StockSymbol, pk=pk)
    if request.method == 'POST':
        form = StockSymbolForm(request.POST, instance=symbol)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
                    report = sync_all_holdings_for_legacy_user()
                messages.success(request, '티커 매핑을 수정했습니다.')
                _notify_holding_sync_result(request, report)
                return redirect('symbol_list')
            except Exception as exc:
                messages.error(request, f'티커 매핑 수정 실패: {exc}')
    else:
        form = StockSymbolForm(instance=symbol)
    return render(request, 'portfolio/symbol_edit.html', {'form': form, 'symbol': symbol})


def symbol_delete(request, pk):
    symbol = get_object_or_404(StockSymbol, pk=pk)
    if request.method == 'POST':
        try:
            with transaction.atomic():
                symbol.delete()
                report = sync_all_holdings_for_legacy_user()
            messages.success(request, '티커 매핑을 삭제했습니다.')
            _notify_holding_sync_result(request, report)
            return redirect('symbol_list')
        except Exception as exc:
            messages.error(request, f'티커 매핑 삭제 실패: {exc}')
    return render(request, 'portfolio/symbol_delete.html', {'symbol': symbol})


def price_board(request):
    seed_default_symbols()
    if request.method == 'POST':
        form = SymbolResolveForm(request.POST)
        if form.is_valid():
            upsert_symbol_mapping(
                stock_name=form.cleaned_data['stock_name'],
                ticker=form.cleaned_data['ticker'],
                note=form.cleaned_data['note'],
            )
            messages.success(request, f"{form.cleaned_data['stock_name']} 티커를 저장했습니다.")
            return redirect(f"{reverse('price_board')}?resolved={form.cleaned_data['stock_name']}")
        messages.error(request, '티커 저장에 실패했습니다.')

    names = list(Transaction.objects.values_list('stock_name', flat=True).distinct())
    snapshots = get_price_board(names)
    unresolved = [item for item in snapshots if item.error]
    unresolved_rows = [
        {
            'snapshot': item,
            'form': SymbolResolveForm(initial={'stock_name': item.stock_name, 'ticker': item.ticker}),
        }
        for item in unresolved
    ]
    return render(request, 'portfolio/price_board.html', {
        'snapshots': snapshots,
        'unresolved_rows': unresolved_rows,
        'resolved_name': request.GET.get('resolved', '').strip(),
    })


def analysis_view(request):
    seed_default_symbols()
    holdings = build_holdings_analysis()
    realized = build_realized_profit_analysis()
    stock_names = sorted(set(Transaction.objects.values_list("stock_name", flat=True)))
    requested_stock_name = request.GET.get("stock_name", "").strip()
    if requested_stock_name in stock_names:
        selected_stock_name = requested_stock_name
    elif stock_names:
        selected_stock_name = stock_names[0]
    else:
        selected_stock_name = ""
    retrospective = (
        build_historical_buy_timing_analysis(selected_stock_name)
        if selected_stock_name
        else None
    )
    retrospective_rankings = build_historical_buy_timing_rankings(stock_names)
    selected_ranking_sort = request.GET.get("ranking_sort", "score").strip() or "score"
    retrospective_rankings, selected_ranking_sort = _sort_retrospective_rankings(
        retrospective_rankings,
        selected_ranking_sort,
    )
    score_rankings, _score_sort = _sort_retrospective_rankings(list(retrospective_rankings), "score")
    ranking_leader_names = _build_retrospective_ranking_leader_names(retrospective_rankings)
    current_sort_top_name = retrospective_rankings[0]["stock_name"] if retrospective_rankings else ""
    score_top_name = score_rankings[0]["stock_name"] if score_rankings else ranking_leader_names.get("score_top", "")
    for row in retrospective_rankings:
        row["is_selected"] = row["stock_name"] == selected_stock_name
        row["is_current_sort_top"] = row["stock_name"] == current_sort_top_name
        row["is_score_top"] = row["stock_name"] == score_top_name
        row["is_consistency_top"] = row["stock_name"] == ranking_leader_names.get("consistency_top", "")
        row["is_good_ratio_top"] = row["stock_name"] == ranking_leader_names.get("good_ratio_top", "")
        row["is_return_20_top"] = row["stock_name"] == ranking_leader_names.get("return_20_top", "")
        row["is_recovery_top"] = row["stock_name"] == ranking_leader_names.get("recovery_top", "")
        row["is_trough_top"] = row["stock_name"] == ranking_leader_names.get("trough_top", "")
    retrospective_ranking_highlights = _build_retrospective_ranking_highlights(retrospective_rankings)
    retrospective_ranking_comparison = _build_retrospective_ranking_comparison(
        retrospective_rankings,
        selected_ranking_sort,
    )
    selected_evaluation_filter = request.GET.get("evaluation_filter", "all").strip() or "all"
    export_type = request.GET.get("export", "").strip()
    if retrospective:
        retrospective = _apply_retrospective_filter(retrospective, selected_evaluation_filter)
    if export_type == "retrospective_rankings_csv" and retrospective_rankings:
        return _export_retrospective_rankings_csv(retrospective_rankings, selected_ranking_sort)
    if export_type == "retrospective_details_csv" and retrospective:
        return _export_retrospective_details_csv(retrospective, selected_evaluation_filter)
    return render(
        request,
        'portfolio/analysis.html',
        {
            'holdings': holdings,
            'realized': realized,
            'analysis_stock_names': stock_names,
            'selected_stock_name': selected_stock_name,
            'selected_evaluation_filter': selected_evaluation_filter,
            'selected_ranking_sort': selected_ranking_sort,
            'retrospective_filter_options': RETROSPECTIVE_FILTER_OPTIONS,
            'retrospective_ranking_sort_options': RETROSPECTIVE_RANKING_SORT_OPTIONS,
            'retrospective': retrospective,
            'retrospective_rankings': retrospective_rankings,
            'retrospective_ranking_highlights': retrospective_ranking_highlights,
            'retrospective_ranking_comparison': retrospective_ranking_comparison,
        },
    )


@login_required
def consulting_holding_list(request):
    holdings = (
        UserHolding.objects.filter(user=request.user)
        .select_related("stock")
        .order_by("-is_active", "-updated_at", "-id")
    )
    active_holdings = []
    inactive_holdings = []
    for holding in holdings:
        summary = _build_holding_consult_summary(holding)
        if holding.is_active and holding.quantity > 0:
            active_holdings.append(summary)
        else:
            inactive_holdings.append(summary)

    return render(
        request,
        "portfolio/holding_list.html",
        {
            "active_holdings": active_holdings,
            "inactive_holdings": inactive_holdings,
        },
    )


@login_required
@ensure_csrf_cookie
def holding_consult_page(request, pk):
    holding = get_object_or_404(
        UserHolding.objects.select_related("stock").filter(user=request.user),
        id=pk,
    )
    holding_summary = _build_holding_consult_summary(holding)
    page_config = {
        "holdingId": holding.id,
        "isConsultable": holding_summary["is_consultable"],
        "consultUrl": reverse("holding-consult", kwargs={"pk": holding.id}),
        "consultHistoryUrl": reverse("holding-consults", kwargs={"pk": holding.id}),
        "holdingsListUrl": reverse("consulting_holding_list"),
    }
    return render(
        request,
        "portfolio/holding_consult.html",
        {
            "holding": holding,
            "holding_summary": holding_summary,
            "page_config": page_config,
        },
    )


@login_required
def chart_summary_api(request):
    return JsonResponse(summarize_transactions())


@login_required
def data_pipeline_status_page(request):
    summary = build_data_pipeline_summary()
    health_summary = summary["health_summary"]
    snapshot_summary = summary["snapshot_summary"]
    provider_summary = summary["provider_summary"]
    ingestion_summary = summary["ingestion_summary"]
    latest_snapshot_rows = []
    if snapshot_summary["latest_as_of_date"] is not None:
        latest_snapshot_rows = list(
            DataQualitySnapshot.objects.filter(as_of_date=snapshot_summary["latest_as_of_date"])
            .select_related("stock")
            .order_by("stock__code")
        )

    status_labels = {
        "healthy": "정상",
        "degraded": "주의",
        "critical": "위험",
    }
    status_classes = {
        "healthy": "status-healthy",
        "degraded": "status-degraded",
        "critical": "status-critical",
    }

    return render(
        request,
        "portfolio/data_pipeline_status.html",
        {
            "health_summary": health_summary,
            "snapshot_summary": snapshot_summary,
            "provider_summary": provider_summary,
            "ingestion_summary": ingestion_summary,
            "latest_snapshot_rows": latest_snapshot_rows,
            "health_label": status_labels.get(health_summary["overall_status"], health_summary["overall_status"]),
            "health_class": status_classes.get(health_summary["overall_status"], "status-UNKNOWN"),
            "summary_api_url": reverse("data-pipeline-summary"),
            "ingestion_logs_api_url": reverse("data-pipeline-ingestion-log-list"),
            "provider_status_api_url": reverse("data-pipeline-provider-status-list"),
        },
    )


@login_required
def data_pipeline_stock_detail_page(request, stock_code):
    stock = get_object_or_404(Stock, code=stock_code)
    provider_filter = request.GET.get("provider", "").strip()
    status_filter = request.GET.get("status", "").strip()
    failed_only = request.GET.get("failed_only") == "1"
    valid_status_filters = {
        DataIngestionLog.STATUS_STARTED,
        DataIngestionLog.STATUS_SUCCESS,
        DataIngestionLog.STATUS_PARTIAL,
        DataIngestionLog.STATUS_FAILED,
    }
    if status_filter not in valid_status_filters:
        status_filter = ""
    snapshot = (
        DataQualitySnapshot.objects.filter(stock=stock)
        .select_related("stock")
        .order_by("-as_of_date", "-id")
        .first()
    )
    provider_data_type_map = {
        StockDataCollectionStatus.TYPE_INVESTOR_FLOW: DataProviderStatus.TYPE_FLOW,
        StockDataCollectionStatus.TYPE_RISK_EVENT: DataProviderStatus.TYPE_RISK,
        StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT: DataProviderStatus.TYPE_FINANCIAL,
    }
    collection_status_rows = []
    for label, status_data_type in [
        ("Investor Flow", StockDataCollectionStatus.TYPE_INVESTOR_FLOW),
        ("Risk Event", StockDataCollectionStatus.TYPE_RISK_EVENT),
        ("Financial Snapshot", StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT),
    ]:
        snapshot_row = get_collection_status_snapshot(stock, status_data_type)
        provider_detail_url = None
        provider_logs_api_url = None
        if snapshot_row.source:
            provider_data_type = provider_data_type_map[status_data_type]
            if DataProviderStatus.objects.filter(provider=snapshot_row.source, data_type=provider_data_type).exists():
                provider_detail_url = (
                    reverse(
                        "data_pipeline_provider_detail_page",
                        kwargs={"provider": snapshot_row.source, "data_type": provider_data_type},
                    )
                    + f"?{urlencode({'stock_code': stock.code})}"
                )
            provider_logs_api_url = (
                reverse("data-pipeline-ingestion-log-list")
                + f"?{urlencode({'provider': snapshot_row.source, 'target_code': stock.code})}"
            )
        collection_status_rows.append(
            {
                "label": label,
                "data_type": status_data_type,
                "snapshot": snapshot_row,
                "provider_detail_url": provider_detail_url,
                "provider_logs_api_url": provider_logs_api_url,
            }
        )
    latest_financial_snapshot = (
        FinancialSnapshot.objects.filter(stock=stock).order_by("-fiscal_year", "-reported_date", "period_type").first()
    )
    base_logs_qs = DataIngestionLog.objects.filter(target_code=stock.code).order_by("-started_at", "-id")
    provider_choices = list(base_logs_qs.values_list("provider", flat=True).distinct())
    if provider_filter and provider_filter not in provider_choices:
        provider_filter = ""
    filtered_logs_qs = base_logs_qs
    if provider_filter:
        filtered_logs_qs = filtered_logs_qs.filter(provider=provider_filter)
    if status_filter:
        filtered_logs_qs = filtered_logs_qs.filter(status=status_filter)
    if failed_only:
        filtered_logs_qs = filtered_logs_qs.exclude(status=DataIngestionLog.STATUS_SUCCESS)
    recent_logs = list(filtered_logs_qs[:10])
    related_holding = (
        UserHolding.objects.filter(user=request.user, stock=stock, is_active=True, quantity__gt=0)
        .select_related("stock")
        .order_by("-updated_at", "-id")
        .first()
    )
    logs_api_query = {"target_code": stock.code}
    if provider_filter:
        logs_api_query["provider"] = provider_filter
    if status_filter:
        logs_api_query["status"] = status_filter
    if failed_only:
        logs_api_query["failed_only"] = "1"
    filter_query = {}
    if provider_filter:
        filter_query["provider"] = provider_filter
    if status_filter:
        filter_query["status"] = status_filter
    if failed_only:
        filter_query["failed_only"] = "1"
    clear_filters_url = reverse("data_pipeline_stock_detail_page", args=[stock.code])
    toggle_query = dict(filter_query)
    if failed_only:
        toggle_query.pop("failed_only", None)
    else:
        toggle_query["failed_only"] = "1"
    toggle_failed_only_url = clear_filters_url
    if toggle_query:
        toggle_failed_only_url += f"?{urlencode(toggle_query)}"

    return render(
        request,
        "portfolio/data_pipeline_stock_detail.html",
        {
            "stock": stock,
            "snapshot": snapshot,
            "collection_status_rows": collection_status_rows,
            "latest_financial_snapshot": latest_financial_snapshot,
            "recent_logs": recent_logs,
            "provider_choices": provider_choices,
            "provider_filter": provider_filter,
            "status_filter": status_filter,
            "status_filter_choices": [
                ("", "전체"),
                (DataIngestionLog.STATUS_SUCCESS, "success"),
                (DataIngestionLog.STATUS_FAILED, "failed"),
                (DataIngestionLog.STATUS_PARTIAL, "partial"),
                (DataIngestionLog.STATUS_STARTED, "started"),
            ],
            "failed_only": failed_only,
            "clear_filters_url": clear_filters_url,
            "toggle_failed_only_url": toggle_failed_only_url,
            "related_holding": related_holding,
            "status_page_url": reverse("data_pipeline_status_page"),
            "data_quality_api_url": reverse("data-pipeline-data-quality-detail", args=[stock.code]),
            "logs_api_url": reverse("data-pipeline-ingestion-log-list") + f"?{urlencode(logs_api_query)}",
            "consult_page_url": None
            if related_holding is None
            else reverse("holding_consult_page", args=[related_holding.id]),
        },
    )


@login_required
def data_pipeline_provider_detail_page(request, provider, data_type):
    provider_status = get_object_or_404(DataProviderStatus, provider=provider, data_type=data_type)
    stock_code = request.GET.get("stock_code", "").strip()
    status_filter = request.GET.get("status", "").strip()
    valid_status_filters = {
        DataIngestionLog.STATUS_STARTED,
        DataIngestionLog.STATUS_SUCCESS,
        DataIngestionLog.STATUS_PARTIAL,
        DataIngestionLog.STATUS_FAILED,
    }
    if status_filter not in valid_status_filters:
        status_filter = ""
    failed_only = request.GET.get("failed_only") == "1"
    related_stock = Stock.objects.filter(code=stock_code).first() if stock_code else None
    base_logs_qs = DataIngestionLog.objects.filter(provider=provider, target_type=data_type).order_by("-started_at", "-id")
    recent_logs = list(base_logs_qs[:15])
    filtered_logs_qs = base_logs_qs
    if stock_code:
        filtered_logs_qs = filtered_logs_qs.filter(target_code=stock_code)
    if status_filter:
        filtered_logs_qs = filtered_logs_qs.filter(status=status_filter)
    if failed_only:
        filtered_logs_qs = filtered_logs_qs.exclude(status=DataIngestionLog.STATUS_SUCCESS)
    filtered_logs = list(filtered_logs_qs[:15])
    recent_failures_qs = base_logs_qs.exclude(status=DataIngestionLog.STATUS_SUCCESS)
    if stock_code:
        recent_failures_qs = recent_failures_qs.filter(target_code=stock_code)
    if status_filter:
        recent_failures_qs = recent_failures_qs.filter(status=status_filter)
    recent_failures = list(recent_failures_qs[:10])
    status_page_url = reverse("data_pipeline_status_page")
    stock_detail_url = None if related_stock is None else reverse("data_pipeline_stock_detail_page", args=[related_stock.code])
    logs_api_query = {"provider": provider, "target_type": data_type}
    if stock_code:
        logs_api_query["target_code"] = stock_code
    if status_filter:
        logs_api_query["status"] = status_filter
    if failed_only:
        logs_api_query["failed_only"] = "1"
    filtered_logs_api_url = reverse("data-pipeline-ingestion-log-list") + f"?{urlencode(logs_api_query)}"
    provider_status_api_url = reverse("data-pipeline-provider-status-list") + f"?{urlencode({'provider': provider, 'data_type': data_type})}"
    filter_query = {}
    if stock_code:
        filter_query["stock_code"] = stock_code
    if status_filter:
        filter_query["status"] = status_filter
    if failed_only:
        filter_query["failed_only"] = "1"
    clear_filters_url = reverse("data_pipeline_provider_detail_page", args=[provider, data_type])
    toggle_query = dict(filter_query)
    if failed_only:
        toggle_query.pop("failed_only", None)
    else:
        toggle_query["failed_only"] = "1"
    toggle_failed_only_url = clear_filters_url
    if toggle_query:
        toggle_failed_only_url += f"?{urlencode(toggle_query)}"

    return render(
        request,
        "portfolio/data_pipeline_provider_detail.html",
        {
            "provider_status": provider_status,
            "recent_logs": recent_logs,
            "filtered_logs": filtered_logs,
            "recent_failures": recent_failures,
            "related_stock": related_stock,
            "status_page_url": status_page_url,
            "stock_detail_url": stock_detail_url,
            "filtered_logs_api_url": filtered_logs_api_url,
            "provider_status_api_url": provider_status_api_url,
            "stock_code_filter": stock_code,
            "status_filter": status_filter,
            "status_filter_choices": [
                ("", "전체"),
                (DataIngestionLog.STATUS_SUCCESS, "success"),
                (DataIngestionLog.STATUS_FAILED, "failed"),
                (DataIngestionLog.STATUS_PARTIAL, "partial"),
                (DataIngestionLog.STATUS_STARTED, "started"),
            ],
            "failed_only": failed_only,
            "clear_filters_url": clear_filters_url,
            "toggle_failed_only_url": toggle_failed_only_url,
        },
    )
