from rest_framework import serializers


class PortfolioSummarySerializer(serializers.Serializer):
    as_of = serializers.CharField(allow_null=True)
    holding_count = serializers.IntegerField()
    active_holding_count = serializers.IntegerField()
    priced_holding_count = serializers.IntegerField()
    missing_price_count = serializers.IntegerField()
    totals = serializers.DictField()
    holdings = serializers.ListField(child=serializers.DictField())
    warnings = serializers.ListField(child=serializers.CharField())
