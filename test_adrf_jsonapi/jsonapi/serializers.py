import re
from asyncio import iscoroutinefunction
from copy import deepcopy
from django.core.exceptions import ImproperlyConfigured, SynchronousOnlyOperation
from django.core.exceptions import ValidationError as DjangoValidationError
from asgiref.sync import sync_to_async
from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.utils.serializer_helpers import (
    BoundField, JSONBoundField, NestedBoundField, ReturnDict
)
from rest_framework.fields import (JSONField, Field, SkipField, get_error_detail)

from .exeptions import NotSelectedForeignKey
from .helpers import (getattr, hasattr, reverse, deepcopy, get_field_info, 
                      JSONAPISerializerRepr, get_type_from_model, 
                      get_related_field_objects, get_errors_formatted)

# TODO: write an JSONAPI object describing the server’s implementation (version)
# TODO: write an included field
# TODO: maybe add the Field class to the bases and use the basic metaclass
class JSONAPIBaseSerializer(Field):
    _creation_counter = 0
    source = None
    initial = None
    field_name = ''
    
    class Meta:
        pass
    
    def __init__(self, instance=None, data=None, 
                 read_only=False, **kwargs):
        if data is not None:
            self.initial_data = data
        validators = list(kwargs.pop('validators', []))
        if validators:
            self.validators = validators
        self.instance = instance
        self.read_only = read_only
        self.initial = {}
        self.url_field_name = 'links'
        self._kwargs = kwargs
        self._args = {}
        self.partial = kwargs.pop('partial', False)
        self.required = kwargs.pop('required', True)
        self._context = kwargs.pop('context', {})
        request = self._context.get('request')
        if request:
            setattr(self, self.url_field_name, 
                    f'http://{request.get_host()}{request.path}')
        kwargs.pop('many', None)
        super().__init__(**kwargs)

    def __new__(cls, *args, **kwargs):
        Meta = getattr.func(cls, 'Meta', None)
        if Meta:
            parent_meta = cls.__bases__[0].Meta.__dict__
            for name, attr in parent_meta.items():
                if not hasattr.func(Meta, name):
                    setattr(Meta, name, attr)
        if kwargs.pop('many', False):
            return cls.many_init(*args, **kwargs)
        return super().__new__(cls)

    def __repr__(self):
        return str(JSONAPISerializerRepr(self))

    def __class_getitem__(cls, *args, **kwargs):
        return cls

    def __aiter__(self):
        self.iter_count = 0
        return self
    
    async def __anext__(self):
        fields = await self.fields
        try:
            key = list(fields.keys())[self.iter_count]
        except IndexError:
            raise StopAsyncIteration
        else:
            self.iter_count += 1
            return await self[key]
    
    async def __getitem__(self, key):
        fields = await self.fields
        field = fields[key]
        field.field_name = key
        if isinstance(field, JSONField):
            value = field.get_value(await self.__class__(self.instance).data)
            error = self._errors.get(key) if await hasattr(self, '_errors') else None
            return JSONBoundField(field, value, error, key)
        elif isinstance(field, JSONAPIBaseSerializer):
            field = field.__class__(self.instance)
            data = await field.data
            data = {
                key: val for key, val in data.items() if key != 'included'
            }
            field.initial_data = data
            await field.is_valid()
            error = await field.errors
            return NestedBoundField(field, data, error, key)
        else:
            data = await self.__class__(self.instance).data
            try:
                value = data['data'].get(key)
            except KeyError:
                value = data.get(key)
            error = self._errors.get(key) if await hasattr(self, '_errors') else None
            return BoundField(field, value, error, key)
    
    @classmethod
    def many_init(cls, *args, **kwargs):
        allow_empty = kwargs.pop('allow_empty', None)
        max_length = kwargs.pop('max_length', None)
        min_length = kwargs.pop('min_length', None)
        child_serializer = cls(*args, **kwargs)
        list_kwargs = {
            'child': child_serializer,
        }
        if allow_empty is not None:
            list_kwargs['allow_empty'] = allow_empty
        if max_length is not None:
            list_kwargs['max_length'] = max_length
        if min_length is not None:
            list_kwargs['min_length'] = min_length
        list_kwargs.update({
            key: value for key, value in kwargs.items()
            if key in serializers.LIST_SERIALIZER_KWARGS
        })
        meta = getattr.func(cls, 'Meta', None)
        list_serializer_class = getattr.func(meta, 'list_serializer_class', serializers.ListSerializer)
        return list_serializer_class(*args, **list_kwargs)
    
    def bind(self, field_name, parent):
        self.field_name = field_name
        self.parent = parent
    
    def validate(self, attrs):
        return attrs
    
    async def run_validators(self, value):
        errors = {}
        validators = await self.validators
        for field_name, validator in validators.items():
            subfield = field_name.split('.')
            if len(subfield) > 1 and field_name.startswith(subfield[0]):
                value_field = value.get(subfield[0]).get(subfield[-1])
            else:
                try:
                    value_field = value[field_name]
                except KeyError as e:
                    raise KeyError((
                        f"Serializer field named '{field_name}' was not not found. You need "
                        "to specify an 'attributes' or 'relationships' subfield."
                    ))
            try:
                if await getattr(validator, 'requires_context', False):
                    validator(value_field, self)
                else:
                    validator(value_field)
            except ValidationError as exc:
                if isinstance(exc.detail, dict):
                    raise
                errors[field_name] = exc.detail
            except DjangoValidationError as exc:
                errors[field_name] = get_error_detail(exc)
            except TypeError as e:
                raise TypeError(
                    f"Wrong '{field_name}' field validator."
                ) from e
        if errors:
            raise ValidationError(errors)
    
    async def set_value(self, dictionary, keys, value):
        if not keys:
            dictionary.update(value)
            return
        for key in keys:
            if key not in dictionary:
                dictionary[key] = type(value)()
            if type(dictionary[key]) == list:
                dictionary[key].extend(value)
            else:
                dictionary[key] = value
    
    @property
    async def fields(self):
        return await self.get_fields()
    
    async def get_fields(self):
        return await deepcopy(self._declared_fields)
    
    async def get_initial(self):
        if callable(self.initial):
            return self.initial()
        return self.initial

    async def get_validators(self):
        meta = await getattr(self, 'Meta', None)
        validators = await getattr(meta, 'validators', None)
        return dict(validators) if validators else {}
    
    async def get_value(self, field_name, dictionary=None):
        return dictionary.get(field_name, None)

    async def run_validation(self, data={}):
        if data is not None:
            self.initial_data = data
        await self.is_valid(raise_exception=True)
        return await self.validated_data
    
    async def is_valid(self, *, raise_exception=False):
        if not await hasattr(self, '_validated_data'):
            try:
                self._validated_data = await self.to_internal_value(self.initial_data)
            except ValidationError as exc:
                self._validated_data = {}
                self._errors = exc.detail
            else:
                self._errors = {}
        if self._errors and raise_exception:
            raise ValidationError(self._errors)
        return not bool(self._errors)
    
    @staticmethod
    async def _to_coroutine(function):
        if not iscoroutinefunction(function):
            function = sync_to_async(function)
        return function
    
    async def to_internal_value(self, data):
        meta = await getattr(self, 'Meta', None)
        read_only_fields = await getattr(meta, 'read_only_fields', [])
        ret = {}
        errors = {}
        fields = await self.fields
        for name, field in fields.items():
            if await hasattr(field, 'child'):
                field.child.required, field = field.required, field.child
                if self.__class__.__name__ == 'Relationships':
                    field.read_only = True
            if field.read_only or name in read_only_fields:
                continue
            value = await self.get_value(name, data)
            value = value.pop('data', value) if type(value) == dict else value
            value = [value] if type(value) != list else value
            run_validation = await self._to_coroutine(field.run_validation)
            validate_method = await getattr(self, 'validate_' + name, None)
            for obj in value:
                if await hasattr(field, '_validated_data'):
                    del field._validated_data
                try:
                    validated_value = await run_validation(obj)
                    if validate_method is not None:
                        validate_method_awaited = await self._to_coroutine(validate_method)
                        validated_value = await validate_method_awaited(obj)
                except ValidationError as exc:
                    detail = exc.detail
                    if type(detail) == dict:
                        for key, val in detail.items():
                            errors[f'{name}.{key}'] = val
                    else:
                        errors[name] = detail
                except DjangoValidationError as exc:
                    errors[name] = get_error_detail(exc)
                except AttributeError as exc:
                    if field.required:
                        errors[name] = ValidationError(
                            'This field may not be null.'
                        ).detail
                except SkipField:
                    pass
                else:
                    await self.set_value(
                        ret, [name], 
                        [validated_value] if len(value) > 1 else validated_value
                    )
        if errors:
            raise ValidationError(errors)
        else:
            return ret
    
    async def to_representation(self, instance):
        fields = await self.fields
        instance_map = {key: await getattr(instance, key) for key in fields.keys()}
        return {name: await self.get_value(name, instance_map) 
                for name in fields.keys()}

    @property
    async def _readable_fields(self):
        fields = await self.fields
        for field in fields.values():
            if not field.read_only:
                yield field
    
    @property
    async def validators(self):
        if not await hasattr(self, '_validators'):
            self._validators = await self.get_validators()
        return self._validators
    
    @property
    async def data(self):
        if await hasattr(self, 'initial_data') and not await hasattr(self, '_validated_data'):
            msg = (
                'When a serializer is passed a `data` keyword argument you '
                'must call `.is_valid()` before attempting to access the '
                'serialized `.data` representation.\n'
                'You should either call `.is_valid()` first, '
                'or access `.initial_data` instead.'
            )
            raise AssertionError(msg)
        
        errors = await getattr(self, '_errors', None)
        if errors:
            return errors

        if not await hasattr(self, '_data'):
            if self.instance is not None:
                self._data = await self.to_representation(self.instance)
            elif await hasattr(self, '_validated_data'):
                self._data = self._validated_data
            else:
                self._data = await self.get_initial()
        return ReturnDict(self._data, serializer=self)

    @property
    async def errors(self):
        if not await hasattr(self, '_errors'):
            msg = 'You must call `.is_valid()` before accessing `.errors`.'
            raise AssertionError(msg)
        return self._errors
    
    @property
    async def validated_data(self):
        if not await hasattr(self, '_validated_data'):
            msg = 'You must call `.is_valid()` before accessing `.validated_data`.'
            raise AssertionError(msg)
        return self._validated_data


class SerializerMetaclass(type):
    @classmethod
    def _get_declared_fields(cls, bases, attrs):
        obj_info = attrs.get('ObjectId', None)
        if issubclass(obj_info.__class__, cls):
            attrs.update(obj_info._declared_fields)
        attrs.update({name: field() for name, field in {
            key.lower(): attrs.get(key, None)
            for key in ('Attributes', 'Relationships')
        }.items() if field is not None})
        fields = [(field_name, attrs.pop(field_name))
                  for field_name, obj in list(attrs.items())
                  if isinstance(obj, Field)]
        known = set(attrs)
        
        def visit(name):
            known.add(name)
            return name
        
        base_fields = [
            (visit(name), f)
            for base in bases if hasattr.func(base, '_declared_fields')
            for name, f in base._declared_fields.items() if name not in known
        ]
        return dict(base_fields + fields)

    def __new__(cls, name, bases, attrs):
        attrs['_declared_fields'] = cls._get_declared_fields(bases, attrs)
        return super().__new__(cls, name, bases, attrs)


class JSONAPIObjectIdSerializer(JSONAPIBaseSerializer, Field, metaclass=SerializerMetaclass):
    type = serializers.CharField()
    id = serializers.IntegerField()
    
    async def to_representation(self, instance):
        return {'type': await get_type_from_model(instance.__class__), 'id': instance.id}


class JSONAPIAttributesSerializer(JSONAPIBaseSerializer, Field, metaclass=SerializerMetaclass):
    pass


# TODO: create the ModelSerializer-like functionality with own coroutine
class JSONAPIRelationsSerializer(JSONAPIBaseSerializer, Field, metaclass=SerializerMetaclass):
    async def to_representation(self, instance):
        fields = await self.fields
        data = {name: await self.get_value(
            name, {key: await getattr(instance, key) for key in fields.keys()}
        ) for name in fields.keys()}
        url = await getattr(self, self.url_field_name, None)
        for key, val in data.items():
            validated_data, is_many = {}, await hasattr(val, 'all')
            objects = [await JSONAPIObjectIdSerializer(obj).data for obj
                       in await get_related_field_objects(val)]
            if objects and not is_many:
                objects, validated_data = objects[0], objects[0]
            elif objects:
                validated_data = objects[0]
            elif not is_many:
                objects = None
            data[key] = {'data': objects}
            if url:
                links = {'self': f"{url}relationships/{key}/"}
                if data[key]['data']:
                    links['related'] = f"{url}{key}/"
                links['included'] = validated_data.get('type')
                data[key][self.url_field_name] = links
        return data


class JSONAPIManySerializer(JSONAPIBaseSerializer, Field):
    child = None
    many = True
    
    def __init__(self, *args, **kwargs):
        self.child = kwargs.pop('child', deepcopy.func(self.child))
        self.allow_empty = kwargs.pop('allow_empty', True)
        self.max_length = kwargs.pop('max_length', None)
        self.min_length = kwargs.pop('min_length', None)
        assert self.child is not None, '`child` is a required argument.'
        super().__init__(*args, **kwargs)
        self.child.field_name, self.child.parent = '', self

    def __repr__(self):
        return str(JSONAPISerializerRepr(self, force_many=self.child))
    
    def __aiter__(self):
        self.iter_count = 0
        return self
    
    async def __anext__(self):
        fields = await self.child.fields
        try:
            key = list(fields.keys())[self.iter_count]
        except IndexError:
            raise StopAsyncIteration
        else:
            self.iter_count += 1
            return await self[key]
    
    async def __getitem__(self, key):
        fields = []
        async for obj in self.instance:
            data = self.child.__class__(obj)
            fields.append(await data[key])
        return fields
    
    async def to_internal_value(self, data):
        error_message = "The field must contain a valid object description."
        try:
            data = data['data']
        except KeyError:
            raise ValidationError({'data': [error_message]})
        else:
            if type(data) != list:
                raise ValidationError({'data': [
                    "Please provide a list of valid objects."
                    if data else error_message
                ]})
        validated_data = []
        for obj_data in data:
            obj_data = await self.child.run_validation({'data': obj_data})
            errors = self.child._errors
            if not errors:
                validated_data.append(await self.child.validated_data)
                del self.child._validated_data
            else:
                raise ValidationError(errors)
        self._validated_data = validated_data
        return validated_data
    
    async def to_representation(self, iterable):
        data, included = [], {}
        async for instance in iterable:
            obj_data = await self.child.__class__(
                instance, context={**self._context, 'is_included_disabled': True}
            ).data
            data.append(obj_data['data'])
            await self.child._get_included(
                instance, obj_data.get('data').get('relationships'), 
                included, self._context.get('is_included_disabled', False)
            )
        # Sort included
        # data['included'] = sorted(
        #    list(included.values()), 
        #    key=lambda x: (x['type'], x['id'])
        #)
        return {'data': data, 'included': list(included.values())}
    
    @property
    async def errors(self):
        return await get_errors_formatted(self)


# TODO: SERIALIZE A LIST OF INTEGERS IN THE ATTRIBUTES SECTION
class JSONAPISerializer(JSONAPIBaseSerializer, Field, metaclass=SerializerMetaclass):
    class ObjectId(JSONAPIObjectIdSerializer):
        pass
    
    class Attributes(JSONAPIAttributesSerializer):
        pass
    
    class Relationships(JSONAPIRelationsSerializer):
        pass
    
    class Meta:
        list_serializer_class = JSONAPIManySerializer
        read_only_fields = ('id')
    
    @property
    async def fields(self):
        if not await hasattr(self, '_fields'):
            self._fields = await self.get_fields()
        return self._fields
    
    async def _get_included(self, instance, rels, included, is_included_disabled=False):
        if not rels or is_included_disabled:
            return
        for rel in rels.keys():
            view_name = rels[rel]['links'].pop('included')
            objects_list = await get_related_field_objects(await getattr(instance, rel))
            field_info = None if not objects_list else await get_field_info(objects_list[0])
            field_info = {key: field_info[key].keys() for key 
                          in ('fields', 'forward_relations') if field_info is not None} 
            for obj in objects_list:
                
                data_included = {'type': await get_type_from_model(obj.__class__), 'id': obj.id}
                key = "_".join(str(data_included.values()))
                if included.get(key):
                    continue
                for attribute in field_info.get('fields'):
                    if attribute == 'id':
                        continue
                    if not data_included.get('attributes'):
                        data_included['attributes'] = {}
                    data_included['attributes'][attribute] = await getattr(obj, attribute)
                for relationship in field_info.get('forward_relations'):
                    objects_list = [await JSONAPIObjectIdSerializer(obj).data for obj 
                                    in await get_related_field_objects(
                                        await getattr(obj, relationship)
                                    )]
                    if objects_list:
                        data_included.update({'relationships': {relationship: {
                            'data': objects_list if len(objects_list) > 1 else objects_list.pop()
                        }}})
                try:
                    data_included['links'] = {'self': await reverse(
                        view_name + '-detail', args=[data_included['id']],
                        request=self._context.get('request')
                    )}
                except TypeError:
                    print(rels[rel]['links'])
                included[key] = data_included
    
    async def to_internal_value(self, data):
        error_message = "The field must contain a valid object description."
        try:
            data = data['data']
            data['type']
        except KeyError:
            raise ValidationError({'data': [error_message]})
        except TypeError:
            raise ValidationError({'data': ["A list of the object identificators is expected."]})
        if not data.get('relationships'):
            data['relationships'] = {}
        await self.run_validators(data)
        data = await JSONAPIBaseSerializer.to_internal_value(self, data)
        relationships = data.get('relationships', {})
        if relationships and await getattr(self.Meta, 'model'):
            for rel in relationships:
                serializer = JSONAPIObjectIdSerializer()
                rel_model = await getattr(self.Meta.model, rel)
                
                class Meta:
                    model = rel_model.field.related_model
                serializer.Meta = Meta
                print(self.Meta.model)
                await self.__class__.validate_type(serializer, relationships[rel]['type'])
        return {**data.get('attributes', {}), 'relationships': relationships}
    
    async def to_representation(self, instance):
        fields = await self.fields
        serializer_map = {
            'attributes': fields['attributes'].__class__(instance),
            'relationships': fields['relationships'].__class__(
                instance, context={**self._context}
            )
        }
        url = await getattr(self, self.url_field_name, None)
        obj_map = await self.ObjectId(instance).data
        parent_id = str(obj_map['id'])
        if url and not url.endswith(parent_id + '/'):
            url = f"{url}{parent_id}/"
        setattr(serializer_map['relationships'], self.url_field_name, url)
        for key, val in serializer_map.items():
            if len(val._declared_fields):
                try:
                    obj_map[key] = await val.data
                except SynchronousOnlyOperation as e:
                    raise NotSelectedForeignKey from e
            else:
                obj_map[key] = {}
        data = {name: await self.get_value(name, obj_map) for name in 
                fields.keys() if name in obj_map}
        data = {key: val for key, val in data.items() if val}
        included = {}
        if url:
            await self._get_included(
                instance, data.get('relationships'), included,
                self._context.get('is_included_disabled', False)
            )
            data['links'] = {'self': url}
        return {'data': data, 'included': [] if not included
                else list(included.values())}

    async def validate_type(self, value):
        obj_type = await getattr(self.Meta, 'model_type', None)
        if obj_type is None:
            obj_type = await getattr(self.Meta, 'model', '')
            obj_type = await get_type_from_model(obj_type) if await hasattr(self.Meta, 'model') else ''
        if not value or value != obj_type:
            raise serializers.ValidationError({'type': [f"\"{value}\" is not a correct object type."]})
        return value
