from decimal import Decimal

from rest_framework import serializers

from .models import AveragingDecision, AveragingProbabilityRecord, HoldingConsultRecord, RiskEvent


def _stringify_nested_decimals(value):
    if isinstance(value, dict):
        return {key: _stringify_nested_decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_nested_decimals(item) for item in value]
    if hasattr(value, "as_tuple"):
        return str(value)
    return value


class RiskEventSerializer(serializers.ModelSerializer):
    stock_code = serializers.CharField(source="stock.code", read_only=True)
    stock_name = serializers.CharField(source="stock.name", read_only=True)

    class Meta:
        model = RiskEvent
        fields = (
            "id",
            "stock",
            "stock_code",
            "stock_name",
            "event_type",
            "title",
            "source",
            "url",
            "event_date",
            "risk_level",
            "description",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "stock_code", "stock_name", "created_at", "updated_at")


class AveragingDecisionSerializer(serializers.ModelSerializer):
    holding_id = serializers.IntegerField(source="holding.id", read_only=True)
    stock_code = serializers.CharField(source="holding.stock.code", read_only=True)
    stock_name = serializers.CharField(source="holding.stock.name", read_only=True)

    class Meta:
        model = AveragingDecision
        fields = (
            "id",
            "holding_id",
            "stock_code",
            "stock_name",
            "score",
            "grade",
            "decision",
            "reason_summary",
            "reasons",
            "score_breakdown",
            "suggested_budget",
            "stop_loss_price",
            "disclaimer",
            "created_at",
        )
        read_only_fields = ("id", "holding_id", "stock_code", "stock_name", "created_at")


class AveragingDecisionListSerializer(AveragingDecisionSerializer):
    pass


class AveragingProbabilityRecordSerializer(serializers.ModelSerializer):
    holding_id = serializers.IntegerField(source="holding.id", read_only=True)
    stock_code = serializers.CharField(source="holding.stock.code", read_only=True)
    stock_name = serializers.CharField(source="holding.stock.name", read_only=True)

    class Meta:
        model = AveragingProbabilityRecord
        fields = (
            "id",
            "holding_id",
            "stock_code",
            "stock_name",
            "scenario_input",
            "response_payload",
            "success_probability",
            "failure_probability",
            "neutral_probability",
            "confidence",
            "disclaimer",
            "created_at",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["scenario_input"] = _stringify_nested_decimals(instance.scenario_input)
        data["response_payload"] = _stringify_nested_decimals(instance.response_payload)
        return data


class HoldingConsultRecordSerializer(serializers.ModelSerializer):
    holding_id = serializers.IntegerField(source="holding.id", read_only=True)
    stock_code = serializers.CharField(source="holding.stock.code", read_only=True)
    stock_name = serializers.CharField(source="holding.stock.name", read_only=True)

    class Meta:
        model = HoldingConsultRecord
        fields = (
            "id",
            "holding_id",
            "stock_code",
            "stock_name",
            "request_input",
            "response_payload",
            "final_grade",
            "consulting_status",
            "summary",
            "disclaimer",
            "created_at",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["request_input"] = _stringify_nested_decimals(instance.request_input)
        data["response_payload"] = _stringify_nested_decimals(instance.response_payload)
        return data


class AveragingProbabilityScenarioSerializer(serializers.Serializer):
    buy_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    buy_quantity = serializers.IntegerField(min_value=1)
    lookahead_days = serializers.IntegerField(min_value=5, max_value=120, default=20)
    target_type = serializers.ChoiceField(
        choices=["new_average_price", "new_average_price_plus_profit", "manual"],
        default="new_average_price",
    )
    target_profit_rate = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
        min_value=Decimal("0"),
        default=Decimal("0.0000"),
    )
    manual_target_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    stop_loss_type = serializers.ChoiceField(
        choices=["support_or_atr", "manual", "fixed_rate", "atr", "support"],
        default="support_or_atr",
    )
    stop_loss_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    same_day_hit_policy = serializers.ChoiceField(
        choices=["conservative", "optimistic", "neutral"],
        default="conservative",
    )

    def validate(self, attrs):
        if attrs["target_type"] == "manual" and not attrs.get("manual_target_price"):
            raise serializers.ValidationError(
                {"manual_target_price": "manual target_type requires manual_target_price."}
            )
        if attrs["stop_loss_type"] == "manual" and not attrs.get("stop_loss_price"):
            raise serializers.ValidationError(
                {"stop_loss_price": "manual stop_loss_type requires stop_loss_price."}
            )
        return attrs


class AveragingProbabilityResultSerializer(serializers.Serializer):
    success_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True)
    failure_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True)
    neutral_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True)
    success_label = serializers.CharField(read_only=True)
    failure_label = serializers.CharField(read_only=True)
    confidence = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True)
    confidence_label = serializers.CharField(read_only=True)
    target_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    stop_loss_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    new_average_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    lookahead_days = serializers.IntegerField(read_only=True)
    basis = serializers.JSONField(read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    disclaimer = serializers.CharField(read_only=True)

    def to_representation(self, instance):
        return {
            "success_probability": self.fields["success_probability"].to_representation(instance.success_probability),
            "failure_probability": self.fields["failure_probability"].to_representation(instance.failure_probability),
            "neutral_probability": self.fields["neutral_probability"].to_representation(instance.neutral_probability),
            "success_label": instance.success_label,
            "failure_label": instance.failure_label,
            "confidence": self.fields["confidence"].to_representation(instance.confidence),
            "confidence_label": instance.confidence_label,
            "target_price": self.fields["target_price"].to_representation(instance.target_price),
            "stop_loss_price": self.fields["stop_loss_price"].to_representation(instance.stop_loss_price),
            "new_average_price": self.fields["new_average_price"].to_representation(instance.new_average_price),
            "lookahead_days": instance.lookahead_days,
            "basis": _stringify_nested_decimals(instance.basis),
            "warnings": instance.warnings,
            "disclaimer": instance.disclaimer,
        }


class ConsultStockSerializer(serializers.Serializer):
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    market = serializers.CharField(read_only=True, allow_blank=True)
    sector = serializers.CharField(read_only=True, allow_blank=True)


class ConsultHoldingSummarySerializer(serializers.Serializer):
    average_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    quantity = serializers.IntegerField(read_only=True)
    current_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, allow_null=True)
    current_price_date = serializers.DateField(read_only=True, allow_null=True)
    loss_rate = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True, allow_null=True)
    max_additional_budget = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    risk_level = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)
    memo = serializers.CharField(read_only=True, allow_blank=True)


class ConsultRiskGateSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    grade_cap = serializers.CharField(read_only=True, allow_null=True)
    score_multiplier = serializers.FloatField(read_only=True)
    critical_events = serializers.ListField(child=serializers.CharField(), read_only=True)
    blockers = serializers.ListField(child=serializers.CharField(), read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    details = serializers.JSONField(read_only=True)


class ConsultDataQualitySerializer(serializers.Serializer):
    overall_score = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    label = serializers.CharField(read_only=True)
    as_of_date = serializers.DateField(read_only=True, allow_null=True, required=False)
    price_data_days = serializers.IntegerField(read_only=True)
    latest_price_age_days = serializers.IntegerField(read_only=True, allow_null=True)
    investor_flow_days = serializers.IntegerField(read_only=True)
    market_data_available = serializers.BooleanField(read_only=True)
    risk_event_available = serializers.BooleanField(read_only=True)
    financial_data_available = serializers.BooleanField(read_only=True, required=False)
    quality_grade = serializers.CharField(read_only=True, required=False)
    missing_fields = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)
    anomaly_flags = serializers.ListField(child=serializers.CharField(), read_only=True, required=False)
    warning = serializers.CharField(read_only=True, allow_blank=True, required=False)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    details = serializers.JSONField(read_only=True)


class ConsultMarketRegimeSerializer(serializers.Serializer):
    regime = serializers.CharField(read_only=True)
    score_adjustment = serializers.IntegerField(read_only=True)
    score_multiplier = serializers.DecimalField(max_digits=8, decimal_places=4, read_only=True)
    grade_cap = serializers.CharField(read_only=True, allow_null=True)
    reasons = serializers.ListField(child=serializers.CharField(), read_only=True)
    details = serializers.JSONField(read_only=True)


class ConsultStockQualitySerializer(serializers.Serializer):
    quality_grade = serializers.CharField(read_only=True)
    score = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True)
    grade_cap = serializers.CharField(read_only=True, allow_null=True)
    blockers = serializers.ListField(child=serializers.CharField(), read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    details = serializers.JSONField(read_only=True)


class ConsultBaseDecisionSerializer(serializers.Serializer):
    score = serializers.IntegerField(read_only=True)
    grade = serializers.CharField(read_only=True)
    decision = serializers.CharField(read_only=True)
    reason_summary = serializers.CharField(read_only=True)
    reasons = serializers.ListField(child=serializers.CharField(), read_only=True)
    score_breakdown = serializers.JSONField(read_only=True)
    suggested_budget = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    stop_loss_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, allow_null=True)


class ConsultProbabilityHighlightsSerializer(serializers.Serializer):
    headline = serializers.CharField(read_only=True, allow_null=True)
    dominant_outcome = serializers.CharField(read_only=True, allow_null=True)
    selection_summary = serializers.CharField(read_only=True, allow_null=True)
    outcome_bias_summary = serializers.CharField(read_only=True, allow_null=True)
    representative_cases = serializers.JSONField(read_only=True)


class ConsultProbabilitySummarySerializer(serializers.Serializer):
    scenario_type = serializers.CharField(read_only=True)
    success_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    failure_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    neutral_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    confidence = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    explanation = serializers.JSONField(read_only=True, allow_null=True)
    highlights = ConsultProbabilityHighlightsSerializer(read_only=True)
    fallback_reason = serializers.CharField(read_only=True, allow_null=True, required=False)


class ConsultScenarioItemSerializer(serializers.Serializer):
    scenario_type = serializers.CharField(read_only=True)
    buy_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    buy_quantity = serializers.IntegerField(read_only=True)
    new_average_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    target_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    stop_loss_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    success_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    failure_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    neutral_probability = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    confidence = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    efficiency_score = serializers.DecimalField(max_digits=6, decimal_places=4, read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    reason_summary = serializers.CharField(read_only=True, allow_null=True)
    probability_explanation = serializers.JSONField(read_only=True, allow_null=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)


class ConsultCapitalPlanSerializer(serializers.Serializer):
    max_allowed_budget = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    first_entry_budget = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    second_entry_budget = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    third_entry_budget = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    first_entry_condition = serializers.CharField(read_only=True)
    second_entry_condition = serializers.CharField(read_only=True)
    third_entry_condition = serializers.CharField(read_only=True)
    stop_loss_price = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True, allow_null=True)
    estimated_max_loss = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    details = serializers.JSONField(read_only=True)


class HoldingConsultResponseSerializer(serializers.Serializer):
    final_grade = serializers.CharField(read_only=True)
    consulting_status = serializers.CharField(read_only=True)
    summary = serializers.CharField(read_only=True)
    decision_summary = serializers.CharField(read_only=True)
    risk_gate = ConsultRiskGateSerializer(read_only=True)
    data_quality = ConsultDataQualitySerializer(read_only=True)
    market_regime = ConsultMarketRegimeSerializer(read_only=True)
    stock_quality = ConsultStockQualitySerializer(read_only=True)
    base_decision = ConsultBaseDecisionSerializer(read_only=True)
    score_breakdown = serializers.JSONField(read_only=True)
    probability = ConsultProbabilitySummarySerializer(read_only=True, allow_null=True)
    scenario_table = ConsultScenarioItemSerializer(many=True, read_only=True)
    capital_plan = ConsultCapitalPlanSerializer(read_only=True)
    main_blockers = serializers.ListField(child=serializers.CharField(), read_only=True)
    positive_factors = serializers.ListField(child=serializers.CharField(), read_only=True)
    recheck_conditions = serializers.ListField(child=serializers.CharField(), read_only=True)
    warnings = serializers.ListField(child=serializers.CharField(), read_only=True)
    disclaimer = serializers.CharField(read_only=True)
    stock = ConsultStockSerializer(read_only=True)
    holding = ConsultHoldingSummarySerializer(read_only=True)


class HoldingConsultRequestSerializer(serializers.Serializer):
    buy_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    lookahead_days = serializers.IntegerField(required=False, min_value=5, max_value=120, default=20)
    target_profit_rate = serializers.DecimalField(
        max_digits=8,
        decimal_places=4,
        required=False,
        default=Decimal("0.0000"),
        min_value=Decimal("0"),
    )
    stop_loss_type = serializers.ChoiceField(
        choices=["support_or_atr", "manual", "fixed_rate", "atr", "support"],
        required=False,
        default="support_or_atr",
    )
    stop_loss_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    include_scenarios = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if attrs.get("stop_loss_type") == "manual" and not attrs.get("stop_loss_price"):
            raise serializers.ValidationError(
                {"stop_loss_price": "manual stop_loss_type requires stop_loss_price."}
            )
        return attrs
