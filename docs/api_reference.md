# API Reference

실제 구현 기준의 요청/응답 계약 요약입니다. 빠른 시작과 운영 메모는 [../README.md](../README.md)를 우선 확인하고, 이 문서는 `holdings` 중심 API와 기준 데이터 API 동작을 정확히 맞추는 용도로 사용합니다.

## 인증
- 기본 인증 방식: `SessionAuthentication`, `BasicAuthentication`
- 모든 API는 인증이 필요합니다.
- 요청에 `X-Request-ID`를 넣으면 응답 header와 서버 로그에도 같은 값이 기록됩니다.
- 자동 schema endpoint: `GET /api/schema/`
- 자동 docs page: `GET /api/docs/`

예시:
```bash
curl -u demo:demo12345! -H "X-Request-ID: demo-req-001" http://127.0.0.1:8000/api/holdings/
```

schema 확인 예시:
```bash
curl -u demo:demo12345! http://127.0.0.1:8000/api/schema/
```

## 공통 규칙
- `UserHolding` 관련 API는 모두 현재 로그인한 사용자 기준입니다.
- 존재하지 않는 holding 또는 타 사용자 holding 접근은 `404`를 반환합니다.
- inactive holding 또는 `quantity <= 0` holding에 대해 `evaluate`, `probability`, `consult`를 호출하면 `400`과 아래 payload를 반환합니다.

```json
{
  "detail": "Inactive holding cannot be evaluated."
}
```

- `POST /api/holdings/{id}/evaluate/`는 `AveragingDecision`를 저장합니다.
- `POST /api/holdings/{id}/probability/`는 `AveragingProbabilityRecord`를 저장합니다.
- `POST /api/holdings/{id}/consult/`는 `HoldingConsultRecord`를 저장합니다.
- serializer validation 실패는 `400`, 예상하지 못한 서버 예외는 `500`입니다.

## Data Pipeline API

### `GET /api/data-pipeline/summary/`
최신 data quality snapshot, provider 상태, 최근 ingestion 로그를 한 번에 요약해서 반환합니다.

응답 필드:
- `health_summary.overall_status`
- `health_summary.latest_snapshot_age_days`
- `health_summary.snapshot_is_stale`
- `health_summary.failing_provider_count`
- `health_summary.recent_failure_count`
- `health_summary.latest_ingestion_started_at`
- `health_summary.latest_success_started_at`
- `snapshot_summary.latest_as_of_date`
- `snapshot_summary.latest_snapshot_age_days`
- `snapshot_summary.snapshot_is_stale`
- `snapshot_summary.stock_count`
- `snapshot_summary.grade_counts`
- `snapshot_summary.financial_missing_count`
- `snapshot_summary.anomaly_stock_count`
- `snapshot_summary.missing_field_counts`
- `snapshot_summary.anomaly_flag_counts`
- `provider_summary.total`
- `provider_summary.active`
- `provider_summary.inactive`
- `provider_summary.failing`
- `provider_summary.failing_providers`
- `ingestion_summary.latest_jobs`
- `ingestion_summary.recent_failures`

### `GET /api/data-pipeline/data-quality/{stock_code}/`
해당 종목의 최신 `DataQualitySnapshot`을 반환합니다.

응답 필드:
- `stock_code`
- `stock_name`
- `as_of_date`
- `price_data_days`
- `latest_price_date`
- `latest_price_age_days`
- `investor_flow_days`
- `latest_flow_date`
- `market_data_available`
- `risk_event_checked_at`
- `financial_data_available`
- `missing_fields`
- `anomaly_flags`
- `overall_score`
- `quality_grade`

### `GET /api/data-pipeline/ingestion-logs/`
파이프라인 실행 로그를 최신순으로 반환합니다.

지원 필터:
- `status`
- `job_name`
- `provider`
- `target_type`
- `target_code`

### `GET /api/data-pipeline/provider-status/`
provider별 최근 성공/실패 상태를 반환합니다.

지원 필터:
- `provider`
- `data_type`
- `is_active`

## Holdings API

### `GET /api/holdings/`
현재 로그인한 사용자의 holding 목록을 반환합니다.

쿼리 파라미터:
- `include_inactive=true`: inactive holding 포함
- `is_active=true|false`: 명시적 필터
- `stock`, `risk_level`: 기본 필터셋 사용

기본 동작:
- `include_inactive`가 없고 `is_active`도 없으면 `is_active=True`만 반환합니다.
- 정렬은 `updated_at DESC`, `id DESC`입니다.

응답 필드:
- `id`
- `user`
- `stock`
- `stock_code`
- `stock_name`
- `stock_market`
- `average_price`
- `quantity`
- `is_active`
- `total_invested_amount`
- `max_additional_budget`
- `risk_level`
- `memo`
- `created_at`
- `updated_at`

예시:
```json
[
  {
    "id": 1,
    "user": 1,
    "stock": 1,
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "stock_market": "KOSPI",
    "average_price": "70000.00",
    "quantity": 20,
    "is_active": true,
    "total_invested_amount": "1400000.00",
    "max_additional_budget": "500000.00",
    "risk_level": "medium",
    "memo": "",
    "created_at": "2026-04-29T12:00:00Z",
    "updated_at": "2026-04-29T12:00:00Z"
  }
]
```

### `POST /api/holdings/{id}/evaluate/`
현재 holding에 대한 물타기 평가를 실행하고 `AveragingDecision`를 저장합니다.

요청 body:
- 없음

응답 필드:
- `id`
- `holding_id`
- `stock_code`
- `stock_name`
- `score`
- `grade`
- `decision`
- `reason_summary`
- `reasons`
- `score_breakdown`
- `suggested_budget`
- `stop_loss_price`
- `disclaimer`
- `created_at`

예시:
```bash
curl -u demo:demo12345! -X POST http://127.0.0.1:8000/api/holdings/1/evaluate/
```

### `GET /api/holdings/{id}/decisions/`
해당 holding의 `AveragingDecision` 이력을 최신순으로 반환합니다.

정렬:
- `created_at DESC`

응답:
- `POST /api/holdings/{id}/evaluate/`의 응답 스키마와 동일한 객체 배열

### `GET /api/holdings/{id}/probabilities/`
해당 holding의 `AveragingProbabilityRecord` 이력을 최신순으로 반환합니다.

응답 필드:
- `id`
- `holding_id`
- `stock_code`
- `stock_name`
- `scenario_input`
- `response_payload`
- `success_probability`
- `failure_probability`
- `neutral_probability`
- `confidence`
- `disclaimer`
- `created_at`

### `POST /api/holdings/{id}/probability/`
추가 매수 시나리오에 대한 성공/실패/중립 확률을 계산하고 `AveragingProbabilityRecord`를 저장합니다.

요청 필드:
- `buy_price`: 필수, decimal
- `buy_quantity`: 필수, integer, `>= 1`
- `lookahead_days`: 선택, integer, 기본 `20`, 범위 `5..120`
- `target_type`: 선택, 기본 `new_average_price`
  - `new_average_price`
  - `new_average_price_plus_profit`
  - `manual`
- `target_profit_rate`: 선택, decimal, 기본 `0.0000`
- `manual_target_price`: `target_type=manual`일 때 필수
- `stop_loss_type`: 선택, 기본 `support_or_atr`
  - `support_or_atr`
  - `manual`
  - `fixed_rate`
  - `atr`
  - `support`
- `stop_loss_price`: `stop_loss_type=manual`일 때 필수
- `same_day_hit_policy`: 선택, 기본 `conservative`
  - `conservative`
  - `optimistic`
  - `neutral`

예시 요청:
```json
{
  "buy_price": "68000.00",
  "buy_quantity": 10,
  "lookahead_days": 20,
  "target_type": "new_average_price_plus_profit",
  "target_profit_rate": "0.0500",
  "stop_loss_type": "support_or_atr",
  "same_day_hit_policy": "conservative"
}
```

응답 필드:
- `success_probability`
- `failure_probability`
- `neutral_probability`
- `success_label`
- `failure_label`
- `confidence`
- `confidence_label`
- `target_price`
- `stop_loss_price`
- `new_average_price`
- `lookahead_days`
- `basis`
- `warnings`
- `disclaimer`

예시 응답:
```json
{
  "success_probability": "0.4123",
  "failure_probability": "0.2877",
  "neutral_probability": "0.3000",
  "success_label": "보통",
  "failure_label": "낮음",
  "confidence": "0.6800",
  "confidence_label": "보통",
  "target_price": "70210.00",
  "stop_loss_price": "65000.00",
  "new_average_price": "66850.00",
  "lookahead_days": 20,
  "basis": {
    "score_component": {},
    "volatility_component": {},
    "historical_component": {}
  },
  "warnings": [],
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다."
}
```

### `POST /api/holdings/{id}/consult/`
평가 엔진, 확률 엔진, 데이터 품질, 리스크 게이트, 시장 국면, 자금 배분 계획을 묶은 종합 컨설팅 응답을 반환하고 `HoldingConsultRecord`를 저장합니다.

요청 필드:
- `buy_price`: 선택, decimal
- `lookahead_days`: 선택, integer, 기본 `20`, 범위 `5..120`
- `target_profit_rate`: 선택, decimal, 기본 `0.0000`
- `stop_loss_type`: 선택, 기본 `support_or_atr`
  - `support_or_atr`
  - `manual`
  - `fixed_rate`
  - `atr`
  - `support`
- `stop_loss_price`: `stop_loss_type=manual`일 때 필수
- `include_scenarios`: 선택, boolean, 기본 `true`

예시 요청:
```json
{
  "buy_price": "68000.00",
  "lookahead_days": 20,
  "target_profit_rate": "0.0500",
  "stop_loss_type": "support_or_atr",
  "include_scenarios": true
}
```

응답 최상위 필드:
- `final_grade`
- `consulting_status`
- `summary`
- `decision_summary`
- `risk_gate`
- `data_quality`
- `market_regime`
- `stock_quality`
- `base_decision`
- `score_breakdown`
- `probability`
- `scenario_table`
- `capital_plan`
- `main_blockers`
- `positive_factors`
- `recheck_conditions`
- `warnings`
- `disclaimer`
- `stock`
- `holding`

화면 친화적 보강 필드:
- `stock.market`
- `stock.sector`
- `holding.average_price`
- `holding.quantity`
- `holding.current_price`
- `holding.current_price_date`
- `holding.loss_rate`
- `holding.max_additional_budget`

예시 응답 골격:
```json
{
  "final_grade": "C",
  "consulting_status": "물타기 금지 구간",
  "summary": "현재 조건에서는 물타기 금지 구간으로 분류됩니다.",
  "decision_summary": "현재 조건에서는 물타기 금지 구간으로 분류됩니다.",
  "score_breakdown": {},
  "stock": {
    "code": "005930",
    "name": "삼성전자",
    "market": "KOSPI",
    "sector": "반도체"
  },
  "holding": {
    "average_price": "70000.00",
    "quantity": 20,
    "current_price": "68900.00",
    "current_price_date": "2026-04-29",
    "loss_rate": "-1.57",
    "max_additional_budget": "500000.00",
    "risk_level": "normal",
    "is_active": true,
    "memo": ""
  },
  "risk_gate": {
    "status": "CAUTION",
    "grade_cap": "C",
    "score_multiplier": "0.8500",
    "critical_events": [],
    "blockers": [],
    "warnings": [],
    "details": {}
  },
  "data_quality": {
    "overall_score": 72,
    "label": "보통",
    "price_data_days": 120,
    "latest_price_age_days": 0,
    "investor_flow_days": 20,
    "market_data_available": true,
    "risk_event_available": true,
    "warnings": [],
    "details": {}
  },
  "market_regime": {
    "regime": "pullback",
    "score_adjustment": 5,
    "score_multiplier": "1.0500",
    "grade_cap": null,
    "reasons": [],
    "details": {}
  },
  "stock_quality": {
    "quality_grade": "UNKNOWN",
    "score": 50,
    "grade_cap": "B",
    "blockers": [],
    "warnings": [],
    "details": {}
  },
  "base_decision": {
    "score": 63,
    "grade": "B",
    "decision": "조건부 관찰",
    "reason_summary": "시장과 종목 추세를 추가 확인해야 합니다.",
    "reasons": [],
    "score_breakdown": {},
    "suggested_budget": "300000.00",
    "stop_loss_price": "65000.00"
  },
  "probability": {
    "scenario_type": "base",
    "success_probability": "0.4123",
    "failure_probability": "0.2877",
    "neutral_probability": "0.3000",
    "confidence": "0.6800"
  },
  "scenario_table": [],
  "capital_plan": {
    "max_allowed_budget": "300000.00",
    "first_entry_budget": "150000.00",
    "second_entry_budget": "90000.00",
    "third_entry_budget": "60000.00",
    "first_entry_condition": "1차 진입 조건",
    "second_entry_condition": "2차 진입 조건",
    "third_entry_condition": "3차 진입 조건",
    "stop_loss_price": "65000.00",
    "estimated_max_loss": "35000.00",
    "warnings": [],
    "details": {}
  },
  "main_blockers": [],
  "positive_factors": [],
  "recheck_conditions": [],
  "warnings": [],
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다.",
  "stock": {
    "code": "005930",
    "name": "삼성전자"
  }
}
```

주의:
- `include_scenarios=false`이면 `scenario_table`은 빈 배열로 반환됩니다.
- 확률 시나리오 비교가 실패해도 컨설팅은 가능한 범위에서 응답하며, 관련 경고는 `warnings`에 포함됩니다.

### `GET /api/holdings/{id}/consults/`
해당 holding의 `HoldingConsultRecord` 이력을 최신순으로 반환합니다.

응답 필드:
- `id`
- `holding_id`
- `stock_code`
- `stock_name`
- `request_input`
- `response_payload`
- `final_grade`
- `consulting_status`
- `summary`
- `disclaimer`
- `created_at`

## 기준 데이터 API

### staff 쓰기 제한이 적용된 API
- `GET /api/stocks/`
- `GET /api/marketdata/daily-prices/`
- `GET /api/marketdata/investor-flows/`
- `GET /api/marketdata/market-indices/`
- `GET /api/decisions/risk-events/`

권한 규칙:
- `GET`, `HEAD`, `OPTIONS`: 인증 사용자 허용
- `POST`, `PUT`, `PATCH`, `DELETE`: `is_staff=True` 사용자만 허용

### 현재 owner-scoped read-only API
- `GET /api/decisions/averaging-decisions/`
- `GET /api/decisions/probability-records/`
- `GET /api/decisions/consult-records/`

권한 규칙:
- 인증 사용자만 접근 가능
- 현재 로그인한 사용자 본인의 `AveragingDecision`만 조회 가능

### 현재 별도 staff 제한이 없는 API
- `GET /api/indicators/technical-indicators/`

현재 동작:
- 인증 사용자 CRUD가 가능합니다.
- 운영 기준으로는 일반 사용자 쓰기를 막지 않은 상태이므로 사용 시 주의가 필요합니다.

## 권장 실사용 흐름
1. `seed_averaging_demo` 또는 holding 준비
2. `refresh_decision_inputs`
기본적으로 `data_pipeline` 경로를 사용합니다. 기존 collector 경로를 강제로 쓰려면 `--legacy`를 사용합니다.
3. `audit_decision_input_quality`
4. `GET /api/holdings/`로 대상 holding 확인
5. `POST /api/holdings/{id}/evaluate/` 또는 `POST /api/holdings/{id}/probability/`
6. 필요 시 `POST /api/holdings/{id}/consult/`
