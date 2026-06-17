from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from stocks.models import Stock

from .models import TechnicalIndicator
from .services.indicator_service import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_moving_average,
    calculate_rsi,
    calculate_volume_ma,
)

User = get_user_model()


class TechnicalIndicatorModelTests(APITestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_indicator_unique_by_stock_and_date(self):
        TechnicalIndicator.objects.create(stock=self.stock, date="2026-04-28", ma5=Decimal("69000.00"))

        with self.assertRaises(IntegrityError):
            TechnicalIndicator.objects.create(stock=self.stock, date="2026-04-28")

    def test_indicator_fields_allow_nulls(self):
        indicator = TechnicalIndicator.objects.create(stock=self.stock, date="2026-04-29")

        self.assertIsNone(indicator.ma5)
        self.assertIsNone(indicator.rsi14)


class TechnicalIndicatorApiSmokeTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice", password="pw12345")
        self.client.force_authenticate(self.user)
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        TechnicalIndicator.objects.create(stock=self.stock, date="2026-04-28")

    def test_indicator_smoke_endpoint(self):
        response = self.client.get("/api/indicators/technical-indicators/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class IndicatorServiceTests(APITestCase):
    def test_moving_average_returns_expected_value(self):
        moving_average = calculate_moving_average([1, 2, 3, 4, 5], 5)

        self.assertEqual(moving_average, Decimal("3.00"))

    def test_moving_average_returns_none_when_data_is_insufficient(self):
        self.assertIsNone(calculate_moving_average([1, 2, 3], 5))

    def test_rsi_returns_100_when_prices_only_rise(self):
        rsi = calculate_rsi(list(range(1, 17)), 14)

        self.assertEqual(rsi, Decimal("100.0000"))

    def test_rsi_returns_50_when_prices_do_not_change(self):
        rsi = calculate_rsi([100] * 15, 14)

        self.assertEqual(rsi, Decimal("50.0000"))

    def test_macd_returns_none_structure_when_data_is_insufficient(self):
        macd = calculate_macd(list(range(1, 30)))

        self.assertEqual(macd, {"macd": None, "signal": None, "histogram": None})

    def test_atr_is_calculated_from_price_rows(self):
        rows = [
            SimpleNamespace(high_price=Decimal(str(12 + index)), low_price=Decimal(str(8 + index)), close_price=Decimal(str(10 + index)))
            for index in range(15)
        ]

        atr = calculate_atr(rows, 14)

        self.assertEqual(atr, Decimal("4.0000"))

    def test_volume_ma20_is_calculated(self):
        volume_ma = calculate_volume_ma([100] * 20, 20)

        self.assertEqual(volume_ma, 100)

    def test_bollinger_bands_are_calculated(self):
        bands = calculate_bollinger_bands([10] * 20, 20)

        self.assertEqual(bands["upper"], Decimal("10.00"))
        self.assertEqual(bands["middle"], Decimal("10.00"))
        self.assertEqual(bands["lower"], Decimal("10.00"))
