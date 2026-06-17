from decimal import Decimal

from decisions.models import AveragingProbabilityRecord, HoldingConsultRecord


def _stringify_nested_decimals(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify_nested_decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_nested_decimals(item) for item in value]
    return value


def create_probability_record(holding, scenario_input, response_payload):
    serialized_input = _stringify_nested_decimals(scenario_input)
    serialized_payload = _stringify_nested_decimals(response_payload)
    return AveragingProbabilityRecord.objects.create(
        holding=holding,
        scenario_input=serialized_input,
        response_payload=serialized_payload,
        success_probability=serialized_payload["success_probability"],
        failure_probability=serialized_payload["failure_probability"],
        neutral_probability=serialized_payload["neutral_probability"],
        confidence=serialized_payload["confidence"],
        disclaimer=serialized_payload["disclaimer"],
    )


def create_consult_record(holding, request_input, response_payload):
    serialized_input = _stringify_nested_decimals(request_input)
    serialized_payload = _stringify_nested_decimals(response_payload)
    return HoldingConsultRecord.objects.create(
        holding=holding,
        request_input=serialized_input,
        response_payload=serialized_payload,
        final_grade=serialized_payload["final_grade"],
        consulting_status=serialized_payload["consulting_status"],
        summary=serialized_payload["summary"],
        disclaimer=serialized_payload["disclaimer"],
    )
