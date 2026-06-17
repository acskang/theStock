# 15_operations_runbook.md

# theStock 운영 Runbook

---

# 0. 문서 목적

이 문서는 `theStock` 운영 중 장애, 배포, 롤백, 데이터 수집 실패, 보안 사고가 발생했을 때 운영자가 따라야 할 절차를 정리한다.

기존 `09_production_deployment_design.md`는 배포 구조를 설계한다.  
이 문서는 실제 운영 중 확인해야 할 명령과 대응 절차를 중심으로 한다.

운영 URL:

```text
https://stock.thesysm.com/
```

---

# 1. 기본 운영 원칙

```text
1. 장애 대응 시 먼저 현재 상태를 기록한다.
2. 원인 확인 전 무리한 재배포를 하지 않는다.
3. DB migration 전 반드시 backup 상태를 확인한다.
4. API key/secret/token은 로그와 문서에 남기지 않는다.
5. 사용자 금융정보를 터미널/로그/캡처에 노출하지 않는다.
6. 장애 복구 후 smoke test를 실행한다.
7. 복구 완료 후 원인과 조치 내용을 기록한다.
```

---

# 2. 서비스 상태 확인

## 2.1 HTTP 상태 확인

```bash
curl -I https://stock.thesysm.com/
curl -s https://stock.thesysm.com/healthz/
curl -s https://stock.thesysm.com/readyz/
```

기대:

```text
healthz: 애플리케이션 프로세스 alive
readyz: DB 등 의존성 확인
```

## 2.2 systemd 상태 확인

서비스명은 실제 배포 스크립트 기준으로 조정한다.

```bash
systemctl status thestock-gunicorn --no-pager
systemctl status thestock-cloudflared --no-pager
systemctl status nginx --no-pager
```

user service인 경우:

```bash
systemctl --user status thestock-gunicorn --no-pager
systemctl --user status thestock-cloudflared --no-pager
```

## 2.3 프로세스 확인

```bash
ps aux | grep -E 'gunicorn|thestock|cloudflared|nginx' | grep -v grep
```

## 2.4 포트 확인

```bash
ss -lntp | grep -E ':80|:443|:8000|:8001|:9000'
```

---

# 3. 로그 확인

## 3.1 systemd journal

```bash
journalctl -u thestock-gunicorn -n 200 --no-pager
journalctl -u thestock-gunicorn -f
```

user service:

```bash
journalctl --user -u thestock-gunicorn -n 200 --no-pager
journalctl --user -u thestock-gunicorn -f
```

## 3.2 nginx 로그

```bash
sudo tail -n 200 /var/log/nginx/access.log
sudo tail -n 200 /var/log/nginx/error.log
```

## 3.3 Django 로그

실제 설정에 맞게 조정한다.

```bash
tail -n 200 logs/thestock.log
tail -f logs/thestock.log
```

## 3.4 Cloudflare Tunnel 로그

```bash
journalctl -u thestock-cloudflared -n 200 --no-pager
journalctl --user -u thestock-cloudflared -n 200 --no-pager
```

---

# 4. 배포 절차

## 4.1 배포 전 확인

```bash
git status
python manage.py check --deploy
python manage.py showmigrations
python manage.py test
```

운영 서버에서 전체 테스트가 부담스러우면 최소 smoke test를 실행한다.

```bash
python manage.py check
python manage.py migrate --check
```

## 4.2 DB backup

PostgreSQL 예:

```bash
pg_dump "$DATABASE_URL" > backups/thestock_$(date +%Y%m%d_%H%M%S).sql
```

또는 DB 이름 기준:

```bash
pg_dump -U thestock_user -h localhost thestock_db > backups/thestock_$(date +%Y%m%d_%H%M%S).sql
```

## 4.3 코드 반영

```bash
git fetch --all
git checkout main
git pull --ff-only
```

## 4.4 의존성 설치

```bash
pip install -r requirements.txt
```

또는 운영 requirements가 분리되어 있으면:

```bash
pip install -r requirements/production.txt
```

## 4.5 migration

```bash
python manage.py migrate
```

## 4.6 static 파일

```bash
python manage.py collectstatic --noinput
```

## 4.7 서비스 재시작

```bash
sudo systemctl restart thestock-gunicorn
sudo systemctl reload nginx
```

user service:

```bash
systemctl --user restart thestock-gunicorn
```

## 4.8 배포 후 smoke test

```bash
curl -s https://stock.thesysm.com/healthz/
curl -s https://stock.thesysm.com/readyz/
```

확인 항목:

```text
1. 첫 화면 200
2. 로그인/SSO redirect 정상
3. admin 접근 정책 정상
4. 보유 종목 목록 본인 것만 표시
5. consult API 정상
6. data pipeline summary 정상
7. 로그에 secret 노출 없음
```

---

# 5. 롤백 절차

## 5.1 코드 롤백

```bash
git log --oneline -n 10
git checkout <previous_commit>
pip install -r requirements.txt
python manage.py collectstatic --noinput
sudo systemctl restart thestock-gunicorn
```

## 5.2 migration 롤백

migration 롤백은 위험하다.  
운영 DB에서는 반드시 다음을 확인한다.

```text
1. migration이 데이터 삭제를 포함하는가?
2. backup이 존재하는가?
3. rollback migration이 안전한가?
4. 코드와 DB schema가 일치하는가?
```

명령 예:

```bash
python manage.py showmigrations
python manage.py migrate <app_name> <previous_migration>
```

## 5.3 DB restore

최후 수단이다.

```bash
psql "$DATABASE_URL" < backups/thestock_YYYYMMDD_HHMMSS.sql
```

restore 전 반드시 현재 DB를 별도 backup한다.

---

# 6. 장애 유형별 대응

## 6.1 사이트 접속 불가

확인 순서:

```text
1. Cloudflare Tunnel 상태
2. nginx 상태
3. gunicorn 상태
4. Django healthz
5. DB 연결
6. 최근 배포 여부
```

명령:

```bash
systemctl status nginx --no-pager
systemctl status thestock-gunicorn --no-pager
systemctl status thestock-cloudflared --no-pager
curl -s http://127.0.0.1:<internal_port>/healthz/
```

## 6.2 502 Bad Gateway

가능 원인:

```text
1. gunicorn 중지
2. socket 경로 오류
3. upstream port 오류
4. permission 문제
5. app import error
```

확인:

```bash
journalctl -u thestock-gunicorn -n 200 --no-pager
sudo tail -n 200 /var/log/nginx/error.log
```

## 6.3 500 Internal Server Error

확인:

```bash
journalctl -u thestock-gunicorn -n 200 --no-pager
tail -n 200 logs/thestock.log
```

대응:

```text
1. 최근 배포 변경 확인
2. migration 누락 확인
3. 환경변수 누락 확인
4. provider 장애인지 app 장애인지 구분
5. 필요 시 이전 commit으로 rollback
```

## 6.4 DB 연결 실패

확인:

```bash
systemctl status postgresql --no-pager
pg_isready
python manage.py dbshell
```

원인:

```text
1. PostgreSQL 중지
2. DATABASE_URL 오류
3. DB password 변경
4. connection limit 초과
5. disk full
```

## 6.5 로그인/SSO 실패

확인:

```text
1. Peach 서비스 상태
2. redirect URI 설정
3. cookie domain
4. SameSite/Secure 설정
5. time sync
6. client id/secret 환경변수
```

주의:

```text
client secret을 로그에 출력하지 않는다.
```

---

# 7. 데이터 파이프라인 장애 대응

운영 기준 provider 우선순위는 다음이다.

```text
1. TossOpenApiProvider
2. pykrx 또는 KRX 보조 provider
3. OPENDART provider
4. 수동 입력 provider
5. MockDataProvider(local/test)
```

Toss OpenAPI가 제공하는 데이터는 Toss를 먼저 확인하고, Toss가 제공하지 않거나 장애가 있는 경우에만 fallback provider를 사용한다.

## 7.1 수집 실패 확인

```bash
python manage.py show_data_provider_status
python manage.py show_recent_ingestion_logs --limit=20
```

명령 이름은 실제 구현에 맞게 조정한다.

## 7.2 Toss API 실패

확인:

```text
1. 인증 실패인지
2. rate limit인지
3. provider 5xx인지
4. network timeout인지
5. 응답 schema 변경인지
6. 계좌 API에서 X-Tossinvest-Account 헤더가 누락되었는지
7. 주문 실행 기능이 비활성화되어야 하는데 호출되었는지
```

대응:

```text
1. token 재발급 시도
2. rate limit이면 스케줄 지연
3. 5xx면 기존 데이터 유지
4. malformed response면 provider DOWN 처리
5. DataIngestionLog에 기록
6. fallback provider로 보강 가능한 데이터인지 확인
7. 실거래 주문 생성/정정/취소 호출은 TOSS_ORDER_EXECUTION_ENABLED=false 상태를 유지하고 차단 여부를 확인
```

장애 중에도 다음 원칙을 지킨다.

```text
1. 기존 정상 데이터를 삭제하지 않는다.
2. partial response로 검증된 데이터를 덮어쓰지 않는다.
3. fallback provider 사용 여부를 ingestion log에 남긴다.
4. 컨설팅 결과에는 data_quality warning을 표시한다.
5. API key/secret/access token/account number는 로그에 출력하지 않는다.
```

## 7.3 데이터 품질 F 급증

가능 원인:

```text
1. provider schema 변경
2. 휴장일 처리 오류
3. 가격 단위 변경
4. corporate action 미반영
5. 수집 중단
```

대응:

```text
1. 최근 수집 로그 확인
2. 대표 종목 raw response 확인
3. 휴장일 여부 확인
4. 정규화 파이프라인 재실행
5. 컨설팅 결과에 데이터 품질 경고 표시
```

---

# 8. Toss OpenAPI smoke 점검 절차

Toss OpenAPI smoke command는 1차 구현 기준으로 운영 설정과 최소 API 연결 가능성을 점검하기 위한 도구다. 기본 점검은 네트워크 호출 없이 실행한다.

## 8.1 네트워크 호출 없는 점검

설정과 provider health_check만 확인한다.

```bash
python manage.py check_toss_provider
```

특성:

```text
1. 네트워크 호출 없음
2. settings와 TossOpenApiProvider.health_check만 확인
3. token 발급 없음
4. quote 조회 없음
5. DB 저장 없음
6. 주문 API 호출 없음
```

token smoke 설정만 확인한다.

```bash
python manage.py toss_token_smoke --no-network
```

특성:

```text
1. 네트워크 호출 없음
2. provider disabled 상태를 안전하게 확인
3. credential missing 상태를 안전하게 확인
4. token endpoint 호출 없음
5. access token 출력 없음
```

quote smoke command 동작만 확인한다.

```bash
python manage.py toss_quote_smoke --symbol=005930 --market=KR --no-network
```

특성:

```text
1. 네트워크 호출 없음
2. token 발급 없음
3. current price endpoint 호출 없음
4. DB 저장 없음
5. DataIngestionLog 기록 없음
6. 주문 API 호출 없음
```

## 8.2 실제 token smoke 수동 실행

운영자가 실제 환경변수를 설정한 뒤에만 다음 명령을 수동 실행한다.

```bash
python manage.py toss_token_smoke
```

주의:

```text
1. 실제 token endpoint 호출이 발생한다.
2. Token endpoint는 POST /oauth2/token 이다.
3. 요청 형식은 application/x-www-form-urlencoded 이다.
4. grant_type은 client_credentials 이다.
5. access token 원문은 stdout, stderr, log에 출력하지 않는다.
6. 실패 reason은 authentication failed, rate limit exceeded 같은 안전한 문구로 요약한다.
7. 운영 로그에 client_secret, access token, account id 원문이 없어야 한다.
```

## 8.3 실제 quote smoke 수동 실행

운영자가 실제 환경변수를 설정한 뒤에만 다음 명령을 수동 실행한다.

```bash
python manage.py toss_quote_smoke --symbol=005930 --market=KR
```

주의:

```text
1. 실제 token endpoint 호출이 발생할 수 있다.
2. 실제 current price endpoint GET /api/v1/prices 호출이 발생할 수 있다.
3. 현재가 조회 query parameter는 symbols 이다.
4. Market Data API이므로 X-Tossinvest-Account header는 사용하지 않는다.
5. DB 저장 없음.
6. DataIngestionLog 기록 없음.
7. 주문 API 호출 없음.
8. 실패 시 safe reason만 출력한다.
```

## 8.4 운영 점검 순서

네트워크 호출 없는 권장 점검 순서:

```bash
python manage.py check
python manage.py check_toss_provider
python manage.py toss_token_smoke --no-network
python manage.py toss_quote_smoke --symbol=005930 --market=KR --no-network
python manage.py test
```

실제 연동 확인 순서:

```bash
python manage.py check_toss_provider
python manage.py toss_token_smoke
python manage.py toss_quote_smoke --symbol=005930 --market=KR
```

실제 연동 확인은 운영자가 환경변수와 네트워크 호출 가능성을 이해한 상태에서만 수행한다.

## 8.5 Toss smoke 장애 대응

safe reason 기준:

```text
provider disabled
credentials missing
no-network
authentication failed
rate limit exceeded
token endpoint request failed
quote request failed
validation failed
```

대응:

```text
1. provider disabled: TOSS_INVEST_PROVIDER_ENABLED 값을 확인한다.
2. credentials missing: TOSS_INVEST_CLIENT_ID, TOSS_INVEST_CLIENT_SECRET 설정을 확인한다.
3. authentication failed: Toss API key/secret을 재확인하고 폐기/재발급 여부를 확인한다.
4. rate limit exceeded: 호출 간격을 조정하고 smoke 반복 실행을 중지한다.
5. quote request failed: symbol 형식을 확인하고 token smoke를 먼저 확인한다.
6. validation failed: symbol에 공백, comma, slash, URL, query string이 포함되었는지 확인한다.
7. 주문 관련 장애: 현재 주문 API는 구현하지 않았으므로 주문 실행 경로가 없어야 한다.
```

TOSS_ORDER_EXECUTION_ENABLED는 기본값 `false`를 유지한다. 주문 생성/정정/취소 API는 1차 smoke 구현 범위가 아니며 운영에서 호출되어서는 안 된다.

---

# 9. 보안 사고 대응

## 9.1 API key/secret 노출

즉시 조치:

```text
1. 노출 key 폐기
2. 새 key 발급
3. 운영 .env 갱신
4. 서비스 재시작
5. 로그와 Git history 확인
6. 의심 호출 확인
7. 사고 기록 작성
```

검색 예:

```bash
grep -R "CLIENT_SECRET" .
grep -R "TOSS" .
git grep -n "SECRET"
git log --all --full-history -- <suspected_file>
```

## 9.2 비정상 로그인/접근

확인:

```text
1. 로그인 실패 반복
2. staff 권한 변경
3. admin 접근 로그
4. 대량 API 호출
5. 사용자 데이터 대량 조회
```

대응:

```text
1. 의심 계정 비활성화
2. Peach 권한 확인
3. 세션 무효화
4. IP 차단 검토
5. 감사 로그 보존
```

---

# 10. 정기 점검

## 10.1 매일

```text
[ ] healthz/readyz 정상
[ ] 최근 24시간 500 오류 확인
[ ] 데이터 수집 성공 여부
[ ] provider status 확인
[ ] Toss smoke command no-network 점검 필요 여부 확인
[ ] DB backup 성공 여부
[ ] disk 사용량 확인
```

## 10.2 매주

```text
[ ] 데이터 품질 리포트 추세 확인
[ ] slow query/API 확인
[ ] 보안 업데이트 확인
[ ] 백업 restore 테스트 계획 확인
[ ] staff 계정 목록 확인
[ ] Toss smoke 로그에 secret/token/account 원문이 없는지 표본 확인
```

## 10.3 매월

```text
[ ] secret rotation 검토
[ ] dependency update 검토
[ ] 백테스트/확률 보정 리포트 검토
[ ] 운영 비용/리소스 확인
[ ] 장애 기록 회고
```

---

# 11. 운영 기록 템플릿

```text
# 장애/작업 기록

일시:
담당자:
유형: 장애 / 배포 / 롤백 / 보안 / 데이터 수집
영향 범위:
사용자 영향:

증상:

확인한 내용:
1.
2.
3.

원인:

조치:
1.
2.
3.

결과:

재발 방지:

추가 작업:
```

---

# 12. 결론

운영 Runbook의 목적은 장애를 완전히 없애는 것이 아니라, 장애가 발생했을 때 빠르게 확인하고 안전하게 복구하는 것이다.

`theStock` 운영에서 가장 중요한 것은 다음이다.

```text
1. 사용자 금융정보 보호
2. 인증/권한 안정성
3. 데이터 파이프라인 안정성
4. 컨설팅 결과 신뢰도
5. API key/secret 보호
6. 장애 시 안전한 rollback
```

이 문서는 운영 중 반복적으로 갱신되어야 한다.
