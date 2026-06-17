from rest_framework import viewsets

from .models import TechnicalIndicator
from .serializers import TechnicalIndicatorSerializer


class TechnicalIndicatorViewSet(viewsets.ModelViewSet):
    queryset = TechnicalIndicator.objects.select_related("stock").all()
    serializer_class = TechnicalIndicatorSerializer
    filterset_fields = ("stock", "date")
    search_fields = ("stock__code", "stock__name")
    ordering_fields = ("date", "ma5", "rsi14", "atr14")

