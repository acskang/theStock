from rest_framework import viewsets

from stock_service.permissions import AuthenticatedReadOnlyOrStaffWrite

from .models import DailyPrice, InvestorFlow, MarketIndex
from .serializers import DailyPriceSerializer, InvestorFlowSerializer, MarketIndexSerializer


class DailyPriceViewSet(viewsets.ModelViewSet):
    queryset = DailyPrice.objects.select_related("stock").all()
    serializer_class = DailyPriceSerializer
    permission_classes = [AuthenticatedReadOnlyOrStaffWrite]
    filterset_fields = ("stock", "date")
    search_fields = ("stock__code", "stock__name")
    ordering_fields = ("date", "close_price", "volume")


class InvestorFlowViewSet(viewsets.ModelViewSet):
    queryset = InvestorFlow.objects.select_related("stock").all()
    serializer_class = InvestorFlowSerializer
    permission_classes = [AuthenticatedReadOnlyOrStaffWrite]
    filterset_fields = ("stock", "date")
    search_fields = ("stock__code", "stock__name")
    ordering_fields = ("date", "foreign_net_buy", "institution_net_buy")


class MarketIndexViewSet(viewsets.ModelViewSet):
    queryset = MarketIndex.objects.all()
    serializer_class = MarketIndexSerializer
    permission_classes = [AuthenticatedReadOnlyOrStaffWrite]
    filterset_fields = ("code", "date")
    search_fields = ("code", "name")
    ordering_fields = ("date", "code", "close_value")
