from rest_framework.routers import DefaultRouter

from .views import TechnicalIndicatorViewSet

router = DefaultRouter()
router.register("technical-indicators", TechnicalIndicatorViewSet, basename="technical-indicator")

urlpatterns = router.urls

