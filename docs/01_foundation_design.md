# 01_foundation_design.md

# 물타기 타이밍 판단 시스템 1단계 설계서: Django Foundation

## 문서 목적

이 문서는 `물타기 타이밍 판단 시스템`의 1단계 구현 범위를 정의한다.

1단계의 목적은 계산 엔진이나 복잡한 평가 API를 구현하는 것이 아니라, 이후 단계에서 안정적으로 확장할 수 있는 Django 서비스의 기본 골격을 만드는 것이다.

이 문서는 다음 상위 문서를 전제로 한다.

```text
00_overview_and_data.md
```

`00_overview_and_data.md`는 시스템의 목적, 물타기의 정의, 필요한 데이터, 판단 철학, 데이터 우선순위를 정의한다.  
본 문서인 `01_foundation_design.md`는 그 정의를 실제 Django 프로젝트 구조, 앱 구조, 모델, serializer, admin, 기본 URL 구조로 구체화한다.

---

# 1. 1단계의 목표

## 1.1 핵심 목표

1단계의 핵심 목표는 다음과 같다.

```text
Django REST Framework 기반 서비스의 기초 구조를 만든다.
데이터 모델을 안정적으로 정의한다.
관리자 화면에서 핵심 데이터를 관리할 수 있게 한다.
API 구현을 위한 serializer와 URL 골격을 준비한다.
2단계 점수 계산 엔진이 사용할 수 있는 서비스 레이어 구조를 만든다.
```

1단계 결과물은 “동작하는 완성 서비스”가 아니라 “이후 구현의 기준이 되는 안정적인 기반 코드”다.

---

## 1.2 1단계 포함 범위

1단계에 포함되는 작업은 다음과 같다.

```text
1. Django 프로젝트 구조 확인 또는 생성
2. Django REST Framework 설정
3. 앱 구조 생성
4. 핵심 데이터 모델 구현
5. 모델 관계 정의
6. 모델 제약 조건 정의
7. admin 등록
8. serializer 작성
9. 기본 ViewSet 또는 APIView 골격 작성
10. 기본 URL 라우팅 작성
11. services/ 디렉터리 생성
12. 핵심 서비스 함수 시그니처 작성
13. 최소 smoke test 작성
14. README 또는 단계별 실행 메모 작성
```

---

## 1.3 1단계 제외 범위

1단계에서는 다음 작업을 구현하지 않는다.

```text
1. 실제 이동평균 계산 로직
2. 실제 RSI 계산 로직
3. 실제 MACD 계산 로직
4. 실제 ATR 계산 로직
5. 실제 지지선 탐색 알고리즘
6. 실제 점수 계산 로직
7. 실제 A/B/C/D 등급 산출 로직
8. 외부 주식 API 연동
9. 뉴스/공시 자동 수집
10. 실시간 시세 연동
11. 복잡한 화면 UI
12. 배포 자동화
```

다만 2단계에서 구현할 수 있도록 함수 시그니처와 파일 구조는 미리 만들어 둔다.

---

## 1.4 1단계 완료 기준

1단계는 다음 조건을 만족하면 완료된 것으로 본다.

```text
1. Django 서버가 실행된다.
2. 마이그레이션이 정상 생성되고 적용된다.
3. 관리자 페이지에서 핵심 모델을 조회하고 등록할 수 있다.
4. serializer가 import 오류 없이 동작한다.
5. URL 라우팅이 깨지지 않는다.
6. 기본 API endpoint가 최소한의 응답을 반환한다.
7. 서비스 레이어 파일이 생성되어 있다.
8. 2단계 계산 엔진에서 사용할 모델 필드가 충분히 준비되어 있다.
9. 테스트 명령어가 정상 실행된다.
```

---

# 2. 전체 프로젝트 구조

## 2.1 권장 프로젝트 구조

권장 구조는 다음과 같다.

```text
project_root/
 ├── manage.py
 ├── config/
 │   ├── __init__.py
 │   ├── settings.py
 │   ├── urls.py
 │   ├── asgi.py
 │   └── wsgi.py
 ├── stocks/
 │   ├── __init__.py
 │   ├── admin.py
 │   ├── apps.py
 │   ├── models.py
 │   ├── serializers.py
 │   ├── views.py
 │   ├── urls.py
 │   ├── services/
 │   │   └── __init__.py
 │   └── tests.py
 ├── holdings/
 │   ├── __init__.py
 │   ├── admin.py
 │   ├── apps.py
 │   ├── models.py
 │   ├── serializers.py
 │   ├── views.py
 │   ├── urls.py
 │   ├── services/
 │   │   └── __init__.py
 │   └── tests.py
 ├── marketdata/
 │   ├── __init__.py
 │   ├── admin.py
 │   ├── apps.py
 │   ├── models.py
 │   ├── serializers.py
 │   ├── views.py
 │   ├── urls.py
 │   ├── services/
 │   │   ├── __init__.py
 │   │   ├── price_service.py
 │   │   └── market_service.py
 │   └── tests.py
 ├── indicators/
 │   ├── __init__.py
 │   ├── admin.py
 │   ├── apps.py
 │   ├── models.py
 │   ├── serializers.py
 │   ├── views.py
 │   ├── urls.py
 │   ├── services/
 │   │   ├── __init__.py
 │   │   └── indicator_service.py
 │   └── tests.py
 ├── decisions/
 │   ├── __init__.py
 │   ├── admin.py
 │   ├── apps.py
 │   ├── models.py
 │   ├── serializers.py
 │   ├── views.py
 │   ├── urls.py
 │   ├── services/
 │   │   ├── __init__.py
 │   │   ├── support_service.py
 │   │   ├── volume_service.py
 │   │   ├── investor_flow_service.py
 │   │   ├── risk_event_service.py
 │   │   ├── scoring_service.py
 │   │   └── averaging_decision_service.py
 │   └── tests.py
 ├── docs/
 │   ├── 00_overview_and_data.md
 │   ├── 01_foundation_design.md
 │   └── 01_codex_prompt.md
 ├── requirements.txt
 └── README.md
```

---

## 2.2 구조 단순화 가능성

프로젝트 초기 구현에서는 앱이 많아 보일 수 있다.  
하지만 본 프로젝트는 다음 도메인이 명확히 분리된다.

```text
종목 정보
사용자 보유 정보
시장/가격 데이터
기술적 지표
판단 결과
```

따라서 앱을 분리하는 편이 장기적으로 유지보수에 유리하다.

다만 Codex가 한 번에 너무 많은 앱을 다루면서 품질이 떨어질 위험이 있다면 다음과 같이 단순화할 수 있다.

```text
stocks
holdings
marketdata
decisions
```

이 경우 `TechnicalIndicator` 모델은 `marketdata` 또는 `decisions`에 포함할 수 있다.  
하지만 권장안은 `indicators` 앱을 별도로 두는 것이다.

---

## 2.3 앱별 책임

| 앱 | 책임 |
|---|---|
| stocks | 종목 기본 정보 관리 |
| holdings | 사용자 보유 종목 관리 |
| marketdata | 일봉 가격, 시장 지수, 수급 데이터 관리 |
| indicators | 기술적 지표 저장 및 계산 준비 |
| decisions | 물타기 판단 결과와 평가 실행 구조 관리 |

---

# 3. Django 설정 설계

## 3.1 필수 패키지

1단계에서 필요한 기본 패키지는 다음과 같다.

```text
Django
djangorestframework
```

개발 편의를 위해 다음 패키지를 사용할 수 있다.

```text
django-filter
python-dotenv
pytest
pytest-django
black
ruff
```

단, 1단계에서는 패키지 설치를 최소화해도 된다.

최소 `requirements.txt` 예시는 다음과 같다.

```text
Django>=5.0
djangorestframework>=3.15
django-filter>=24.0
python-dotenv>=1.0
pytest>=8.0
pytest-django>=4.8
```

---

## 3.2 settings.py 설정

`INSTALLED_APPS`에는 다음을 포함한다.

```python
INSTALLED_APPS = [
    # Django default apps
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party apps
    "rest_framework",
    "django_filters",

    # Local apps
    "stocks",
    "holdings",
    "marketdata",
    "indicators",
    "decisions",
]
```

DRF 기본 설정은 다음처럼 둔다.

```python
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.BasicAuthentication",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}
```

개발 초기에는 인증을 완화하고 싶을 수 있지만, 이 시스템은 사용자 보유 종목 데이터를 다루므로 기본값은 `IsAuthenticated`가 적절하다.

---

## 3.3 시간대와 언어

한국 주식 데이터를 기본 대상으로 하므로 다음 설정을 권장한다.

```python
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True
```

---

## 3.4 Decimal 사용 원칙

주가, 평균 단가, 투자 금액, 손절가, 제안 예산 등은 부동소수점 오류를 피하기 위해 `DecimalField`를 사용한다.

다음 값에는 `FloatField`를 사용하지 않는다.

```text
가격
평균 매입가
현재가
투자 금액
제안 예산
손절가
```

단, 점수나 비율은 상황에 따라 `DecimalField` 또는 `FloatField`를 사용할 수 있다.  
일관성을 위해 손익률도 `DecimalField`를 권장한다.

---

# 4. 모델 설계 개요

## 4.1 핵심 모델 목록

1단계에서 구현할 모델은 다음과 같다.

```text
Stock
UserHolding
DailyPrice
MarketIndex
InvestorFlow
TechnicalIndicator
RiskEvent
AveragingDecision
```

각 모델의 역할은 다음과 같다.

| 모델 | 역할 |
|---|---|
| Stock | 종목 기본 정보 |
| UserHolding | 사용자 보유 종목 |
| DailyPrice | 종목별 일봉 가격 데이터 |
| MarketIndex | 시장 지수 데이터 |
| InvestorFlow | 종목별 투자 주체 수급 |
| TechnicalIndicator | 기술적 지표 저장 |
| RiskEvent | 뉴스/공시 기반 위험 이벤트 |
| AveragingDecision | 물타기 판단 결과 이력 |

---

# 5. stocks 앱 설계

## 5.1 Stock 모델 목적

`Stock` 모델은 주식 종목의 기본 정보를 저장한다.

이 모델은 다른 거의 모든 모델에서 참조된다.

```text
UserHolding → Stock
DailyPrice → Stock
InvestorFlow → Stock
TechnicalIndicator → Stock
RiskEvent → Stock
```

---

## 5.2 Stock 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| code | CharField | 종목 코드 |
| name | CharField | 종목명 |
| market | CharField | 시장 구분 |
| sector | CharField | 업종 |
| is_active | BooleanField | 사용 여부 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

## 5.3 Stock 모델 예시

```python
class Stock(models.Model):
    MARKET_KOSPI = "KOSPI"
    MARKET_KOSDAQ = "KOSDAQ"
    MARKET_KONEX = "KONEX"
    MARKET_ETF = "ETF"
    MARKET_ETN = "ETN"

    MARKET_CHOICES = [
        (MARKET_KOSPI, "KOSPI"),
        (MARKET_KOSDAQ, "KOSDAQ"),
        (MARKET_KONEX, "KONEX"),
        (MARKET_ETF, "ETF"),
        (MARKET_ETN, "ETN"),
    ]

    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=100, db_index=True)
    market = models.CharField(max_length=20, choices=MARKET_CHOICES)
    sector = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## 5.4 Stock 제약 조건

`code`는 유일해야 한다.

```python
code = models.CharField(max_length=20, unique=True, db_index=True)
```

종목명은 중복될 수 있으므로 unique를 걸지 않는다.  
ETF, 우선주, 스팩, 리츠 등은 이름이 유사할 수 있다.

---

## 5.5 Stock Meta

```python
class Meta:
    ordering = ["code"]
    verbose_name = "Stock"
    verbose_name_plural = "Stocks"
```

---

## 5.6 Stock __str__

```python
def __str__(self):
    return f"{self.code} {self.name}"
```

---

## 5.7 Stock serializer

기본 serializer는 다음 필드를 포함한다.

```text
id
code
name
market
sector
is_active
created_at
updated_at
```

등록 시에는 `code`, `name`, `market`, `sector`, `is_active`를 받는다.

---

## 5.8 Stock admin

관리자 페이지에서 다음 구성을 권장한다.

```python
list_display = ("code", "name", "market", "sector", "is_active", "updated_at")
list_filter = ("market", "is_active", "sector")
search_fields = ("code", "name", "sector")
ordering = ("code",)
```

---

# 6. holdings 앱 설계

## 6.1 UserHolding 모델 목적

`UserHolding`은 사용자가 어떤 종목을 얼마에, 몇 주 보유하고 있는지를 저장한다.

이 모델은 물타기 판단의 출발점이다.

---

## 6.2 UserHolding 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| user | ForeignKey(User) | 보유 사용자 |
| stock | ForeignKey(Stock) | 보유 종목 |
| average_price | DecimalField | 평균 매입 단가 |
| quantity | PositiveIntegerField | 보유 수량 |
| max_additional_budget | DecimalField | 추가 매수 가능 예산 |
| risk_level | CharField | 사용자 위험 성향 |
| memo | TextField | 사용자 메모 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

## 6.3 UserHolding risk_level

위험 성향은 다음 세 가지를 기본값으로 한다.

| 값 | 의미 |
|---|---|
| conservative | 보수적 |
| normal | 일반 |
| aggressive | 공격적 |

모델에서는 다음 choices를 둔다.

```python
RISK_CONSERVATIVE = "conservative"
RISK_NORMAL = "normal"
RISK_AGGRESSIVE = "aggressive"

RISK_LEVEL_CHOICES = [
    (RISK_CONSERVATIVE, "Conservative"),
    (RISK_NORMAL, "Normal"),
    (RISK_AGGRESSIVE, "Aggressive"),
]
```

기본값은 `normal`로 한다.

---

## 6.4 UserHolding 모델 예시

```python
class UserHolding(models.Model):
    RISK_CONSERVATIVE = "conservative"
    RISK_NORMAL = "normal"
    RISK_AGGRESSIVE = "aggressive"

    RISK_LEVEL_CHOICES = [
        (RISK_CONSERVATIVE, "Conservative"),
        (RISK_NORMAL, "Normal"),
        (RISK_AGGRESSIVE, "Aggressive"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="holdings",
    )
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="holdings",
    )
    average_price = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.PositiveIntegerField()
    max_additional_budget = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    risk_level = models.CharField(
        max_length=20,
        choices=RISK_LEVEL_CHOICES,
        default=RISK_NORMAL,
    )
    memo = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## 6.5 UserHolding 제약 조건

같은 사용자가 같은 종목을 여러 개 등록할 수 있게 할지 결정해야 한다.

1단계 권장안은 같은 사용자가 같은 종목을 하나만 등록하는 것이다.

```python
constraints = [
    models.UniqueConstraint(
        fields=["user", "stock"],
        name="unique_user_stock_holding",
    )
]
```

이 방식은 평균 매입가와 수량을 하나의 대표 보유 상태로 관리한다.

향후 매수 내역별 관리를 하고 싶다면 별도의 `TradeTransaction` 모델을 추가할 수 있다.  
하지만 1단계에서는 복잡도를 줄이기 위해 `UserHolding` 하나로 관리한다.

---

## 6.6 UserHolding 계산 속성

모델 또는 serializer에서 다음 값을 계산할 수 있다.

```text
total_invested_amount = average_price * quantity
```

현재가는 `DailyPrice`의 최신 종가를 기준으로 가져온다.

```text
current_price = latest DailyPrice.close_price
```

손익률은 다음 공식으로 계산한다.

```text
loss_rate = ((current_price - average_price) / average_price) * 100
```

1단계에서는 계산 속성을 serializer method field로 구현하거나, 2단계 이후 서비스에서 계산해도 된다.

---

## 6.7 UserHolding serializer

### 6.7.1 등록 serializer

등록 시 입력 필드는 다음과 같다.

```text
stock
average_price
quantity
max_additional_budget
risk_level
memo
```

`user`는 request.user에서 자동으로 설정한다.

### 6.7.2 조회 serializer

조회 시 반환 필드는 다음과 같다.

```text
id
user
stock
stock_code
stock_name
average_price
quantity
total_invested_amount
max_additional_budget
risk_level
memo
created_at
updated_at
```

`stock_code`, `stock_name`, `total_invested_amount`는 읽기 전용 필드로 제공한다.

---

## 6.8 UserHolding admin

```python
list_display = (
    "id",
    "user",
    "stock",
    "average_price",
    "quantity",
    "max_additional_budget",
    "risk_level",
    "updated_at",
)
list_filter = ("risk_level", "stock__market")
search_fields = ("user__username", "stock__code", "stock__name")
autocomplete_fields = ("user", "stock")
```

---

# 7. marketdata 앱 설계

`marketdata` 앱은 종목별 일봉 가격, 시장 지수, 투자 주체별 수급 데이터를 관리한다.

---

## 7.1 DailyPrice 모델

### 7.1.1 목적

`DailyPrice`는 종목별 일봉 가격 데이터를 저장한다.

이 데이터는 다음 계산의 기반이다.

```text
현재가
손익률
이동평균
RSI
MACD
ATR
지지선
거래량 평균
변동성
```

---

### 7.1.2 DailyPrice 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| stock | ForeignKey(Stock) | 종목 |
| date | DateField | 거래일 |
| open_price | DecimalField | 시가 |
| high_price | DecimalField | 고가 |
| low_price | DecimalField | 저가 |
| close_price | DecimalField | 종가 |
| volume | BigIntegerField | 거래량 |
| change_rate | DecimalField | 등락률 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

### 7.1.3 DailyPrice 모델 예시

```python
class DailyPrice(models.Model):
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="daily_prices",
    )
    date = models.DateField(db_index=True)
    open_price = models.DecimalField(max_digits=14, decimal_places=2)
    high_price = models.DecimalField(max_digits=14, decimal_places=2)
    low_price = models.DecimalField(max_digits=14, decimal_places=2)
    close_price = models.DecimalField(max_digits=14, decimal_places=2)
    volume = models.BigIntegerField(default=0)
    change_rate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### 7.1.4 DailyPrice 제약 조건

종목과 거래일 조합은 유일해야 한다.

```python
constraints = [
    models.UniqueConstraint(
        fields=["stock", "date"],
        name="unique_stock_daily_price",
    )
]
```

조회 성능을 위해 인덱스를 둔다.

```python
indexes = [
    models.Index(fields=["stock", "-date"]),
]
```

---

### 7.1.5 DailyPrice Meta

```python
class Meta:
    ordering = ["-date"]
```

---

### 7.1.6 DailyPrice 데이터 검증

다음 조건을 만족해야 한다.

```text
high_price >= low_price
high_price >= open_price
high_price >= close_price
low_price <= open_price
low_price <= close_price
volume >= 0
```

1단계에서는 모델 clean 메서드 또는 serializer validate에서 구현할 수 있다.  
복잡한 검증은 2단계 또는 데이터 수집 단계에서 보강한다.

---

## 7.2 InvestorFlow 모델

### 7.2.1 목적

`InvestorFlow`는 투자 주체별 수급 데이터를 저장한다.

물타기 판단에서는 외국인과 기관의 순매수 여부가 중요한 보조 신호다.

---

### 7.2.2 InvestorFlow 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| stock | ForeignKey(Stock) | 종목 |
| date | DateField | 거래일 |
| foreign_net_buy | BigIntegerField | 외국인 순매수 |
| institution_net_buy | BigIntegerField | 기관 순매수 |
| individual_net_buy | BigIntegerField | 개인 순매수 |
| program_net_buy | BigIntegerField | 프로그램 순매수 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

### 7.2.3 InvestorFlow 모델 예시

```python
class InvestorFlow(models.Model):
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="investor_flows",
    )
    date = models.DateField(db_index=True)

    foreign_net_buy = models.BigIntegerField(default=0)
    institution_net_buy = models.BigIntegerField(default=0)
    individual_net_buy = models.BigIntegerField(default=0)
    program_net_buy = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### 7.2.4 InvestorFlow 제약 조건

```python
constraints = [
    models.UniqueConstraint(
        fields=["stock", "date"],
        name="unique_stock_investor_flow",
    )
]
```

---

## 7.3 MarketIndex 모델

### 7.3.1 목적

`MarketIndex`는 시장 지수 데이터를 저장한다.

예시는 다음과 같다.

```text
KOSPI
KOSDAQ
S&P500
NASDAQ
USD/KRW
```

엄밀히 말하면 환율은 지수가 아니지만, 시장 환경 데이터로 같이 관리할 수 있다.

---

### 7.3.2 MarketIndex 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| code | CharField | 지수 코드 |
| name | CharField | 지수명 |
| date | DateField | 기준일 |
| close_value | DecimalField | 종가 또는 기준값 |
| change_rate | DecimalField | 등락률 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

### 7.3.3 MarketIndex 모델 예시

```python
class MarketIndex(models.Model):
    code = models.CharField(max_length=30, db_index=True)
    name = models.CharField(max_length=100)
    date = models.DateField(db_index=True)
    close_value = models.DecimalField(max_digits=16, decimal_places=4)
    change_rate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### 7.3.4 MarketIndex 제약 조건

```python
constraints = [
    models.UniqueConstraint(
        fields=["code", "date"],
        name="unique_market_index_date",
    )
]
```

---

## 7.4 marketdata serializer

1단계에서 다음 serializer를 만든다.

```text
DailyPriceSerializer
InvestorFlowSerializer
MarketIndexSerializer
```

각 serializer는 기본 CRUD에 필요한 필드를 제공한다.

---

## 7.5 marketdata admin

### DailyPrice admin

```python
list_display = ("stock", "date", "open_price", "high_price", "low_price", "close_price", "volume")
list_filter = ("stock__market", "date")
search_fields = ("stock__code", "stock__name")
autocomplete_fields = ("stock",)
date_hierarchy = "date"
```

### InvestorFlow admin

```python
list_display = ("stock", "date", "foreign_net_buy", "institution_net_buy", "individual_net_buy")
list_filter = ("date", "stock__market")
search_fields = ("stock__code", "stock__name")
autocomplete_fields = ("stock",)
date_hierarchy = "date"
```

### MarketIndex admin

```python
list_display = ("code", "name", "date", "close_value", "change_rate")
list_filter = ("code", "date")
search_fields = ("code", "name")
date_hierarchy = "date"
```

---

# 8. indicators 앱 설계

## 8.1 TechnicalIndicator 모델 목적

`TechnicalIndicator`는 종목별 기술적 지표 값을 저장한다.

2단계에서 계산 엔진이 완성되면 가격 데이터를 기반으로 이 모델에 값을 저장하거나, API 호출 시 계산 결과를 반환할 수 있다.

1단계에서는 저장 구조만 만든다.

---

## 8.2 TechnicalIndicator 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| stock | ForeignKey(Stock) | 종목 |
| date | DateField | 기준일 |
| ma5 | DecimalField | 5일 이동평균 |
| ma20 | DecimalField | 20일 이동평균 |
| ma60 | DecimalField | 60일 이동평균 |
| ma120 | DecimalField | 120일 이동평균 |
| rsi14 | DecimalField | 14일 RSI |
| macd | DecimalField | MACD |
| macd_signal | DecimalField | MACD signal |
| macd_histogram | DecimalField | MACD histogram |
| atr14 | DecimalField | 14일 ATR |
| volume_ma20 | BigIntegerField | 20일 평균 거래량 |
| bb_upper | DecimalField | Bollinger upper band |
| bb_middle | DecimalField | Bollinger middle band |
| bb_lower | DecimalField | Bollinger lower band |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

## 8.3 TechnicalIndicator 모델 예시

```python
class TechnicalIndicator(models.Model):
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="technical_indicators",
    )
    date = models.DateField(db_index=True)

    ma5 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ma20 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ma60 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ma120 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    rsi14 = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)

    macd = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    macd_signal = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    macd_histogram = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)

    atr14 = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    volume_ma20 = models.BigIntegerField(null=True, blank=True)

    bb_upper = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    bb_middle = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    bb_lower = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

## 8.4 TechnicalIndicator 제약 조건

```python
constraints = [
    models.UniqueConstraint(
        fields=["stock", "date"],
        name="unique_stock_technical_indicator",
    )
]
```

인덱스는 다음을 권장한다.

```python
indexes = [
    models.Index(fields=["stock", "-date"]),
]
```

---

## 8.5 TechnicalIndicator serializer

기본 serializer는 모든 지표 필드를 읽기 전용 또는 일반 필드로 제공한다.

1단계에서는 관리자가 직접 입력할 수 있도록 일반 serializer로 구성해도 된다.  
2단계 이후에는 계산 엔진을 통해 생성하는 것을 기본 흐름으로 한다.

---

## 8.6 TechnicalIndicator admin

```python
list_display = (
    "stock",
    "date",
    "ma5",
    "ma20",
    "ma60",
    "rsi14",
    "macd",
    "atr14",
    "volume_ma20",
)
list_filter = ("date", "stock__market")
search_fields = ("stock__code", "stock__name")
autocomplete_fields = ("stock",)
date_hierarchy = "date"
```

---

# 9. decisions 앱 설계

`decisions` 앱은 위험 이벤트와 물타기 판단 결과를 관리한다.

---

## 9.1 RiskEvent 모델

### 9.1.1 목적

`RiskEvent`는 뉴스, 공시, 거래소 공지, 실적 악화 등 종목의 위험 이벤트를 저장한다.

이 모델은 점수 계산보다 우선하는 위험 필터의 근거가 된다.

---

### 9.1.2 RiskEvent 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| stock | ForeignKey(Stock) | 종목 |
| event_type | CharField | 이벤트 유형 |
| title | CharField | 제목 |
| source | CharField | 출처 |
| url | URLField | 원문 URL |
| event_date | DateField | 이벤트 발생일 |
| risk_level | CharField | 위험 수준 |
| description | TextField | 설명 |
| is_active | BooleanField | 현재 유효 여부 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

---

### 9.1.3 RiskEvent risk_level

위험 수준은 다음 네 단계로 정의한다.

| 값 | 의미 | 기본 처리 |
|---|---|---|
| low | 낮음 | 참고 |
| medium | 중간 | 감점 |
| high | 높음 | C 또는 D |
| critical | 치명적 | D |

---

### 9.1.4 RiskEvent event_type

이벤트 유형은 다음 값을 기본으로 한다.

```text
trading_halt
delisting_risk
managed_stock
audit_opinion_rejected
capital_reduction
paid_in_capital_increase
embezzlement
earnings_shock
operating_loss
capital_impairment
disclosure_violation
other
```

---

### 9.1.5 RiskEvent 모델 예시

```python
class RiskEvent(models.Model):
    RISK_LOW = "low"
    RISK_MEDIUM = "medium"
    RISK_HIGH = "high"
    RISK_CRITICAL = "critical"

    RISK_LEVEL_CHOICES = [
        (RISK_LOW, "Low"),
        (RISK_MEDIUM, "Medium"),
        (RISK_HIGH, "High"),
        (RISK_CRITICAL, "Critical"),
    ]

    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="risk_events",
    )
    event_type = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    source = models.CharField(max_length=100, blank=True)
    url = models.URLField(blank=True)
    event_date = models.DateField(db_index=True)
    risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

---

### 9.1.6 RiskEvent 인덱스

```python
indexes = [
    models.Index(fields=["stock", "-event_date"]),
    models.Index(fields=["risk_level", "is_active"]),
]
```

---

## 9.2 AveragingDecision 모델

### 9.2.1 목적

`AveragingDecision`은 특정 사용자의 보유 종목에 대해 실행한 물타기 판단 결과를 저장한다.

이 모델은 이력 관리에 사용된다.

---

### 9.2.2 AveragingDecision 필드 설계

| 필드 | 타입 | 설명 |
|---|---|---|
| holding | ForeignKey(UserHolding) | 평가 대상 보유 종목 |
| score | IntegerField | 최종 점수 |
| grade | CharField | A/B/C/D 등급 |
| decision | CharField | 판단 상태 |
| reason_summary | TextField | 판단 요약 |
| reasons | JSONField | 판단 사유 목록 |
| score_breakdown | JSONField | 항목별 점수 |
| suggested_budget | DecimalField | 제안 예산 |
| stop_loss_price | DecimalField | 손절 기준 가격 |
| disclaimer | TextField | 투자 참고용 고지 |
| created_at | DateTimeField | 생성일 |

---

### 9.2.3 AveragingDecision grade

```python
GRADE_A = "A"
GRADE_B = "B"
GRADE_C = "C"
GRADE_D = "D"

GRADE_CHOICES = [
    (GRADE_A, "A - Reviewable"),
    (GRADE_B, "B - Watch"),
    (GRADE_C, "C - Avoid Averaging Down"),
    (GRADE_D, "D - Review Stop Loss"),
]
```

---

### 9.2.4 AveragingDecision decision

`decision`은 사용자에게 보여줄 짧은 판단 문구다.

허용 예시는 다음과 같다.

```text
추가 매수 가능성 검토 구간
관찰 구간
물타기 금지 구간
손절 또는 비중 축소 기준 점검 구간
```

절대 다음 표현을 쓰면 안 된다.

```text
매수 추천
매도 추천
지금 매수
반드시 반등
수익 가능
```

---

### 9.2.5 AveragingDecision 모델 예시

```python
class AveragingDecision(models.Model):
    GRADE_A = "A"
    GRADE_B = "B"
    GRADE_C = "C"
    GRADE_D = "D"

    GRADE_CHOICES = [
        (GRADE_A, "A - Reviewable"),
        (GRADE_B, "B - Watch"),
        (GRADE_C, "C - Avoid Averaging Down"),
        (GRADE_D, "D - Review Stop Loss"),
    ]

    holding = models.ForeignKey(
        "holdings.UserHolding",
        on_delete=models.CASCADE,
        related_name="decisions",
    )
    score = models.PositiveSmallIntegerField()
    grade = models.CharField(max_length=1, choices=GRADE_CHOICES)
    decision = models.CharField(max_length=100)
    reason_summary = models.TextField()
    reasons = models.JSONField(default=list, blank=True)
    score_breakdown = models.JSONField(default=dict, blank=True)
    suggested_budget = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    stop_loss_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    disclaimer = models.TextField(default="본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다.")

    created_at = models.DateTimeField(auto_now_add=True)
```

---

### 9.2.6 AveragingDecision 인덱스

```python
indexes = [
    models.Index(fields=["holding", "-created_at"]),
    models.Index(fields=["grade", "-created_at"]),
]
```

---

## 9.3 decisions serializer

1단계에서 다음 serializer를 만든다.

```text
RiskEventSerializer
AveragingDecisionSerializer
AveragingDecisionListSerializer
```

### 9.3.1 AveragingDecisionSerializer 반환 필드

```text
id
holding
score
grade
decision
reason_summary
reasons
score_breakdown
suggested_budget
stop_loss_price
disclaimer
created_at
```

---

## 9.4 decisions admin

### RiskEvent admin

```python
list_display = ("stock", "event_type", "risk_level", "title", "event_date", "is_active")
list_filter = ("risk_level", "event_type", "is_active", "event_date")
search_fields = ("stock__code", "stock__name", "title", "description")
autocomplete_fields = ("stock",)
date_hierarchy = "event_date"
```

### AveragingDecision admin

```python
list_display = ("holding", "score", "grade", "decision", "suggested_budget", "stop_loss_price", "created_at")
list_filter = ("grade", "created_at")
search_fields = ("holding__user__username", "holding__stock__code", "holding__stock__name", "reason_summary")
autocomplete_fields = ("holding",)
date_hierarchy = "created_at"
```

---

# 10. Serializer 상세 설계

## 10.1 공통 원칙

Serializer는 다음 원칙을 따른다.

```text
1. 등록용과 조회용을 필요하면 분리한다.
2. 외래키 객체는 ID로 입력받고, 조회 시에는 읽기 전용 상세 정보를 제공한다.
3. Decimal 값은 문자열로 반환될 수 있음을 고려한다.
4. 사용자 필드는 request.user를 기준으로 자동 설정한다.
5. 자기 데이터만 접근 가능하도록 view에서 queryset을 제한한다.
```

---

## 10.2 StockSerializer

반환 필드:

```text
id
code
name
market
sector
is_active
created_at
updated_at
```

---

## 10.3 UserHoldingSerializer

입력 필드:

```text
stock
average_price
quantity
max_additional_budget
risk_level
memo
```

조회 필드:

```text
id
stock
stock_code
stock_name
stock_market
average_price
quantity
total_invested_amount
max_additional_budget
risk_level
memo
created_at
updated_at
```

`total_invested_amount`는 serializer method field로 구현할 수 있다.

---

## 10.4 DailyPriceSerializer

반환 필드:

```text
id
stock
stock_code
stock_name
date
open_price
high_price
low_price
close_price
volume
change_rate
created_at
updated_at
```

---

## 10.5 InvestorFlowSerializer

반환 필드:

```text
id
stock
stock_code
stock_name
date
foreign_net_buy
institution_net_buy
individual_net_buy
program_net_buy
created_at
updated_at
```

---

## 10.6 MarketIndexSerializer

반환 필드:

```text
id
code
name
date
close_value
change_rate
created_at
updated_at
```

---

## 10.7 TechnicalIndicatorSerializer

반환 필드:

```text
id
stock
stock_code
stock_name
date
ma5
ma20
ma60
ma120
rsi14
macd
macd_signal
macd_histogram
atr14
volume_ma20
bb_upper
bb_middle
bb_lower
created_at
updated_at
```

---

## 10.8 RiskEventSerializer

반환 필드:

```text
id
stock
stock_code
stock_name
event_type
title
source
url
event_date
risk_level
description
is_active
created_at
updated_at
```

---

## 10.9 AveragingDecisionSerializer

반환 필드:

```text
id
holding
stock_code
stock_name
score
grade
decision
reason_summary
reasons
score_breakdown
suggested_budget
stop_loss_price
disclaimer
created_at
```

---

# 11. View와 URL 설계

## 11.1 1단계 View 원칙

1단계에서는 모든 기능을 완성하지 않는다.

다만 다음 기본 API 골격은 만든다.

```text
stocks CRUD
holdings CRUD
daily prices CRUD
investor flows CRUD
market indices CRUD
technical indicators CRUD
risk events CRUD
decisions list/retrieve
evaluate endpoint placeholder
```

`evaluate endpoint`는 3단계에서 완성한다.  
1단계에서는 명확한 placeholder 응답을 반환한다.

---

## 11.2 권한 원칙

기본 권한은 다음과 같다.

```text
IsAuthenticated
```

`UserHolding`과 `AveragingDecision`은 반드시 자기 데이터만 접근 가능해야 한다.

예:

```python
def get_queryset(self):
    return UserHolding.objects.filter(user=self.request.user)
```

관리자용 데이터인 `Stock`, `DailyPrice`, `MarketIndex`, `TechnicalIndicator`, `RiskEvent`는 초기에는 인증 사용자 조회를 허용할 수 있다.

추후 권한 정책은 다음처럼 나눌 수 있다.

```text
일반 사용자: 조회만 가능
관리자: 생성/수정/삭제 가능
```

1단계에서는 단순화를 위해 ViewSet을 만들되 권한 강화는 3단계에서 보강한다.

---

## 11.3 URL 구조

권장 API URL은 다음과 같다.

```text
/api/stocks/
/api/holdings/
/api/marketdata/daily-prices/
/api/marketdata/investor-flows/
/api/marketdata/market-indices/
/api/indicators/technical-indicators/
/api/decisions/risk-events/
/api/decisions/averaging-decisions/
/api/holdings/{id}/evaluate/
/api/holdings/{id}/decisions/
```

---

## 11.4 config/urls.py

프로젝트 URL은 다음 앱 URL을 include한다.

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/stocks/", include("stocks.urls")),
    path("api/holdings/", include("holdings.urls")),
    path("api/marketdata/", include("marketdata.urls")),
    path("api/indicators/", include("indicators.urls")),
    path("api/decisions/", include("decisions.urls")),
]
```

---

## 11.5 holdings evaluate placeholder

1단계에서는 다음 endpoint를 placeholder로 만든다.

```http
POST /api/holdings/{id}/evaluate/
```

응답 예시:

```json
{
  "detail": "Evaluation engine is not implemented in step 1. This endpoint will be completed in step 3.",
  "next_step": "Implement scoring engine services in step 2."
}
```

이 placeholder는 3단계에서 실제 평가 실행 API로 교체된다.

---

# 12. 서비스 레이어 골격 설계

## 12.1 서비스 레이어 목적

서비스 레이어는 비즈니스 로직을 view에서 분리하기 위한 구조다.

1단계에서는 실제 계산 로직을 구현하지 않고, 2단계에서 구현할 함수의 파일과 시그니처만 준비한다.

---

## 12.2 marketdata/services/price_service.py

예상 함수:

```python
def get_latest_price(stock):
    """Return the latest DailyPrice for the given stock."""
    raise NotImplementedError


def get_recent_prices(stock, limit=120):
    """Return recent DailyPrice queryset/list ordered by date ascending or descending."""
    raise NotImplementedError
```

1단계에서는 `raise NotImplementedError` 대신 간단한 queryset을 반환해도 된다.

---

## 12.3 marketdata/services/market_service.py

예상 함수:

```python
def get_latest_market_index(code):
    """Return the latest MarketIndex by code."""
    raise NotImplementedError


def get_market_context(stock):
    """Return market context for the stock's market."""
    raise NotImplementedError
```

---

## 12.4 indicators/services/indicator_service.py

예상 함수:

```python
def calculate_moving_average(prices, window):
    """Calculate simple moving average."""
    raise NotImplementedError


def calculate_rsi(prices, period=14):
    """Calculate RSI."""
    raise NotImplementedError


def calculate_macd(prices):
    """Calculate MACD values."""
    raise NotImplementedError


def calculate_atr(prices, period=14):
    """Calculate ATR."""
    raise NotImplementedError
```

1단계에서는 함수 시그니처만 둔다.  
2단계에서 실제 구현한다.

---

## 12.5 decisions/services/risk_event_service.py

예상 함수:

```python
def get_active_risk_events(stock):
    """Return active risk events for a stock."""
    raise NotImplementedError


def has_critical_risk(stock):
    """Return whether the stock has critical risk events."""
    raise NotImplementedError
```

---

## 12.6 decisions/services/scoring_service.py

예상 함수:

```python
def calculate_total_score(*, trend_score, support_score, volume_score, flow_score, market_score, risk_score):
    """Calculate final score."""
    raise NotImplementedError


def convert_score_to_grade(score):
    """Convert score to A/B/C/D grade."""
    raise NotImplementedError
```

---

## 12.7 decisions/services/averaging_decision_service.py

예상 함수:

```python
def evaluate_averaging_timing(holding):
    """Evaluate averaging down timing for a holding."""
    raise NotImplementedError


def create_decision_from_result(holding, result):
    """Persist AveragingDecision from evaluation result."""
    raise NotImplementedError
```

---

# 13. Admin 설계 통합 기준

관리자 페이지는 초기 데이터 입력과 확인에 중요하다.

1단계 admin 구현 시 다음 공통 원칙을 따른다.

```text
1. list_display를 충분히 제공한다.
2. search_fields를 제공한다.
3. 날짜가 있는 모델은 date_hierarchy를 제공한다.
4. FK가 있는 모델은 autocomplete_fields를 사용한다.
5. list_filter를 적극 사용한다.
```

관리자에서 최소한 다음 작업을 할 수 있어야 한다.

```text
종목 등록
보유 종목 등록
일봉 가격 등록
수급 데이터 등록
시장 지수 등록
기술 지표 확인
위험 이벤트 등록
판단 결과 확인
```

---

# 14. 테스트 설계

## 14.1 1단계 테스트 목적

1단계 테스트는 비즈니스 로직 검증이 아니라 foundation 검증이 목적이다.

검증 대상은 다음과 같다.

```text
모델 생성 가능 여부
unique constraint 동작 여부
serializer validation 동작 여부
URL reverse 가능 여부
기본 API 접근 가능 여부
자기 보유 종목 queryset 제한 여부
```

---

## 14.2 필수 테스트 케이스

1단계에서 최소한 다음 테스트를 작성한다.

### Stock 테스트

```text
종목 생성 가능
종목 코드 중복 생성 불가
__str__ 반환 확인
```

### UserHolding 테스트

```text
사용자 보유 종목 생성 가능
같은 사용자가 같은 종목 중복 등록 불가
다른 사용자는 같은 종목 등록 가능
total_invested_amount 계산 확인
```

### DailyPrice 테스트

```text
종목+날짜 중복 저장 불가
최신 가격 조회 가능
```

### InvestorFlow 테스트

```text
종목+날짜 중복 저장 불가
순매수 값 음수 허용
```

### TechnicalIndicator 테스트

```text
종목+날짜 중복 저장 불가
지표 값 null 허용
```

### RiskEvent 테스트

```text
critical risk event 생성 가능
is_active 필드 동작 확인
```

### AveragingDecision 테스트

```text
판단 결과 생성 가능
disclaimer 기본값 포함
grade choices 동작 확인
```

---

## 14.3 API smoke test

다음 endpoint가 URL 오류 없이 동작하는지 확인한다.

```text
GET /api/stocks/
GET /api/holdings/
GET /api/marketdata/daily-prices/
GET /api/marketdata/investor-flows/
GET /api/marketdata/market-indices/
GET /api/indicators/technical-indicators/
GET /api/decisions/risk-events/
GET /api/decisions/averaging-decisions/
```

인증이 필요한 경우 테스트 클라이언트에서 로그인한 사용자로 요청한다.

---

# 15. 데이터 생성 예시

1단계에서는 실제 외부 API 연동 없이 수동 또는 테스트 fixture로 데이터를 넣는다.

## 15.1 Stock 예시

```json
{
  "code": "005930",
  "name": "삼성전자",
  "market": "KOSPI",
  "sector": "반도체",
  "is_active": true
}
```

## 15.2 UserHolding 예시

```json
{
  "stock": 1,
  "average_price": "75000.00",
  "quantity": 10,
  "max_additional_budget": "1000000.00",
  "risk_level": "normal",
  "memo": "테스트 보유 종목"
}
```

## 15.3 DailyPrice 예시

```json
{
  "stock": 1,
  "date": "2026-04-28",
  "open_price": "69000.00",
  "high_price": "70000.00",
  "low_price": "68000.00",
  "close_price": "69500.00",
  "volume": 12345678,
  "change_rate": "1.2000"
}
```

## 15.4 RiskEvent 예시

```json
{
  "stock": 1,
  "event_type": "earnings_shock",
  "title": "분기 영업이익 감소",
  "source": "manual",
  "event_date": "2026-04-28",
  "risk_level": "medium",
  "description": "테스트용 위험 이벤트",
  "is_active": true
}
```

---

# 16. 1단계 산출물

1단계 완료 후 산출물은 다음과 같아야 한다.

```text
1. Django 앱 구조
2. 모델 코드
3. 마이그레이션 파일
4. admin 등록 코드
5. serializer 코드
6. 기본 view 코드
7. URL 라우팅 코드
8. service skeleton 코드
9. foundation 테스트 코드
10. 실행 방법 문서
```

---

# 17. Codex 구현 시 주의사항

Codex가 1단계를 구현할 때 반드시 지켜야 할 사항은 다음과 같다.

```text
1. 2단계 계산 로직을 성급하게 구현하지 않는다.
2. views.py에 비즈니스 로직을 넣지 않는다.
3. 모델 필드명을 설계서와 일관되게 유지한다.
4. DecimalField를 사용해 가격과 금액을 표현한다.
5. UserHolding은 request.user 기준으로 소유권을 처리한다.
6. AveragingDecision에는 disclaimer 기본값을 포함한다.
7. RiskEvent의 critical 위험은 이후 D 등급 판단에 사용될 수 있도록 구조화한다.
8. 각 앱의 admin, serializer, urls를 누락하지 않는다.
9. 마이그레이션 가능해야 한다.
10. import cycle이 생기지 않도록 문자열 FK 또는 lazy reference를 사용한다.
```

---

# 18. 1단계에서 만들면 안 되는 것

1단계에서는 다음을 만들지 않는다.

```text
1. 외부 증권사 API 연동
2. 실시간 시세 WebSocket
3. 뉴스 크롤러
4. 공시 크롤러
5. 완성된 평가 알고리즘
6. 복잡한 프론트엔드 화면
7. 실제 매수/매도 주문 기능
8. 투자 추천 문구
```

이러한 기능은 프로젝트 범위 밖이거나 이후 단계에서 별도로 설계해야 한다.

---

# 19. 다음 단계 연결

1단계가 완료되면 2단계에서는 다음을 구현한다.

```text
02_scoring_engine_design.md
```

2단계 주요 작업은 다음과 같다.

```text
1. 이동평균 계산
2. RSI 계산
3. MACD 계산
4. ATR 계산
5. Volume MA20 계산
6. 지지선 탐색
7. 거래량 점수 계산
8. 수급 점수 계산
9. 시장 점수 계산
10. 위험 이벤트 필터
11. 총점 계산
12. A/B/C/D 등급 변환
```

1단계에서 만든 모델과 service skeleton은 2단계 계산 엔진의 기반이 된다.

---

# 20. 최종 요약

1단계의 목적은 “계산”이 아니라 “기반 구축”이다.

핵심은 다음과 같다.

```text
1. 데이터 모델을 안정적으로 만든다.
2. 관리자에서 데이터를 넣고 확인할 수 있게 한다.
3. serializer와 URL 구조를 준비한다.
4. 서비스 레이어 구조를 만든다.
5. 2단계 계산 엔진이 들어올 자리를 만든다.
```

이 단계가 안정적으로 만들어져야 2단계의 판단 엔진, 3단계의 API 워크플로우, 4단계의 테스트와 품질 보강이 흔들리지 않는다.
