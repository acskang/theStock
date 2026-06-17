from rest_framework.routers import DefaultRouter

from .views import StockViewSet

router = DefaultRouter()
router.register("", StockViewSet, basename="stock")

urlpatterns = router.urls

