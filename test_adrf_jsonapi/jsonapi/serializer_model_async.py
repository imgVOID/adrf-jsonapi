import traceback
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.serializers import ModelSerializer, BaseSerializer
from rest_framework.utils import html, model_meta, representation
from asgiref.sync import sync_to_async

setattr, getattr = sync_to_async(setattr), sync_to_async(getattr)


def raise_errors_on_nested_writes(method_name, serializer, validated_data):
    ModelClass = serializer.Meta.model
    model_field_info = model_meta.get_field_info(ModelClass)
    assert not any(
        isinstance(field, BaseSerializer) and
        (field.source in validated_data) and
        (field.source in model_field_info.relations) and
        isinstance(validated_data[field.source], (list, dict))
        for field in serializer._writable_fields
    ), (
        'The `.{method_name}()` method does not support writable nested '
        'fields by default.\nWrite an explicit `.{method_name}()` method for '
        'serializer `{module}.{class_name}`, or set `read_only=True` on '
        'nested serializer fields.'.format(
            method_name=method_name,
            module=serializer.__class__.__module__,
            class_name=serializer.__class__.__name__
        )
    )
    assert not any(
        len(field.source_attrs) > 1 and
        (field.source_attrs[0] in validated_data) and
        (field.source_attrs[0] in model_field_info.relations) and
        isinstance(validated_data[field.source_attrs[0]], (list, dict))
        for field in serializer._writable_fields
    ), (
        'The `.{method_name}()` method does not support writable dotted-source '
        'fields by default.\nWrite an explicit `.{method_name}()` method for '
        'serializer `{module}.{class_name}`, or set `read_only=True` on '
        'dotted-source serializer fields.'.format(
            method_name=method_name,
            module=serializer.__class__.__module__,
            class_name=serializer.__class__.__name__
        )
    )


class ModelSerializerAsync(ModelSerializer):
    async def create(self, validated_data):
        raise_errors_on_nested_writes('create', self, validated_data)

        ModelClass = self.Meta.model

        info = model_meta.get_field_info(ModelClass)
        many_to_many = {}
        for field_name, relation_info in info.relations.items():
            if not relation_info.to_many:
                relation_model = relation_info.related_model
                try:
                    validated_data[field_name] = await relation_info.related_model.objects.aget(
                        id=validated_data[field_name]
                    )
                except ObjectDoesNotExist:
                    raise ObjectDoesNotExist(
                        f'There are not any "{str(relation_model)}" inctance'
                        'with the "{validated_data[field_name]}" id.'
                    )
            if relation_info.to_many and (field_name in validated_data):
                many_to_many[field_name] = validated_data.pop(field_name)

        try:
            instance = await ModelClass._default_manager.acreate(**validated_data)
        except TypeError:
            tb = traceback.format_exc()
            msg = (
                'Got a `TypeError` when calling `%s.%s.create()`. '
                'This may be because you have a writable field on the '
                'serializer class that is not a valid argument to '
                '`%s.%s.create()`. You may need to make the field '
                'read-only, or override the %s.create() method to handle '
                'this correctly.\nOriginal exception was:\n %s' %
                (
                    ModelClass.__name__,
                    ModelClass._default_manager.name,
                    ModelClass.__name__,
                    ModelClass._default_manager.name,
                    self.__class__.__name__,
                    tb
                )
            )
            raise TypeError(msg)

        if many_to_many:
            for field_name, value in many_to_many.items():
                field = await getattr(instance, field_name)
                await field.aset(value)

        return instance

    async def update(self, instance, validated_data):
        raise_errors_on_nested_writes('update', self, validated_data)
        info = model_meta.get_field_info(instance)

        m2m_fields = []
        for attr, value in validated_data.items():
            if attr in info.relations and info.relations[attr].to_many:
                m2m_fields.append((attr, value))
            else:
                setattr(instance, attr, value)

        instance.save()
        
        for attr, value in m2m_fields:
            field = await getattr(instance, attr)
            field.set(value)

        return instance

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

        if not hasattr(self, '_data'):
            if self.instance is not None and not await getattr(self, '_errors', None):
                self._data = await sync_to_async(self.to_representation)(self.instance)
            elif hasattr(self, '_validated_data') and not await getattr(self, '_errors', None):
                self._data = await sync_to_async(self.to_representation)(self.validated_data)
            else:
                self._data = await sync_to_async(self.get_initial)()
        return self._data

    @property
    async def errors(self):
        if not hasattr(self, '_errors'):
            msg = 'You must call `.is_valid()` before accessing `.errors`.'
            raise AssertionError(msg)
        return self._errors

    @property
    async def validated_data(self):
        if not hasattr(self, '_validated_data'):
            msg = 'You must call `.is_valid()` before accessing `.validated_data`.'
            raise AssertionError(msg)
        return self._validated_data
    
    async def is_valid(self, *args, raise_exception=False):
        await sync_to_async(BaseSerializer.is_valid)(self, *args, raise_exception=False)
