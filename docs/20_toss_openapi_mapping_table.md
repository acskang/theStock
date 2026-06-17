# 20_toss_openapi_mapping_table.md

# Toss OpenAPI Mapping Table

---

# 0. 문서 목적

이 문서는 Toss OpenAPI endpoint와 `theStock` 내부 데이터 영역의 매핑을 정리한다.

기준 문서:

```text
https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md
https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
```

---

# 1. Endpoint 매핑

| Toss API 그룹 | Endpoint | Toss 설명 | theStock 매핑 | 우선순위 |
|---|---|---|---|---:|
| Auth | `POST /oauth2/token` | OAuth2 액세스 토큰 발급 | Toss token service/cache | 1 |
| Account | `GET /api/v1/accounts` | 계좌 목록 조회 | 사용자 계좌 연결 후보 | 1 |
| Asset | `GET /api/v1/holdings` | 보유 주식 조회 | UserHolding 자동 동기화 후보 | 1 |
| Market Data | `GET /api/v1/prices` | 현재가 조회 | MarketPrice 또는 DailyPrice 최신값 | 1 |
| Market Data | `GET /api/v1/orderbook` | 호가 조회 | Orderbook snapshot 또는 보조 시세 | 1 |
| Market Data | `GET /api/v1/trades` | 최근 체결 내역 조회 | Trade snapshot 또는 체결 보조 지표 | 1 |
| Market Data | `GET /api/v1/price-limits` | 상/하한가 조회 | PriceLimit, risk/price guard | 1 |
| Market Data | `GET /api/v1/candles` | 캔들 차트 조회 | DailyPrice, intraday candle 후보 | 1 |
| Stock Info | `GET /api/v1/stocks` | 종목 기본 정보 조회 | Stock master | 1 |
| Stock Info | `GET /api/v1/stocks/{symbol}/warnings` | 매수 유의사항 조회 | StockWarning 또는 RiskEvent | 1 |
| Market Info | `GET /api/v1/exchange-rate` | 환율 조회 | ExchangeRate, USD/KRW 보정 | 1 |
| Market Info | `GET /api/v1/market-calendar/KR` | 국내 장 운영 정보 조회 | MarketCalendar(KR) | 1 |
| Market Info | `GET /api/v1/market-calendar/US` | 해외 장 운영 정보 조회 | MarketCalendar(US) | 1 |
| Order Info | `GET /api/v1/buying-power` | 매수 가능 금액 조회 | Capital plan 참고 데이터 | 1 |
| Order Info | `GET /api/v1/sellable-quantity` | 판매 가능 수량 조회 | 보유 수량 검증 | 1 |
| Order Info | `GET /api/v1/commissions` | 매매 수수료 조회 | 손익/손절 계산 보정 | 1 |
| Order History | `GET /api/v1/orders` | 주문 목록 조회 | 주문 상태 참고 데이터 | 1 |
| Order History | `GET /api/v1/orders/{orderId}` | 주문 상세 조회 | 주문 상태 참고 데이터 | 1 |
| Order | `POST /api/v1/orders` | 주문 생성 | 비활성, 별도 승인 필요 | 보류 |
| Order | `POST /api/v1/orders/{orderId}/modify` | 주문 정정 | 비활성, 별도 승인 필요 | 보류 |
| Order | `POST /api/v1/orders/{orderId}/cancel` | 주문 취소 | 비활성, 별도 승인 필요 | 보류 |

---

# 2. 내부 모델 후보

| theStock 영역 | 내부 모델 후보 | Toss 우선 여부 | fallback |
|---|---|---:|---|
| 종목 마스터 | Stock | 예 | pykrx, manual |
| 현재가 | MarketPrice 또는 DailyPrice 최신값 | 예 | pykrx |
| 일봉 | DailyPrice | 예 | pykrx |
| 분봉 | IntradayCandle 후보 | 예 | 없음 또는 추후 |
| 호가 | OrderbookSnapshot 후보 | 예 | 없음 |
| 체결 | TradeSnapshot 후보 | 예 | 없음 |
| 가격 제한 | PriceLimit 후보 | 예 | KRX/manual |
| 종목 경고 | StockWarning 또는 RiskEvent | 예 | KRX/manual |
| 환율 | ExchangeRate 후보 | 예 | finance provider |
| 시장 캘린더 | MarketCalendar 후보 | 예 | KRX/NYSE calendar provider |
| 계좌 목록 | UserBrokerAccount 후보 | 예 | 수동 연결 |
| 보유주식 | UserHolding | 예 | 사용자 수동 입력 |
| 매수 가능 금액 | AccountBuyingPower 후보 | 예 | 사용자 수동 입력 |
| 매도 가능 수량 | SellableQuantity 후보 | 예 | UserHolding |
| 수수료 | CommissionSchedule 후보 | 예 | manual |
| 재무제표 | FinancialSnapshot | 아니오 | OPENDART |
| 공시 상세 | DisclosureEvent 후보 | 아니오 | OPENDART |
| 뉴스/리스크 이벤트 | RiskEvent | 아니오 | news/risk provider, manual |
| 투자자별 수급 | InvestorFlow | 문서 확인 필요 | pykrx |

---

# 3. 인증 및 헤더 매핑

공통:

```text
Authorization: Bearer {access_token}
```

계좌, 자산, 주문 관련 API:

```text
Authorization: Bearer {access_token}
X-Tossinvest-Account: {accountSeq}
```

주의:

```text
1. Authorization header 원문을 로그에 남기지 않는다.
2. X-Tossinvest-Account header 원문을 로그에 남기지 않는다.
3. access token은 DB 평문 저장을 지양한다.
4. accountSeq는 사용자 금융정보에 준해 보호한다.
```

---

# 4. 수집 작업 매핑

| 수집 작업 | Toss endpoint | 실행 주기 | 실패 시 처리 |
|---|---|---|---|
| token refresh | `POST /oauth2/token` | 만료 전 또는 인증 실패 시 | 1회 재발급 후 실패 기록 |
| stock master sync | `GET /api/v1/stocks` | 1일 1회 또는 주 1회 | pykrx/manual fallback |
| daily price sync | `GET /api/v1/candles` | 장마감 후 | pykrx fallback |
| current price sync | `GET /api/v1/prices` | 필요 시 또는 제한된 주기 | 기존 데이터 유지 |
| orderbook sync | `GET /api/v1/orderbook` | 필요 시 | 기존 데이터 유지 |
| trade sync | `GET /api/v1/trades` | 필요 시 | 기존 데이터 유지 |
| warning sync | `GET /api/v1/stocks/{symbol}/warnings` | 장 시작 전/장중 제한 주기 | manual fallback |
| exchange rate sync | `GET /api/v1/exchange-rate` | 1분 이상 제한 주기 또는 필요 시 | finance provider fallback |
| market calendar sync | market-calendar endpoints | 월 1회 및 장 시작 전 | calendar provider fallback |
| account sync | `GET /api/v1/accounts` | 사용자 연동 시 | 사용자 재인증 요청 |
| holdings sync | `GET /api/v1/holdings` | 사용자 요청 또는 제한된 주기 | 수동 입력 유지 |
| buying power sync | `GET /api/v1/buying-power` | 사용자 요청 시 | 경고 표시 |
| sellable quantity sync | `GET /api/v1/sellable-quantity` | 사용자 요청 시 | 경고 표시 |
| commissions sync | `GET /api/v1/commissions` | 1일 1회 또는 필요 시 | manual fallback |

---

# 5. 미확정 항목

```text
1. DailyPrice 저장 기준이 수정주가인지 비수정주가인지 확인해야 한다.
2. 투자자별 수급을 Toss가 제공하는지 확인 전까지 pykrx 등 fallback을 유지한다.
3. 분봉 저장 모델을 실제로 둘지, 현재 consult에는 일봉만 사용할지 결정해야 한다.
4. 계좌 연동 동의 UX와 철회 UX가 필요하다.
5. 주문 실행 API 활성화는 투자자 보호, 권한, 감사 로그, 사용자 확인 UX 설계 이후 별도 승인으로만 진행한다.
```
