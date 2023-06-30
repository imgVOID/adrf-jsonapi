from rest_framework.authentication import SessionAuthentication
from rest_framework.reverse import reverse
from asgiref.sync import sync_to_async

from jsonapi.viewsets import JSONAPIViewSet
from .models import Test, TestIncluded, TestIncludedRelation
from adrf_jsonapi.permissions import AuthenticatedReadIsStaffOtherPermission
from adrf_jsonapi.serializers import TestSerializer, TestIncludedSerializer, TestIncludedRelationSerializer
from rest_framework.reverse import reverse
from asgiref.sync import sync_to_async

reverse = sync_to_async(reverse)


class TestViewSet(JSONAPIViewSet):
    permission_classes = [AuthenticatedReadIsStaffOtherPermission]
    authentication_classes = [SessionAuthentication]
    serializer = TestSerializer
    queryset = Test.objects.prefetch_related('many_to_many').select_related('foreign_key').all()


class TestIncludedViewSet(JSONAPIViewSet):
    permission_classes = [AuthenticatedReadIsStaffOtherPermission]
    authentication_classes = [SessionAuthentication]
    serializer = TestIncludedSerializer
    queryset = TestIncluded.objects.prefetch_related('many_to_many_included').select_related('foreign_key_included').all()


class TestIncludedRelationViewSet(JSONAPIViewSet):
    permission_classes = [AuthenticatedReadIsStaffOtherPermission]
    authentication_classes = [SessionAuthentication]
    serializer = TestIncludedRelationSerializer
    queryset = TestIncludedRelation.objects.all()