from rest_framework.routers import DefaultRouter

from .views import DailyPriceViewSet, InvestorFlowViewSet, MarketIndexViewSet

router = DefaultRouter()
router.register("daily-prices", DailyPriceViewSet, basename="daily-price")
router.register("investor-flows", InvestorFlowViewSet, basename="investor-flow")
router.register("market-indices", MarketIndexViewSet, basename="market-index")

urlpatterns = router.urls

