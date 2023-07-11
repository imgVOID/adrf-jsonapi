from rest_framework import routers
from rest_framework.urlpatterns import format_suffix_patterns

from . import views

router = routers.DefaultRouter()

router.register(r"test", views.TestViewSet, basename="test")
router.register(r"test-included", views.TestIncludedViewSet, basename="test-included")
router.register(r"test-included-relation", views.TestIncludedRelationViewSet, basename="test-included-relation")
router.register(r"test-model", views.TestModelViewSet, basename="test-model")

urlpatterns = router.urls
