import time
from django.core.exceptions import ObjectDoesNotExist
from django.http.response import HttpResponseRedirect
from rest_framework.response import Response
from rest_framework.decorators import action
from adrf.viewsets import ViewSet

from .filters import JSONAPIFilter
from .paginations import LimitOffsetAsyncPagination
from .helpers import (reverse, hasattr, get_type_from_model, 
                      get_related_field_kwarg, get_related_field_objects)


class JSONAPIViewSet(ViewSet):
    view_is_async = True
    pagination_class = LimitOffsetAsyncPagination
    filterset_class = JSONAPIFilter
    
    # TODO: fix pagination 'last' when with filters
    async def list(self, request, pk=None):
        pagination = self.pagination_class()
        queryset = await self.filterset_class(self.queryset, request).filter_queryset()
        objects = await pagination.paginate_queryset(queryset.order_by('id'), request=request)
        data = await self.serializer(
            objects, many=True, context={'request': request}
        ).data
        if data.get('data'):
            response = await pagination.get_paginated_response(data)
        else:
            response = Response({'data': []})
        return response
    
    async def retrieve(self, request, pk):
        try:
            object = await self.queryset.aget(id=pk)
        except ObjectDoesNotExist:
            response = Response({'data': None}, status=404)
        else:
            response = Response(await self.serializer(
                object, context={'request': request}
            ).data, status=200)
        return response
    
    async def create(self, request):
        startT = time.time()
        data = request.data
        is_many = True if 'data' in data.keys() and type(data['data']) == list else False
        serializer = self.serializer(
            data=data, many=is_many, context={'request': request}
        )
        if await serializer.is_valid():
            response_data = await serializer.validated_data
            status = 200
        else:
            response_data = await serializer.errors
            status = 403
        print(f'function time: {time.time() - startT}ms')
        return Response(data=response_data, status=status)
    
    @action(methods=["get", "put"], detail=False, url_name="self",
            url_path=r'(?P<pk>\d+)/relationships/(?P<field_name>\w+)')
    async def self(self, request, *args, **kwargs):
        field, data = await get_related_field_kwarg(self.queryset, kwargs), None
        if request.method.lower() == 'get':
            if await hasattr(field, 'all'):
                data = []
                for obj in await get_related_field_objects(field):
                    obj_data = await self.serializer.ObjectId(obj).data
                    obj_data.update({'links': {'self': await reverse(
                        await get_type_from_model(field.model) + '-detail',
                        args=[obj.id], request=request
                    )}})
                    data.append(obj_data)
            elif field:
                data = await self.serializer.ObjectId(field).data
                data['links'] = {'self': await reverse(
                    await get_type_from_model(field.__class__) + '-detail', 
                    args=[field.id], request=request
                )}
        # TODO: write the put method
        elif request.method.lower() == 'put':
            data = request.data
            is_many = True if 'data' in data.keys() and type(data['data']) == list else False
            serializer = self.serializer.Relationships._declared_fields[kwargs['field_name']]
            if type(data['data']) == list:
                serializer = serializer
            serializer = serializer.__class__(
                data=data, many=is_many, context={'request': request}
            )
            if await serializer.is_valid():
                response_data = await serializer.validated_data
                status = 200
            else:
                response_data = await serializer.errors
                status = 403
            return Response(data=response_data, status=status)
    
        return Response(data={'data': data})
    
    @action(methods=["get"], detail=False, url_name="related", 
            url_path=r'(?P<pk>\d+)/(?P<field_name>\w+)')
    async def related(self, request, *args, **kwargs):
        ids, empty_data = '', {'data': None}
        field = await get_related_field_kwarg(self.queryset, kwargs)
        if await hasattr(field, 'all'):
            empty_data = {'data': []}
            ids = ",".join(await get_related_field_objects(field))
            link = '{}?filter[id]={}'.format(await reverse(
                await get_type_from_model(field.model) + '-list', request=request
            ), ids)
        elif field:
            link, ids = await reverse(
                await get_type_from_model(field.__class__) + '-detail', 
                args=[field.id], request=request
            ), str(field.id)
        if ids:
            return HttpResponseRedirect(link)
        else:
            return Response(empty_data, status=404)

