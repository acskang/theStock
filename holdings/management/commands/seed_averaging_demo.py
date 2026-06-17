from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from holdings.models import UserHolding
from marketdata.models import DailyPrice, InvestorFlow, MarketIndex
from stocks.models import Stock


class Command(BaseCommand):
    help = "물타기 판단 API를 바로 테스트할 수 있는 샘플 데이터를 생성합니다."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", default="demo12345!")

    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@example.com"},
        )
        user.set_password(password)
        user.save(update_fields=["password"])

        stock, _ = Stock.objects.update_or_create(
            code="005930",
            defaults={
                "name": "삼성전자",
                "market": Stock.MARKET_KOSPI,
                "sector": "반도체",
                "is_active": True,
            },
        )
        holding, _ = UserHolding.objects.update_or_create(
            user=user,
            stock=stock,
            defaults={
                "average_price": Decimal("71000.00"),
                "quantity": 10,
                "max_additional_budget": Decimal("1000000.00"),
                "risk_level": UserHolding.RISK_NORMAL,
                "memo": "샘플 데이터 보유 종목",
            },
        )

        daily_price_count = self._seed_daily_prices(stock)
        investor_flow_count = self._seed_investor_flows(stock)
        market_index_count = self._seed_market_indices()

        self.stdout.write(
            self.style.SUCCESS(
                "샘플 데이터 생성 완료 "
                f"(user={user.username}, holding_id={holding.id}, daily_prices={daily_price_count}, "
                f"investor_flows={investor_flow_count}, market_indices={market_index_count})"
            )
        )
        self.stdout.write(
            "평가 테스트: "
            f"python manage.py shell -c \"from holdings.models import UserHolding; "
            f"print(UserHolding.objects.get(id={holding.id}).id)\""
        )

    def _seed_daily_prices(self, stock):
        start = date.today() - timedelta(days=119)
        count = 0
        for offset in range(120):
            close_price = Decimal("68000.00") + (Decimal("120.00") * offset)
            volume = 1000000 + (offset * 5000)
            if offset == 119:
                volume = int(volume * 2)
            DailyPrice.objects.update_or_create(
                stock=stock,
                date=start + timedelta(days=offset),
                defaults={
                    "open_price": close_price - Decimal("250.00"),
                    "high_price": close_price + Decimal("500.00"),
                    "low_price": close_price - Decimal("450.00"),
                    "close_price": close_price,
                    "volume": volume,
                    "change_rate": Decimal("0.5000"),
                },
            )
            count += 1
        return count

    def _seed_investor_flows(self, stock):
        start = date.today() - timedelta(days=4)
        count = 0
        for offset in range(5):
            InvestorFlow.objects.update_or_create(
                stock=stock,
                date=start + timedelta(days=offset),
                defaults={
                    "foreign_net_buy": 100000 + (offset * 1000),
                    "institution_net_buy": 120000 + (offset * 1500),
                    "individual_net_buy": -(220000 + (offset * 2500)),
                    "program_net_buy": 10000 + (offset * 500),
                },
            )
            count += 1
        return count

    def _seed_market_indices(self):
        start = date.today() - timedelta(days=59)
        count = 0
        for code, name, base_value, step in (
            ("KOSPI", "KOSPI", Decimal("2400.0000"), Decimal("5.0000")),
            ("NASDAQ", "NASDAQ", Decimal("15000.0000"), Decimal("10.0000")),
            ("USDKRW", "USD/KRW", Decimal("1300.0000"), Decimal("0.2000")),
        ):
            for offset in range(60):
                MarketIndex.objects.update_or_create(
                    code=code,
                    date=start + timedelta(days=offset),
                    defaults={
                        "name": name,
                        "close_value": base_value + (step * offset),
                        "change_rate": Decimal("0.3000"),
                    },
                )
                count += 1
        return count
