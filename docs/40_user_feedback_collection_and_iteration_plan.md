# User Feedback Collection and Iteration Plan

## 1. 목적

이 문서는 Portfolio Summary and Simulation MVP 배포 후 사용자 피드백을 어떻게 수집하고, 어떤 기준으로 분류해 후속 작업에 반영할지 정의한다.

현재 MVP는 저장된 `UserHolding`과 `DailyPrice`를 기반으로 포트폴리오 요약과 평균단가 계산 시뮬레이션을 제공한다. 기능은 read-only이며 주문 실행, 자동매매, 매수/매도 추천, 수익 보장을 포함하지 않는다.

피드백 반영 원칙:

- 사용자 가치가 명확한 작은 UI/문구 개선은 빠르게 반영한다.
- 계산 공식, API schema, DB schema, Toss API 사용이 바뀌는 요청은 설계 문서를 먼저 작성한다.
- 주문 API, 자동 주문, 수익 보장, 민감정보 표시 요청은 금지 또는 보류한다.
- 모든 후속 작업은 `simulation_only=true`, `order_execution=false`, DB-only/read-only 정책을 훼손하지 않아야 한다.

## 2. 현재 MVP 상태

배포 후 smoke 기준 완료 상태:

- Step S 운영 배포 전 최종 점검 PASS.
- Step T 배포 후 smoke PASS.
- `GET /portfolio/summary/` 화면 정상.
- `GET /api/portfolio/summary/` 정상.
- `POST /api/holdings/{id}/additional-buy-simulation/` 정상.
- Simulation inline UI 정상.
- 화면/API 호출 전후 DB count 변화 없음.
- `DataIngestionLog` 생성 없음.
- Toss API 호출 없음.
- 주문 API 호출 없음.
- 민감정보 노출 없음.
- 금지 CTA 없음.

마지막 수동 검증 기준:

| Model | Count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 3 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 85 |

사용자 기능:

- Portfolio Summary 화면
  - `GET /portfolio/summary/`
  - 로그인 사용자 자신의 보유 현황 요약.
  - 보유종목, 평균단가, 최신가, 평가금액, 손익률 표시.
  - Simulation inline UI 포함.
  - 주문 버튼 없음.
- Portfolio Summary API
  - `GET /api/portfolio/summary/`
  - DB-only read-only JSON API.
- Additional Buy Simulation API
  - `POST /api/holdings/{id}/additional-buy-simulation/`
  - 추가 예산 기준 평균단가 계산.
  - `simulation_only=true`.
  - `order_execution=false`.
  - DB-only read-only calculation.

## 3. 피드백 수집 대상

### 내부 운영자

확인할 항목:

- `/portfolio/summary/` 화면 접근이 쉬운가.
- 인증/권한 동작이 자연스러운가.
- 운영 command 정책이 이해되는가.
- 운영 DB count와 `DataIngestionLog` 정책이 명확한가.
- 배포 전/후 smoke 절차가 충분한가.
- no-network command도 `DataIngestionLog` row를 만들 수 있다는 점이 명확한가.

### 실제 사용자 또는 테스트 사용자

확인할 항목:

- 포트폴리오 요약이 이해되는가.
- 평균단가, 평가금액, 손익률 표시가 유용한가.
- "최신가"가 실시간 가격이 아니라 저장된 최신 일봉 종가 기준임을 이해하는가.
- 추가 예산 기반 평균단가 계산 입력이 쉬운가.
- 계산 결과가 투자 권유가 아니라 참고용 계산이라는 점이 명확한가.
- 모바일과 데스크톱에서 화면을 읽기 쉬운가.
- 안전 문구가 충분하면서도 사용을 방해하지 않는가.

### 개발자

확인할 항목:

- service/API/template 경계가 유지보수하기 쉬운가.
- 테스트가 충분한가.
- owner scope와 민감정보 제외 정책이 코드에서 확인하기 쉬운가.
- optional live quote, 수수료/세금, batch commit 같은 후속 기능의 영향 범위가 명확한가.
- 주문 API 비활성 정책이 후속 작업에서도 흔들리지 않는가.

## 4. 피드백 질문지

### Portfolio Summary 화면 질문

- [ ] 보유종목 목록이 이해하기 쉬운가.
- [ ] 평균단가, 최신가, 평가금액, 손익률이 명확한가.
- [ ] 최신가가 실시간 가격이 아니라 저장된 일봉 기준임을 이해했는가.
- [ ] 수익률/손익 표시 형식이 보기 좋은가.
- [ ] warning과 안전 문구가 과하거나 부족하지 않은가.
- [ ] 모바일 화면에서 표가 보기 쉬운가.
- [ ] 추가로 보고 싶은 항목이 있는가.
- [ ] "Latest" 또는 "최신가" label이 사용자에게 충분히 명확한가.

### Additional Buy Simulation 질문

- [ ] 추가 예산 입력 방식이 이해하기 쉬운가.
- [ ] 계산 기준 가격을 비우면 저장된 최신가를 사용한다는 점이 이해되는가.
- [ ] 목표가 기준 계산이 이해되는가.
- [ ] 추가 가능 수량, 남은 예산, 새 평균단가가 유용한가.
- [ ] "주문을 실행하지 않습니다"라는 점이 명확한가.
- [ ] 결과가 매수/매도 추천이 아니라 계산용이라는 점이 명확한가.
- [ ] 수수료와 세금 미포함 안내가 충분한가.
- [ ] validation error가 이해하기 쉬운가.

### 안전/신뢰 질문

- [ ] 계좌 정보가 화면에 보이지 않아 안심되는가.
- [ ] 주문 버튼이 없어 혼동이 없는가.
- [ ] "수익을 보장하지 않습니다" 문구가 충분한가.
- [ ] 투자 조언처럼 느껴지는 문구가 있는가.
- [ ] 화면/API 결과에 사용자 식별자, 계좌, token, raw response가 없다는 점이 신뢰에 도움이 되는가.

## 5. 피드백 분류 기준

### A. 즉시 반영 후보

조건:

- 문구 개선.
- label 개선.
- 화면 배치 개선.
- warning 문구 개선.
- 테스트 추가.
- DB schema 변경 없음.
- Toss API 호출 없음.
- 주문 API 무관.

예:

- "최신가"를 "최근 일봉 종가"로 바꾸기.
- "Latest" label을 한국어로 통일하기.
- "수익률"에 기준 설명 추가.
- 계산 결과의 "수수료와 세금 미포함" 문구 위치 개선.
- 모바일 표 가독성 개선 중 CSS/template 범위에 머무는 작업.

처리:

- 작은 Step으로 구현한다.
- `python manage.py check`와 관련 테스트를 실행한다.
- 금지 표현 grep과 민감정보 grep을 유지한다.

### B. 설계 후 반영 후보

조건:

- API 변경 필요.
- service 계산 변경 필요.
- JavaScript 결과 표시 변경 필요.
- 추가 테스트 필요.
- 사용자 영향 중간.
- 투자 조언 오해 가능성 검토 필요.

예:

- 수수료/세금 입력 추가.
- `additional_quantity` 직접 입력 지원.
- `target_price` 결과 UI 개선.
- Portfolio Summary에 market/sector grouping 추가.
- 계산 결과에 기준일과 데이터 출처 설명 강화.

처리:

- 설계 문서를 먼저 작성한다.
- request/response schema와 validation 정책을 정리한다.
- DB write, Toss API 호출, 주문 API 관련 여부를 별도로 점검한다.

### C. 별도 프로젝트 후보

조건:

- DB schema 변경 필요.
- batch commit 필요.
- scheduler 필요.
- live quote 필요.
- 운영 리스크 있음.
- rollback 계획이 필요함.

예:

- optional live quote UI.
- DailyPrice batch commit.
- UserHolding 대량 sync.
- `DataProviderStatus` 자동 갱신.
- alerting 연동.
- US/fractional holdings 저장.
- currency field 확장.

처리:

- 별도 milestone으로 분리한다.
- 운영 command policy와 DB backup 필요 여부를 먼저 검토한다.
- smoke, rollback, monitoring 계획을 포함한다.

### D. 금지/보류

조건:

- 주문 API 관련 요청.
- 자동매매 또는 자동 주문 요청.
- 매수/매도 추천 요청.
- 수익 보장 요청.
- 계좌 원문 표시 요청.
- token, secret, raw response 저장/출력 요청.

예:

- "추천 매수 버튼" 추가.
- "조건 충족 시 자동 주문" 추가.
- "목표 수익 보장" 표시.
- 토스 계좌번호 원문 표시.
- access token 표시.
- raw Toss response 전체 저장 또는 출력.

처리:

- 구현하지 않는다.
- 필요한 경우 "계산용 시뮬레이션", "저장된 데이터 기반 요약", "사용자가 직접 판단" 대체 방향으로 안내한다.
- 주문 API는 계속 비활성 상태를 유지한다.

## 6. 우선순위 판단 기준

후속 요청은 다음 기준으로 평가한다.

| 기준 | 질문 | 점수 예 |
|---|---|---|
| 사용자 가치 | 실제 사용자의 이해와 반복 사용에 도움이 되는가 | 높음 / 중간 / 낮음 |
| 안전성 | 투자 권유, 주문 실행, 민감정보 노출 위험이 낮은가 | 높음 / 중간 / 낮음 |
| DB 변경 여부 | schema나 운영 데이터 변경이 필요한가 | 없음 / 있음 |
| Toss API 호출 여부 | live/network 호출이 필요한가 | 없음 / 선택 / 필수 |
| 주문 API 관련 여부 | 주문 생성/정정/취소 또는 자동매매와 관련 있는가 | 없음 / 관련 / 직접 관련 |
| 구현 난이도 | 변경 범위와 테스트 부담이 어느 정도인가 | 낮음 / 중간 / 높음 |
| 테스트 가능성 | 자동 테스트와 smoke로 검증 가능한가 | 높음 / 중간 / 낮음 |
| rollback 가능성 | 문제 발생 시 되돌리기 쉬운가 | 높음 / 중간 / 낮음 |
| 운영 부담 | 운영 command, monitoring, failure 대응이 필요한가 | 낮음 / 중간 / 높음 |
| 투자 조언 오해 가능성 | 매수/매도 추천처럼 보일 위험이 있는가 | 낮음 / 중간 / 높음 |

추천 처리:

```text
사용자 가치 높음 + 운영 리스크 낮음 + 주문 API 무관 = 즉시 반영 후보
사용자 가치 높음 + 계산/API 변경 필요 = 설계 후 반영 후보
운영 리스크 높음 또는 DB/schema 변경 필요 = 별도 프로젝트 후보
주문 API/자동매매/수익 보장/민감정보 노출 = 금지 또는 보류
```

## 7. 예상 피드백과 선제 대응

### 최신가가 실시간이 아닌 점

예상 피드백:

- "왜 현재가와 다르냐."
- "실시간 가격이 아닌가."
- "Latest라는 label이 모호하다."

대응:

- label을 "최근 일봉 종가"로 명확히 변경하는 Step Q3를 검토한다.
- Portfolio Summary 설명에 "저장된 DailyPrice 기준" 문구를 더 가까운 위치에 둔다.
- optional live quote는 Step U에서 별도 설계한다.
- live quote가 추가되더라도 기본 MVP의 DB-only summary와 분리한다.

### 수수료/세금 미포함

예상 피드백:

- "실제 손익과 다르다."
- "수수료와 세금을 반영하고 싶다."

대응:

- 현재는 "수수료와 세금은 포함하지 않습니다" 문구를 유지한다.
- 수수료/세금 입력 또는 고정 비율 옵션은 B 분류로 설계 후 반영한다.
- 기본 계산과 fee/tax 포함 계산을 구분해 표시하는 방안을 검토한다.

### 추가매수 수량 계산

예상 피드백:

- "직접 수량을 입력하고 싶다."
- "소수점 수량이나 미국 주식도 계산하고 싶다."

대응:

- `additional_quantity` 직접 입력은 B 분류로 service/API validation 설계 후 진행한다.
- 현재 MVP는 국내 주식 정수 수량 기준이다.
- US/fractional holdings는 currency, quantity precision, market 정책이 필요하므로 C 분류로 별도 설계한다.

### 매수 추천처럼 보이는 위험

예상 피드백:

- "이 기능이 매수 추천인가."
- "계산 결과대로 매수하면 되는가."

대응:

- "계산 전용", "주문을 실행하지 않습니다", "매수/매도 추천이 아닙니다", "수익을 보장하지 않습니다" 문구를 유지한다.
- 버튼명은 "평균단가 계산" 또는 "계산하기"를 유지한다.
- "추천", "신호", "성공 확률" 같은 표현은 단독 사용하지 않는다.

### 모바일 가독성

예상 피드백:

- "표가 길다."
- "휴대폰에서 숫자를 비교하기 어렵다."

대응:

- 카드형 레이아웃 또는 responsive table 개선을 A 또는 B로 분류한다.
- 핵심 값 우선순위를 정한다.
- 모바일에서 Simulation form이 주문 UI처럼 보이지 않도록 안전 문구를 유지한다.

## 8. 피드백 반영 workflow

1. 피드백을 수집한다.
2. 화면/API/운영/계산/데이터/성능/안전 범주를 태깅한다.
3. A/B/C/D로 분류한다.
4. Red flag를 확인한다.
   - 주문 API 요구.
   - 자동 주문 요구.
   - 수익 보장 요구.
   - 계좌 원문 표시 요구.
   - token, header, raw response 노출 요구.
5. A 분류의 작은 문구/UI 개선은 독립 Step으로 구현한다.
6. B 분류의 계산/API 변경은 설계 문서를 먼저 작성한다.
7. C 분류의 DB/schema/운영 변경은 migration, backup, rollback 계획을 먼저 작성한다.
8. D 분류는 구현하지 않고 대체 안내를 정리한다.
9. 구현 후 release note 또는 관련 docs를 업데이트한다.
10. `python manage.py check`, 관련 테스트, 금지 표현 grep, 민감정보 grep을 실행한다.
11. 화면/API smoke를 재실행한다.

## 9. 금지/보류 요청 처리 정책

다음 요청은 거절 또는 보류한다.

| 요청 | 처리 | 대체 안내 |
|---|---|---|
| 주문을 실행해 달라 | 금지 | 주문은 서비스 밖에서 사용자가 직접 실행 |
| 매수/매도 추천을 자동으로 해 달라 | 금지 | 계산용 시뮬레이션과 저장 데이터 요약만 제공 |
| 조건 충족 시 자동 주문해 달라 | 금지 | 자동매매 기능 없음 |
| 수익이 보장되는 종목을 알려 달라 | 금지 | 수익 보장 표현 금지 |
| 계좌번호/accountSeq를 화면에 보여 달라 | 금지 | 계좌 원문 노출 금지 |
| access token을 보여 달라 | 금지 | token 원문 노출 금지 |
| raw Toss response를 그대로 저장/출력해 달라 | 금지 | 필요한 필드만 안전하게 mapping |
| 주문 API를 켜 달라 | 보류 | 별도 보안/법무/운영 설계 전까지 비활성 유지 |

공통 대체 문구:

```text
이 기능은 저장된 데이터와 사용자가 입력한 값을 기반으로 한 계산용 시뮬레이션입니다.
주문을 실행하지 않으며, 매수/매도 추천이나 수익 보장이 아닙니다.
실제 투자 결정과 주문은 사용자가 서비스 밖에서 직접 판단하고 실행해야 합니다.
```

## 10. 사용자 피드백 기록 양식

```markdown
## 사용자 피드백 기록

- 날짜:
- 사용자 유형:
- 화면/API:
- 피드백 내용:
- 분류: A/B/C/D
- 사용자 가치:
- 운영 리스크:
- 투자 조언 오해 가능성:
- 주문 API 관련 여부:
- 민감정보 관련 여부:
- 제안 처리:
- 담당자:
- 후속 Step:
```

분류 작성 가이드:

- `A`: 문구, label, 화면 배치처럼 즉시 반영 가능한 개선.
- `B`: API, service, validation, 계산 방식 설계가 필요한 개선.
- `C`: DB, scheduler, live quote, batch commit 등 별도 프로젝트.
- `D`: 주문 API, 자동매매, 수익 보장, 민감정보 노출 등 금지/보류.

## 11. 다음 실행 후보

- Step Q1: 실제 사용자 피드백 수집.
- Step Q2: 피드백 기반 UI 문구 개선.
- Step Q3: "최신가" 또는 `Latest` label을 "최근 일봉 종가"로 개선.
- Step Q4: 모바일 가독성 개선 설계.
- Step U: optional live quote 설계.
- Step V: DailyPrice batch commit 설계.
- 주문 API는 계속 비활성 유지.
