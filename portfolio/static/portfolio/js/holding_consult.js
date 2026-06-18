function getConsultPageConfig() {
  const script = document.getElementById("consult-page-config");
  if (!script) {
    return null;
  }
  return JSON.parse(script.textContent);
}

function getCsrfToken(config = {}) {
  const normalizeToken = (value) => decodeURIComponent(value || "").trim().replace(/^"|"$/g, "");
  const isValidLength = (value) => value.length === 32 || value.length === 64;
  const configToken = normalizeToken(config.csrfToken);
  if (isValidLength(configToken)) {
    return configToken;
  }
  const metaToken = normalizeToken(document.querySelector('meta[name="csrf-token"]')?.getAttribute("content"));
  if (isValidLength(metaToken)) {
    return metaToken;
  }
  const cookies = document.cookie ? document.cookie.split(";") : [];
  for (const cookie of cookies) {
    const trimmed = cookie.trim();
    if (trimmed.startsWith("csrftoken=")) {
      const cookieToken = normalizeToken(trimmed.slice("csrftoken=".length));
      if (isValidLength(cookieToken)) {
        return cookieToken;
      }
    }
  }
  return "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatCurrency(value) {
  const parsed = toNumber(value);
  if (parsed === null) {
    return "데이터 없음";
  }
  return `${parsed.toLocaleString("ko-KR")}원`;
}

function formatPercent(value) {
  const parsed = toNumber(value);
  if (parsed === null) {
    return "데이터 없음";
  }
  const sign = parsed > 0 ? "+" : "";
  return `${sign}${parsed.toFixed(2)}%`;
}

function formatProbability(value) {
  const parsed = toNumber(value);
  if (parsed === null) {
    return "계산 없음";
  }
  return `${(parsed * 100).toFixed(1)}%`;
}

function formatCount(value, suffix = "") {
  if (value === null || value === undefined || value === "") {
    return "데이터 없음";
  }
  return `${value}${suffix}`;
}

function badgeClass(prefix, value) {
  return `${prefix}-${String(value ?? "UNKNOWN").replaceAll(" ", "_")}`;
}

function buildList(items, emptyMessage, listClass = "consult-warning-list") {
  if (!items || items.length === 0) {
    return `<p class="consult-subdued mb-0">${escapeHtml(emptyMessage)}</p>`;
  }
  return `<ul class="${listClass}">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function buildLabelChips(items) {
  if (!items || items.length === 0) {
    return "";
  }
  return `<div class="consult-label-cluster">${items
    .map((item) => `<span class="badge text-bg-light border">${escapeHtml(item)}</span>`)
    .join("")}</div>`;
}

function renderScoreBreakdown(scoreBreakdown) {
  const entries = Object.entries(scoreBreakdown || {});
  if (!entries.length) {
    return `<p class="consult-subdued mb-0">score breakdown 데이터가 없습니다.</p>`;
  }
  return entries
    .map(([label, value]) => {
      const numericValue = Math.max(0, Math.min(100, toNumber(value) ?? 0));
      return `
        <div class="consult-score-row">
          <div class="d-flex justify-content-between small mb-1">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
          </div>
          <div class="progress">
            <div class="progress-bar bg-dark" role="progressbar" style="width: ${numericValue}%"></div>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderProbabilityBoxes(probability) {
  if (!probability) {
    return `<p class="consult-subdued mb-0">확률 데이터가 없습니다.</p>`;
  }
  return `
    <div class="consult-probability-strip">
      <div class="consult-probability-box">
        <div class="consult-metric-label">성공 확률</div>
        <div class="consult-metric-value">${formatProbability(probability.success_probability)}</div>
      </div>
      <div class="consult-probability-box">
        <div class="consult-metric-label">실패 확률</div>
        <div class="consult-metric-value">${formatProbability(probability.failure_probability)}</div>
      </div>
      <div class="consult-probability-box">
        <div class="consult-metric-label">중립 확률</div>
        <div class="consult-metric-value">${formatProbability(probability.neutral_probability)}</div>
      </div>
    </div>
  `;
}

function renderScenarioTable(items) {
  if (!items || items.length === 0) {
    return `<p class="consult-subdued mb-0">시나리오 비교 테이블이 비어 있습니다. 확률 엔진 degraded 상태일 수 있습니다.</p>`;
  }
  return `
    <div class="consult-table-wrap">
      <table class="table align-middle consult-table">
        <thead>
          <tr>
            <th>시나리오</th>
            <th>매수가</th>
            <th>수량</th>
            <th>새 평단</th>
            <th>목표가</th>
            <th>손절가</th>
            <th>성공</th>
            <th>실패</th>
            <th>중립</th>
            <th>신뢰도</th>
            <th>상태</th>
            <th>요약</th>
          </tr>
        </thead>
        <tbody>
          ${items
            .map(
              (item) => `
                <tr>
                  <td><strong>${escapeHtml(item.scenario_type)}</strong></td>
                  <td>${formatCurrency(item.buy_price)}</td>
                  <td>${formatCount(item.buy_quantity, "주")}</td>
                  <td>${formatCurrency(item.new_average_price)}</td>
                  <td>${formatCurrency(item.target_price)}</td>
                  <td>${formatCurrency(item.stop_loss_price)}</td>
                  <td>${formatProbability(item.success_probability)}</td>
                  <td>${formatProbability(item.failure_probability)}</td>
                  <td>${formatProbability(item.neutral_probability)}</td>
                  <td>${formatProbability(item.confidence)}</td>
                  <td><span class="status-pill ${badgeClass("status", item.status)}">${escapeHtml(item.status)}</span></td>
                  <td class="small">${escapeHtml(item.reason_summary || "설명 없음")}</td>
                </tr>
              `
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderCapitalPlan(capitalPlan) {
  if (!capitalPlan) {
    return `<p class="consult-subdued mb-0">자본 배분 계획 데이터가 없습니다.</p>`;
  }
  return `
    <div class="consult-kpi"><span>최대 허용 예산</span><strong>${formatCurrency(capitalPlan.max_allowed_budget)}</strong></div>
    <div class="consult-kpi"><span>1차 진입</span><strong>${formatCurrency(capitalPlan.first_entry_budget)}</strong></div>
    <div class="small consult-subdued mb-2">${escapeHtml(capitalPlan.first_entry_condition || "")}</div>
    <div class="consult-kpi"><span>2차 진입</span><strong>${formatCurrency(capitalPlan.second_entry_budget)}</strong></div>
    <div class="small consult-subdued mb-2">${escapeHtml(capitalPlan.second_entry_condition || "")}</div>
    <div class="consult-kpi"><span>3차 진입</span><strong>${formatCurrency(capitalPlan.third_entry_budget)}</strong></div>
    <div class="small consult-subdued mb-2">${escapeHtml(capitalPlan.third_entry_condition || "")}</div>
    <div class="consult-kpi"><span>기준 손절가</span><strong>${formatCurrency(capitalPlan.stop_loss_price)}</strong></div>
    <div class="consult-kpi"><span>예상 최대 손실</span><strong>${formatCurrency(capitalPlan.estimated_max_loss)}</strong></div>
    ${buildList(capitalPlan.warnings, "추가 경고 없음")}
  `;
}

function renderOutcomeHighlights(probability) {
  if (!probability || !probability.highlights) {
    return "";
  }
  const highlights = probability.highlights;
  const cases = highlights.representative_cases || {};
  const caseLines = ["success", "failure", "neutral"]
    .map((key) => {
      const example = cases[key];
      if (!example) {
        return "";
      }
      return `<li><strong>${escapeHtml(key)}</strong>: ${escapeHtml(example.reason_summary || example.date || "대표 사례")}</li>`;
    })
    .filter(Boolean)
    .join("");
  return `
    <div class="mt-3">
      <p class="mb-2">${escapeHtml(highlights.headline || "확률 해설 없음")}</p>
      ${caseLines ? `<ul class="consult-factors-list small mb-0">${caseLines}</ul>` : ""}
    </div>
  `;
}

function renderConsultingResult(payload) {
  const scoreBreakdown = payload.score_breakdown || payload.base_decision?.score_breakdown || {};
  const probability = payload.probability;
  return `
    ${payload.warnings && payload.warnings.length ? `<div class="alert alert-warning">${buildList(payload.warnings, "", "consult-warning-list")}</div>` : ""}
    <div class="consult-grid">
      <section class="consult-panel-card span-12">
        <div class="d-flex flex-wrap justify-content-between align-items-start gap-3">
          <div>
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="consult-grade-badge ${badgeClass("grade", payload.final_grade)}">${escapeHtml(payload.final_grade)}</span>
              <span class="status-pill ${badgeClass("status", payload.risk_gate?.status || payload.final_grade)}">${escapeHtml(payload.consulting_status)}</span>
            </div>
            <h2 class="consult-section-title mb-2">최종 판단 요약</h2>
            <p class="mb-3">${escapeHtml(payload.decision_summary || payload.summary || "요약 없음")}</p>
            ${buildLabelChips(payload.positive_factors)}
          </div>
          <div class="small consult-subdued">
            <div>Risk Gate: <strong>${escapeHtml(payload.risk_gate?.status || "-")}</strong></div>
            <div>Market Regime: <strong>${escapeHtml(payload.market_regime?.regime || "-")}</strong></div>
            <div>Stock Quality: <strong>${escapeHtml(payload.stock_quality?.quality_grade || "-")}</strong></div>
          </div>
        </div>
      </section>

      <section class="consult-panel-card span-4">
        <h3 class="consult-section-title">Data Quality</h3>
        <div class="consult-kpi"><span>등급</span><strong>${escapeHtml(payload.data_quality?.label || "-")}</strong></div>
        <div class="consult-kpi"><span>가격 데이터</span><strong>${formatCount(payload.data_quality?.price_data_days, "일")}</strong></div>
        <div class="consult-kpi"><span>수급 데이터</span><strong>${formatCount(payload.data_quality?.investor_flow_days, "일")}</strong></div>
        <div class="consult-kpi"><span>시장 데이터</span><strong>${payload.data_quality?.market_data_available ? "있음" : "없음"}</strong></div>
        ${buildList(payload.data_quality?.warnings, "Data Quality 경고 없음")}
      </section>

      <section class="consult-panel-card span-4">
        <h3 class="consult-section-title">Risk Gate</h3>
        <div class="d-flex align-items-center gap-2 mb-3">
          <span class="status-pill ${badgeClass("status", payload.risk_gate?.status)}">${escapeHtml(payload.risk_gate?.status || "-")}</span>
          <span class="small consult-subdued">grade cap ${escapeHtml(payload.risk_gate?.grade_cap || "없음")}</span>
        </div>
        ${buildList(payload.main_blockers, "주요 차단 사유 없음")}
      </section>

      <section class="consult-panel-card span-4">
        <h3 class="consult-section-title">Market / Stock Quality</h3>
        <div class="consult-kpi"><span>시장 국면</span><strong>${escapeHtml(payload.market_regime?.regime || "-")}</strong></div>
        <div class="small consult-subdued mb-3">${escapeHtml((payload.market_regime?.reasons || []).join(" / ") || "시장 사유 없음")}</div>
        <div class="consult-kpi"><span>종목 품질</span><strong>${escapeHtml(payload.stock_quality?.quality_grade || "-")}</strong></div>
        ${buildList(payload.stock_quality?.blockers, "종목 품질 차단 사유 없음")}
      </section>

      <section class="consult-panel-card span-6">
        <h3 class="consult-section-title">Probability</h3>
        ${renderProbabilityBoxes(probability)}
        ${renderOutcomeHighlights(probability)}
      </section>

      <section class="consult-panel-card span-6">
        <h3 class="consult-section-title">Score Breakdown</h3>
        ${renderScoreBreakdown(scoreBreakdown)}
      </section>

      <section class="consult-panel-card span-12">
        <h3 class="consult-section-title">Scenario Comparison</h3>
        ${renderScenarioTable(payload.scenario_table)}
      </section>

      <section class="consult-panel-card span-6">
        <h3 class="consult-section-title">Capital Allocation</h3>
        ${renderCapitalPlan(payload.capital_plan)}
      </section>

      <section class="consult-panel-card span-6">
        <h3 class="consult-section-title">재점검 조건</h3>
        ${buildList(payload.recheck_conditions, "재점검 조건이 없습니다.", "consult-check-list")}
      </section>

      <section class="consult-panel-card span-12 consult-disclaimer">
        <h3 class="consult-section-title">Disclaimer</h3>
        <p class="mb-0">${escapeHtml(payload.disclaimer || "본 결과는 투자 참고용 데이터 분석입니다.")}</p>
      </section>
    </div>
  `;
}

function renderInactiveState(root) {
  root.innerHTML = `
    <div class="card consult-card">
      <div class="card-body">
        <h2 class="h5 mb-2">비활성 보유 종목입니다.</h2>
        <p class="mb-0 text-secondary">청산 또는 비활성 상태인 보유 종목은 consult API를 실행하지 않습니다.</p>
      </div>
    </div>
  `;
}

function renderErrorState(root, message) {
  root.innerHTML = `
    <div class="card consult-card">
      <div class="card-body">
        <h2 class="h5 mb-2">컨설팅 결과를 불러오지 못했습니다.</h2>
        <p class="text-secondary mb-3">${escapeHtml(message)}</p>
        <button id="consult-retry-inline" class="btn btn-dark">다시 시도</button>
      </div>
    </div>
  `;
}

function renderBanner(payload) {
  const container = document.getElementById("consult-status-banner");
  if (!container) {
    return;
  }
  const riskStatus = payload.risk_gate?.status;
  if (riskStatus === "CRITICAL" || riskStatus === "BLOCK") {
    container.innerHTML = `<div class="alert alert-danger">이 종목은 현재 악재 또는 위험 이벤트가 있어서, 단순 확률 계산으로 추가 매수를 판단하지 말고 리스크를 먼저 확인하세요.</div>`;
    return;
  }
  if (payload.probability?.scenario_type === "fallback") {
    container.innerHTML = `<div class="alert alert-warning">확률 엔진 degraded 상태입니다. 이번 화면은 fallback probability summary를 포함합니다.</div>`;
    return;
  }
  container.innerHTML = "";
}

function updateHeader(payload) {
  const holding = payload.holding || {};
  const fieldMap = {
    average_price: formatCurrency(holding.average_price),
    current_price: formatCurrency(holding.current_price),
    loss_rate: formatPercent(holding.loss_rate),
    max_additional_budget: formatCurrency(holding.max_additional_budget),
  };
  Object.entries(fieldMap).forEach(([field, value]) => {
    const node = document.querySelector(`[data-header-field="${field}"]`);
    if (node) {
      node.textContent = value;
      if (field === "loss_rate") {
        node.classList.remove("text-danger", "text-success");
        const numericValue = toNumber(holding.loss_rate);
        if (numericValue !== null) {
          if (numericValue < 0) {
            node.classList.add("text-danger");
          } else if (numericValue > 0) {
            node.classList.add("text-success");
          }
        }
      }
    }
  });
}

async function fetchConsulting(config) {
  const csrfToken = getCsrfToken(config);
  if (!csrfToken) {
    throw new Error("CSRF 토큰을 확인하지 못했습니다. 화면을 새로고침해 주세요.");
  }
  const response = await fetch(config.consultUrl, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    let detail = `Consulting API failed: ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      detail = detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

async function loadConsulting(root, config) {
  const refreshButton = document.getElementById("consult-refresh-button");
  if (refreshButton) {
    refreshButton.disabled = true;
  }
  try {
    const payload = await fetchConsulting(config);
    updateHeader(payload);
    renderBanner(payload);
    root.innerHTML = renderConsultingResult(payload);
  } catch (error) {
    renderErrorState(root, error.message || "알 수 없는 오류");
    const retryButton = document.getElementById("consult-retry-inline");
    if (retryButton) {
      retryButton.addEventListener("click", () => loadConsulting(root, config));
    }
  } finally {
    if (refreshButton) {
      refreshButton.disabled = false;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const config = getConsultPageConfig();
  const root = document.getElementById("consult-screen-root");
  if (!config || !root) {
    return;
  }

  const refreshButton = document.getElementById("consult-refresh-button");
  if (refreshButton) {
    refreshButton.addEventListener("click", () => loadConsulting(root, config));
  }

  if (!config.isConsultable) {
    renderInactiveState(root);
    return;
  }

  loadConsulting(root, config);
});
