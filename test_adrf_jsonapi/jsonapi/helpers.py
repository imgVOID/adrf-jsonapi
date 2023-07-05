from re import findall
from copy import deepcopy
from asyncio import iscoroutinefunction
from asgiref.sync import sync_to_async
from rest_framework.reverse import reverse
from rest_framework.response import Response

getattr, reverse, deepcopy = sync_to_async(getattr), sync_to_async(reverse), sync_to_async(deepcopy)


async def to_coroutine(function):
    if not iscoroutinefunction(function):
        function = sync_to_async(function)
    return function


async def get_field_info(obj):
    fields, forward_relations = {}, {}
    if hasattr(obj.__class__, '_meta'):
        for field in obj.__class__._meta.fields:
            data = fields if not field.remote_field else forward_relations
            data[field.name] = {}
    return {'fields': fields, 'forward_relations': forward_relations}


async def get_errors_formatted(serializer):
        errors_remplate = {"jsonapi": { "version": "1.1" }, 'errors': []}
        if not hasattr(serializer, '_errors'):
            msg = 'You must call `.is_valid()` before accessing `.errors`.'
            raise AssertionError(msg)
        elif serializer._errors.get('errors', None):
            errors_remplate['errors'] = serializer._errors
            return errors_remplate
        error_details = []
        for key, val in serializer._errors.items():
            url = await getattr(serializer, serializer.url_field_name, None)
            error, error_detail = None, {'code': 403}
            if type(val) == dict:
                error = val
            else:
                key = 'type' if key == 'type.type' else key
                error = {key: val}
            if not error:
                continue
            if url:
                error_detail['source'] = {'pointer': url}
            error_detail['detail'] = "The JSON field {0}caused an exception: {1}".format(
                "\"" + key + "\" ", error[key][0].lower()
            )
            error_details.append(error_detail)
        if not error_details:
            return None
        serializer._errors = {"jsonapi": { "version": "1.1" }, 'errors': error_details}
        return serializer._errors


async def get_type_from_model(obj_type):
    return '-'.join(findall('[A-Z][^A-Z]*', obj_type.__name__)).lower()


async def get_related_field(queryset, kwargs):
    object = await queryset.aget(id=kwargs['pk'])
    try:
        field_name = kwargs['field_name']
        field = await getattr(object, field_name)
    except AttributeError:
        return Response({'data': None}, status=404)
    else:
        return field

async def get_related_field_objects(field):
    try:
        field = [obj async for obj in 
                 await sync_to_async(field.all)()]
    except (AttributeError, TypeError):
        field = [field] if field else []
    return field
