# 17_openapi_schema_design.md

# theStock OpenAPI Schema 안정화 설계서

---

# 0. 문서 목적

`theStock`는 Django REST Framework 기반 API를 통해 보유 종목, 물타기 판단, 확률 분석, 컨설팅 결과, 데이터 파이프라인 정보를 제공한다.

기존 `api_reference.md`는 사람이 읽는 API 문서로 유용하다.  
하지만 운영 서비스에서는 기계가 읽을 수 있는 OpenAPI schema가 필요하다.

필요 이유:

```text
1. 프론트엔드와 백엔드 응답 구조 불일치 방지
2. API 변경 시 하위 호환성 확인
3. 자동 문서 생성
4. 테스트 자동화
5. 외부 클라이언트 연동 안정화
6. consult/probability처럼 큰 응답의 schema drift 방지
```

이 문서는 OpenAPI schema를 안정화하기 위한 설계 기준을 정의한다.

---

# 1. 기본 원칙

## 1.1 API 문서의 단일 기준

운영 기준 API schema는 다음을 원칙으로 한다.

```text
OpenAPI schema가 기계 판독 가능한 기준이다.
api_reference.md는 설명 문서다.
```

둘이 충돌하면 OpenAPI schema와 실제 테스트 결과를 기준으로 문서를 갱신한다.

## 1.2 하위 호환성 원칙

기존 API 응답 필드는 임의로 제거하지 않는다.

허용:

```text
1. optional field 추가
2. nullable field 추가
3. enum 값 추가 시 문서화
4. 새로운 endpoint 추가
```

주의 또는 금지:

```text
1. 기존 field 제거
2. field type 변경
3. enum 의미 변경
4. 기존 endpoint URL 변경
5. 인증 정책 변경을 문서 없이 적용
```

## 1.3 큰 응답은 전용 serializer로 문서화

다음 API는 dict builder만으로 두면 schema drift 위험이 크다.

```text
POST /api/holdings/{id}/consult/
POST /api/holdings/{id}/probability/
GET /api/data-pipeline/summary/
GET /api/data-pipeline/data-quality/{stock_code}/
```

전용 response serializer 또는 drf-spectacular inline serializer를 사용한다.

---

# 2. 도구 선택

권장 도구:

```text
drf-spectacular
```

이유:

```text
1. Django REST Framework와 호환
2. OpenAPI 3 schema 생성
3. serializer 기반 문서화 가능
4. Swagger UI / Redoc 지원
5. extend_schema로 복잡한 응답 문서화 가능
```

대체:

```text
drf-yasg
```

하지만 신규 적용은 drf-spectacular를 권장한다.

---

# 3. 문서 URL

권장 endpoint:

```text
/api/schema/
/api/docs/swagger/
/api/docs/redoc/
```

운영 접근 정책:

| URL | local | staging | production |
|---|---:|---:|---:|
| /api/schema/ | 허용 | staff | staff 또는 비공개 |
| /api/docs/swagger/ | 허용 | staff | staff 또는 비공개 |
| /api/docs/redoc/ | 허용 | staff | staff 또는 비공개 |

민감한 내부 API가 노출될 수 있으므로 production public 공개는 신중해야 한다.

---

# 4. 인증 schema

OpenAPI에는 인증 방식을 명확히 표시한다.

production 기준:

```text
Peach SSO session 기반 인증
```

개발 기준:

```text
SessionAuthentication
BasicAuthentication local only
```

OpenAPI 설명에는 BasicAuthentication이 production에서 허용되는 것처럼 보이면 안 된다.

---

# 5. 주요 Schema 정의

## 5.1 UserHolding

필드 예:

```text
id
stock
stock_code
stock_name
quantity
average_price
current_price
created_at
updated_at
```

주의:

```text
owner/user 필드는 일반 사용자 응답에서 직접 노출하지 않는다.
```

## 5.2 AveragingDecision

필드 예:

```text
id
holding
decision_code
decision_label
score_total
risk_level
created_at
```

## 5.3 ProbabilityResult

필드 예:

```text
target_hit_probability
stop_loss_hit_probability
expected_return
expected_loss
scenario_probabilities
calibration_version
warnings
```

확률 필드는 0~1 또는 0~100 중 하나로 통일한다.

권장:

```text
0.0 ~ 1.0 float
```

화면에서 `%`로 변환한다.

## 5.4 ConsultingResult

상위 구조:

```json
{
  "holding": {},
  "decision": {},
  "score": {},
  "probability": {},
  "capital_plan": {},
  "risk": {},
  "portfolio_risk": {},
  "data_basis": {},
  "warnings": [],
  "disclaimer": ""
}
```

---

# 6. Enum 정책

## 6.1 decision_code

예:

```text
REVIEW_POSSIBLE
HOLD_REVIEW_REQUIRED
AVERAGING_NOT_SUITABLE
RISK_TOO_HIGH
DATA_INSUFFICIENT
BLOCKED_BY_RISK_EVENT
```

문구는 label로 분리한다.

```text
decision_code = 기계 판독용
decision_label = 사용자 표시용
```

## 6.2 risk_grade

```text
LOW
MODERATE
HIGH
CRITICAL
UNKNOWN
```

## 6.3 data_quality_grade

```text
A
B
C
D
F
UNKNOWN
```

## 6.4 provider_status

```text
UP
DEGRADED
DOWN
AUTH_FAILED
RATE_LIMITED
DISABLED
UNKNOWN
```

---

# 7. Error Response Schema

모든 API 오류 응답은 가능한 한 동일 구조를 사용한다.

```json
{
  "error": {
    "code": "PERMISSION_DENIED",
    "message": "접근 권한이 없습니다.",
    "details": {},
    "request_id": "req_abc123"
  }
}
```

공통 error code:

```text
VALIDATION_ERROR
AUTHENTICATION_REQUIRED
PERMISSION_DENIED
NOT_FOUND
DATA_QUALITY_TOO_LOW
RISK_EVENT_BLOCKED
PROVIDER_UNAVAILABLE
INTERNAL_ERROR
```

DRF 기본 오류와 완전히 맞추기 어렵다면, consult/probability 같은 핵심 API부터 통일한다.

---

# 8. Pagination / Filtering / Ordering

list API는 다음 정책을 문서화한다.

```text
pagination: limit/offset 또는 page number 중 하나로 통일
filtering: query parameter 명시
ordering: ordering parameter 명시
```

예:

```http
GET /api/holdings/?limit=20&offset=0&ordering=-created_at
```

응답 예:

```json
{
  "count": 120,
  "next": "...",
  "previous": null,
  "results": []
}
```

---

# 9. Schema 검증 테스트

## 9.1 schema 생성 테스트

```bash
python manage.py spectacular --file schema.yaml --validate
```

## 9.2 CI 체크

```text
1. schema 생성 성공
2. schema validation 성공
3. 주요 endpoint가 schema에 존재
4. 인증 scheme이 production 정책과 일치
5. consult response serializer가 깨지지 않음
```

## 9.3 schema diff

운영 배포 전 이전 schema와 diff를 확인한다.

주의할 변경:

```text
1. field 삭제
2. required field 추가
3. type 변경
4. enum 제거
5. endpoint 삭제
```

---

# 10. 버전 관리

초기에는 URL versioning을 바로 도입하지 않아도 된다.

현재 권장:

```text
/api/...
```

향후 외부 연동이 많아지면:

```text
/api/v1/...
```

API 응답에는 schema version 또는 engine version을 포함할 수 있다.

```json
{
  "schema_version": "2026-06-01",
  "engine_version": "scoring-2026-06-v1"
}
```

---

# 11. 문서 표시 문구

Swagger/Redoc 상단에는 다음을 표시한다.

```text
theStock API는 투자 권유가 아닌 데이터 기반 참고 분석을 제공한다.
확률 및 컨설팅 결과는 미래 수익을 보장하지 않는다.
```

운영 인증 설명에는 다음을 표시한다.

```text
Production API는 Peach SSO 인증 세션을 기준으로 보호된다.
BasicAuthentication은 production에서 지원하지 않는다.
```

---

# 12. 구현 체크리스트

```text
[ ] drf-spectacular 설치
[ ] SPECTACULAR_SETTINGS 추가
[ ] /api/schema/ URL 추가
[ ] Swagger UI URL 추가
[ ] Redoc URL 추가
[ ] production 접근 제한 설정
[ ] consult response serializer 정의
[ ] probability response serializer 정의
[ ] data pipeline summary serializer 정의
[ ] error response schema 정의
[ ] 주요 enum 문서화
[ ] schema validation command 실행
[ ] schema diff 절차 문서화
[ ] api_reference.md와 schema 일치 확인
```

---

# 13. Codex 작업 지시 요약

```text
theStock API에 drf-spectacular 기반 OpenAPI schema를 추가한다.
기존 API URL과 응답 구조는 깨지지 않아야 한다.
consult/probability/data-pipeline처럼 큰 dict 응답은 전용 response serializer 또는 extend_schema로 문서화한다.
production에서는 API 문서 접근을 staff 또는 내부 접근으로 제한한다.
BasicAuthentication이 production 인증 방식처럼 보이지 않게 문서화한다.
schema 생성/validation 테스트를 추가한다.
```

---

# 14. 결론

OpenAPI schema는 단순 문서가 아니다.

`theStock`에서는 다음을 보장하는 안전장치다.

```text
1. API 응답 구조가 갑자기 깨지지 않는다.
2. 프론트엔드와 백엔드가 같은 계약을 본다.
3. 컨설팅/확률 응답의 큰 구조가 관리된다.
4. 인증 정책이 명확해진다.
5. 운영 배포 전 breaking change를 찾을 수 있다.
```

따라서 OpenAPI schema 안정화는 운영 서비스 전환을 위한 필수 보강 항목이다.
