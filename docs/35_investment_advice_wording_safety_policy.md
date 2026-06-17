# Investment Advice Wording Safety Policy

## 1. 목적

이 문서는 theStock의 화면, API, 문서, 버튼, 오류 메시지가 투자 권유, 매수/매도 추천, 수익 보장, 주문 실행, 자동매매처럼 오해되지 않도록 표현 기준을 정리한다.

현재 구현된 Portfolio Summary와 Additional Buy Simulation 기능은 저장된 데이터 기반의 요약과 계산 기능이다. 이 문서는 기능을 변경하지 않고, 이후 UI/API/문서 작업에서 지켜야 할 문구 정책을 정의한다.

## 2. 현재 기능 상태

현재 완료된 기능:

- Portfolio Summary service
  - `build_portfolio_summary(user, include_inactive=False)`
  - DB-only 계산
- Portfolio Summary API
  - `GET /api/portfolio/summary/`
  - `request.user` owner scope
  - Toss API 호출 없음
  - DB write 없음
  - `DataIngestionLog` 생성 없음
- Portfolio Summary 화면
  - `GET /portfolio/summary/`
  - read-only 화면
  - 주문 버튼 없음
  - 자동매매 UI 없음
- Additional Buy Simulation service/API
  - `POST /api/holdings/{id}/additional-buy-simulation/`
  - `simulation_only=true`
  - `order_execution=false`
  - Toss API 호출 없음
  - DB write 없음
  - 주문 API 호출 없음

현재 주문 API는 미구현 및 비활성 상태이며, 자동매매 기능은 없다.

## 3. 표현 위험 등급

### Red: 사용 금지

화면, API, 문서, 버튼, 링크, 로그 어디에도 사용자 행동을 직접 유도하는 의미로 사용하지 않는다.

예:

- 매수 추천
- 매도 추천
- 지금 사야 합니다
- 지금 팔아야 합니다
- 수익 보장
- 확정 수익
- 무조건 반등
- 자동매매
- 자동 주문
- 주문 실행
- 매수하기
- 매도하기
- 주문하기
- 추천대로 매수
- 목표 수익 보장
- 손실 회복 보장

정책:

- 주문 API 구현 전에도 사용하지 않는다.
- 특히 버튼명, primary CTA, API action 이름으로 사용하지 않는다.
- 정책 설명 목적으로 문서에 예시를 적을 수는 있으나, 실제 UI 문구로 사용하지 않는다.

### Orange: 매우 주의해서 제한적으로 사용

설명 문맥 없이 쓰면 투자 권유처럼 보일 수 있는 표현이다.

예:

- 추천
- 컨설팅
- 목표가
- 회복가
- 확률
- 리스크 등급
- 투자 판단
- 매수 신호
- 과매도
- 추가매수 판단
- 성공 확률
- 실패 확률

정책:

- 단독으로 강조하지 않는다.
- "계산 결과", "시뮬레이션", "참고 정보", "추정"과 함께 사용한다.
- 매수/매도 추천이 아니고 수익을 보장하지 않는다는 문구를 함께 제공한다.
- 확률은 미래 수익의 보장이 아니라 과거 데이터와 현재 조건 기반 추정치로만 표현한다.

### Yellow: 안전 문구와 함께 사용

금융 화면에서 자연스럽게 필요한 표현이지만, 설명 없이 쓰면 행동 유도로 오해될 수 있다.

예:

- 추가매수
- 물타기
- 손익
- 수익률
- 평균단가
- 목표가
- 필요 상승률
- 리스크
- 시뮬레이션
- 손익분기점

정책:

- 계산 전용임을 함께 표시한다.
- 주문 실행과 무관함을 표시한다.
- 수수료, 세금, 슬리피지 미포함 여부를 표시한다.
- 실시간 가격이 아니라 저장된 데이터 기준이면 그 사실을 표시한다.

### Green: 권장 표현

계산/요약/참고 성격을 분명히 하는 표현이다.

예:

- 포트폴리오 요약
- 보유 현황
- 계산 전용
- 시뮬레이션
- 참고용
- 저장된 데이터 기준
- 최근 종가 기준
- 주문을 실행하지 않습니다
- 매수/매도 추천이 아닙니다
- 수익을 보장하지 않습니다
- 수수료와 세금은 포함하지 않습니다
- 사용자가 입력한 값 기준 계산

## 4. 금지 표현

다음 표현은 신규 화면/API/문서에서 사용하지 않는다.

- 매수 추천
- 매도 추천
- 매수하기
- 매도하기
- 주문하기
- 지금 매수
- 지금 매도
- 추천대로 매수
- 자동매매 시작
- 자동 주문
- 주문 실행
- 수익 보장
- 확정 수익
- 무조건 반등
- 손실 회복 보장

예외:

- 안전 정책 문서에서 금지어 예시로 설명하는 경우.
- "주문 실행 화면이 아닙니다", "주문을 실행하지 않습니다"처럼 부정문으로 안전 고지를 하는 경우.

## 5. 주의 표현

다음 표현은 서비스 도메인상 필요할 수 있으나 단독 사용을 피한다.

- 컨설팅
- 확률
- 목표가
- 회복가
- 리스크
- 물타기
- 추가매수
- 추가매수 판단
- 투자 판단
- 성공 확률
- 실패 확률

권장 사용 방식:

- "추가매수 시뮬레이션"
- "평균단가 계산"
- "목표가 기준 계산"
- "확률 기반 참고 정보"
- "리스크 점검 정보"
- "투자 권유가 아닌 계산 결과"

## 6. 권장 표현

Portfolio Summary:

- 포트폴리오 요약
- 보유 현황 요약
- 저장된 보유/일봉 데이터 기준
- 최근 종가 기준 평가
- read-only 요약
- 실시간 가격이나 주문 실행 화면이 아닙니다

Additional Buy Simulation:

- 추가매수 시뮬레이션
- 평균단가 시뮬레이션
- 추가매수 계산
- 계산 전용
- 사용자가 입력한 예산과 가격 기준 계산
- 주문을 실행하지 않습니다
- 수수료와 세금은 포함하지 않습니다

공통:

- 매수/매도 추천이 아닙니다
- 수익을 보장하지 않습니다
- 실제 투자 결정은 사용자가 직접 판단해야 합니다

## 7. 대체 표현표

| 위험 표현 | 대체 표현 | 비고 |
|---|---|---|
| 매수 추천 | 추가매수 시뮬레이션 | 추천이 아니라 입력값 기반 계산 |
| 매도 추천 | 보유 상태 참고 정보 | 매도 행동 유도 금지 |
| 매수하기 | 계산하기 | 주문 버튼처럼 보이지 않게 |
| 매도하기 | 상세 보기 | 실행 행동으로 오해되지 않게 |
| 주문하기 | 사용 금지 | 주문 API 미구현 및 비활성 |
| 주문 실행 | 주문을 실행하지 않습니다 | 안전 고지로만 사용 |
| 자동매매 | 사용 금지 | 자동매매 기능 없음 |
| 목표 수익 | 목표가 기준 계산 | 보장 표현 금지 |
| 회복 가능성 | 손익분기점 기준 필요 상승률 | 확정성 표현 금지 |
| 추천 매수 금액 | 입력 예산 기준 계산 결과 | 추천/권유 표현 금지 |
| 성공 확률이 높으니 매수 | 조건 기반 추정 확률 | 행동 지시 금지 |
| 손실 회복 보장 | 수익을 보장하지 않습니다 | 보장 표현 금지 |

## 8. Portfolio Summary 화면 문구 기준

화면 성격:

```text
GET /portfolio/summary/
저장된 UserHolding + DailyPrice 기반 read-only 화면
```

권장 제목:

- 포트폴리오 요약
- 보유 현황 요약

권장 설명:

```text
이 화면은 저장된 보유 정보와 최신 일봉 데이터를 기반으로 계산한 참고용 요약입니다.
실시간 가격이나 주문 실행 화면이 아닙니다.
이 화면에서는 주문 생성, 정정, 취소 기능을 제공하지 않습니다.
```

현재 화면의 안전 문구:

```text
이 화면은 저장된 보유/일봉 데이터 기반 read-only 요약입니다.
실시간 가격이나 주문 실행 화면이 아니며, 주문 생성/정정/취소 기능을 제공하지 않습니다.
추가매수 시뮬레이션은 계산 전용이며 주문을 실행하지 않습니다.
```

금지 표현:

- 매수하기
- 매도하기
- 주문하기
- 추천 종목
- 지금 매수
- 자동매매 시작
- 수익 보장

## 9. Additional Buy Simulation 문구 기준

API 성격:

```text
POST /api/holdings/{id}/additional-buy-simulation/
DB-only 계산 API
simulation_only=true
order_execution=false
```

권장 제목:

- 추가매수 시뮬레이션
- 평균단가 시뮬레이션
- 추가매수 계산

권장 설명:

```text
입력한 예산과 가격을 기준으로 평균단가 변화를 계산합니다.
이 결과는 계산용 참고 정보이며 매수/매도 추천이 아닙니다.
이 기능은 주문을 실행하지 않습니다.
수수료와 세금은 포함하지 않습니다.
```

API warnings 권장:

```text
Calculation-only simulation. No orders are placed.
This is not investment advice and does not guarantee returns.
Fees and taxes are not included.
```

현재 service warning:

```text
This is a calculation-only simulation and does not place orders.
Fees and taxes are not included.
```

금지 표현:

- 이 가격에 매수하세요
- 추천 매수 금액
- 수익 보장
- 자동 주문
- 매수하기
- 주문 실행

## 10. API response 표현 기준

Additional Buy Simulation response의 안전 필드:

- `simulation_only`
- `order_execution`
- `current_position`
- `simulation`
- `target_projection`
- `warnings`

정책:

- `simulation_only`는 `true`를 유지한다.
- `order_execution`은 `false`를 유지한다.
- `order_id`, `orderNo`, `order_status` 등 주문처럼 보이는 필드는 금지한다.
- `recommendation`, `buy_signal`, `should_buy`, `must_buy` 같은 필드는 금지한다.
- `target_projection`은 "목표가 기준 계산"으로만 설명한다.
- `warnings`에는 계산 전용, 주문 없음, 수수료/세금 제외 문구를 포함한다.
- username, email, user id, 계좌, token, header, raw response를 포함하지 않는다.

## 11. Error message 표현 기준

권장 safe error message:

```text
additional_budget must be greater than zero.
latest price is required when buy_price is not provided.
additional budget is too small to calculate at least one share.
inactive holdings cannot be simulated.
buy_price must be greater than zero.
target_price must be greater than zero.
```

금지 error message:

```text
이 종목은 매수하면 안 됩니다.
이 종목은 매수해야 합니다.
손실 회복이 불가능합니다.
반드시 추가매수하세요.
수익을 회복할 수 있습니다.
```

오류 메시지 정책:

- validation 조건만 설명한다.
- 투자 행동을 지시하지 않는다.
- raw exception을 그대로 노출하지 않는다.
- 민감정보를 message에 넣지 않는다.

## 12. 공통 고지 문구

화면 하단 또는 결과 박스 권장 문구:

```text
이 결과는 사용자가 입력한 값과 저장된 데이터를 기반으로 한 계산용 시뮬레이션입니다.
매수, 매도, 보유에 대한 투자 권유가 아니며 수익을 보장하지 않습니다.
실제 투자 결정은 사용자가 직접 판단해야 합니다.
이 서비스는 주문을 실행하지 않습니다.
```

API warning 권장 문구:

```text
Calculation-only simulation. No orders are placed.
This is not investment advice and does not guarantee returns.
Fees and taxes are not included.
```

짧은 UI 문구:

```text
계산 전용이며 주문을 실행하지 않습니다.
매수/매도 추천이 아니며 수익을 보장하지 않습니다.
```

## 13. 현재 코드/문서 표현 점검 결과

점검 명령:

```text
grep -RniE "추천|권유|매수하|매도하|사야|팔아|수익 보장|확정 수익|무조건|자동매매|자동 주문|주문 실행|매수하기|매도하기|주문하기|목표가|회복가|리스크|확률|컨설팅|시뮬레이션|추가매수|물타기|손익|수익률" portfolio holdings decisions indicators marketdata stocks docs | head -300
```

안전한 표현:

- `portfolio/templates/portfolio/summary.html`
  - "read-only 요약"
  - "주문 생성/정정/취소 기능을 제공하지 않습니다"
  - "추가매수 시뮬레이션은 계산 전용이며 주문을 실행하지 않습니다"
  - "계산 전용 API 사용 가능"
- `docs/33_additional_buy_simulation_api_design.md`
  - "투자 권유나 매수 추천이 아니다"
  - "`simulation_only=true`"
  - "`order_execution=false`"
  - "수익 보장 표현 금지"
- `docs/34_portfolio_and_simulation_api_reference.md`
  - "주문을 실행하지 않습니다"
  - "투자 권유가 아니다"
  - "수익 보장이 아니다"
- `decisions/models.py`, `decisions/services/probability_dataclasses.py`, `decisions/services/consulting_service.py`
  - "매수·매도 추천이 아닙니다" disclaimer 존재

주의 필요한 표현:

- `portfolio/templates/portfolio/holding_list.html`
  - "물타기 판단", "확률", "리스크 게이트", "컨설팅 리포트"
  - 서비스 맥락상 가능하나 투자 권유가 아님을 함께 표시해야 한다.
- `portfolio/templates/portfolio/base.html`
  - "물타기 컨설팅"
  - navigation 문구로는 가능하나 화면 진입 후 disclaimer가 필요하다.
- `portfolio/templates/portfolio/landing.html`
  - "물타기 판단", "추가 매수 판단과 확률 요약", "실행 여부를 비교"
  - 마케팅/소개 문구에서 행동 유도로 보이지 않게 "참고", "계산", "주문 없음"을 강화할 필요가 있다.
- `portfolio/static/portfolio/js/holding_consult.js`
  - "성공 확률", "실패 확률", "목표가", "리스크 차단"
  - 확률이 수익 보장처럼 보이지 않도록 confidence와 disclaimer를 함께 표시해야 한다.
- `decisions/services/consulting_service.py`
  - "실패 확률이 높아 보수적 접근이 필요합니다"
  - 조언처럼 읽힐 수 있으므로 "참고 정보" 또는 "재점검" 문맥을 함께 유지해야 한다.
- `decisions/services/scenario_comparison_service.py`
  - "목표가", "손절가"
  - 주문 지시가 아니라 시나리오 입력값임을 표시해야 한다.

후속 수정 후보:

- Portfolio/consulting legacy 화면의 제목과 CTA에 "계산", "참고", "주문 없음" 문구 보강.
- landing page의 "실행 여부" 표현을 "조건 비교" 또는 "참고 판단"으로 완화.
- Additional Buy Simulation warning에 "This is not investment advice and does not guarantee returns." 추가 검토.
- consulting 화면에 공통 고지 문구를 화면 상단 또는 결과 박스에 고정 표시.

유지 가능 표현:

- "포트폴리오 요약"
- "보유 현황"
- "평가손익"
- "수익률"
- "시뮬레이션"
- "계산 전용"
- "주문을 실행하지 않습니다"
- "매수·매도 추천이 아닙니다"

## 14. UI 버튼/링크 네이밍 정책

허용 버튼/링크:

- 계산하기
- 시뮬레이션 보기
- 평균단가 계산
- 포트폴리오 요약 보기
- 상세 보기
- 조건 비교 보기
- 데이터 상태 보기

금지 버튼/링크:

- 매수하기
- 매도하기
- 주문하기
- 자동매매 시작
- 추천대로 매수
- 수익 실현하기
- 지금 매수
- 지금 매도

주의 버튼/링크:

- 추가매수
- 물타기
- 목표가
- 리스크
- 컨설팅
- 확률

주의 표현은 반드시 "계산", "시뮬레이션", "참고", "조건 비교"와 함께 사용한다.

## 15. 향후 PR 체크리스트

- [ ] 주문 실행처럼 보이는 버튼이 없는가.
- [ ] 매수/매도 추천처럼 보이는 문장이 없는가.
- [ ] 수익 보장 표현이 없는가.
- [ ] 자동매매 또는 자동 주문처럼 보이는 문구가 없는가.
- [ ] `simulation_only=true`가 유지되는가.
- [ ] `order_execution=false`가 유지되는가.
- [ ] warnings에 계산 전용 문구가 있는가.
- [ ] warnings에 주문을 실행하지 않는다는 문구가 있는가.
- [ ] 필요한 경우 "투자 권유가 아님" 문구가 함께 표시되는가.
- [ ] 수수료/세금 미포함 여부가 표시되는가.
- [ ] username/email/account/token/header가 response나 화면에 없는가.
- [ ] 주문 ID, 주문번호, 주문 상태 필드가 response에 없는가.
- [ ] 사용자 시뮬레이션 조회를 `DataIngestionLog`에 기록하지 않는가.
- [ ] Toss API를 호출하지 않는 DB-only MVP인지 확인했는가.
- [ ] 실시간 가격이 아닌 경우 latest DailyPrice 기준임을 표시했는가.
- [ ] 확률 값이 수익 보장처럼 강조되지 않는가.

## 16. 보류/주의 사항

- 이번 문서는 코드, template, API response를 수정하지 않는다.
- 기존 consulting/analysis 화면에는 "컨설팅", "확률", "물타기", "목표가" 표현이 남아 있다.
- 해당 표현은 서비스 도메인상 유지 가능하지만, 후속 UI 정리 Step에서 안전 고지를 강화하는 것이 좋다.
- 주문 API는 계속 미구현 및 비활성 상태를 유지한다.
- 자동매매 또는 조건 충족 시 자동 주문 로직은 설계/구현 대상이 아니다.
