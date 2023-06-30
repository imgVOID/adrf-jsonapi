from re import sub, findall
from copy import deepcopy
from asgiref.sync import sync_to_async
from rest_framework.reverse import reverse
from rest_framework.response import Response

getattr, hasattr = sync_to_async(getattr), sync_to_async(hasattr)
reverse, deepcopy = sync_to_async(reverse), sync_to_async(deepcopy)


class JSONAPISerializerRepr:
    def __init__(self, serializer, indent=1, force_many=None):
        self._serializer = serializer
        self._indent = indent
        self._force_many = force_many
    
    @staticmethod
    def _has_child(field):
        return hasattr.func(field, 'child')
    
    @staticmethod
    def _smart_repr(value):
        value = repr(value)
        if value.startswith("u'") and value.endswith("'"):
            return value[1:]
        return sub(' at 0x[0-9A-Fa-f]{4,32}>', '>', value)
    
    @classmethod
    def _field_repr(cls, field, force_many=False):
        kwargs = field._kwargs
        if force_many:
            kwargs = kwargs.copy()
            kwargs['many'] = True
            kwargs.pop('child', None)
        arg_string = ', '.join([cls._smart_repr(val) for val in field._args])
        kwarg_string = ', '.join([
            '%s=%s' % (key, cls._smart_repr(val))
            for key, val in sorted(kwargs.items())
        ])
        if arg_string and kwarg_string:
            arg_string += ', '
        if force_many:
            class_name = force_many.__class__.__name__
        else:
            class_name = field.__class__.__name__
        return "%s(%s%s)" % (class_name, arg_string, kwarg_string)
    
    #TODO: test case when list field contains numbers not serializers
    def __repr__(self):
        serializer, indent = self._serializer, self._indent
        ret = self._field_repr(serializer, self._force_many) + ':'
        indent_str = '    ' * indent
        if self._force_many:
            fields = self._force_many._declared_fields
        else:
            fields = serializer._declared_fields
        for field_name, field in fields.items():
            ret += '\n' + indent_str + field_name + ' = '
            required_string = '' if field.required else f'required={field.required}'
            if hasattr.func(field, '_declared_fields'):
                ret += self.__class__(field, indent + 1).__repr__().replace(
                    '()', f"({required_string})"
                )
            elif self._has_child(field):
                child = field.child
                if hasattr.func(child, '_declared_fields'):
                    ret += '{}({}child={})'.format(
                        field.__class__.__name__, required_string + ', ',
                        self.__class__(child, indent + 1).__repr__(),
                    )
                else:
                    ret += self._field_repr(child)
            elif hasattr.func(field, 'child_relation'):
                ret += self._field_repr(field.child_relation, force_many=field.child_relation)
            else:
                ret += self._field_repr(field)
        return ret


async def get_field_info(obj):
    fields, forward_relations = {}, {}
    if await hasattr(obj.__class__, '_meta'):
        for field in obj.__class__._meta.fields:
            data = fields if not field.remote_field else forward_relations
            data[field.name] = {}
    return {'fields': fields, 'forward_relations': forward_relations}


async def get_errors_formatted(serializer):
    if not await hasattr(serializer, '_errors'):
        msg = 'You must call `.is_valid()` before accessing `.errors`.'
        raise AssertionError(msg)
    error_details = []
    for key, val in serializer._errors.items():
        error = None
        if type(val) == dict:
            error = val
        else:
            key = 'type' if key == 'type.type' else key
            error = {key: val}
        if not error:
            continue
        error_detail = {'code': 403}
        url = await getattr(serializer, serializer.url_field_name, None)
        if url:
            error_detail['source'] = {'pointer': url}
        error_detail['detail'] = "The JSON field {0}caused an exception: {1}".format(
            "\"" + key + "\" ", error[key][0].lower()
        )
        error_details.append(error_detail)
    if not error_details:
        return None
    return {"jsonapi": { "version": "1.1" }, 'errors': error_details}


async def get_type_from_model(obj_type):
    return '-'.join(findall('[A-Z][^A-Z]*', obj_type.__name__)).lower()


async def get_related_field_kwarg(queryset, kwargs):
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
