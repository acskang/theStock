# Portfolio Simulation UI Design

## 1. 목적

이 문서는 Portfolio Summary 화면에서 `Additional Buy Simulation API`를 안전하게 사용할 수 있는 UI 설계를 정의한다.

목표는 사용자가 보유종목별로 추가 예산과 가격 가정을 입력해 평균단가 변화를 계산하는 것이다. 이 UI는 주문 실행, 자동매매, 매수/매도 추천, 수익 보장 기능이 아니다.

## 2. 현재 구현 상태

구현 완료 항목:

- Portfolio Summary 화면
  - `GET /portfolio/summary/`
  - `portfolio_summary_page`
  - `portfolio/summary.html`
  - login required
  - DB-only read-only 화면
- Portfolio Summary API
  - `GET /api/portfolio/summary/`
  - `request.user` owner scope
- Additional Buy Simulation API
  - `POST /api/holdings/{id}/additional-buy-simulation/`
  - `AdditionalBuySimulationInputSerializer`
  - `simulation_only=true`
  - `order_execution=false`
  - DB write 없음
  - Toss API 호출 없음
  - 주문 API 호출 없음

현재 Portfolio Summary 화면은 holdings table의 `Simulation` 열에 `계산 전용 API 사용 가능` 안내만 표시한다. 현재 `build_portfolio_summary()` 반환 item에는 holding id가 포함되어 있지 않으므로, Step O 구현 시 API endpoint를 만들기 위해 다음 중 하나를 결정해야 한다.

- summary item에 safe `holding_id`를 추가한다.
- 화면 view에서 별도 owner-scoped mapping을 만들어 template에 전달한다.
- 별도 detail route를 사용한다.

MVP 권장안은 summary item 또는 view context에 `request.user` 소유 holding id만 포함하는 것이다. holding id는 DOM에 노출될 수 있지만, API 서버는 이미 `request.user` owner scope로 다시 검증해야 한다.

## 3. UI 배치 후보

### 후보 A: 각 holding row 안에 접힌 inline form

형태:

- 각 row에 `평균단가 계산` 버튼 표시
- 클릭하면 해당 row 아래에 입력 form 표시
- `additional_budget`, `buy_price`, `target_price` 입력
- `계산하기` 버튼으로 API 호출
- 결과를 같은 row 아래에 표시

장점:

- holding과 계산 결과의 관계가 명확하다.
- 화면 이동이 없다.
- 구현이 단순하다.
- 주문 UI처럼 보이지 않도록 문구와 스타일을 통제하기 쉽다.

단점:

- holdings가 많으면 화면이 복잡해질 수 있다.
- table row 하위 확장 UI의 반응형 처리가 필요하다.

### 후보 B: modal dialog

형태:

- 각 row의 `시뮬레이션` 버튼 클릭
- modal에서 입력과 결과 표시

장점:

- 기본 table 화면이 깔끔하다.
- 입력/결과 영역을 한 곳에 모을 수 있다.

단점:

- 구현 복잡도가 높다.
- keyboard focus trap, escape, aria 속성 등 접근성 처리가 필요하다.
- modal action이 주문 확인 UI처럼 보이지 않게 더 주의해야 한다.

### 후보 C: 별도 detail page

형태:

- `/holdings/{id}/simulation/` 같은 별도 화면으로 이동

장점:

- 입력과 결과를 넓게 표시할 수 있다.
- 복잡한 설명과 history가 붙는 후속 확장에 유리하다.

단점:

- 새 page route와 template이 필요하다.
- MVP에는 과하다.
- Summary 화면에서 즉시 비교하기 어렵다.

## 4. 권장 UI 방향

Step O MVP는 후보 A인 row 아래 접힌 inline form으로 시작한다.

이유:

- 기존 `/portfolio/summary/` 화면 흐름을 유지한다.
- 보유 row와 계산 결과를 같은 위치에 둬 관계가 명확하다.
- 별도 page나 modal 접근성 부담 없이 구현할 수 있다.
- Step M의 안전 문구 정책을 row 단위로 강제하기 쉽다.
- 버튼 문구를 `평균단가 계산`으로 제한하면 주문 버튼처럼 보일 위험이 낮다.

권장 구조:

- 기본 table은 기존처럼 표시한다.
- 각 active holding row에 `평균단가 계산` 버튼을 둔다.
- 버튼은 `btn-outline-secondary` 수준의 보수적 스타일을 사용한다.
- 버튼 클릭 시 바로 아래 hidden row가 열린다.
- hidden row에는 form, 안전 고지, 결과 영역이 있다.
- inactive holding은 기본 화면에서 제외되며, `include_inactive=true`에서도 simulation form은 disabled 또는 미표시를 권장한다.

## 5. 버튼/링크 문구 정책

허용 버튼/링크:

- 평균단가 계산
- 계산하기
- 시뮬레이션 열기
- 계산 결과 보기
- 닫기

주의해서 사용 가능한 문구:

- 추가매수 시뮬레이션
- 추가매수 계산

주의 문구는 반드시 다음 안전 문구와 함께 사용한다.

```text
계산 전용이며 주문을 실행하지 않습니다.
매수/매도 추천이 아니며 수익을 보장하지 않습니다.
```

금지 버튼/링크:

- 매수하기
- 매도하기
- 주문하기
- 추천대로 매수
- 자동매매 시작
- 수익 실현
- 지금 매수
- 지금 팔기

스타일 정책:

- 주문 버튼처럼 보이는 강한 primary CTA를 피한다.
- `계산하기`는 form 내부의 계산 실행 버튼일 뿐이며 주문 실행이 아니다.
- `order_execution=false` 의미를 결과 영역에 항상 표시한다.

## 6. 입력 form 설계

MVP 입력 필드:

| Field | Label | Required | 설명 |
|---|---|---:|---|
| `additional_budget` | 추가 예산 | 예 | 입력한 예산으로 살 수 있는 정수 수량을 계산한다. |
| `buy_price` | 계산 기준 가격 | 아니오 | 비워두면 저장된 최신 종가를 사용한다. |
| `target_price` | 목표가 기준 계산 | 아니오 | 입력하면 해당 가격 기준의 손익을 함께 계산한다. |

도움말:

- 추가 예산: 입력한 예산으로 계산 가능한 정수 수량을 산출합니다.
- 계산 기준 가격: 비워두면 저장된 최신 종가를 사용합니다.
- 목표가 기준 계산: 입력하면 해당 가격 기준의 손익을 함께 계산합니다.

validation UI:

- `additional_budget`은 필수이다.
- `additional_budget`은 0보다 커야 한다.
- `buy_price`는 선택이며, 입력 시 0보다 커야 한다.
- `target_price`는 선택이며, 입력 시 0보다 커야 한다.
- 1주도 계산할 수 없는 예산이면 safe error를 표시한다.
- latest `DailyPrice`가 없고 `buy_price`도 없으면 safe error를 표시한다.

금지 입력:

- 계좌 선택
- 주문 수량
- 주문 유형
- 시장가/지정가 주문
- 매수 가능 금액 조회
- 매도 가능 수량 조회
- 주문 확인
- 주문 실행
- 자동 주문 설정

## 7. API 호출 설계

Endpoint:

```text
POST /api/holdings/{id}/additional-buy-simulation/
```

Method:

```text
POST
```

Request body:

```json
{
  "additional_budget": "100000",
  "buy_price": "16000",
  "target_price": "18000"
}
```

CSRF/session:

- Django session authentication을 사용한다.
- same-origin `fetch`를 사용한다.
- CSRF token을 header에 포함한다.
- Authorization header를 직접 다루지 않는다.

사용하지 않는 값:

- Toss access token
- account header
- accountNo/accountSeq
- raw API response
- order id/orderNo

성공 조건:

- HTTP 200
- `simulation_only=true`
- `order_execution=false`

오류 조건:

- HTTP 400 validation error
- safe `error`와 `message`만 표시
- raw exception 표시 금지

예상 safe error code:

- `invalid_additional_budget`
- `invalid_buy_price`
- `invalid_target_price`
- `latest_price_required`
- `additional_quantity_too_small`
- `additional_quantity_not_supported`
- `conflicting_input`
- `inactive_holding`

## 8. 결과 표시 설계

결과 영역 표시 항목:

- 계산 전용 여부
- 주문 실행 여부: `주문을 실행하지 않습니다`
- 현재 보유 수량
- 현재 평균단가
- 현재 투자금
- 현재 평가금액
- 현재 손익률
- 추가 가능 수량
- 사용 예산
- 남은 예산
- 추가 후 총 수량
- 추가 후 총 투자금
- 추가 후 평균단가
- 손익분기점
- 목표가 기준 손익, optional
- 수수료/세금 미포함 안내

결과 박스 권장 문구:

```text
이 결과는 입력값 기준 계산용 시뮬레이션입니다.
주문을 실행하지 않습니다.
매수/매도 추천이 아니며 수익을 보장하지 않습니다.
수수료와 세금은 포함하지 않습니다.
```

금지 표시:

- 매수하세요
- 추천 수량
- 수익 보장
- 주문 완료
- 자동매매
- 주문번호
- 주문 상태

## 9. 상태 처리

UI 상태:

- `idle`
- `loading`
- `success`
- `validation_error`
- `server_error`

상태별 정책:

### idle

- form 닫힘 또는 입력 대기 상태.
- 안전 문구는 form 근처에 표시한다.

### loading

- `계산 중...` 표시.
- 버튼 중복 클릭을 방지한다.
- loading 상태도 주문 진행처럼 보이지 않게 `계산 중`으로만 표현한다.

### success

- 계산 결과를 렌더링한다.
- `simulation_only=true`와 `order_execution=false` 의미를 명시한다.
- 주문 ID나 주문 상태는 표시하지 않는다.

### validation_error

- safe error code/message를 표시한다.
- field별 오류가 있으면 해당 입력 아래에 표시한다.
- raw exception을 표시하지 않는다.

### server_error

- 민감정보 없는 일반 오류를 표시한다.
- 예: `계산 결과를 가져오지 못했습니다. 잠시 후 다시 시도하세요.`
- stack trace, raw response, header를 표시하지 않는다.

## 10. 접근성 / progressive enhancement

MVP는 JavaScript 기반 inline form을 사용할 수 있다.

원칙:

- JavaScript가 없어도 Portfolio Summary table은 정상 표시되어야 한다.
- Simulation UI는 progressive enhancement로 동작한다.
- toggle은 `<button type="button">`을 사용한다.
- form label은 input `id`와 연결한다.
- 결과 영역에는 `aria-live="polite"`를 사용한다.
- loading 상태는 버튼 텍스트와 `aria-busy`로 표현한다.
- keyboard만으로 form 열기, 입력, 계산, 닫기가 가능해야 한다.
- 색상만으로 손익 상태를 구분하지 않는다.
- 오류 메시지는 field와 인접하게 표시하고, 결과 영역에도 요약한다.

반응형:

- 모바일에서는 table 가로 스크롤이 유지되어야 한다.
- simulation row는 table 아래 full-width 영역으로 보이게 한다.
- 입력 필드는 한 줄에 억지로 배치하지 않고 세로 stack을 허용한다.

## 11. 보안 정책

- 화면은 `request.user`의 holdings만 렌더링한다.
- API도 `request.user` owner scope를 적용한다.
- holding id가 DOM에 노출될 수 있으나 서버에서 owner scope를 반드시 재검증한다.
- username/email/user id는 화면에 표시하지 않는다.
- accountNo/accountSeq는 화면/API에 없다.
- Toss token/header는 화면/API에 없다.
- raw response를 표시하지 않는다.
- CSRF 보호가 필요하다.
- 주문 실행 버튼은 없다.
- 자동매매 UI는 없다.
- localStorage/sessionStorage에 민감정보를 저장하지 않는다.

## 12. 데이터 변경 정책

- Portfolio Summary 화면 조회는 DB write를 하지 않는다.
- Simulation API 호출도 DB write를 하지 않는다.
- `DataIngestionLog`를 생성하지 않는다.
- `UserHolding`, `DailyPrice`, `Stock`을 저장하거나 수정하지 않는다.
- 시뮬레이션 결과 저장은 MVP 범위가 아니다.
- 결과 저장이 필요하면 별도 schema, consent, retention, audit 정책을 먼저 설계한다.

## 13. 화면 mock 구조

아래는 구조 예시이며 실제 holding id, user id, account, token 값을 포함하지 않는다.

```html
<tr>
  <td>035250</td>
  <td>강원랜드</td>
  <td>2</td>
  <td>15116.50</td>
  <td>16340.00</td>
  <td>8.09%</td>
  <td>
    <button type="button" class="simulation-toggle" aria-expanded="false">
      평균단가 계산
    </button>
  </td>
</tr>
<tr class="simulation-row" hidden>
  <td colspan="13">
    <form data-holding-id="<HOLDING_ID>">
      <p>계산 전용이며 주문을 실행하지 않습니다.</p>

      <label for="additional-budget-<HOLDING_ID>">추가 예산</label>
      <input
        id="additional-budget-<HOLDING_ID>"
        name="additional_budget"
        inputmode="decimal"
        autocomplete="off"
      >

      <label for="buy-price-<HOLDING_ID>">계산 기준 가격</label>
      <input
        id="buy-price-<HOLDING_ID>"
        name="buy_price"
        inputmode="decimal"
        autocomplete="off"
      >

      <label for="target-price-<HOLDING_ID>">목표가 기준 계산</label>
      <input
        id="target-price-<HOLDING_ID>"
        name="target_price"
        inputmode="decimal"
        autocomplete="off"
      >

      <button type="button">계산하기</button>
    </form>

    <div class="simulation-result" aria-live="polite"></div>
    <p>매수/매도 추천이 아니며 수익을 보장하지 않습니다.</p>
  </td>
</tr>
```

주의:

- `<HOLDING_ID>`는 placeholder다.
- user id, account, token 예시를 넣지 않는다.
- button 문구를 `매수하기`, `주문하기`로 바꾸지 않는다.

## 14. JavaScript 동작 설계

기능:

1. `평균단가 계산` 버튼 클릭 시 해당 row의 form을 표시/숨김한다.
2. form 입력값을 수집한다.
3. CSRF token을 읽어 request header에 포함한다.
4. `POST /api/holdings/{id}/additional-buy-simulation/`를 호출한다.
5. `loading` 상태를 표시한다.
6. 성공 시 결과를 렌더링한다.
7. HTTP 400이면 safe error code/message를 표시한다.
8. 네트워크 오류 또는 500이면 일반 오류를 표시한다.
9. 결과 영역에 `주문을 실행하지 않습니다` 문구를 유지한다.

금지:

- Toss API 직접 호출
- secret/token/header 직접 다루기
- account header 생성
- 주문 API 호출
- localStorage에 민감정보 저장
- raw response 전체 표시
- order id/orderNo/order status 표시

결과 렌더링 필드:

- `current_position.quantity`
- `current_position.average_price`
- `current_position.invested_amount`
- `current_position.market_value`
- `current_position.profit_loss_rate`
- `simulation.additional_quantity`
- `simulation.additional_invested_amount`
- `simulation.unused_budget`
- `simulation.new_quantity`
- `simulation.new_average_price`
- `simulation.break_even_price`
- `target_projection.target_profit_loss_rate`, optional
- `warnings`

## 15. 테스트 전략

후속 Step O 구현 시 테스트할 항목:

1. 화면에 `평균단가 계산` 버튼이 표시된다.
2. `매수하기`, `주문하기`, `자동매매` 버튼이 없다.
3. JavaScript 없이도 Portfolio Summary가 표시된다.
4. 인증 사용자만 화면에 접근할 수 있다.
5. 다른 user holding은 표시되지 않는다.
6. inactive holding은 기본 제외된다.
7. form endpoint가 owner-scoped holding id에 연결된다.
8. API mock success 결과가 화면에 표시된다.
9. API validation error가 safe하게 표시된다.
10. API response의 `order_execution=false`가 확인된다.
11. 화면 조회는 DB write를 하지 않는다.
12. simulation 호출은 DB write를 하지 않는다.
13. `DataIngestionLog`가 생성되지 않는다.
14. Toss API가 호출되지 않는다.
15. username/email/account/token/header가 표시되지 않는다.
16. CSRF token을 사용한다.
17. 결과 영역에 `계산 전용`, `주문 없음`, `수익 보장 아님` 문구가 표시된다.

## 16. 단계별 구현 계획

### Step O1: template에 inline form skeleton 추가

- 각 holding row에 `평균단가 계산` 버튼 추가.
- 각 holding row 아래 hidden simulation row 추가.
- form, 결과 영역, 안전 문구 추가.
- holding id 노출 방식은 owner-scoped로 제한.

### Step O2: lightweight JavaScript 추가

- toggle 동작.
- `fetch` POST.
- CSRF header 포함.
- success/error 렌더링.
- 중복 클릭 방지.

### Step O3: 화면 smoke

- 인증 없는 접근 확인.
- 인증 사용자 화면 렌더링 확인.
- simulation UI 표시 확인.
- DB write 없음 확인.
- Toss API 호출 없음 확인.

### Step O4: 표현 안전 점검

- Step M 정책 재검증.
- 금지 표현 grep.
- 버튼/링크가 주문 UI처럼 보이지 않는지 확인.

### Step O5: 사용자 피드백 반영

- 입력 UX 개선.
- 모바일 table/row 확장 UX 조정.
- optional live quote는 계속 보류.

## 17. 금지/보류 항목

금지:

- 주문 생성/정정/취소
- Order API 호출
- Order History/Info API 호출
- 매수 가능 금액 API 호출
- 매도 가능 수량 API 호출
- 자동매매
- 조건 충족 시 자동 주문
- 계좌 선택 UI
- 주문 수량/주문 유형 입력
- `매수하기`, `매도하기`, `주문하기` 버튼
- `추천 매수`, `수익 보장` 문구

보류:

- simulation 결과 저장
- live quote 연결
- 수수료/세금 모델
- 다중 종목 예산 배분
- Portfolio 전체 기준 simulation
- 별도 simulation detail page

주문 API는 계속 비활성 상태를 유지한다.
