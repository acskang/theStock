# 09_production_deployment_design.md

# theStock 9단계 설계서: Production Deployment & Peach SSO Integration

---

# 0. 문서 목적

이 문서는 `theStock` 프로젝트를 운영환경에 배포하기 위한 9단계 구현 계획을 정의한다.

이전 단계까지 `theStock`는 다음 상태에 도달했다.

```text
1. Django foundation
2. scoring / probability / consulting API
3. consulting UI
4. data pipeline / data quality 구조
```

하지만 아직 운영 배포에 필요한 핵심 조건이 충족되지 않았다.

```text
1. Peach SSO relying-party 연동이 없다.
2. 운영 배포 자산(deploy/production)이 없다.
3. 운영 보안 설정이 prod 기준으로 충분히 강화되지 않았다.
4. Cloudflare Tunnel / Nginx / Gunicorn / systemd 설치 자동화가 없다.
5. 데이터 수집 운영 스케줄 전략이 정리되지 않았다.
```

따라서 9단계의 목적은 다음이다.

```text
1. theStock를 Peach SSO relying service로 전환
2. 운영 보안 설정을 prod 수준으로 보강
3. anglangl/deploy와 동일한 형태의 배포 자산 생성
4. 운영환경 설치/검증 스크립트 작성
5. 데이터 파이프라인 운영 스케줄 방안 정리
6. 배포/검증/롤백 순서를 문서화
```

이 단계는 기능 확장이 아니다.  
이 단계는 `theStock`를 실제 운영환경에 올릴 수 있게 만드는 **인증/배포/운영 전환 단계**다.

---

# 1. 기준 시스템과 전제

## 1.1 기준 프로젝트

이번 단계는 아래 두 시스템을 기준으로 한다.

```text
1. Peach SSO 제공자:
   /home/cskang/ganzskang/ThePeach

2. 운영 배포 템플릿:
   /home/cskang/ganzskang/anglangl/deploy/production
```

사용자가 처음 제시한 경로명과 실제 디렉토리명은 일부 다르므로, 이번 설계서는 **실제 확인된 경로**를 기준으로 작성한다.

---

## 1.2 현재 theStock 상태 요약

현재 `theStock`는 아래 특징을 가진다.

```text
1. Django 기본 auth login 화면 사용
2. SessionAuthentication / BasicAuthentication 기반 API 보호
3. prod settings는 PostgreSQL 전환만 있고 보안 설정은 최소 수준
4. healthz / readyz 엔드포인트 존재
5. deploy/production 자산 부재
6. Celery worker 없음
7. 데이터 수집은 management command 기반
```

즉, `anglangl`처럼 바로 배포 스크립트를 복제해서 끝나는 구조가 아니다.

핵심 선행 작업은 다음이다.

```text
운영 배포 이전에 Peach SSO relying-party 구조를 먼저 넣어야 한다.
```

---

## 1.3 운영 토폴로지

운영 토폴로지는 `ThePeach` 및 `anglangl`과 동일 계열로 맞춘다.

```text
Client
  -> Cloudflare
  -> Nginx
  -> Gunicorn
  -> Django(stock_service.settings.prod)
```

운영 기본값:

```text
- Django 직접 외부 노출 금지
- Nginx가 static 제공
- Gunicorn이 Django 트래픽 처리
- PostgreSQL 기본 사용
- Cloudflare Tunnel ingress 사용
```

---

# 2. 핵심 원칙

## 2.1 Peach가 유일한 인증 소스다

`theStock`는 독립 로그인/회원가입 서비스를 운영하지 않는다.

반드시 다음 원칙을 따른다.

```text
1. 사용자는 theStock 로그인 화면에서 자격증명을 입력한다.
2. 자격증명 검증은 theStock 서버가 Peach API로 relay 한다.
3. Peach가 access / refresh token을 발급한다.
4. 공유 SSO cookie는 .thesysm.com 범위에서 사용한다.
5. theStock의 local session은 Peach 인증 결과의 캐시일 뿐이다.
6. local user row가 생기더라도 shadow user로 취급한다.
```

금지:

```text
- theStock 독자 회원가입 유지
- theStock 독자 비밀번호 저장 정책 운영
- 브라우저 JS에서 Peach auth API 직접 cross-origin 호출
```

---

## 2.2 anglangl의 배포 형태를 유지하되, 기능 없는 구성은 억지로 복제하지 않는다

배포 디렉토리 구조는 `anglangl/deploy/production`을 따른다.

하지만 `theStock`에 없는 기능은 그대로 복제하지 않는다.

예시:

```text
유지:
- install script
- run script
- validate script
- gunicorn service
- gunicorn config
- nginx conf
- cloudflared ingress fragment
- env example

복제하지 않음:
- celery service
```

이유:

```text
theStock는 현재 Celery 기반 비동기 worker가 없고,
데이터 파이프라인은 management command 기반이기 때문이다.
```

---

## 2.3 배포 전에 prod security check를 통과해야 한다

`python manage.py check --deploy`는 이번 단계의 필수 기준이다.

현재 보완이 필요한 항목은 다음이다.

```text
1. SECURE_SSL_REDIRECT
2. SECURE_HSTS_SECONDS
3. SESSION_COOKIE_SECURE
4. CSRF_COOKIE_SECURE
5. reverse proxy 신뢰 설정
```

단, `SECRET_KEY` 경고는 테스트용 임시 secret이 아니라 실제 운영 secret으로 해결한다.

---

## 2.4 데이터 수집 운영은 Celery가 아니라 scheduler-first로 시작한다

현재 `theStock`는 다음 커맨드를 이미 제공한다.

```text
- collect_daily_prices
- collect_market_indices
- collect_investor_flows
- collect_risk_events
- collect_financial_snapshots
- refresh_decision_inputs
- run_daily_pipeline
```

따라서 9단계에서는 다음 접근을 채택한다.

```text
1. 우선 systemd timer 또는 cron 기반 운영 스케줄 정의
2. 필요한 경우에만 후속 단계에서 Celery 전환 검토
```

---

# 3. 구현 범위

## 3.1 포함 범위

```text
1. platform_auth 앱 추가
2. Peach SSO middleware / services / cookies / session / views 구현
3. 로그인/로그아웃 route 교체
4. prod settings 보안 보강
5. deploy/production 디렉토리 생성
6. gunicorn/nginx/cloudflared/systemd 자산 생성
7. env example 작성
8. install / run / validate 스크립트 작성
9. 운영 스케줄 전략 문서화
10. 테스트 및 smoke 절차 문서화
```

---

## 3.2 제외 범위

```text
1. Peach OAuth provider 변경
2. theStock 도메인 외 추가 서비스 연동
3. Celery 도입
4. 대규모 UI 리디자인
5. business logic refactor
6. 데이터 모델 구조 대수술
7. 자동 배포 CI/CD 완성
```

---

# 4. 단계별 작업 계획

## 4.1 Phase 0 - 배포 전 고정값 확정

목표:

```text
운영환경에서 바뀌면 안 되는 식별자와 외부 의존값을 먼저 확정한다.
```

확정 항목:

```text
1. public domain
2. /etc/thestock/thestock.env 경로
3. PostgreSQL DB 이름/계정
4. Peach public host header
5. 로그 디렉토리
6. Gunicorn socket 경로
7. static root alias 경로
8. 데이터 수집 스케줄 실행 주기
```

권장값:

```text
PUBLIC_DOMAIN=stock.thesysm.com
ENV_FILE=/etc/thestock/thestock.env
LOG_DIR=/logs/thestock
SOCKET_SYMLINK=/run/gunicorn_thestock.sock
SOCKET_REAL=/run/thestock/gunicorn.sock
STATIC_ALIAS=/var/www/thestock/static
```

주의:

```text
운영 도메인은 반드시 .thesysm.com 하위여야 Peach 공유 쿠키가 정상 동작한다.
```

---

## 4.2 Phase 1 - Peach SSO relying-party 계층 도입

목표:

```text
theStock를 Peach 인증을 신뢰하는 relying service로 전환한다.
```

새 앱:

```text
platform_auth/
 ├── __init__.py
 ├── apps.py
 ├── urls.py
 ├── views.py
 ├── services.py
 ├── middleware.py
 ├── cookies.py
 ├── session.py
 ├── forms.py
 └── tests.py
```

구현 포인트:

```text
1. local login POST -> Peach /api/v1/auth/login/ relay
2. access token 검증 -> Peach /api/v1/auth/me/
3. access 만료 시 -> Peach /api/v1/auth/token/refresh/
4. logout -> Peach /api/v1/auth/logout/
5. thepeach_sso_access / thepeach_sso_refresh cookie 사용
6. local session에는 auth source, token, profile cache 저장
7. shadow user 생성/동기화
```

적용 대상:

```text
- 현재 /accounts/login/ 진입 흐름
- login_required 기반 HTML 화면
- SessionAuthentication 기반 API
```

핵심 의사결정:

```text
1. 기존 route 명은 가능하면 유지한다.
2. 내부 구현만 Peach relay 방식으로 바꾼다.
3. 독립 signup은 제거하거나 Peach signup으로 redirect 한다.
```

완료 기준:

```text
1. 같은 브라우저에서 Peach 로그인 상태를 theStock가 자동 인식한다.
2. refresh token 기반 재인증이 동작한다.
3. logout 시 Peach 공유 쿠키가 같이 정리된다.
```

---

## 4.3 Phase 2 - 운영 settings 보강

목표:

```text
stock_service.settings.prod를 운영 보안 수준으로 강화한다.
```

필수 설정:

```text
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
```

추가 환경 변수:

```text
DJANGO_CSRF_TRUSTED_ORIGINS
DJANGO_LOG_DIR
DJANGO_SECURE_SSL_REDIRECT
DJANGO_SECURE_HSTS_SECONDS
THEPEACH_AUTH_BASE_URL
THEPEACH_LOGIN_BASE_URL
THEPEACH_UPSTREAM_HOST_HEADER
THEPEACH_SSO_ACCESS_COOKIE_NAME
THEPEACH_SSO_REFRESH_COOKIE_NAME
THEPEACH_SSO_COOKIE_DOMAIN
THEPEACH_SSO_COOKIE_PATH
THEPEACH_SSO_COOKIE_SAMESITE
THEPEACH_AUTH_TIMEOUT
```

주의:

```text
1. manage.py 기본 dev 설정은 유지
2. prod는 반드시 환경 변수로 명시 실행
3. insecure default를 prod에서 허용하지 않는다
```

완료 기준:

```text
python manage.py check --settings=stock_service.settings.prod 통과
python manage.py check --deploy --settings=stock_service.settings.prod 경고 제거
```

---

## 4.4 Phase 3 - deploy/production 자산 생성

목표:

```text
anglangl/deploy/production와 동일한 배포 자산 체계를 theStock에 만든다.
```

생성 파일:

```text
deploy/production/
 ├── README.md
 ├── thestock.env.example
 ├── gunicorn_thestock.config.py
 ├── gunicorn_thestock.service
 ├── gunicornctl.sh
 ├── nginx_thestock.conf
 ├── cloudflared_thestock_ingress.yml
 ├── install_thestock.sh
 ├── run_thestock_deploy.sh
 └── validate_thestock.sh
```

구성 원칙:

```text
1. 실행 경로는 /home/cskang/ganzskang/theStock 기준
2. Python 실행기는 conda env dj5 기준
3. systemd service는 root system scope를 우선 사용
4. Nginx는 unix socket proxy 사용
5. Cloudflare ingress는 hostname + unixSocketPath 형태 사용
```

Gunicorn 기준:

```text
WorkingDirectory=/home/cskang/ganzskang/theStock
ExecStart=/home/cskang/miniconda3/envs/dj5/bin/gunicorn ...
```

Nginx 기준:

```text
1. X-Forwarded-Proto https 강제
2. static alias 직접 제공
3. media alias는 현재 optional
4. /healthz/ 와 /readyz/ 접근 가능
```

주의:

```text
theStock는 현재 실질적 업로드 media 의존성이 거의 없으므로,
media alias는 placeholder 수준으로 둘 수 있다.
```

---

## 4.5 Phase 4 - 운영 환경 변수 설계

목표:

```text
운영에서 필요한 모든 값을 /etc/thestock/thestock.env 하나로 수렴한다.
```

필수 변수:

```text
DJANGO_SECRET_KEY
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
DJANGO_SETTINGS_MODULE=stock_service.settings.prod
DJANGO_LOG_DIR=/logs/thestock
DJANGO_LOG_LEVEL=INFO
DJANGO_TIME_ZONE=Asia/Seoul
DJANGO_SECURE_SSL_REDIRECT=true
POSTGRES_DB
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_HOST
POSTGRES_PORT
APP_VERSION
APP_BUILD_SHA
READINESS_CHECK_MIGRATIONS=1
LEGACY_PORTFOLIO_USERNAME
OPENDART_API_KEY
DATA_PIPELINE_PROVIDER=auto
THEPEACH_AUTH_BASE_URL=http://127.0.0.1
THEPEACH_LOGIN_BASE_URL=http://127.0.0.1
THEPEACH_UPSTREAM_HOST_HEADER=peach.thesysm.com
THEPEACH_SSO_COOKIE_DOMAIN=.thesysm.com
THEPEACH_SSO_COOKIE_SAMESITE=Lax
```

운영 확인 필요 항목:

```text
1. KRX 관련 자격정보 필요 여부
2. 배포 시 APP_VERSION / APP_BUILD_SHA 주입 방식
3. stock.thesysm.com 실제 hostname 확정 여부
```

---

## 4.6 Phase 5 - 설치/검증 자동화

목표:

```text
운영 서버에서 사람이 반복하는 수작업을 스크립트로 묶는다.
```

`install_thestock.sh` 책임:

```text
1. /etc/thestock, /var/www/thestock, /logs/thestock 생성
2. env 파일 생성 또는 유지
3. nginx / systemd / cloudflared 파일 설치
4. static symlink 생성
5. pip install -r requirements.txt
6. collectstatic
7. migrate
8. manage.py check --deploy
9. systemctl daemon-reload
10. gunicorn / nginx / cloudflared restart
```

`validate_thestock.sh` 책임:

```text
1. manage.py check
2. unix socket 기반 /healthz/ 확인
3. unix socket 기반 /readyz/ 확인
4. gunicorn 상태 확인
5. nginx 상태 확인
6. cloudflared 상태 확인
```

---

## 4.7 Phase 6 - 데이터 파이프라인 운영 스케줄

목표:

```text
theStock 판단 엔진이 실제 운영 데이터로 갱신되도록 최소 운영 주기를 정의한다.
```

초기 권장안:

```text
1. 평일 장 마감 후 1회 run_daily_pipeline
2. 필요 시 refresh_decision_inputs 수동 실행
3. 실패 로그는 application log + data pipeline 상태 API로 확인
```

권장 실행 형태:

```text
systemd timer 또는 cron
```

예시:

```text
weekday 18:30 Asia/Seoul
python manage.py run_daily_pipeline --provider auto
```

주의:

```text
1. OPENDART_API_KEY 없으면 리스크/재무 단계가 실패한다.
2. 투자자 수급은 pykrx 운영환경 제약을 사전 확인해야 한다.
3. 9단계에서는 스케줄러 정의까지만 하고, worker 시스템은 도입하지 않는다.
```

---

## 4.8 Phase 7 - 스모크 테스트와 운영 전환

목표:

```text
기능이 아니라 실제 운영 시나리오가 통하는지 확인한다.
```

스모크 체크리스트:

```text
1. GET /healthz/ -> 200
2. GET /readyz/ -> 200 또는 문제 원인 명시
3. /accounts/login/ 또는 호환 login route 접근 가능
4. Peach 계정 로그인 성공
5. consulting/holdings/ 접근 성공
6. API docs/schema 접근 정책 확인
7. static 파일 정상 제공
8. logout 후 재접속 시 anonymous 처리
9. run_daily_pipeline --dry-run 성공
```

수동 브라우저 확인:

```text
1. Peach 로그인
2. 같은 브라우저에서 theStock 열기
3. 추가 로그인 없이 인증 인식되는지 확인
4. logout 시 shared cookie 정리 확인
```

---

# 5. 파일별 구현 계획

## 5.1 신규 파일

```text
platform_auth/apps.py
platform_auth/urls.py
platform_auth/views.py
platform_auth/services.py
platform_auth/middleware.py
platform_auth/cookies.py
platform_auth/session.py
platform_auth/forms.py
platform_auth/tests.py
deploy/production/README.md
deploy/production/thestock.env.example
deploy/production/gunicorn_thestock.config.py
deploy/production/gunicorn_thestock.service
deploy/production/gunicornctl.sh
deploy/production/nginx_thestock.conf
deploy/production/cloudflared_thestock_ingress.yml
deploy/production/install_thestock.sh
deploy/production/run_thestock_deploy.sh
deploy/production/validate_thestock.sh
```

---

## 5.2 수정 파일

```text
stock_service/settings/base.py
stock_service/settings/prod.py
stock_service/urls.py
templates/registration/login.html
README.md
.env.example
requirements.txt
```

설명:

```text
1. settings에 Peach 연동 변수 추가
2. prod security hardening
3. auth route 연결
4. login template를 Peach relay 방식에 맞게 조정
5. 운영 문서와 env 예시 갱신
6. 배포 실행에 필요한 의존성 선언 정리
```

---

# 6. 검증 전략

## 6.1 코드 검증

```bash
conda activate dj5
python manage.py check
python manage.py check --settings=stock_service.settings.prod
python manage.py check --deploy --settings=stock_service.settings.prod
python manage.py test
```

권장 추가 테스트:

```text
1. platform_auth services 단위 테스트
2. platform_auth middleware 인증/refresh/clear 테스트
3. login/logout view 테스트
4. anonymous -> redirect 테스트
5. authenticated cookie reuse 테스트
```

---

## 6.2 배포 검증

```bash
bash deploy/production/install_thestock.sh
bash deploy/production/validate_thestock.sh
```

---

## 6.3 브라우저 검증

```text
1. Peach login
2. theStock 자동 인증 인식
3. holding consulting page 접근
4. logout 연동
5. 새 브라우저 세션 anonymous 확인
```

---

# 7. 리스크와 대응

## 7.1 도메인 미확정 리스크

문제:

```text
도메인이 .thesysm.com 하위가 아니면 Peach SSO 공유 쿠키가 동작하지 않는다.
```

대응:

```text
Phase 0에서 public domain을 먼저 확정한다.
```

---

## 7.2 기존 BasicAuthentication 문서와 운영 정책 충돌

문제:

```text
현재 README 예시는 BasicAuthentication curl 사용을 전제한다.
```

대응:

```text
1. 운영 정책을 browser session 중심으로 재정리
2. 필요 시 후속 단계에서 Peach JWT 신뢰 auth를 추가 검토
```

---

## 7.3 데이터 수집 환경 변수 누락

문제:

```text
OPENDART_API_KEY 또는 pykrx 운영 제약이 준비되지 않으면 데이터 품질이 떨어진다.
```

대응:

```text
1. env example에 명시
2. validate script에는 dry-run 또는 최소 점검 포함
3. 운영 runbook에 실패 시 조치 문구 추가
```

---

## 7.4 shadow user 권한 정책 미정

문제:

```text
Peach 사용자 동기화만으로는 theStock admin/staff 권한 정책이 자동 해결되지 않는다.
```

대응:

```text
1. 기본 shadow user는 일반 사용자로 생성
2. 운영자 계정은 별도 승격 절차 정의
```

---

# 8. 권장 구현 순서

```text
1. Phase 0: 운영 고정값 확정
2. Phase 1: Peach SSO relying-party 계층 구현
3. Phase 2: prod settings 보안 보강
4. Phase 3: deploy/production 자산 생성
5. Phase 4: env example / requirements / README 갱신
6. Phase 5: install / validate 스크립트 완성
7. Phase 6: 데이터 파이프라인 스케줄 정의
8. Phase 7: smoke / rollout / rollback 검증
```

한 줄 요약:

```text
theStock 운영 배포의 본질은 단순 서버 실행이 아니라,
Peach SSO relying-party 전환 + prod security hardening + anglangl형 배포 자산 작성이다.
```
