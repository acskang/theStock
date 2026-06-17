from django.urls import reverse
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONOpenAPIRenderer, OpenAPIRenderer, TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.schemas import get_schema_view
from rest_framework.schemas.openapi import SchemaGenerator
from rest_framework.views import APIView

SCHEMA_TITLE = "Stock Workbench API"
SCHEMA_DESCRIPTION = (
    "주식 거래 관리, 물타기 평가, 확률 계산, 종합 컨설팅을 제공하는 인증 기반 API입니다."
)
SCHEMA_VERSION = "1.0.0"
SCHEMA_EXCLUDED_PATHS = {"/api/schema/", "/api/docs/"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


schema_view = get_schema_view(
    title=SCHEMA_TITLE,
    description=SCHEMA_DESCRIPTION,
    version=SCHEMA_VERSION,
    public=False,
    permission_classes=[IsAuthenticated],
    renderer_classes=[OpenAPIRenderer, JSONOpenAPIRenderer],
)


def _read_schema_paths(schema):
    if schema is None:
        return {}
    if isinstance(schema, dict):
        return schema.get("paths", {})
    try:
        return schema["paths"]
    except Exception:
        return getattr(schema, "paths", {})


def _normalize_operation(method, operation):
    if not isinstance(operation, dict):
        operation = {}
    return {
        "method": method.upper(),
        "summary": operation.get("summary") or operation.get("operationId") or "",
        "description": operation.get("description") or "",
        "tags": operation.get("tags") or [],
    }


def _group_name_for_path(path):
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        return "root"
    if parts[0] == "api" and len(parts) > 1:
        return parts[1]
    return parts[0]


def _build_path_groups(schema):
    groups = {}
    for path, path_item in sorted(_read_schema_paths(schema).items()):
        if path in SCHEMA_EXCLUDED_PATHS:
            continue
        operations = []
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            operations.append(_normalize_operation(method, operation))
        if not operations:
            continue
        group_name = _group_name_for_path(path)
        groups.setdefault(group_name, []).append({"path": path, "operations": operations})
    return [
        {"name": group_name, "entries": groups[group_name]}
        for group_name in sorted(groups.keys())
    ]


class ApiDocsView(APIView):
    permission_classes = [IsAuthenticated]
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "api_docs.html"

    def get(self, request):
        generator = SchemaGenerator(
            title=SCHEMA_TITLE,
            description=SCHEMA_DESCRIPTION,
            version=SCHEMA_VERSION,
        )
        schema = generator.get_schema(request=request, public=False)
        context = {
            "schema_title": SCHEMA_TITLE,
            "schema_description": SCHEMA_DESCRIPTION,
            "schema_path": reverse("api-schema"),
            "schema_groups": _build_path_groups(schema),
        }
        return Response(context, template_name=self.template_name)
