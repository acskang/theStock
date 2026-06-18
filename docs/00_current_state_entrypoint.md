# 00_current_state_entrypoint.md

# theStock 현재 상태 진입 문서

---

# 0. 문서 목적

이 문서는 `theStock` 프로젝트의 현재 상태를 한눈에 확인하기 위한 진입점 문서다.

기존 문서들은 단계별 설계와 Codex 실행 프롬프트를 잘 나누고 있지만, 새 GPT 창이나 Codex 작업자가 프로젝트를 이어받을 때 다음 질문에 바로 답하기 어렵다.

```text
1. 현재 기준 서비스 URL은 무엇인가?
2. 어떤 단계까지 설계 또는 구현되었는가?
3. 현재 기준 문서 세트는 무엇인가?
4. 운영 전 반드시 보강해야 할 항목은 무엇인가?
5. 다음 작업은 어디서 시작해야 하는가?
```

따라서 이 문서는 기존 설계서를 대체하지 않는다.  
이 문서는 기존 설계서 위에 추가되는 **현재 상태 기준 문서**다.

---

# 1. 서비스 기준 정보

## 1.1 서비스명

```text
theStock
```

## 1.2 운영 URL

```text
https://stock.thesysm.com/
```

## 1.3 서비스 성격

`theStock`는 사용자의 보유 주식에 대해 물타기, 추가 매수, 손절, 관망 여부를 데이터 기반으로 판단하도록 돕는 주식 컨설팅 보조 서비스다.

핵심 목표는 다음이다.

```text
1. 단순 가격 하락만 보고 물타기하지 않도록 한다.
2. 펀더멘털, 기술적 지표, 수급, 시장, 리스크 이벤트를 함께 본다.
3. 물타기 가능/보류/금지 판단을 구조화한다.
4. 추가 매수 시 자본 계획과 손실 한도를 계산한다.
5. 확률 기반 시나리오를 제공하되, 투자 권유가 아니라 참고 정보로 제공한다.
```

---

## 1.4 데이터 공급 정책

운영 기준으로 `theStock`는 토스증권 OpenAPI를 1순위 데이터 provider로 사용한다.

토스증권 OpenAPI에서 제공하는 국내/미국 주식 시세, 호가, 체결, 캔들, 가격 제한, 종목정보, 종목 경고/주의 정보, 환율, 국내/미국 시장 캘린더, 계좌 목록, 보유주식, 주문 가능 금액, 매도 가능 수량, 수수료와 주문 조회 데이터는 우선적으로 `TossOpenApiProvider`를 통해 수집한다.

단, 재무제표, 공시 상세, 뉴스/리스크 이벤트, 투자자별 수급처럼 토스증권 OpenAPI에서 제공하지 않거나 제공 범위가 부족한 데이터는 기존 보조 provider를 fallback으로 사용한다.

fallback provider는 다음 목적을 위해 유지한다.

```text
1. Toss API 장애 또는 rate limit 발생 시 서비스 전체 중단 방지
2. Toss가 제공하지 않는 데이터 보강
3. local/test 환경의 재현 가능한 테스트 데이터 제공
4. 운영 장애 시 기존 정상 데이터 기반의 제한적 컨설팅 제공
```

실제 주문 생성/정정/취소 기능은 투자자 보호와 안전장치 설계가 완료되고 별도 운영 승인이 있기 전까지 운영 화면과 자동화 흐름에서 비활성화한다. 주문 관련 조회 API는 자본 계획, 보유 수량 검증, 수수료 계산 보정 용도로만 사용한다.

Toss API Key, Secret Key, Access Token, 계좌번호는 문서, Git, 테스트 fixture에 저장하지 않는다. `.env.example`에는 변수명만 남기고 실제 값은 운영 서버의 `.env` 또는 secret manager에서 관리한다.

2026-06-18 현재 물타기 컨설팅 입력 데이터 수집은 다음 운영 보조 provider를 함께 사용한다.

```text
1. DailyPrice: yfinance 우선, 국내 종목 yfinance 누락 시 Naver 일별 시세 fallback
2. InvestorFlow: Naver 투자자별 매매동향 fallback 우선, 필요 시 pykrx 보조
3. MarketIndex: yfinance 기반 KOSPI/KOSDAQ/USDKRW/NASDAQ/SP500 수집
4. RiskEvent: OpenDART 공시 우선, API key 또는 corp_code 누락 시 Naver 공시/뉴스 fallback
5. FinancialSnapshot: OpenDART 재무제표 기반 최근 2개년 주요 재무 스냅샷 수집
6. DataQualitySnapshot: 위 입력 데이터 수집 후 `update_data_quality`로 재계산
```

운영 자동 수집 후보 파일은 `deploy/production/thestock_investor_flow_collect.service`와 `deploy/production/thestock_investor_flow_collect.timer`다. 이름은 초기 수급 수집에서 출발했지만, 현재 서비스 파일은 가격, 시장, 수급, 리스크 이벤트, 재무 스냅샷, 데이터 품질 갱신을 순차 실행하는 decision input 수집 job으로 확장되어 있다.

보유 종목 컨설팅 화면은 `UserHolding.max_additional_budget`를 기준으로 추가 예산을 계산한다. `/consulting/holdings/` 화면의 `추가예산설정` 버튼에서 전체 추가 예산을 입력하면 활성 보유 종목에 균등 배분하고, 개별 종목 금액을 바꾸면 총액과 배정 비중을 다시 계산해 저장한다.

종목명/시세 조회 티커 수동 관리 화면은 운영 메뉴의 `종목마스터 관리/등록`으로 둔다. 일반 사용자 주요 흐름에서는 직접 노출하지 않는다. 장기적으로는 KRX 국내 종목 master와 미국 종목 master 자동 적재 기능으로 대체하고, 수동 화면은 누락/충돌 보정용 운영 도구로 축소한다.

2026-06 기술 아키텍처 보강 기준에서는 일반 사용자 기능의 최종 방향을 사용자별 Toss credential 1:1 구조로 둔다. 전역 `.env` Toss credential은 staff-only 운영 점검 또는 전환 기간에만 제한적으로 유지할 수 있으며, 일반 사용자 데이터 조회에는 사용하지 않는다. `.env` 파일 자체는 삭제하지 않고 `DJANGO_SECRET_KEY`, DB 설정, `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY` 같은 운영 secret 관리 수단으로 유지한다.

SQLite 환경에서 SQLCipher는 DB 파일 유출 방어용 보조 계층으로 검토한다. Toss credential column 보안의 핵심은 SQLCipher가 아니라 application-level encrypted field이며, SQL query 결과에서도 `client_id`, `client_secret`, token 평문이 보이면 안 된다. 상세 기준은 `docs/54_technical_architecture_and_toss_credential_design.md`를 따른다.

`docs/54_technical_architecture_and_toss_credential_design.md`는 최신 기술 아키텍처 기준 문서이고, `docs/55_security_foundation_research_report.md`는 Phase 1 보안 기반 조사 보고서다. docs/55의 service-layer encryption, SQLCipher 역할 분리, Toss 인증 모델 Open Question 결론은 docs/54에 반영한다.

상세 정책은 다음 문서를 기준으로 한다.

```text
docs/19_toss_openapi_first_provider_policy.md
docs/20_toss_openapi_mapping_table.md
docs/21_toss_openapi_security_checklist.md
docs/54_technical_architecture_and_toss_credential_design.md
docs/55_security_foundation_research_report.md
```

---

# 2. 현재 기준 문서 세트

현재 기준 문서 세트는 다음 파일들을 포함한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/01_codex_prompt.md
docs/02_scoring_engine_design.md
docs/02_codex_prompt.md
docs/03_api_workflow_design.md
docs/03_codex_prompt.md
docs/04_quality_release_design.md
docs/04_codex_prompt.md
docs/05_probability_engine_design.md
docs/05_codex_prompt.md
docs/06_optimized_consulting_system_design.md
docs/06_codex_prompt_optimized_consulting_system.md
docs/07_consulting_screen_design.md
docs/07_codex_prompt_consulting_screen.md
docs/08_data_pipeline_design.md
docs/08_codex_prompt_data_pipeline.md
docs/09_production_deployment_design.md
docs/09_codex_prompt_production_deployment.md
docs/10_toss_openapi_provider_design.md
docs/11_investor_protection_and_compliance_design.md
docs/12_backtesting_and_probability_calibration_design.md
docs/13_market_data_normalization_design.md
docs/14_portfolio_risk_engine_design.md
docs/15_operations_runbook.md
docs/16_observability_and_alerting_design.md
docs/17_openapi_schema_design.md
docs/18_privacy_and_financial_data_policy.md
docs/19_toss_openapi_first_provider_policy.md
docs/20_toss_openapi_mapping_table.md
docs/21_toss_openapi_security_checklist.md
docs/54_technical_architecture_and_toss_credential_design.md
docs/55_security_foundation_research_report.md
docs/56_toss_credential_issuance_model_research_report.md
docs/57_holdings_realized_profit_screen_guide.md
docs/58_holdings_realized_profit_screen_split_design.md
docs/api_reference.md
docs/check-list.txt
```

이 문서 이후 추가되는 보강 문서는 다음 성격을 가진다.

```text
1. 운영 안정화
2. 인증 정책 정리
3. Toss OpenAPI 실제 연동
4. 투자자 보호/법적 리스크 완화
5. 백테스트와 확률 보정
6. 시장 데이터 정규화
7. 포트폴리오 리스크
8. 운영 Runbook
9. 관측성/알림
10. OpenAPI schema 안정화
11. 개인정보/금융정보 보호
```

---

# 3. 단계별 현재 상태 요약

## 3.1 00단계: 개요 및 데이터 정의

상태:

```text
설계 완료
```

주요 내용:

```text
1. 물타기의 정의
2. 판단 대상 데이터
3. 리스크 게이트
4. 점수화 대상
5. 판단 결과 구조
6. 사용자 보유 종목 기반 의사결정 흐름
```

보강 필요:

```text
1. 투자자 보호 표현 가이드와 연결
2. 포트폴리오 전체 리스크 관점 추가
3. 법적 고지 문구의 중앙화
```

## 3.2 01단계: Foundation

상태:

```text
설계 완료 또는 구현 기준 문서 존재
```

주요 내용:

```text
1. Django 프로젝트 기본 구조
2. 핵심 모델
3. 관리자 화면
4. 기본 API
5. 테스트 구조
```

보강 필요:

```text
1. 운영 인증 정책과 모델 권한 재점검
2. 개인정보/금융정보 보호 정책 연결
3. TechnicalIndicator 등 기준 데이터 쓰기 권한 재검토
```

## 3.3 02단계: Scoring Engine

상태:

```text
설계 완료
```

주요 내용:

```text
1. 펀더멘털 점수
2. 기술적 점수
3. 수급 점수
4. 시장 점수
5. 리스크 게이트
6. 최종 판단
```

보강 필요:

```text
1. 시장 국면별 가중치 검증
2. 종목군별 가중치 차등화
3. 백테스트 기반 threshold 보정
```

## 3.4 03단계: API Workflow

상태:

```text
설계 완료
```

주요 내용:

```text
1. 보유 종목 등록
2. 의사결정 API
3. 사용자별 owner scope
4. API workflow
```

보강 필요:

```text
1. OpenAPI schema 안정화
2. 운영 인증 방식 명확화
3. rate limit / abuse protection 추가
```

## 3.5 04단계: Quality Release

상태:

```text
설계 완료
```

주요 내용:

```text
1. 테스트 기준
2. 릴리스 기준
3. 품질 확인
```

보강 필요:

```text
1. 운영 smoke test
2. 롤백 기준
3. 배포 후 검증 절차
```

## 3.6 05단계: Probability Engine

상태:

```text
설계 완료
```

주요 내용:

```text
1. 목표가 도달 확률
2. 손절가 도달 확률
3. 시나리오별 확률
4. 기대 손익
```

보강 필요:

```text
1. 백테스트
2. calibration curve
3. Brier score
4. false safe 판단 비율
5. 확률 설명 문구
```

## 3.7 06단계: Optimized Consulting System

상태:

```text
설계 완료
```

주요 내용:

```text
1. 종합 컨설팅 API
2. 자본 계획
3. 손절 기준
4. 시나리오 설명
5. 사용자 친화적 응답 구조
```

보강 필요:

```text
1. 투자 권유로 오해되지 않는 문구
2. 포트폴리오 전체 비중 제한
3. 사용자 위험 성향 반영
```

## 3.8 07단계: Consulting Screen

상태:

```text
설계 완료
```

주요 내용:

```text
1. 컨설팅 화면
2. 입력 폼
3. 결과 카드
4. 리스크 표시
5. 사용자 액션 동선
```

보강 필요:

```text
1. 법적 고지 UI
2. 데이터 품질 낮음 경고
3. 확률값 오해 방지 문구
4. 모바일 화면 최적화
```

## 3.9 08단계: Data Pipeline

상태:

```text
설계 완료
```

주요 내용:

```text
1. DataProvider 추상화
2. MockDataProvider
3. pykrx / OPENDART / KRX 확장 가능 구조
4. DataIngestionLog
5. DataQualityReport
6. management command 기반 수집
```

보강 필요:

```text
1. Toss OpenAPI 실제 provider 설계
2. 수정주가/액면분할/배당락 정규화
3. 거래정지/상장폐지/관리종목 처리
4. 장마감 이후 스케줄
5. 데이터 품질 알림
```

## 3.10 09단계: Production Deployment & Peach SSO

상태:

```text
운영 배포 설계 문서 존재
```

주요 내용:

```text
1. Peach SSO relying service 전환
2. prod settings 강화
3. Gunicorn / Nginx / systemd / Cloudflare Tunnel
4. 운영 배포 스크립트
5. healthz / readyz
```

보강 필요:

```text
1. 인증 정책 단일 문서화
2. 운영 Runbook
3. 장애 대응 절차
4. 백업/복구 절차
5. 관측성/알림
```

---

# 4. 현재 중요 리스크

## 4.1 인증 정책 혼선

현재 설계서에는 다음 방식이 함께 언급된다.

```text
1. Django SessionAuthentication
2. BasicAuthentication
3. Peach SSO
```

운영 기준에서는 Peach SSO가 유일한 인증 소스가 되어야 한다.  
BasicAuthentication은 운영에서 제거하거나 내부 테스트 전용으로 제한해야 한다.

## 4.2 기준 데이터 쓰기 권한

기준 데이터는 컨설팅 결과의 근거가 된다.

```text
Stock
DailyPrice
InvestorFlow
MarketIndex
RiskEvent
TechnicalIndicator
FinancialSnapshot
```

이 데이터는 일반 사용자가 임의로 수정할 수 없어야 한다.

## 4.3 확률 엔진 검증 부족

Probability Engine은 사용자에게 강한 신뢰감을 줄 수 있다.  
하지만 백테스트와 보정 없이 제공되는 확률은 오해를 만들 수 있다.

따라서 확률은 다음처럼 표현해야 한다.

```text
예측 확률이 아니라, 현재 데이터와 과거 패턴에 기반한 조건부 추정값입니다.
```

## 4.4 투자자 보호 문구 부족

서비스가 물타기, 추가 매수, 손절 기준을 다루므로 투자 권유로 오해될 수 있다.

모든 화면과 API 설명에는 다음 원칙이 필요하다.

```text
1. 매수/매도 추천 금지
2. 수익 보장 표현 금지
3. 손실 회피 보장 표현 금지
4. 최종 판단은 사용자 책임임을 고지
5. 데이터 지연/오류 가능성 고지
```

## 4.5 운영 Runbook 부재

배포 문서는 있어도 장애 발생 시 운영자가 따라 할 Runbook이 부족하다.

필요한 Runbook 항목:

```text
1. 서비스 상태 확인
2. 로그 확인
3. 배포 절차
4. 롤백 절차
5. DB backup / restore
6. 데이터 파이프라인 실패 대응
7. API key 노출 대응
```

---

# 5. 다음 작업 권장 순서

## 5.1 P0: 운영 안정성 선행 작업

```text
1. docs/10_auth_policy_design.md 작성 및 적용
2. TechnicalIndicator API 권한 잠금
3. 운영에서 BasicAuthentication 제거 또는 제한
4. docs/15_operations_runbook.md 작성
5. docs/16_observability_and_alerting_design.md 작성
```

## 5.2 P1: 데이터 연동 선행 작업

```text
1. docs/10_toss_openapi_provider_design.md 기준으로 Toss provider 구현
2. API key는 .env에서만 관리
3. DataProviderStatus와 DataIngestionLog 연동
4. 수집 실패 시 기존 데이터 보존
5. 수집 스케줄과 장마감 기준 정리
```

## 5.3 P2: 신뢰도 고도화

```text
1. docs/12_backtesting_and_probability_calibration_design.md 기준 백테스트 구현
2. docs/13_market_data_normalization_design.md 기준 수정주가/권리락 처리
3. docs/14_portfolio_risk_engine_design.md 기준 포트폴리오 리스크 추가
4. 확률값 보정과 설명 문구 개선
```

---

# 6. 작업 시 금지 사항

후속 Codex 작업에서는 다음을 금지한다.

```text
1. 기존 서비스 URL 변경 금지
2. 기존 API 응답 구조 임의 파괴 금지
3. 기존 migration 무리한 삭제 금지
4. 운영 인증 정책을 우회하는 임시 로그인 추가 금지
5. API key / secret / token 문서 저장 금지
6. 컨설팅 결과를 매수/매도 추천으로 표현 금지
7. 일반 사용자가 기준 데이터를 수정할 수 있게 만들기 금지
```

---

# 7. 후속 문서 목록

이 문서 이후 보강 문서는 다음 순서로 관리한다.

```text
docs/10_auth_policy_design.md
docs/10_toss_openapi_provider_design.md
docs/11_investor_protection_and_compliance_design.md
docs/12_backtesting_and_probability_calibration_design.md
docs/13_market_data_normalization_design.md
docs/14_portfolio_risk_engine_design.md
docs/15_operations_runbook.md
docs/16_observability_and_alerting_design.md
docs/17_openapi_schema_design.md
docs/18_privacy_and_financial_data_policy.md
docs/54_technical_architecture_and_toss_credential_design.md
```

---

# 8. 결론

`theStock`는 이미 물타기 판단 서비스의 핵심 기능 설계가 상당 부분 정리되어 있다.

하지만 운영 서비스로 안정적으로 전환하려면 다음 축을 보강해야 한다.

```text
1. 인증 정책 확정
2. 실제 데이터 provider 연동
3. 투자자 보호와 법적 리스크 완화
4. 백테스트와 확률 보정
5. 시장 데이터 정규화
6. 포트폴리오 전체 리스크
7. 운영 Runbook
8. 모니터링과 알림
9. API schema 안정화
10. 개인정보/금융정보 보호
```

이 문서는 새 작업자가 `theStock` 프로젝트에 진입할 때 가장 먼저 읽어야 하는 문서다.
