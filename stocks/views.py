from rest_framework import viewsets

from stock_service.permissions import AuthenticatedReadOnlyOrStaffWrite

from .models import Stock
from .serializers import StockSerializer


class StockViewSet(viewsets.ModelViewSet):
    queryset = Stock.objects.all()
    serializer_class = StockSerializer
    permission_classes = [AuthenticatedReadOnlyOrStaffWrite]
    filterset_fields = ("market", "is_active")
    search_fields = ("code", "name", "sector")
    ordering_fields = ("code", "name", "updated_at")
