from rest_framework import serializers
from rest_framework.schemas.openapi import AutoSchema


class RequestResponseAutoSchema(AutoSchema):
    def _build_serializer(self, serializer_ref):
        if serializer_ref is None:
            return None
        if isinstance(serializer_ref, serializers.BaseSerializer):
            return serializer_ref
        if isinstance(serializer_ref, type) and issubclass(serializer_ref, serializers.BaseSerializer):
            return serializer_ref()
        return serializer_ref()

    def _get_view_serializer(self, attribute_name):
        serializer_ref = getattr(self.view, attribute_name, None)
        if serializer_ref is None:
            return None
        return self._build_serializer(serializer_ref)

    def get_request_serializer(self, path, method):
        serializer = self._get_view_serializer("request_serializer_class")
        if serializer is not None:
            return serializer
        return super().get_request_serializer(path, method)

    def get_response_serializer(self, path, method):
        serializer = self._get_view_serializer("response_serializer_class")
        if serializer is not None:
            return serializer
        return super().get_response_serializer(path, method)

    def get_components(self, path, method):
        if method.lower() == "delete":
            return {}

        request_serializer = self._get_view_serializer("request_serializer_class")
        response_serializer = self._get_view_serializer("response_serializer_class")
        if not isinstance(request_serializer, serializers.Serializer) and not isinstance(
            response_serializer,
            serializers.Serializer,
        ):
            return super().get_components(path, method)

        components = {}
        if isinstance(request_serializer, serializers.Serializer):
            components.setdefault(
                self.get_component_name(request_serializer),
                self.map_serializer(request_serializer),
            )
        if isinstance(response_serializer, serializers.Serializer):
            components.setdefault(
                self.get_component_name(response_serializer),
                self.map_serializer(response_serializer),
            )
        return components

    def get_responses(self, path, method):
        response_serializer = self._get_view_serializer("response_serializer_class")
        if isinstance(response_serializer, serializers.Serializer):
            self.response_media_types = self.map_renderers(path, method)
            response_schema = self.get_reference(response_serializer)
            response_status_code = str(
                getattr(self.view, "response_status_code", "201" if method == "POST" else "200")
            )
            return {
                response_status_code: {
                    "content": {
                        content_type: {"schema": response_schema}
                        for content_type in self.response_media_types
                    },
                    "description": "",
                }
            }

        responses = super().get_responses(path, method)
        response_status_code = getattr(self.view, "response_status_code", None)
        if response_status_code is None:
            return responses

        response_status_code = str(response_status_code)
        default_status_code = "201" if method == "POST" else "200"
        if response_status_code == default_status_code or default_status_code not in responses:
            return responses

        responses[response_status_code] = responses.pop(default_status_code)
        return responses
