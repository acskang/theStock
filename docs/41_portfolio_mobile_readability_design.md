# Portfolio Mobile Readability Design

## 1. 목적

이 문서는 Portfolio Summary 화면의 모바일 가독성 개선 방향을 정리한다.

현재 화면은 `GET /portfolio/summary/`에서 저장된 `UserHolding`과 최신 `DailyPrice`를 기반으로 read-only 포트폴리오 요약과 Additional Buy Simulation inline UI를 제공한다. 기능은 정상 동작하고 있으며, 이번 문서는 코드/template/JS/CSS를 수정하지 않고 후속 구현 방향만 설계한다.

목표:

- 작은 리스크로 모바일에서 보유종목 table을 읽기 쉽게 만든다.
- Simulation form과 결과 영역을 좁은 화면에서도 입력/확인하기 쉽게 만든다.
- 계산 전용, 주문 미실행, 투자 권유 아님, 수익 보장 아님 문구를 유지한다.
- 주문 버튼, 자동매매 UI, 매수/매도 추천처럼 보이는 표현을 만들지 않는다.

## 2. 현재 화면 구조

현재 Portfolio Summary 화면:

- template: `portfolio/templates/portfolio/summary.html`
- route: `GET /portfolio/summary/`
- view: `portfolio_summary_page`
- auth: `login_required`
- CSS:
  - Bootstrap 5.3.3 CDN을 직접 로드한다.
  - `portfolio/static/portfolio/css/styles.css`를 로드한다.
- JS:
  - template 하단에 inline JavaScript가 있다.
  - `simulation-toggle`, `simulation-submit`, `fetch`, `X-CSRFToken`, `credentials: same-origin`을 사용한다.
- base:
  - `portfolio/templates/portfolio/base.html`도 존재하지만 Summary 화면은 현재 standalone HTML이다.

현재 holdings table:

- Bootstrap `.table`, `.table-striped`, `.table-hover`, `.align-middle` 사용.
- `.table-responsive` wrapper가 이미 있다.
- 컬럼:
  - Code
  - Name
  - Market
  - Qty
  - Average
  - 최근 일봉 종가
  - 일봉 기준일
  - Invested
  - Value
  - P/L
  - P/L %
  - Price status
  - Simulation
- `portfolio/static/portfolio/css/styles.css`에는 `.table td, .table th { white-space: nowrap; }`가 있어 숫자와 label 줄바꿈은 줄지만, 모바일에서 전체 table 폭은 커질 수 있다.

현재 Simulation form:

- 각 holding row 바로 아래 hidden `<tr>`에 form이 있다.
- form은 table cell 안의 block으로 렌더링된다.
- 입력:
  - `additional_budget`
  - `buy_price`
  - `target_price`
- Bootstrap grid:
  - `col-12 col-md-4`
  - 모바일에서는 세로 1열, md 이상에서는 3열이다.
- 결과 영역:
  - `.simulation-result`
  - `aria-live="polite"`
  - JS가 성공/오류 메시지를 안전하게 렌더링한다.

## 3. 모바일 가독성 문제 진단

### Portfolio Summary table

진단:

- holdings table의 컬럼 수가 13개로 많다.
- 종목 식별, 수량, 평균단가, 최근 일봉 종가, 일봉 기준일, 투자금, 평가금액, 손익, price status, simulation action이 한 행에 들어간다.
- 모바일 화면에서는 가로 폭이 부족해 좌우 스크롤이 필요할 가능성이 높다.
- 공통 CSS의 `white-space: nowrap` 때문에 숫자와 header는 읽기 좋지만, table 전체 폭은 더 넓어진다.
- 사용자가 가로 스크롤 가능성을 인지하지 못하면 오른쪽 컬럼, 특히 `Simulation` 버튼을 찾기 어려울 수 있다.

### Simulation inline form

진단:

- form이 table 내부 hidden row에 있어 모바일에서 table scroll context와 form 입력 context가 겹칠 수 있다.
- 입력 필드는 Bootstrap grid 덕분에 모바일에서 세로 배치가 되지만, table cell 자체가 넓은 table 안에 있으므로 화면에 맞는 block처럼 보이지 않을 수 있다.
- `additional_budget`, `buy_price`, `target_price`는 모바일 키보드 입력이 필요해 충분한 터치 영역과 label/help text가 중요하다.
- result 영역은 여러 metric과 warning 문구가 쌓여 길어질 수 있다.

### 안전 문구

진단:

- 계산 전용, 주문 미실행, 매수/매도 추천 아님, 수익 보장 아님, 수수료/세금 제외 문구는 유지해야 한다.
- 모바일에서는 안전 문구가 길어져 핵심 숫자보다 먼저 화면을 많이 차지할 수 있다.
- 그러나 안전 문구를 제거하면 투자 권유 또는 주문 실행처럼 오해될 수 있으므로 축약하더라도 의미는 유지해야 한다.

### 터치 UX

진단:

- `평균단가 계산` 버튼은 table 마지막 컬럼에 있어 모바일에서 도달하려면 스크롤이 필요하다.
- `계산하기` 버튼은 `btn-sm`이라 터치 영역이 작게 느껴질 수 있다.
- form input은 기본 Bootstrap control이라 터치 가능하지만, 좁은 화면에서는 full width와 충분한 vertical spacing이 더 적합하다.
- 결과 영역과 오류 영역은 사용자가 계산 버튼을 누른 뒤 바로 인지할 수 있어야 한다.

## 4. 개선 후보 비교

### 후보 A: 기존 table 유지 + 가로 스크롤 wrapper

설명:

- 기존 table 구조를 유지한다.
- holdings table을 명시적 scroll wrapper로 감싼다.
- `overflow-x: auto`, `-webkit-overflow-scrolling: touch`를 적용한다.
- 모바일 안내 문구를 추가한다.

장점:

- 구현이 가장 간단하다.
- 기존 template 변경이 작다.
- JS와 API 연결 구조를 거의 건드리지 않는다.
- 테스트 영향이 작다.
- 현재 MVP 안정성을 유지하기 쉽다.

단점:

- 사용자는 여전히 좌우 스크롤을 해야 한다.
- 모바일 UX는 근본적으로 card layout보다 제한적이다.
- 마지막 컬럼의 `평균단가 계산` 버튼을 찾기 어려울 수 있다.

### 후보 B: 모바일에서 holding card layout으로 전환

설명:

- desktop은 table을 유지한다.
- 모바일에서는 각 holding을 card로 표시한다.
- card에는 핵심 정보와 Simulation form/result를 함께 둔다.

장점:

- 모바일 가독성이 가장 좋다.
- 종목별 정보와 simulation 결과의 관계가 명확하다.
- 터치 영역과 result 영역을 자연스럽게 구성할 수 있다.

단점:

- template 변경이 크다.
- desktop/mobile 중복 markup 또는 더 복잡한 CSS가 필요하다.
- 테스트 보강 범위가 커진다.
- 동일 데이터를 table과 card에 모두 렌더링하면 민감정보/금지 표현 검증 지점이 늘어난다.

### 후보 C: table 축약 + detail disclosure

설명:

- 모바일 table에는 핵심 컬럼만 보여준다.
- 보조 정보는 `상세 보기` disclosure로 펼친다.

장점:

- table과 card의 중간 형태다.
- 기존 table 구조를 일부 유지하면서 모바일 표시량을 줄일 수 있다.

단점:

- 어떤 컬럼을 숨길지 정책이 필요하다.
- `aria-expanded`, `aria-controls`, keyboard interaction을 관리해야 한다.
- Simulation row와 detail row가 겹치면 구조가 복잡해질 수 있다.

### 후보 D: 별도 mobile summary page

설명:

- `/portfolio/summary/mobile/` 같은 별도 route를 만든다.

장점:

- 모바일 전용 UX를 완전히 최적화할 수 있다.

단점:

- route와 template 유지보수 부담이 늘어난다.
- desktop/mobile 기능 차이가 생길 수 있다.
- MVP에는 과하다.

## 5. 권장 방향

권장:

- 단기: 후보 A를 적용한다.
- 중기: 사용자 피드백이 계속 불편하다고 판단되면 후보 B를 별도 설계한다.

이유:

- 현재 MVP는 화면/API/Simulation 연결이 이미 검증된 상태다.
- 모바일 가독성은 중요하지만, 큰 template 재구성은 안정성을 흔들 수 있다.
- 우선 table horizontal scroll, scroll 안내, form/button touch 개선을 적용하면 작은 변경으로 체감 개선이 가능하다.
- card layout은 사용자 피드백과 실제 모바일 사용 패턴을 더 본 뒤 결정하는 것이 안전하다.

단계:

1. Step Q4A: table horizontal scroll + form vertical/touch 개선 구현.
2. Step Q4B: 화면 smoke.
3. Step Q4C: 실제 모바일 사용자 피드백 수집.
4. Step Q4D: card layout 전환 여부 결정.

## 6. 단기 개선안

### table wrapper

후속 구현 후보:

```html
<p class="small text-secondary d-md-none">
  표를 좌우로 스크롤할 수 있습니다.
</p>
<div class="portfolio-table-scroll" tabindex="0" aria-label="보유 종목 표, 좌우 스크롤 가능">
  ...
</div>
```

CSS 후보:

```css
.portfolio-table-scroll {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.portfolio-table-scroll table {
  min-width: 960px;
}
```

주의:

- 현재 `.table-responsive`가 이미 있으므로, 후속 구현에서는 Bootstrap wrapper를 유지할지 custom class로 대체/확장할지 선택한다.
- `tabindex="0"`는 keyboard 사용자가 scroll 영역에 접근할 수 있도록 검토한다.
- mobile 안내 문구는 desktop에서는 숨기는 것이 좋다.

### horizontal scroll

정책:

- table 전체를 억지로 줄이지 않는다.
- 숫자와 금액은 줄바꿈으로 깨지지 않게 유지한다.
- 사용자가 스크롤 가능함을 안내한다.
- `Simulation` column이 너무 멀면 후속으로 첫 번째 또는 두 번째 column 쪽 action 위치를 재검토한다.

### form vertical layout

현재 form은 `col-12 col-md-4`라 모바일에서 이미 세로 배치된다.

후속 개선:

- 모바일에서 `.simulation-submit`을 full width 또는 충분한 padding으로 확대한다.
- input과 도움말 사이 간격을 유지한다.
- result 영역을 table cell 안에서도 독립 block처럼 보이게 한다.

CSS 후보:

```css
@media (max-width: 768px) {
  .simulation-submit {
    width: 100%;
    min-height: 44px;
  }

  .simulation-result {
    display: block;
    padding: 0.75rem;
    border: 1px solid var(--app-border);
    border-radius: 0.5rem;
    background: var(--app-surface);
  }
}
```

### mobile 안내 문구

후속 구현 문구 후보:

```text
표를 좌우로 스크롤할 수 있습니다.
가격은 저장된 최근 일봉 종가 기준이며 실시간 가격이 아닙니다.
```

주의:

- 안내는 짧게 유지한다.
- 주문이나 추천처럼 보이는 문구를 넣지 않는다.

### safety copy

모바일 축약 문구 후보:

```text
계산 전용입니다. 주문을 실행하지 않습니다.
매수/매도 추천이 아니며 수익을 보장하지 않습니다.
수수료와 세금은 포함하지 않습니다.
```

정책:

- 문구가 길어도 삭제하지 않는다.
- 결과 영역에도 `order_execution=false`의 의미가 계속 드러나야 한다.

## 7. Simulation form 모바일 설계

모바일 form 원칙:

- label은 input 위에 둔다.
- input은 width 100%를 유지한다.
- 도움말은 input 바로 아래에 둔다.
- `계산하기` 버튼은 충분한 터치 영역을 가진다.
- result 영역은 `aria-live="polite"`를 유지한다.
- 오류 메시지는 result 영역에 안전 문구로 표시한다.
- raw response 전체를 표시하지 않는다.

권장 표시 순서:

1. 안전 문구.
2. 추가 예산.
3. 계산 기준 가격.
4. 목표가 기준 계산.
5. 계산하기 버튼.
6. 계산 결과 또는 오류.

결과 영역 모바일 표시:

- 추가 가능 수량.
- 사용 예산.
- 남은 예산.
- 추가 후 총 수량.
- 추가 후 평균단가.
- 손익분기점.
- 최근 일봉 종가 기준 예상 손익률.
- target projection은 있을 때만 표시.
- 계산 전용/주문 미실행/추천 아님 문구.

## 8. 정보 우선순위

### 핵심 정보

모바일에서 우선 노출해야 할 정보:

- 종목명/code.
- 보유 수량.
- 평균단가.
- 최근 일봉 종가.
- 평가손익률.
- 평가손익금액.
- 평균단가 계산 버튼.

### 보조 정보

가로 스크롤 또는 상세 영역에 남겨도 되는 정보:

- 시장.
- 일봉 기준일.
- 투자금.
- 평가금액.
- `price_status`.
- warnings.

### 숨김/접힘 후보

후속 card/disclosure layout에서 접힘 후보:

- 상세 totals.
- 세부 warnings.
- target projection 상세.
- `price_status`의 기술적 문자열.

## 9. 접근성 기준

후속 구현에서 지킬 기준:

- `simulation-toggle`의 `aria-expanded`를 유지한다.
- `simulation-toggle`의 `aria-controls`를 유지한다.
- result 영역의 `aria-live="polite"`를 유지한다.
- form label과 input id 연결을 유지한다.
- scroll wrapper에 필요 시 `aria-label`을 둔다.
- scroll wrapper에 keyboard focus 가능성을 검토한다.
- 버튼 터치 영역은 충분히 확보한다.
- 색상만으로 손익을 구분하지 않는다.
- 숫자 값은 텍스트로 표시한다.
- mobile 안내 문구를 제공한다.

## 10. 표현 안전성 유지

모바일 개선에서도 다음 원칙을 유지한다.

- `매수하기`, `매도하기`, `주문하기` 버튼을 만들지 않는다.
- `평균단가 계산`과 `계산하기`만 사용한다.
- `추천`, `수익 보장`, `자동매매` 표현을 CTA로 사용하지 않는다.
- safety copy는 화면 크기가 작아도 유지한다.
- Simulation 결과에는 주문을 실행하지 않는다는 의미를 계속 표시한다.
- 주문 API, Order API, Order History, Order Info, 매수 가능 금액, 매도 가능 수량 API를 연결하지 않는다.
- `simulation_only=true`, `order_execution=false` 정책을 유지한다.

## 11. 테스트 전략

후속 구현 Step Q4A에서 테스트할 항목:

1. table scroll wrapper class가 존재한다.
2. 모바일 scroll 안내 문구가 존재한다.
3. `additional_budget`, `buy_price`, `target_price` input이 계속 존재한다.
4. `simulation-toggle`, `simulation-submit`, `data-simulation-endpoint`가 계속 존재한다.
5. `aria-expanded`, `aria-controls`, `aria-live="polite"`가 유지된다.
6. 계산 전용, 주문 미실행, 매수/매도 추천 아님, 수익 보장 아님, 수수료/세금 제외 문구가 유지된다.
7. 금지 CTA가 없다.
8. username, email, user id, account, token, header, raw response가 화면에 없다.
9. 화면 조회 전후 DB count 변화가 없다.
10. `DataIngestionLog` 생성이 없다.
11. Toss API 호출이 없다.
12. 주문 API 호출이 없다.

한계:

- Django template test는 실제 CSS rendering, 터치 영역, iOS/Android scroll 감각을 완전히 검증하지 못한다.
- 자동 테스트는 class/markup/safety 문구 중심으로 작성한다.
- 실제 모바일 브라우저 smoke는 별도 수동 확인이 필요하다.

## 12. 구현 단계 제안

### Step Q4A: 최소 모바일 가독성 개선 구현

- holdings table scroll wrapper 추가.
- 모바일 안내 문구 추가.
- form/button mobile class 추가.
- 기존 `portfolio/static/portfolio/css/styles.css` 활용 우선.
- 필요 시 template 내 inline style 대신 static CSS에 작게 추가.
- 테스트 보강.

### Step Q4B: 모바일 화면 smoke

- RequestFactory 또는 Django test client로 렌더링 확인.
- 주요 문구와 markup 확인.
- 금지 CTA와 민감정보 미포함 확인.
- DB count 변화 없음 확인.

### Step Q4C: 사용자 피드백 수집

- iOS Safari narrow width 확인.
- Android Chrome narrow width 확인.
- desktop browser responsive mode 확인.
- table scroll 안내 이해 여부 확인.
- Simulation form 입력 편의성 확인.

### Step Q4D: card layout 설계 여부 결정

- 여전히 table scroll이 불편하면 card layout을 별도 설계한다.
- card layout에서는 종목별 핵심 정보와 Simulation UI를 한 card 안에 둔다.
- desktop table과 mobile card의 중복 rendering에 따른 테스트/보안 검증을 추가한다.

## 13. 보류 항목

이번 설계에서 보류하는 항목:

- 모바일 card layout 즉시 구현.
- 별도 mobile page.
- frontend framework 도입.
- 새 CSS framework 도입.
- Tailwind, Bulma, Vite, webpack 도입.
- Toss live quote UI.
- optional live quote API 호출.
- 주문 버튼.
- 자동매매.
- 매수/매도 추천 표현.
- 수익 보장 표현.
- 계좌/token/header/raw response 노출.
