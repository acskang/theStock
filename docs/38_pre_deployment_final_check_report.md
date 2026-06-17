# Pre-deployment Final Check Report

## 1. 목적

이 문서는 Portfolio Summary and Simulation MVP 운영 배포 전 최종 점검 결과를 기록한다.

점검 범위는 이미 구현된 화면/API/service의 read-only 동작, 인증/owner scope, 안전 문구, 민감정보 노출 여부, 주문 API/자동매매 비활성 상태, DB count 불변 여부이다.

이번 점검에서는 코드, template, JavaScript, settings, migration, schema를 수정하지 않았다. Toss API smoke command, no-network command, 저장 command, scheduler command, 주문 API는 실행하지 않았다.

## 2. 점검 대상

대상 기능:

- Portfolio Summary API
  - `GET /api/portfolio/summary/`
  - `PortfolioSummaryAPIView`
  - `build_portfolio_summary(...)`
- Portfolio Summary 화면
  - `GET /portfolio/summary/`
  - `portfolio_summary_page`
  - `portfolio/summary.html`
- Additional Buy Simulation API
  - `POST /api/holdings/{id}/additional-buy-simulation/`
  - `UserHoldingViewSet.additional_buy_simulation`
  - `build_additional_buy_simulation(...)`
- Portfolio Summary 화면 inline simulation UI
  - `simulation-toggle`
  - `simulation-submit`
  - `data-simulation-endpoint`

참고 문서:

- `docs/37_release_notes_portfolio_simulation_mvp.md`
- `docs/35_investment_advice_wording_safety_policy.md`
- `docs/34_portfolio_and_simulation_api_reference.md`
- `docs/27_operational_command_policy.md`
- `docs/28_sensitive_order_db_safety_checklist.md`

## 3. check/test 결과

실행 결과:

```text
python manage.py check
System check identified no issues (0 silenced).
```

```text
python manage.py test
Ran 392 tests
OK
```

주의:

- 전체 테스트 실행 중 기존 테스트 DB 기반 management command 테스트 로그가 출력되었다.
- 운영 DB에 대해 no-network command, 실제 Toss command, 저장 command, scheduler command는 직접 실행하지 않았다.

판정: PASS

## 4. settings 안전 상태

settings 기준 확인 결과:

```text
TOSS_ORDER_EXECUTION_ENABLED: False
TOSS_INVEST_PROVIDER_ENABLED: True
```

판정:

- 주문 실행 flag는 비활성 상태이다.
- Toss provider enabled 여부는 boolean만 확인했고 secret/account/token 원문은 출력하지 않았다.

판정: PASS

## 5. DB count 변화

smoke 전:

| Model | Count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 3 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 85 |

smoke 후:

| Model | Count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 3 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 85 |

변화:

- `Stock`: 변화 없음
- `DailyPrice`: 변화 없음
- `UserHolding`: 변화 없음
- `DataProviderStatus`: 변화 없음
- `DataIngestionLog`: 변화 없음

판정: PASS

## 6. Portfolio Summary API smoke

호출 방식:

- `APIClient.force_authenticate`
- `HTTP_HOST=localhost`
- `GET /api/portfolio/summary/`

결과:

```text
status_code: 200
holding_count: 1
priced_holding_count: 1
missing_price_count: 0
```

확인된 holding summary:

```text
stock_code: 035250
stock_name: 강원랜드
quantity: 2
average_price: 15116.50
latest_price: 16340.00
market_value: 32680.00
profit_loss_rate: 8.09
price_status: priced
```

금지 key 포함 여부:

- `username`: False
- `email`: False
- `user_id`: False
- `accountNo`: False
- `accountSeq`: False
- `X-Tossinvest-Account`: False
- `access_token`: False
- `Authorization`: False
- `raw_response`: False
- `order_id`: False
- `orderNo`: False

판정: PASS

## 7. Portfolio Summary 화면 smoke

호출 방식:

- `RequestFactory`
- `HTTP_HOST=localhost`
- `request.user` 직접 지정
- `GET /portfolio/summary/`

결과:

```text
status_code: 200
```

표시 확인:

- `포트폴리오`: True
- `035250`: True
- `강원랜드`: True
- `평균단가`: True
- `Latest`: True
- `16340.00`: True
- `평가금액`: True
- `손익`: True
- `평균단가 계산`: True
- `계산하기`: True
- `계산 전용`: True
- `주문을 실행하지 않습니다`: True
- `수익을 보장하지 않습니다`: True
- `simulation-toggle`: True
- `simulation-submit`: True
- `data-simulation-endpoint`: True

주의:

- 최신가 컬럼은 현재 template에서 `Latest`로 표시된다.
- latest price 값 `16340.00`은 화면에 표시된다.

금지 표현/민감정보 포함 여부:

- `username`: False
- `email`: False
- `user_id`: False
- `accountNo`: False
- `accountSeq`: False
- `X-Tossinvest-Account`: False
- `access_token`: False
- `Authorization`: False
- `raw_response`: False
- `order_id`: False
- `orderNo`: False
- `매수하기`: False
- `매도하기`: False
- `주문하기`: False
- `자동매매`: False

판정: PASS

## 8. Additional Buy Simulation API smoke

호출 방식:

- `APIClient.force_authenticate`
- `HTTP_HOST=localhost`
- `POST /api/holdings/1/additional-buy-simulation/`
- body: `{"additional_budget": "100000"}`

결과:

```text
status_code: 200
simulation_only: True
order_execution: False
stock: 035250 강원랜드
```

simulation result:

```text
additional_quantity: 6
additional_invested_amount: 98040.00
unused_budget: 1960.00
new_quantity: 8
new_total_invested_amount: 128273.00
new_average_price: 16034.13
break_even_price: 16034.13
required_rise_to_break_even: -1.87
simulated_market_value_at_latest: 130720.00
simulated_profit_loss_amount_at_latest: 2447.00
simulated_profit_loss_rate_at_latest: 1.91
```

warnings:

- `This is a calculation-only simulation and does not place orders.`
- `This is not investment advice and does not guarantee returns.`
- `Fees and taxes are not included.`

금지 key 포함 여부:

- `username`: False
- `email`: False
- `user_id`: False
- `accountNo`: False
- `accountSeq`: False
- `X-Tossinvest-Account`: False
- `access_token`: False
- `Authorization`: False
- `raw_response`: False
- `order_id`: False
- `orderNo`: False

판정: PASS

## 9. validation smoke

호출 방식:

- `APIClient.force_authenticate`
- `HTTP_HOST=localhost`
- `POST /api/holdings/1/additional-buy-simulation/`
- body: `{"additional_budget": "0"}`

결과:

```json
{
  "error": "invalid_additional_budget",
  "message": "additional_budget must be greater than zero."
}
```

status:

```text
status_code: 400
```

확인:

- safe error code/message 반환.
- raw exception 노출 없음.
- 민감정보 노출 없음.

판정: PASS

## 10. read-only 보장

이번 점검에서 수행한 화면/API smoke:

- Portfolio Summary API 조회
- Portfolio Summary 화면 렌더링
- Additional Buy Simulation API 계산
- validation error 확인

read-only 확인:

- Toss API 호출 없음
- DB write 없음
- `DataIngestionLog` 생성 없음
- 주문 API 호출 없음
- no-network command 직접 실행 없음
- scheduler command 실행 없음

DB count 전후 비교 결과 모든 대상 count가 동일했다.

판정: PASS

## 11. 민감정보 점검

민감정보 grep:

```text
grep result: empty
```

점검 패턴:

- raw access token
- raw Bearer token
- raw `TOSS_INVEST_CLIENT_SECRET`
- raw `X-Tossinvest-Account`

화면/API response 점검:

- username/email 노출 없음
- user id 노출 없음
- accountNo/accountSeq 노출 없음
- access token 노출 없음
- Authorization header 노출 없음
- raw response 노출 없음

판정: PASS

## 12. 주문 API / 자동매매 점검

확인 결과:

- `TOSS_ORDER_EXECUTION_ENABLED=False`
- Portfolio Summary API는 주문 API와 무관
- Portfolio Summary 화면에 주문 버튼 없음
- Simulation API는 `order_execution=False`
- Simulation API response에 주문 ID/주문번호 없음
- 화면에 `매수하기`, `매도하기`, `주문하기`, `자동매매` 문구 없음
- Order API / Order History / Order Info / 매수 가능 금액 / 매도 가능 수량 API 호출 없음
- scheduler command 실행 없음

판정: PASS

## 13. 금지 표현 점검

구현/route grep:

- `portfolio_summary_page` 확인
- `PortfolioSummaryAPIView` 확인
- `additional-buy-simulation` 확인
- `simulation_only` 확인
- `order_execution` 확인
- `simulation-toggle` 확인
- `simulation-submit` 확인

금지 표현 grep:

```text
portfolio/tests.py:512 "주문하기"
portfolio/tests.py:513 "매수하기"
portfolio/tests.py:514 "매도하기"
```

판정:

- grep 결과는 테스트의 부정 검증 문자열이다.
- 실제 template/service UI/API response 금지 CTA로 확인되지 않았다.

판정: PASS

## 14. 배포 가능 여부

최종 판정: PASS

이유:

- `python manage.py check` 통과.
- `python manage.py test` 통과.
- `TOSS_ORDER_EXECUTION_ENABLED=False`.
- Portfolio Summary API smoke 200.
- Portfolio Summary 화면 smoke 200.
- Additional Buy Simulation API smoke 200.
- validation smoke 400 safe error.
- DB count 변화 없음.
- `DataIngestionLog` count 변화 없음.
- 민감정보 grep 결과 없음.
- 주문 API 호출 없음.
- 금지 CTA 없음.

주의:

- 운영 배포 후에도 실제 ingress/proxy host, session auth, CSRF cookie 동작은 배포 환경에서 별도 smoke가 필요하다.
- 이번 점검에서 APIClient는 운영 settings의 `ALLOWED_HOSTS` 정책 때문에 `HTTP_HOST=localhost`로 수행했다.

## 15. 남은 주의사항

- no-network command도 `DataIngestionLog` row를 생성할 수 있으므로 운영 smoke에서 별도 승인 없이 실행하지 않는다.
- 실제 Toss API smoke, DailyPrice/UserHolding 저장 command, scheduler command는 이번 점검에서 실행하지 않았다.
- Portfolio Summary는 latest `DailyPrice` 기준이며 실시간 가격이 아니다.
- Simulation 결과는 수수료, 세금, 슬리피지를 포함하지 않는다.
- Simulation 결과는 투자 권유가 아니며 수익을 보장하지 않는다.
- 주문 API와 자동매매는 계속 비활성 상태를 유지한다.
- 배포 후 실제 도메인에서 `/portfolio/summary/`, `/api/portfolio/summary/`, `/api/holdings/{id}/additional-buy-simulation/` smoke를 다시 수행한다.
