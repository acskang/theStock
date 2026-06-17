from rest_framework import serializers

from .models import UserHolding


class UserHoldingSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    stock_code = serializers.CharField(source="stock.code", read_only=True)
    stock_name = serializers.CharField(source="stock.name", read_only=True)
    stock_market = serializers.CharField(source="stock.market", read_only=True)
    total_invested_amount = serializers.SerializerMethodField()

    class Meta:
        model = UserHolding
        fields = (
            "id",
            "user",
            "stock",
            "stock_code",
            "stock_name",
            "stock_market",
            "average_price",
            "quantity",
            "is_active",
            "total_invested_amount",
            "max_additional_budget",
            "risk_level",
            "memo",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "user",
            "stock_code",
            "stock_name",
            "stock_market",
            "is_active",
            "total_invested_amount",
            "created_at",
            "updated_at",
        )

    def get_total_invested_amount(self, obj):
        return f"{obj.total_invested_amount:.2f}"


class AdditionalBuySimulationInputSerializer(serializers.Serializer):
    additional_budget = serializers.DecimalField(
        max_digits=16,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    additional_quantity = serializers.DecimalField(
        max_digits=16,
        decimal_places=6,
        required=False,
        allow_null=True,
    )
    buy_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    target_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    def validate(self, attrs):
        additional_budget = attrs.get("additional_budget")
        additional_quantity = attrs.get("additional_quantity")
        buy_price = attrs.get("buy_price")
        target_price = attrs.get("target_price")

        if additional_budget is not None and additional_quantity is not None:
            raise serializers.ValidationError(
                {
                    "error": "conflicting_input",
                    "message": "additional_budget and additional_quantity cannot be used together.",
                }
            )
        if additional_quantity is not None:
            raise serializers.ValidationError(
                {
                    "error": "additional_quantity_not_supported",
                    "message": "additional_quantity is not supported in this MVP.",
                }
            )
        if additional_budget is None:
            raise serializers.ValidationError(
                {
                    "error": "additional_budget_required",
                    "message": "additional_budget is required.",
                }
            )
        if additional_budget <= 0:
            raise serializers.ValidationError(
                {
                    "error": "invalid_additional_budget",
                    "message": "additional_budget must be greater than zero.",
                }
            )
        if buy_price is not None and buy_price <= 0:
            raise serializers.ValidationError(
                {
                    "error": "invalid_buy_price",
                    "message": "buy_price must be greater than zero.",
                }
            )
        if target_price is not None and target_price <= 0:
            raise serializers.ValidationError(
                {
                    "error": "invalid_target_price",
                    "message": "target_price must be greater than zero.",
                }
            )
        return attrs
