# 10_auth_policy_design.md

# theStock 인증 및 권한 정책 설계서

---

# 0. 문서 목적

이 문서는 `theStock`의 인증, 세션, 권한, API 접근 정책을 정리한다.

기존 문서에서는 다음 인증 방식이 함께 언급된다.

```text
1. Django SessionAuthentication
2. BasicAuthentication
3. Peach SSO
```

개발 단계에서는 여러 인증 방식이 공존할 수 있지만, 운영 단계에서는 인증 정책이 명확해야 한다.  
특히 `theStock`는 사용자 보유 종목, 평균 단가, 수량, 투자금, 컨설팅 결과를 다루므로 일반적인 게시판 서비스보다 권한 관리가 중요하다.

이 문서의 목적은 다음이다.

```text
1. 운영 인증의 단일 기준을 확정한다.
2. 개발/테스트/운영 환경별 인증 허용 범위를 분리한다.
3. 사용자 데이터 owner scope 원칙을 명확히 한다.
4. 기준 데이터 write 권한을 staff로 제한한다.
5. Peach SSO 연동 후 shadow user 정책을 정의한다.
6. API 인증, 세션, 로그아웃, 관리자 접근 정책을 정리한다.
```

---

# 1. 인증 정책의 최상위 원칙

## 1.1 운영 인증 원칙

운영 환경에서 `theStock`의 인증 원칙은 다음과 같다.

```text
Peach SSO를 유일한 사용자 인증 소스로 사용한다.
```

즉, 운영환경에서는 다음을 지양한다.

```text
1. theStock 자체 회원가입
2. theStock 자체 일반 사용자 로그인 화면
3. 운영 API에 대한 BasicAuthentication 허용
4. 임시 관리자 계정 남발
5. 사용자 식별 없이 보유 종목 또는 컨설팅 API 접근
```

## 1.2 개발 인증 원칙

개발환경에서는 구현과 테스트 편의를 위해 다음을 허용할 수 있다.

```text
1. Django admin login
2. Django SessionAuthentication
3. 테스트 전용 BasicAuthentication
4. fixture 기반 테스트 사용자
```

단, 개발 인증 허용은 반드시 환경변수 또는 settings 분기로 통제해야 한다.

예:

```python
if DEBUG:
    REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ]
else:
    REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] = [
        "thestock.auth.peach.PeachSessionAuthentication",
    ]
```

실제 구현명은 프로젝트 구조에 맞게 조정한다.

---

# 2. 환경별 인증 허용 범위

## 2.1 local 개발환경

| 항목 | 허용 여부 | 설명 |
|---|---:|---|
| Django admin login | 허용 | 개발자 관리용 |
| SessionAuthentication | 허용 | DRF browsable API 테스트용 |
| BasicAuthentication | 제한 허용 | local/test only |
| Peach SSO | 선택 | 연동 테스트 시 사용 |
| anonymous consult API | 금지 | 사용자 보유 종목 기반이므로 금지 |

## 2.2 staging 환경

| 항목 | 허용 여부 | 설명 |
|---|---:|---|
| Django admin login | 제한 허용 | staff only |
| SessionAuthentication | 제한 허용 | admin/session 기반 확인 |
| BasicAuthentication | 원칙적 금지 | 자동 테스트용이면 IP 제한 필요 |
| Peach SSO | 필수 | 운영과 동일하게 검증 |
| anonymous consult API | 금지 | 운영과 동일 |

## 2.3 production 환경

| 항목 | 허용 여부 | 설명 |
|---|---:|---|
| Django admin login | staff superuser만 제한 허용 | 접근 IP/2FA/터널 보호 권장 |
| SessionAuthentication | Peach SSO 세션 연동용 | 독립 로그인 금지 |
| BasicAuthentication | 금지 | 운영 API 노출 방지 |
| Peach SSO | 필수 | 유일한 사용자 인증 소스 |
| anonymous consult API | 금지 | 개인정보/금융정보 보호 |

---

# 3. 사용자 모델 정책

## 3.1 Shadow User 원칙

`theStock`는 Peach SSO를 인증 원천으로 사용하되, 내부 DB에는 서비스 운영에 필요한 사용자 레코드를 유지할 수 있다.

이를 shadow user라고 한다.

```text
Peach 사용자 = 인증 원천
theStock User = 서비스 내부 권한/소유권/로그 연결용 shadow user
```

## 3.2 Shadow User 생성 시점

Peach SSO 인증이 성공하고 `theStock`로 돌아온 시점에 다음을 수행한다.

```text
1. Peach user id 또는 subject 값을 확인한다.
2. 기존 shadow user가 있으면 연결한다.
3. 없으면 새 shadow user를 생성한다.
4. email, display_name 등 필요한 최소 정보만 저장한다.
5. 마지막 로그인 시각을 기록한다.
```

## 3.3 저장 권장 필드

```text
peach_subject
email
display_name
is_active
is_staff
last_login
created_at
updated_at
```

민감하거나 불필요한 Peach 원본 profile 전체를 저장하지 않는다.

---

# 4. Staff 권한 정책

## 4.1 staff 권한의 의미

`theStock`에서 staff는 다음 작업을 할 수 있는 운영자 권한이다.

```text
1. 기준 데이터 등록/수정
2. 데이터 수집 로그 확인
3. 데이터 품질 리포트 확인
4. 모든 사용자 요청 장애 조사
5. 관리자 화면 접근
```

staff는 일반 사용자보다 훨씬 강한 권한이므로 자동 부여하지 않는다.

## 4.2 staff 부여 기준

권장 기준:

```text
1. Peach 관리자 그룹에 속한 사용자
2. 별도 allowlist에 등록된 사용자
3. Django superuser가 수동 승인한 사용자
```

운영에서는 다음 방식 중 하나를 택한다.

```text
PEACH_STAFF_GROUP=thestock_admin
또는
THESTOCK_STAFF_EMAILS=admin1@example.com,admin2@example.com
```

## 4.3 staff 권한 동기화

로그인 시점마다 Peach group 또는 allowlist를 확인하여 `is_staff`를 갱신한다.

주의:

```text
1. 한 번 staff였다고 영구 staff로 남기지 않는다.
2. Peach에서 권한이 제거되면 theStock에서도 제거되어야 한다.
3. 권한 변경 내역은 감사 로그로 남긴다.
```

---

# 5. 권한 Matrix

## 5.1 사용자 보유 데이터

| 리소스 | 일반 사용자 | staff | 비고 |
|---|---:|---:|---|
| UserHolding | 본인 CRUD | 전체 조회/관리 | owner scope 필수 |
| AveragingDecision | 본인 조회 | 전체 조회 | 생성은 엔진/시스템 |
| ConsultingResult | 본인 조회 | 전체 조회 | 민감 정보 포함 |
| ProbabilityResult | 본인 조회 | 전체 조회 | 투자 판단 정보 |

## 5.2 기준 데이터

| 리소스 | 일반 사용자 | staff | 비고 |
|---|---:|---:|---|
| Stock | 조회 | 쓰기 | 기준 데이터 |
| DailyPrice | 조회 | 쓰기 | 가격 데이터 |
| InvestorFlow | 조회 | 쓰기 | 수급 데이터 |
| MarketIndex | 조회 | 쓰기 | 시장 데이터 |
| RiskEvent | 조회 | 쓰기 | 리스크 데이터 |
| TechnicalIndicator | 조회 | 쓰기 | 일반 사용자 write 금지 |
| FinancialSnapshot | 조회 | 쓰기 | 재무 데이터 |
| DataQualityReport | 제한 조회 | 전체 조회/관리 | 데이터 품질 |
| DataIngestionLog | 제한 조회 | 전체 조회 | 운영 로그 |

## 5.3 운영 API

| API | 일반 사용자 | staff | 비고 |
|---|---:|---:|---|
| holding list/detail | 본인만 | 전체 가능 | owner scope |
| consult | 본인 holding만 | 제한적 가능 | 감사 로그 권장 |
| probability | 본인 holding만 | 제한적 가능 | 감사 로그 권장 |
| data pipeline run | 금지 | 가능 | 운영자 전용 |
| provider status | 제한 조회 | 전체 조회 | 내부 정보 노출 주의 |
| admin | 금지 | 가능 | staff/superuser |

---

# 6. API 인증 구현 원칙

## 6.1 기본 원칙

모든 개인화 API는 인증 필수다.

```text
1. UserHolding 관련 API 인증 필수
2. consult API 인증 필수
3. probability API 인증 필수
4. 사용자 컨설팅 이력 API 인증 필수
5. 기준 데이터 조회 API도 운영에서는 인증 권장
```

## 6.2 owner scope 필터링

ViewSet의 queryset은 항상 사용자 기준으로 제한한다.

예시:

```python
def get_queryset(self):
    user = self.request.user
    if user.is_staff:
        return UserHolding.objects.all()
    return UserHolding.objects.filter(user=user)
```

단, staff가 전체 데이터를 볼 때도 목적과 로그가 필요하다.

## 6.3 object permission

단순 queryset filter만으로 부족할 수 있다.  
object-level permission을 별도로 둔다.

```text
1. 소유자가 아니면 접근 불가
2. staff는 접근 가능하되 감사 로그 기록
3. 비활성 사용자의 데이터 접근 차단
```

---

# 7. BasicAuthentication 운영 차단

## 7.1 차단 이유

BasicAuthentication은 다음 문제가 있다.

```text
1. 운영 API에 계정/비밀번호가 반복 전달될 수 있다.
2. 브라우저/프록시/로그에 노출될 위험이 있다.
3. Peach SSO 정책과 충돌한다.
4. 서비스별 독립 계정 운영을 유도한다.
```

따라서 production에서는 비활성화한다.

## 7.2 예외

운영에서 자동 smoke test가 반드시 필요하다면 다음 조건을 모두 만족해야 한다.

```text
1. 별도 internal endpoint
2. IP allowlist
3. 장기 비밀번호 금지
4. token 기반 단기 인증
5. 접근 로그 필수
```

---

# 8. 세션 정책

## 8.1 세션 수명

권장:

```text
SESSION_COOKIE_AGE=7200
SESSION_SAVE_EVERY_REQUEST=False
SESSION_EXPIRE_AT_BROWSER_CLOSE=True 또는 정책에 따라 False
```

투자 정보 서비스이므로 너무 긴 세션은 피한다.

## 8.2 쿠키 보안

production 필수:

```text
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_HTTPONLY=True
CSRF_COOKIE_HTTPONLY=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax
```

Peach SSO 연동 방식에 따라 `SameSite=None`이 필요할 수 있다.  
이 경우 반드시 `Secure=True`가 필요하다.

## 8.3 로그아웃

로그아웃은 다음을 구분한다.

```text
1. theStock local session logout
2. Peach global logout
```

권장 동작:

```text
1. theStock logout 버튼 클릭
2. theStock session 삭제
3. Peach logout URL로 redirect할지 정책에 따라 결정
4. 사용자가 명시적으로 전체 로그아웃을 원하면 Peach global logout 수행
```

---

# 9. CSRF / CORS 정책

## 9.1 CSRF

브라우저 기반 session 인증을 쓰는 경우 CSRF 보호는 유지한다.

```text
1. HTML form POST는 CSRF 필수
2. AJAX POST도 CSRF token 전달
3. consult/probability API가 session 기반이면 CSRF 필요
```

## 9.2 CORS

운영에서는 허용 origin을 제한한다.

```text
CORS_ALLOWED_ORIGINS=https://stock.thesysm.com,https://peach.thesysm.com
```

와일드카드 사용 금지:

```text
CORS_ALLOW_ALL_ORIGINS=True 금지
```

---

# 10. 감사 로그 정책

다음 행위는 감사 로그로 남긴다.

```text
1. 로그인 성공/실패
2. 로그아웃
3. staff 권한 변경
4. staff의 사용자 보유 데이터 조회
5. consult API 실행
6. probability API 실행
7. 기준 데이터 수정
8. 데이터 파이프라인 수동 실행
9. API 인증 실패 반복
```

로그에는 민감 정보를 직접 저장하지 않는다.

금지:

```text
1. 평균 단가 전체 노출
2. 보유 수량 전체 노출
3. 투자금 전체 노출
4. access token 저장
5. secret key 저장
```

---

# 11. 구현 체크리스트

```text
[ ] production settings에서 BasicAuthentication 제거
[ ] Peach SSO 인증 backend 또는 middleware 정리
[ ] shadow user 생성/갱신 로직 구현
[ ] staff allowlist/group 동기화 구현
[ ] UserHolding owner scope 테스트
[ ] consult API owner permission 테스트
[ ] probability API owner permission 테스트
[ ] TechnicalIndicator write 권한 staff 제한
[ ] 기준 데이터 API write 권한 staff 제한 통일
[ ] CORS/CSRF production 설정 확인
[ ] session cookie secure 설정 확인
[ ] logout 동작 확인
[ ] 감사 로그 기본 구조 구현
```

## 12.1 External Integration Credential 권한 정책

사용자별 Toss credential 구조를 도입할 경우 다음 권한 정책을 적용한다.

일반 사용자:

- 본인의 `TossInvestCredential` 등록/수정/삭제/상태 조회만 가능하다.
- 다른 사용자의 credential, account mapping, Toss 조회 결과에 접근할 수 없다.
- credential reveal은 본인 재인증 후 짧은 시간 동안만 허용한다.
- user-scoped Toss holdings/order history는 owner scope를 반드시 강제한다.

Staff:

- 기본적으로 사용자 `client_secret`, access token, refresh token 평문 reveal은 불가하다.
- 연결 상태, masked account, safe error, audit summary 확인은 운영 목적에 한해 허용할 수 있다.
- staff-only global credential 기반 기능과 일반 사용자 user-scoped 기능을 URL/API/template/permission에서 분리한다.
- staff 민감 조회는 audit log 대상이다.

금지:

- `user_id`, username, email query로 다른 사용자 credential 조회.
- account 원문 query 허용.
- credential/token/header 원문 response.
- 전역 Toss credential로 일반 사용자 holdings/order history를 조회.
- 컨설팅 결과를 주문 API 또는 자동매매에 연결.

Audit:

- credential 등록/수정/삭제/reveal/access/token refresh/Toss 조회/permission denied 이벤트를 기록한다.
- AuditLog에는 actor/target/account를 hash 또는 opaque reference로 저장한다.
- AuditLog에도 credential 원문, account 원문, token/header, raw response, order id 원문을 저장하지 않는다.

---

# 12. Codex 작업 지시 요약

후속 구현 시 Codex에는 다음 원칙을 강조한다.

```text
1. 운영 환경에서는 Peach SSO만 사용자 인증 원천으로 사용한다.
2. BasicAuthentication은 production에서 제거한다.
3. 기존 API URL과 응답 구조는 깨지지 않게 한다.
4. 모든 사용자 데이터는 owner scope를 반드시 적용한다.
5. 기준 데이터 write는 staff에게만 허용한다.
6. TechnicalIndicator API도 staff write로 통일한다.
7. 인증/권한 변경 후 기존 테스트와 smoke test를 반드시 실행한다.
8. API key, token, secret은 코드와 문서에 저장하지 않는다.
```

---

# 13. 결론

`theStock`의 운영 인증 기준은 Peach SSO다.

개발 편의 때문에 존재했던 SessionAuthentication, BasicAuthentication, Django 기본 login 흐름은 production에서 명확히 제한되어야 한다.

가장 중요한 원칙은 다음 세 가지다.

```text
1. 사용자의 투자 정보는 본인만 볼 수 있다.
2. 기준 데이터는 staff만 수정할 수 있다.
3. 운영 인증은 Peach SSO로 일원화한다.
```
