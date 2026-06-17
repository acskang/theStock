# 18_privacy_and_financial_data_policy.md

# theStock 개인정보 및 금융정보 보호 정책 설계서

---

# 0. 문서 목적

`theStock`는 사용자의 보유 종목, 평균 단가, 수량, 투자금, 손익률, 컨설팅 결과를 저장하거나 처리할 수 있다.

이 정보는 단순 개인정보를 넘어 사용자 개인의 금융 상태와 투자 성향을 추정할 수 있는 민감한 정보다.

이 문서의 목적은 다음이다.

```text
1. 어떤 사용자 정보를 저장하는지 정의한다.
2. 어떤 정보가 민감한 금융정보인지 분류한다.
3. 접근 권한과 로그 정책을 정리한다.
4. 삭제/보관/백업 정책을 정리한다.
5. 운영자 접근과 감사 로그 기준을 정한다.
6. API, 로그, 화면에서 민감 정보가 과도하게 노출되지 않게 한다.
```

이 문서는 제품/기술 설계 기준이며, 운영 전에는 필요한 경우 법률/개인정보보호 검토가 필요하다.

---

# 1. 데이터 분류

## 1.1 계정 정보

```text
user id
Peach subject
email
display name
last login
staff 여부
```

보호 수준:

```text
개인정보
```

## 1.2 보유 종목 정보

```text
stock code
stock name
quantity
average price
purchase amount
current value
unrealized profit/loss
```

보호 수준:

```text
민감한 금융 관련 정보
```

## 1.3 컨설팅 결과 정보

```text
decision code
score summary
probability result
capital plan
stop loss reference
portfolio risk result
warnings
created_at
```

보호 수준:

```text
민감한 금융 관련 정보
```

## 1.4 데이터 파이프라인 정보

```text
provider status
ingestion log
data quality report
market data
```

보호 수준:

```text
서비스 운영 정보
```

시장 데이터 자체는 일반적으로 사용자 개인정보는 아니지만, provider credential과 운영 로그는 보호 대상이다.

## 1.5 Toss 계좌 연동 정보

Toss OpenAPI 계좌/자산 API 연동 시 다음 정보는 민감한 금융 관련 정보로 분류한다.

```text
accountSeq
계좌 식별자 또는 계좌번호에 준하는 값
보유 종목과 수량
매입가, 평가금액, 손익
매수 가능 금액
매도 가능 수량
주문 목록과 주문 상세
수수료 조회 결과 중 사용자 계좌와 연결되는 정보
```

보호 수준:

```text
민감한 금융 관련 정보
```

`X-Tossinvest-Account` 헤더 값, access token, refresh token 또는 token에 준하는 값은 로그, 문서, Git, 테스트 fixture에 저장하지 않는다.

---

# 2. 최소 수집 원칙

다음 원칙을 따른다.

```text
1. 컨설팅에 필요한 정보만 수집한다.
2. 사용 목적이 없는 개인정보는 저장하지 않는다.
3. Peach profile 전체를 복사 저장하지 않는다.
4. 계좌 전체 자동 연동 전에는 사용자의 명시 입력을 기준으로 한다.
5. 로그에는 원문 투자금/수량/평균단가를 남기지 않는다.
6. Toss 계좌 연동은 사용자가 명시적으로 연결한 계좌 범위로 제한한다.
7. 주문 실행 API는 별도 승인 전까지 비활성화하고 조회 목적 API만 사용한다.
```

---

# 3. 접근 권한 원칙

## 3.1 일반 사용자

일반 사용자는 본인 데이터만 접근할 수 있다.

```text
1. 본인 UserHolding
2. 본인 ConsultingResult
3. 본인 ProbabilityResult
4. 본인 PortfolioSnapshot
```

## 3.2 staff

staff는 운영상 필요한 경우에만 사용자 데이터를 조회할 수 있다.

원칙:

```text
1. 기본 목록에서는 민감 정보 마스킹
2. 상세 조회 시 감사 로그 기록
3. 대량 다운로드 금지 또는 별도 승인
4. 컨설팅 결과 수동 조작 금지
```

## 3.3 superuser

superuser는 최소 인원만 유지한다.

```text
1. 개인 계정 사용
2. 공유 계정 금지
3. 접근 로그 기록
4. 정기 권한 점검
```

---

# 4. Owner Scope 테스트

다음 테스트는 필수다.

```text
1. 사용자 A가 사용자 B의 holding detail 접근 시 404 또는 403
2. 사용자 A가 사용자 B의 consult 실행 시 404 또는 403
3. 사용자 A가 사용자 B의 probability 조회 시 404 또는 403
4. list API에서 본인 데이터만 표시
5. staff는 접근 가능하되 로그 기록
```

권장:

```text
다른 사용자의 object id를 추측해 접근하는 테스트를 자동화한다.
```

---

# 5. 로그 정책

## 5.1 로그에 남겨도 되는 정보

```text
request_id
user_id_hash
endpoint
status_code
duration_ms
decision_code
risk_grade
data_quality_grade
provider_status
```

## 5.2 로그에 남기면 안 되는 정보

```text
평균 단가 원문
보유 수량 원문
총 투자금 원문
구체적인 보유 종목 전체 목록
access token
refresh token
client secret
Toss accountSeq
session cookie
Authorization header
X-Tossinvest-Account header
```

## 5.3 마스킹 예

```text
average_price=***masked***
quantity=***masked***
investment_amount_bucket=1M_5M
user_id_hash=u_8f31...
```

---

# 6. 데이터 보관 기간

운영 정책으로 확정해야 한다.

초기 권장:

| 데이터 | 보관 기간 | 비고 |
|---|---:|---|
| UserHolding | 사용자가 삭제할 때까지 | 사용자 직접 관리 |
| ConsultingResult | 1년 또는 사용자 삭제 시 | 감사/이력 목적 |
| ProbabilityResult | 1년 또는 사용자 삭제 시 | 결과 재현 목적 |
| PortfolioSnapshot | 1년 또는 사용자 삭제 시 | 민감도 높음 |
| DataIngestionLog | 1년 이상 | 운영 품질 |
| SecurityAuditLog | 1년 이상 | 보안 감사 |
| AccessLog | 30~90일 | 서버 운영 |

정확한 기간은 서비스 약관/개인정보 처리방침과 일치해야 한다.

---

# 7. 사용자 삭제 요청

## 7.1 삭제 대상

사용자가 계정 또는 데이터 삭제를 요청하면 다음을 삭제 또는 익명화한다.

```text
1. UserHolding
2. ConsultingResult
3. ProbabilityResult
4. PortfolioSnapshot
5. 사용자 입력 현금/위험 성향
6. shadow user의 개인 식별 정보
```

## 7.2 보존 가능 데이터

운영/보안상 필요한 로그는 법적/정책상 허용되는 기간 동안 보관할 수 있다.

단, 가능한 익명화한다.

```text
user_id -> hash 또는 deleted_user
email 제거
투자금/종목 정보 제거 또는 집계화
```

## 7.3 삭제 처리 로그

삭제 처리 자체는 기록한다.

```text
user
deleted_at
deleted_data_categories
operator 또는 self_service
```

단, 삭제된 민감 데이터를 로그에 남기지 않는다.

---

# 8. 백업 데이터 정책

백업에는 삭제된 사용자의 데이터가 일정 기간 남을 수 있다.

정책 필요:

```text
1. 백업 보관 기간
2. 백업 암호화 여부
3. 백업 접근 권한
4. restore 시 삭제 요청 데이터 재삭제 절차
```

권장:

```text
1. 백업 파일 암호화
2. 백업 저장소 접근 제한
3. restore 후 deletion replay script 실행
```

---

# 9. 관리자 화면 보호

Django admin 또는 staff dashboard에서 다음을 적용한다.

```text
1. 평균 단가/수량/투자금 기본 마스킹
2. 상세 보기 클릭 시 감사 로그
3. CSV export 제한
4. 검색 조건 제한
5. staff 권한 없는 사용자 접근 차단
```

관리자 화면에서 민감 필드를 그대로 list_display에 넣지 않는다.

---

# 10. API 응답 보호

## 10.1 본인 응답

본인 API에는 필요한 정보를 제공할 수 있다.

하지만 과도한 내부 정보는 제외한다.

제외 권장:

```text
internal user id
provider raw payload
staff memo
audit fields
```

## 10.2 staff 응답

staff API에는 마스킹 옵션을 둔다.

```text
?include_sensitive=true
```

이 옵션 사용 시 감사 로그를 남긴다.

## 10.3 캐시 주의

사용자별 민감 응답은 public cache하면 안 된다.

header 예:

```text
Cache-Control: no-store
```

특히 consult/probability/portfolio API에 적용한다.

---

# 11. 암호화 정책

## 11.1 전송 구간

production은 HTTPS만 허용한다.

```text
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## 11.2 저장 구간

DB 전체 암호화 또는 디스크 암호화는 운영 환경 정책에 따른다.

민감 필드 개별 암호화가 필요한 후보:

```text
available_cash
portfolio snapshot 상세
user risk profile 상세
```

초기에는 접근 제어와 로그 마스킹을 우선 적용하고, 필요 시 필드 암호화를 추가한다.

---

# 12. 외부 연동 정책

Toss/OpenDART/KRX 등 외부 provider로부터 받는 시장 데이터와 사용자 개인정보를 섞어 외부로 보내지 않는다.

금지:

```text
1. 사용자 평균 단가를 외부 provider API에 전송
2. 사용자 보유 수량을 외부 provider API에 전송
3. 사용자 컨설팅 결과를 외부 분석 API에 전송
```

외부 API 호출은 시장 데이터 조회에 한정한다.

단, 사용자가 Toss 계좌 연동을 명시적으로 활성화한 경우에만 계좌 목록, 보유주식, 주문 가능 금액, 매도 가능 수량, 수수료, 주문 조회 API를 호출할 수 있다. 이 경우에도 호출 목적은 사용자의 theStock 화면과 컨설팅 보조 계산에 한정하며, 실거래 주문 생성/정정/취소는 별도 승인 전까지 비활성화한다.

Toss credential과 계좌 식별자는 다음 위치에 저장하지 않는다.

```text
1. 문서
2. Git
3. 테스트 fixture
4. 일반 application log
5. DataIngestionLog details 원문
6. 오류 추적 시스템의 raw payload
```

---

# 13. 개인정보 처리방침에 들어갈 기술 항목

서비스 문서/약관에는 다음이 반영되어야 한다.

```text
1. 수집하는 정보
2. 수집 목적
3. 보관 기간
4. 삭제 요청 방법
5. 제3자 제공 여부
6. 외부 API 사용 여부
7. 보안 조치
8. 문의/관리자 연락 방법
```

---

# 14. 구현 체크리스트

```text
[ ] 사용자 금융정보 데이터 분류표 작성
[ ] UserHolding owner scope 테스트 추가
[ ] consult/probability owner scope 테스트 추가
[ ] staff 상세 조회 감사 로그 추가
[ ] 관리자 화면 민감 필드 마스킹
[ ] consult/probability API Cache-Control no-store 적용
[ ] 로그 마스킹 filter 추가
[ ] 사용자 삭제 요청 처리 command 또는 admin action 추가
[ ] 백업 보관 기간 문서화
[ ] restore 후 삭제 replay 절차 문서화
[ ] 개인정보 처리방침 초안 작성
```

---

# 15. Codex 작업 지시 요약

```text
theStock의 사용자 보유 종목, 평균 단가, 수량, 투자금, 컨설팅 결과를 민감한 금융 관련 정보로 취급한다.
모든 사용자 데이터 API에는 owner scope를 적용한다.
staff 조회는 허용하되 감사 로그를 남기고 관리자 화면에서는 민감 필드를 기본 마스킹한다.
consult/probability/portfolio API에는 Cache-Control: no-store를 적용한다.
로그에는 평균 단가, 보유 수량, 투자금, token, secret, cookie를 남기지 않는다.
사용자 삭제 요청과 백업 데이터 처리 정책을 문서화하고 구현 준비를 한다.
```

---

# 16. 결론

`theStock`가 다루는 데이터는 단순 주식 관심종목 정보가 아니다.

다음 정보는 사용자의 재정 상태와 투자 판단을 드러낼 수 있다.

```text
1. 평균 단가
2. 보유 수량
3. 총 투자금
4. 손익률
5. 추가 매수 가능 금액
6. 손절 기준
7. 포트폴리오 비중
```

따라서 `theStock`의 개인정보/금융정보 보호 원칙은 다음이다.

```text
1. 필요한 정보만 수집한다.
2. 본인만 볼 수 있게 한다.
3. 운영자 접근은 기록한다.
4. 로그에는 민감 정보를 남기지 않는다.
5. 삭제 요청에 대응할 수 있게 한다.
6. 백업과 restore까지 고려한다.
```
