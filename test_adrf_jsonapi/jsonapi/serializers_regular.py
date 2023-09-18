from django.core.exceptions import (ValidationError as DjangoValidationError, 
                                    SynchronousOnlyOperation, ImproperlyConfigured)
from rest_framework import serializers
from rest_framework.reverse import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import SerializerMetaclass
from rest_framework.fields import (JSONField, Field, SkipField, get_error_detail)
from rest_framework.utils.serializer_helpers import (BoundField, JSONBoundField, 
                                                     NestedBoundField, ReturnDict)

from .utils import JSONAPISerializerRepr, NotSelectedForeignKey, cached_property
from .helpers import (getattr, deepcopy, reverse, to_coroutine, get_field_info, 
                      get_type_from_model, get_related_field_objects, 
                      get_errors_formatted)

from jsonapi.serializers import JSONAPIObjectIdSerializer


# TODO: write an JSONAPI object describing the server’s implementation (version)
# TODO: write an included field
class BaseSerializer(Field):
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
        kwargs.pop('many', None)
        super().__init__(**kwargs)

    def __new__(cls, *args, **kwargs):
        Meta = getattr.func(cls, 'Meta', None)
        if Meta:
            parent_meta = cls.__bases__[0].Meta.__dict__
            for name, attr in parent_meta.items():
                if not hasattr(Meta, name):
                    setattr(Meta, name, attr)
        if kwargs.pop('many', False):
            return serializers.BaseSerializer.many_init.__func__(cls, *args, **kwargs)
        return super().__new__(cls)

    def __repr__(self):
        return str(JSONAPISerializerRepr(self, force_many=hasattr(self, 'child')))

    def __class_getitem__(cls, *args, **kwargs):
        return cls

    def __aiter__(self):
        self.iter_count = 0
        return self
    
    async def __anext__(self):
        fields = await self.child.fields if self.many else self.fields
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
            error = self._errors.get(key) if hasattr(self, '_errors') else None
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
            error = self._errors.get(key) if hasattr(self, '_errors') else None
            return BoundField(field, value, error, key)
    
    def bind(self, field_name, parent):
        self.field_name, self.parent = field_name, parent
    
    def validate(self, attrs):
        return attrs
    
    async def run_validators(self, value):
        errors, validators = {}, await self.validators
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
                        "to specify the 'attributes' or the 'relationships' subfield."
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
        for key in keys:
            if key not in dictionary:
                dictionary[key] = type(value)()
            if type(dictionary[key]) == list:
                dictionary[key].extend(value)
            else:
                dictionary[key] = value
        dictionary.update(value) if not keys else None
    
    @cached_property
    async def fields(self):
        return await self.get_fields()
    
    @property
    async def _readable_fields(self):
        try:
            fields = await self.fields
        except TypeError:
            fields = self.fields
        for field in fields.values():
            if type(field) == dict and 'read_only' in field:
                for val in field.values():
                    yield val
            if field.read_only:
                yield field
    
    @property
    async def _writable_fields(self):
        try:
            fields = await self.fields
        except TypeError:
            fields = self.fields
        for field in fields.values():
            if type(field) == dict and 'read_only' not in field:
                for val in field.values():
                    yield val
            elif not field.read_only:
                yield field
    
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
        if not hasattr(self, '_validated_data'):
            try:
                self._validated_data = await self.to_internal_value(self.initial_data)
            except ValidationError as exc:
                self._validated_data = {}
                self._errors = exc.detail
            else:
                self._errors = {}
        if self._errors and raise_exception:
            raise ValidationError(self._errors)
        self._errors = await get_errors_formatted(self)
        return not bool(self._errors)
    
    async def to_internal_value(self, data):
        meta = await getattr(self, 'Meta', None)
        read_only_fields = await getattr(meta, 'read_only_fields', [])
        ret = {}
        errors = {}
        try:
            fields = await self.fields
        except TypeError:
            fields = self.fields
        for name, field in fields.items():
            if hasattr(field, 'child'):
                field.child.required, field = field.required, field.child
                if self.__class__.__name__ == 'Relationships':
                    field.read_only = True
            if field.read_only or name in read_only_fields:
                continue
            value = await self.get_value(name, data)
            value = value.pop('data', value) if type(value) == dict else value
            value = [value] if type(value) != list else value
            run_validation = await to_coroutine(field.run_validation)
            validate_method = await getattr(self, 'validate_' + name, None)
            for obj in value:
                if hasattr(field, '_validated_data'):
                    del field._validated_data
                try:
                    validated_value = await run_validation(obj)
                    if validate_method is not None:
                        validate_method_awaited = await to_coroutine(validate_method)
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
        raise NotImplemented('This method is not implemented')
    
    @property
    async def validators(self):
        if not hasattr(self, '_validators'):
            self._validators = await self.get_validators()
        return self._validators
    
    @property
    async def data(self):
        if hasattr(self, 'initial_data') and not hasattr(self, '_validated_data'):
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

        if not hasattr(self, '_data'):
            if self.instance is not None:
                self._data = await self.to_representation(self.instance)
            elif hasattr(self, '_validated_data'):
                self._data = self._validated_data
            else:
                self._data = await self.get_initial()
        return ReturnDict(self._data, serializer=self)
    
    @property
    async def errors(self):
        return self._errors
    
    @property
    async def validated_data(self):
        if not hasattr(self, '_validated_data'):
            msg = 'You must call `.is_valid()` before accessing `.validated_data`.'
            raise AssertionError(msg)
        validated_data = [self._validated_data] if type(self._validated_data) != list else self._validated_data

        for obj in validated_data:
            for name, field in list(obj.items()):
                if hasattr(field, 'pk'):
                    if type(self._validated_data) == list:
                        self._validated_data.remove(field)
                        self._validated_data.append(await JSONAPIObjectIdSerializer(field).data)
                    else:
                        del self._validated_data[name]
                        self._validated_data[name] = await JSONAPIObjectIdSerializer(field).data
        return self._validated_data


class SerializerMetaclass(SerializerMetaclass):
    def __new__(cls, name, bases, attrs):
        obj_info = attrs.get('ObjectId', None)
        if issubclass(obj_info.__class__, cls):
            attrs.update(obj_info._declared_fields)
        attrs.update({name: field() for name, field in {
            key.lower(): attrs.get(key, None)
            for key in ('Attributes', 'Relationships')
        }.items() if field is not None})
        attrs['_declared_fields'] = super()._get_declared_fields(bases, attrs)
        return type.__new__(cls, name, bases, attrs)


class ManySerializer2(BaseSerializer):
    child, many = None, True
    
    def __init__(self, *args, **kwargs):
        self.child = kwargs.pop('child', deepcopy.func(self.child))
        self.allow_empty = kwargs.pop('allow_empty', True)
        self.max_length = kwargs.pop('max_length', None)
        self.min_length = kwargs.pop('min_length', None)
        assert self.child is not None, '`child` is a required argument.'
        super().__init__(*args, **kwargs)
        self.child.field_name, self.child.parent = '', self
    
    async def __getitem__(self, key):
        fields = []
        async for obj in self.instance:
            data = self.child.__class__(obj)
            fields.append(await data[key])
        return fields
    
    async def to_internal_value(self, data):
        validated_data = []
        for obj_data in data:
            obj_data = await self.child.run_validation(obj_data)
            errors = await self.child.errors
            if not errors:
                validated_data.append(await self.child.validated_data)
                del self.child._validated_data
            else:
                raise ValidationError(errors)
        self._validated_data = validated_data
        return validated_data
    
    async def _to_representation_instance(self, instance, data):
        data.append(obj_data = await self.child.__class__(
            instance, context=self._context
        ).data)
    
    async def to_representation(self, iterable):
        data = []
        try:
            async for instance in iterable:
                await self._to_representation_instance(instance, data)
        except SynchronousOnlyOperation:
            for instance in iterable:
                await self._to_representation_instance(instance, data)
        # Sort included
        # data['included'] = sorted(
        #    list(included.values()), 
        #    key=lambda x: (x['type'], x['id'])
        #)
        return data



class JSONAPISerializer(BaseSerializer, metaclass=SerializerMetaclass):
    class Meta:
        list_serializer_class = ManySerializer2
        read_only_fields = ('id',)
    
    async def to_internal_value(self, data):
        await self.run_validators(data)
        data = await BaseSerializer.to_internal_value(self, data)
        return data
    
    async def to_representation(self, instance):
        fields = await self.fields
        serializer_map = {
            'attributes': fields['attributes'].__class__(instance),
            'relationships': fields['relationships'].__class__(
                instance, context={**self._context}
            )
        }
        obj_map = await self.ObjectId(instance).data
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
        return data

    async def validate_type(self, value):
        obj_type = await getattr(self.Meta, 'model_type', None)
        if obj_type is None:
            obj_type = await getattr(self.Meta, 'model', '')
            obj_type = await get_type_from_model(obj_type) if hasattr(self.Meta, 'model') else ''
        if not value or value != obj_type:
            raise serializers.ValidationError({'type': [f"\"{value}\" is not a correct object type."]})
        return value
