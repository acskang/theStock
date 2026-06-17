# 09_codex_prompt_production_deployment.md

# Codex 실행 프롬프트: 9단계 Production Deployment & Peach SSO Integration 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 9단계 실행 프롬프트다.

Codex에게 이 파일과 함께 다음 문서를 반드시 참조하게 한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
docs/08_data_pipeline_design.md
docs/09_production_deployment_design.md
```

이번 단계의 직접 기준 문서는 다음이다.

```text
docs/09_production_deployment_design.md
```

추가로 참고해야 할 외부 기준 프로젝트는 다음이다.

```text
/home/cskang/ganzskang/ThePeach
/home/cskang/ganzskang/anglangl/deploy/production
```

---

# 실행 프롬프트 본문

너는 Django 서비스를 실운영 가능한 상태로 전환하는 개발 에이전트다.

이번 작업은 `theStock` 프로젝트의 **9단계 Production Deployment & Peach SSO Integration 구현**이다.

현재 `theStock`는 이미 다음이 구현된 상태라고 가정한다.

```text
1. Django foundation
2. holdings / stocks / marketdata / decisions API
3. consulting holding UI
4. data pipeline / data quality command 및 API
5. healthz / readyz 모니터링 엔드포인트
```

하지만 아직 운영 배포에 필요한 다음 요소가 없다.

```text
1. Peach SSO relying-party auth layer
2. production-grade security settings
3. deploy/production host assets
4. install / validate automation
5. 운영 스케줄 기준
```

이번 단계의 목표는 다음이다.

```text
1. platform_auth 앱 추가
2. Peach login / me / refresh / logout relay 구현
3. shared SSO cookie 기반 자동 인증 middleware 구현
4. local shadow user sync 구현
5. prod settings security hardening
6. deploy/production 자산 생성
7. Gunicorn / Nginx / Cloudflare / env / systemd 스크립트 생성
8. README / .env.example / requirements 정리
9. 테스트와 smoke validation 완성
```

---

# 1. 반드시 지킬 원칙

## 1.1 Peach가 유일한 인증 소스다

다음을 지켜라.

```text
1. theStock는 독립 비밀번호 시스템을 운영하지 않는다.
2. 로그인 검증은 반드시 server-side relay 방식으로 Peach API를 호출한다.
3. local Django session은 Peach 인증 결과의 캐시로만 사용한다.
4. local user는 shadow user로만 취급한다.
```

금지:

```text
- 브라우저 JS에서 Peach auth API 직접 fetch
- theStock 독립 signup 유지
- Peach와 무관한 별도 auth source 추가
```

---

## 1.2 최소 변경 원칙을 지켜라

이 단계는 business logic 재작성 단계가 아니다.

따라서:

```text
1. holdings / decisions / data_pipeline 도메인 로직은 건드리지 마라.
2. 인증, settings, deploy asset, 문서 범위 중심으로 수정하라.
3. 기존 route와 template 구조는 가능하면 유지하라.
```

---

## 1.3 배포 자산은 anglangl 형식을 따른다

다음 형식을 유지하라.

```text
deploy/production/
 ├── *.env.example
 ├── gunicorn_*.config.py
 ├── gunicorn_*.service
 ├── nginx_*.conf
 ├── install_*.sh
 ├── run_*_deploy.sh
 ├── validate_*.sh
 └── cloudflared_*_ingress.yml
```

단, 없는 기능은 억지로 만들지 마라.

예시:

```text
Celery가 없으면 celery service를 만들지 않는다.
```

---

## 1.4 운영 검증은 dj5 conda 환경 기준이다

모든 검증 커맨드는 다음 방식으로 실행하라.

```bash
source /home/cskang/miniconda3/etc/profile.d/conda.sh
conda activate dj5
```

필수 검증:

```bash
python manage.py check
python manage.py check --settings=stock_service.settings.prod
python manage.py check --deploy --settings=stock_service.settings.prod
python manage.py test
```

---

# 2. 단계별 구현 순서

아래 순서를 바꾸지 말고 진행하라.

## Phase 0. 기준 파악

먼저 다음을 읽어라.

```text
1. stock_service/settings/base.py
2. stock_service/settings/prod.py
3. stock_service/urls.py
4. templates/registration/login.html
5. README.md
6. /home/cskang/ganzskang/ThePeach/docs/peach-sso-service-integration-guide.md
7. /home/cskang/ganzskang/anglangl/platform_auth/*
8. /home/cskang/ganzskang/anglangl/deploy/production/*
```

확인할 사실:

```text
1. theStock current auth 방식
2. current prod security gap
3. healthz / readyz 실제 경로
4. data pipeline 운영 command 목록
5. Peach SSO contract
6. anglangl deploy asset 형태
```

---

## Phase 1. platform_auth 앱 추가

다음 파일을 만들어라.

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
```

필수 동작:

```text
1. login_with_thepeach(email, password)
2. fetch_thepeach_profile(access_token)
3. refresh_thepeach_access_token(refresh_token)
4. logout_from_thepeach(access_token, refresh_token)
5. sync_local_user(profile)
6. shared cookie 기반 middleware auto-login
7. invalid access -> refresh 시도
8. refresh 실패 -> local auth clear
```

구현 기준:

```text
anglangl/platform_auth 를 참조하되,
theStock route / template / naming에 맞게 최소 수정으로 적용하라.
```

---

## Phase 2. 기존 login 흐름 교체

수정 대상:

```text
stock_service/urls.py
templates/registration/login.html
필요 시 signup/logout template
```

원칙:

```text
1. /accounts/login/ 진입 호환성 유지 우선
2. login_required 흐름이 깨지지 않게 유지
3. 필요하면 /auth/ namespace를 추가하되 기존 redirect가 망가지지 않게 한다
```

완료 기준:

```text
1. anonymous 사용자는 보호 페이지 접근 시 login redirect
2. login POST는 Peach relay
3. 로그인 성공 후 consulting 화면 접근 가능
```

---

## Phase 3. settings 보강

수정 대상:

```text
stock_service/settings/base.py
stock_service/settings/prod.py
.env.example
```

필수 추가:

```text
1. Peach 관련 env 설정
2. SECURE_PROXY_SSL_HEADER
3. USE_X_FORWARDED_HOST
4. SECURE_SSL_REDIRECT
5. SESSION_COOKIE_SECURE
6. CSRF_COOKIE_SECURE
7. CSRF_COOKIE_HTTPONLY
8. SECURE_HSTS_SECONDS
9. SECURE_HSTS_INCLUDE_SUBDOMAINS
10. SECURE_HSTS_PRELOAD
```

주의:

```text
1. manage.py 기본 dev 설정은 유지
2. prod에서 필수 env가 없으면 명시적으로 실패하게 한다
3. insecure fallback을 prod에서 허용하지 않는다
```

---

## Phase 4. deploy/production 자산 생성

다음 파일을 만들어라.

```text
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

구현 기준:

```text
1. anglangl deploy 파일 형식을 따른다
2. Python 실행기는 /home/cskang/miniconda3/envs/dj5/bin/python 및 gunicorn 사용
3. WorkingDirectory=/home/cskang/ganzskang/theStock
4. socket path는 /run/thestock/gunicorn.sock
5. public proxy host는 stock.thesysm.com 가정
6. /healthz/ 와 /readyz/를 validate target으로 사용
```

금지:

```text
1. celery service 추가
2. theStock에 없는 worker 가정
3. 실제 비밀값 하드코딩
```

---

## Phase 5. 문서 정리

수정 대상:

```text
README.md
.env.example
필요 시 docs 하위 관련 문서
```

반영 내용:

```text
1. 운영 auth가 Peach SSO 기반임을 명시
2. healthz / readyz 운영 검증 방법 명시
3. deploy/production 사용법 명시
4. data pipeline 운영 시 필요한 env 명시
```

---

## Phase 6. 테스트 및 검증

반드시 실행:

```bash
source /home/cskang/miniconda3/etc/profile.d/conda.sh
conda activate dj5
python manage.py check
python manage.py check --settings=stock_service.settings.prod
python manage.py check --deploy --settings=stock_service.settings.prod
python manage.py test
```

가능하면 추가 실행:

```bash
bash deploy/production/validate_thestock.sh
```

테스트 초점:

```text
1. login view success / failure
2. middleware cookie reuse
3. refresh fallback
4. logout clears cookies
5. anonymous redirect
6. prod settings deploy check
```

---

# 3. 구현 세부 지침

## 3.1 settings 항목

base settings에 다음 군을 추가하라.

```text
THEPEACH_AUTH_BASE_URL
THEPEACH_LOGIN_BASE_URL
THEPEACH_UPSTREAM_HOST_HEADER
THEPEACH_SSO_ACCESS_COOKIE_NAME
THEPEACH_SSO_REFRESH_COOKIE_NAME
THEPEACH_SSO_COOKIE_DOMAIN
THEPEACH_SSO_COOKIE_PATH
THEPEACH_SSO_COOKIE_SAMESITE
THEPEACH_LOGIN_PATH
THEPEACH_SIGNUP_PATH
THEPEACH_REFRESH_PATH
THEPEACH_LOGOUT_PATH
THEPEACH_PROFILE_PATH
THEPEACH_AUTH_TIMEOUT
```

prod settings에는 다음을 강제하라.

```text
1. strong secret required
2. allowed hosts required
3. secure proxy / cookie / HSTS 설정
```

---

## 3.2 deploy env 예시 항목

`deploy/production/thestock.env.example`에는 최소한 다음을 넣어라.

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

---

## 3.3 validate 스크립트 기준

`validate_thestock.sh`는 다음을 확인해야 한다.

```text
1. env file 존재
2. manage.py check
3. curl via unix socket -> /healthz/
4. curl via unix socket -> /readyz/
5. gunicorn service status
6. nginx status
7. cloudflared status
```

---

# 4. 산출물 완료 기준

다음 조건을 모두 만족해야 완료다.

```text
1. theStock가 Peach SSO relying service로 동작한다
2. prod settings가 deploy security check를 통과한다
3. deploy/production 자산이 생성된다
4. install / validate script가 존재한다
5. README / env example이 최신화된다
6. 테스트와 check 결과를 final report에 명시한다
```

---

# 5. 최종 보고 형식

작업이 끝나면 최종 답변은 아래 형식을 따른다.

```text
Summary
Files changed
Commands run
Verification
Risks / follow-ups
```

각 항목은 짧고 구체적으로 작성하라.

특히 `Verification`에는 실제 실행한 명령과 결과를 정확히 적어라.

---

# 6. 한 줄 요약

```text
이번 9단계의 본질은 theStock를 Peach SSO를 신뢰하는 운영 서비스로 바꾸고,
anglangl형 deploy/production 자산까지 갖춘 상태로 만드는 것이다.
```
