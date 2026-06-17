from rest_framework import serializers

from .models import DailyPrice, InvestorFlow, MarketIndex


class DailyPriceSerializer(serializers.ModelSerializer):
    stock_code = serializers.CharField(source="stock.code", read_only=True)
    stock_name = serializers.CharField(source="stock.name", read_only=True)

    class Meta:
        model = DailyPrice
        fields = (
            "id",
            "stock",
            "stock_code",
            "stock_name",
            "date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "change_rate",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "stock_code", "stock_name", "created_at", "updated_at")

    def validate(self, attrs):
        open_price = attrs.get("open_price", getattr(self.instance, "open_price", None))
        high_price = attrs.get("high_price", getattr(self.instance, "high_price", None))
        low_price = attrs.get("low_price", getattr(self.instance, "low_price", None))
        close_price = attrs.get("close_price", getattr(self.instance, "close_price", None))
        volume = attrs.get("volume", getattr(self.instance, "volume", None))

        if None not in (high_price, low_price) and high_price < low_price:
            raise serializers.ValidationError("high_price must be greater than or equal to low_price.")
        if None not in (high_price, open_price) and high_price < open_price:
            raise serializers.ValidationError("high_price must be greater than or equal to open_price.")
        if None not in (high_price, close_price) and high_price < close_price:
            raise serializers.ValidationError("high_price must be greater than or equal to close_price.")
        if None not in (low_price, open_price) and low_price > open_price:
            raise serializers.ValidationError("low_price must be less than or equal to open_price.")
        if None not in (low_price, close_price) and low_price > close_price:
            raise serializers.ValidationError("low_price must be less than or equal to close_price.")
        if volume is not None and volume < 0:
            raise serializers.ValidationError("volume must be greater than or equal to zero.")
        return attrs


class InvestorFlowSerializer(serializers.ModelSerializer):
    stock_code = serializers.CharField(source="stock.code", read_only=True)
    stock_name = serializers.CharField(source="stock.name", read_only=True)

    class Meta:
        model = InvestorFlow
        fields = (
            "id",
            "stock",
            "stock_code",
            "stock_name",
            "date",
            "foreign_net_buy",
            "institution_net_buy",
            "individual_net_buy",
            "program_net_buy",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "stock_code", "stock_name", "created_at", "updated_at")


class MarketIndexSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketIndex
        fields = (
            "id",
            "code",
            "name",
            "date",
            "close_value",
            "change_rate",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

