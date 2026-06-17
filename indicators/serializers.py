from rest_framework import serializers

from .models import TechnicalIndicator


class TechnicalIndicatorSerializer(serializers.ModelSerializer):
    stock_code = serializers.CharField(source="stock.code", read_only=True)
    stock_name = serializers.CharField(source="stock.name", read_only=True)

    class Meta:
        model = TechnicalIndicator
        fields = (
            "id",
            "stock",
            "stock_code",
            "stock_name",
            "date",
            "ma5",
            "ma20",
            "ma60",
            "ma120",
            "rsi14",
            "macd",
            "macd_signal",
            "macd_histogram",
            "atr14",
            "volume_ma20",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "stock_code", "stock_name", "created_at", "updated_at")

