from django.contrib import admin
from adrf_jsonapi.models import Test, TestIncluded, TestIncludedRelation


@admin.register(Test)
class TestAdmin(admin.ModelAdmin):
    pass


@admin.register(TestIncluded)
class TestIncludedAdmin(admin.ModelAdmin):
    pass


@admin.register(TestIncludedRelation)
class TestIncludedRelationAdmin(admin.ModelAdmin):
    pass