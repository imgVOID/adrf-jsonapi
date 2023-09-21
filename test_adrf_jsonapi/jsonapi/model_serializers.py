import copy
import contextlib
import traceback
from time import timezone

from django.db import models
from django.db.models.fields import Field as DjangoModelField
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import (
    ValidationError as DjangoValidationError, 
    FieldDoesNotExist, ImproperlyConfigured
)

from rest_framework.exceptions import ValidationError
from rest_framework.settings import api_settings
from rest_framework.utils import model_meta
from rest_framework.fields import (
    CreateOnlyDefault, SkipField, empty, JSONField, 
    Field, SkipField, CharField, ChoiceField, 
    HiddenField, HStoreField, JSONField, ListField, 
    ModelField, ReadOnlyField, get_error_detail
)
from rest_framework.validators import (
    UniqueForDateValidator, UniqueForMonthValidator, UniqueForYearValidator,
    UniqueTogetherValidator
)
from rest_framework.relations import (
    HyperlinkedIdentityField, HyperlinkedRelatedField,
    PrimaryKeyRelatedField, ManyRelatedField
)
from rest_framework.utils.field_mapping import (
    ClassLookupDict, get_field_kwargs, get_nested_relation_kwargs,
    get_relation_kwargs, get_url_kwargs
)
from rest_framework.compat import postgres_fields
from rest_framework.serializers import ModelSerializer

from .serializers import (
    JSONAPISerializer, SerializerMetaclass, 
    JSONAPIAttributesSerializer, JSONAPIObjectIdSerializer,
    JSONAPIBaseSerializer
)
from .helpers import (
    get_relation_kwargs, get_type_from_model, to_coroutine, getattr
)

ALL_FIELDS = '__all__'


def raise_errors_on_nested_writes(method_name, serializer, validated_data):
    ModelClass = serializer.Meta.model
    model_field_info = model_meta.get_field_info(ModelClass)
    
    assert not any(
        isinstance(field, JSONAPIBaseSerializer) and
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


class JSONAPIModelSerializer(JSONAPISerializer, metaclass=SerializerMetaclass):
    serializer_field_mapping = ModelSerializer.serializer_field_mapping
    
    if hasattr(models, 'JSONField'):
        serializer_field_mapping[models.JSONField] = JSONField
    if postgres_fields:
        serializer_field_mapping[postgres_fields.HStoreField] = HStoreField
        serializer_field_mapping[postgres_fields.ArrayField] = ListField
        serializer_field_mapping[postgres_fields.JSONField] = JSONField
    serializer_object_id_field = JSONAPIObjectIdSerializer
    serializer_related_field = PrimaryKeyRelatedField
    serializer_related_field_many = ManyRelatedField
    serializer_related_to_field = PrimaryKeyRelatedField
    serializer_url_field = HyperlinkedIdentityField
    serializer_choice_field = ChoiceField
    
    async def get_fields(self):
        """
        Return the dict of field names -> field instances that should be
        used for `await self.fields` when instantiating the serializer.
        """
        if self.url_field_name is None:
            self.url_field_name = api_settings.URL_FIELD_NAME

        assert hasattr(self, 'Meta'), (
            'Class {serializer_class} missing "Meta" attribute'.format(
                serializer_class=self.__class__.__name__
            )
        )
        assert hasattr(self.Meta, 'model'), (
            'Class {serializer_class} missing "Meta.model" attribute'.format(
                serializer_class=self.__class__.__name__
            )
        )
        if model_meta.is_abstract_model(self.Meta.model):
            raise ValueError(
                'Cannot use ModelSerializer with Abstract Models.'
            )

        declared_fields = copy.deepcopy(self._declared_fields)
        model = await getattr(self.Meta, 'model')
        depth = await getattr(self.Meta, 'depth', 0)

        if depth is not None:
            assert depth >= 0, "'depth' may not be negative."
            assert depth <= 10, "'depth' may not be greater than 10."

        # Retrieve metadata about fields & relationships on the model class.
        info = model_meta.get_field_info(model)
        field_names = await self.get_field_names(declared_fields, info)

        # Determine any extra field arguments and hidden fields that
        # should be included
        extra_kwargs = await self.get_extra_kwargs()
        extra_kwargs, hidden_fields = await self.get_uniqueness_extra_kwargs(
            field_names, declared_fields, extra_kwargs
        )

        # Determine the fields that should be included on the serializer.
        fields = {}

        for field_name in field_names:
            # If the field is explicitly declared on the class then use that.
            if field_name in declared_fields:
                fields[field_name] = declared_fields[field_name]
                continue

            extra_field_kwargs = extra_kwargs.get(field_name, {})
            source = extra_field_kwargs.get('source', '*')
            if source == '*':
                source = field_name

            # Determine the serializer field class and keyword arguments.
            field_class, field_kwargs = await self.build_field(
                source, info, model, depth
            )

            # Include any kwargs defined in `Meta.extra_kwargs`
            field_kwargs = await self.include_extra_kwargs(
                field_kwargs, extra_field_kwargs
            )

            # Create the serializer field.
            fields[field_name] = field_class(**field_kwargs)

        # Add in any hidden fields.
        fields.update(hidden_fields)
        fields_jsonapi = {'id': fields.pop('id'), 'attributes': {}, 'relationships': {}}
        for key, field in fields.items():
            if type(field) in [self.serializer_related_field, 
                               self.serializer_related_field_many]:
                fields_jsonapi['relationships'][key] = field
            else:
                fields_jsonapi['attributes'][key] = field
        return fields_jsonapi

    async def get_field_names(self, declared_fields, info):
        """
        Returns the list of all field names that should be created when
        instantiating this serializer class. This is based on the default
        set of fields, but also takes into account the `Meta.fields` or
        `Meta.exclude` options if they have been specified.
        """
        fields = await getattr(self.Meta, 'fields', None)
        exclude = await getattr(self.Meta, 'exclude', None)

        if fields and fields != ALL_FIELDS and not isinstance(fields, (list, tuple)):
            raise TypeError(
                'The `fields` option must be a list or tuple or "__all__". '
                'Got %s.' % type(fields).__name__
            )

        if exclude and not isinstance(exclude, (list, tuple)):
            raise TypeError(
                'The `exclude` option must be a list or tuple. Got %s.' %
                type(exclude).__name__
            )

        assert not (fields and exclude), (
            "Cannot set both 'fields' and 'exclude' options on "
            "serializer {serializer_class}.".format(
                serializer_class=self.__class__.__name__
            )
        )

        assert not (fields is None and exclude is None), (
            "Creating a ModelSerializer without either the 'fields' attribute "
            "or the 'exclude' attribute has been deprecated since 3.3.0, "
            "and is now disallowed. Add an explicit fields = '__all__' to the "
            "{serializer_class} serializer.".format(
                serializer_class=self.__class__.__name__
            ),
        )
        if fields[0] == '__all__':
            fields = [f.name for f in self.Meta.model._meta.get_fields() 
                      if not f.auto_created or f.name == 'id']

        if fields is not None:
            required_field_names = set(declared_fields)
            for cls in self.__class__.__bases__:
                required_field_names -= set(await getattr(cls, '_declared_fields', []))

            for field_name in required_field_names:
                assert field_name in fields, (
                    "The field '{field_name}' was declared on serializer "
                    "{serializer_class}, but has not been included in the "
                    "'fields' option.".format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )
            return fields

        # Use the default set of field names if `Meta.fields` is not specified.
        fields = await self.get_default_field_names(declared_fields, info)

        if exclude is not None:
            # If `Meta.exclude` is included, then remove those fields.
            for field_name in exclude:
                assert field_name not in self._declared_fields, (
                    "Cannot both declare the field '{field_name}' and include "
                    "it in the {serializer_class} 'exclude' option. Remove the "
                    "field or, if inherited from a parent serializer, disable "
                    "with `{field_name} = None`."
                    .format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )

                assert field_name in fields, (
                    "The field '{field_name}' was included on serializer "
                    "{serializer_class} in the 'exclude' option, but does "
                    "not match any model field.".format(
                        field_name=field_name,
                        serializer_class=self.__class__.__name__
                    )
                )
                fields.remove(field_name)

        return fields

    async def get_default_field_names(self, declared_fields, model_info):
        """
        Return the default list of field names that will be used if the
        `Meta.fields` option is not specified.
        """
        return (
            [self.url_field_name] +
            list(declared_fields) +
            list(model_info.fields) +
            list(model_info.forward_relations)
        )

    # Methods for constructing serializer fields...

    async def build_field(self, field_name, info, model_class, nested_depth):
        """
        Return a two tuple of (cls, kwargs) to build a serializer field with.
        """
        if field_name in info.fields_and_pk:
            model_field = info.fields_and_pk[field_name]
            return await self.build_standard_field(field_name, model_field)

        elif field_name in info.relations:
            relation_info = info.relations[field_name]
            if not nested_depth:
                return await self.build_relational_field(field_name, relation_info)
            else:
                return await self.build_nested_field(field_name, relation_info, nested_depth)

        elif hasattr(model_class, field_name):
            return await self.build_property_field(field_name, model_class)

        elif field_name == self.url_field_name:
            return await self.build_url_field(field_name, model_class)

        return await self.build_unknown_field(field_name, model_class)

    async def build_standard_field(self, field_name, model_field):
        """
        Create regular model fields.
        """
        field_mapping = ClassLookupDict(self.serializer_field_mapping)

        field_class = field_mapping[model_field]
        field_kwargs = get_field_kwargs(field_name, model_field)

        # Special case to handle when a OneToOneField is also the primary key
        if model_field.one_to_one and model_field.primary_key:
            field_class = self.serializer_related_field
            field_kwargs['queryset'] = model_field.related_model.objects

        if 'choices' in field_kwargs:
            # Fields with choices get coerced into `ChoiceField`
            # instead of using their regular typed field.
            field_class = self.serializer_choice_field
            # Some model fields may introduce kwargs that would not be valid
            # for the choice field. We need to strip these out.
            # Eg. models.DecimalField(max_digits=3, decimal_places=1, choices=DECIMAL_CHOICES)
            valid_kwargs = {
                'read_only', 'write_only',
                'required', 'default', 'initial', 'source',
                'label', 'help_text', 'style',
                'error_messages', 'validators', 'allow_null', 'allow_blank',
                'choices'
            }
            for key in list(field_kwargs):
                if key not in valid_kwargs:
                    field_kwargs.pop(key)

        if not issubclass(field_class, ModelField):
            # `model_field` is only valid for the fallback case of
            # `ModelField`, which is used when no other typed field
            # matched to the model field.
            field_kwargs.pop('model_field', None)

        if not issubclass(field_class, CharField) and not issubclass(field_class, ChoiceField):
            # `allow_blank` is only valid for textual fields.
            field_kwargs.pop('allow_blank', None)

        is_django_jsonfield = hasattr(models, 'JSONField') and isinstance(model_field, models.JSONField)
        if (postgres_fields and isinstance(model_field, postgres_fields.JSONField)) or is_django_jsonfield:
            # Populate the `encoder` argument of `JSONField` instances generated
            # for the model `JSONField`.
            field_kwargs['encoder'] = await getattr(model_field, 'encoder', None)
            if is_django_jsonfield:
                field_kwargs['decoder'] = await getattr(model_field, 'decoder', None)

        if postgres_fields and isinstance(model_field, postgres_fields.ArrayField):
            # Populate the `child` argument on `ListField` instances generated
            # for the PostgreSQL specific `ArrayField`.
            child_model_field = model_field.base_field
            child_field_class, child_field_kwargs = await self.build_standard_field(
                'child', child_model_field
            )
            field_kwargs['child'] = child_field_class(**child_field_kwargs)

        return field_class, field_kwargs

    async def build_relational_field(self, field_name, relation_info):
        """
        Create fields for forward and reverse relationships.
        """
        field_class = self.serializer_related_field
        field_kwargs = get_relation_kwargs(field_name, relation_info)

        to_field = field_kwargs.pop('to_field', None)
        if to_field and not relation_info.reverse and not relation_info.related_model._meta.get_field(to_field).primary_key:
            field_kwargs['slug_field'] = to_field
            field_class = self.serializer_related_to_field

        # `view_name` is only valid for hyperlinked relationships.
        if not issubclass(field_class, HyperlinkedRelatedField):
            field_kwargs.pop('view_name', None)
        return field_class, field_kwargs

    async def build_nested_field(self, field_name, relation_info, nested_depth):
        """
        Create nested fields for forward and reverse relationships.
        """
        class NestedSerializer(JSONAPIModelSerializer):
            class Meta:
                model = relation_info.related_model
                depth = nested_depth - 1
                fields = '__all__'

        field_class = NestedSerializer
        field_kwargs = get_nested_relation_kwargs(relation_info)

        return field_class, field_kwargs

    async def build_property_field(self, field_name, model_class):
        """
        Create a read only field for model methods and properties.
        """
        field_class = ReadOnlyField
        field_kwargs = {}

        return field_class, field_kwargs

    async def build_url_field(self, field_name, model_class):
        """
        Create a field representing the object's own URL.
        """
        field_class = self.serializer_url_field
        field_kwargs = get_url_kwargs(model_class)

        return field_class, field_kwargs

    async def build_unknown_field(self, field_name, model_class):
        """
        Raise an error on any unknown fields.
        """
        raise ImproperlyConfigured(
            'Field name `%s` is not valid for model `%s`.' %
            (field_name, model_class.__name__)
        )

    async def include_extra_kwargs(self, kwargs, extra_kwargs):
        """
        Include any 'extra_kwargs' that have been included for this field,
        possibly removing any incompatible existing keyword arguments.
        """
        if extra_kwargs.get('read_only', False):
            for attr in [
                'required', 'default', 'allow_blank', 'min_length',
                'max_length', 'min_value', 'max_value', 'validators', 'queryset'
            ]:
                kwargs.pop(attr, None)

        if extra_kwargs.get('default') and kwargs.get('required') is False:
            kwargs.pop('required')

        if extra_kwargs.get('read_only', kwargs.get('read_only', False)):
            extra_kwargs.pop('required', None)  # Read only fields should always omit the 'required' argument.

        kwargs.update(extra_kwargs)

        return kwargs

    # Methods for determining additional keyword arguments to apply...

    async def get_extra_kwargs(self):
        """
        Return a dictionary mapping field names to a dictionary of
        additional keyword arguments.
        """
        extra_kwargs = copy.deepcopy(await getattr(self.Meta, 'extra_kwargs', {}))

        read_only_fields = await getattr(self.Meta, 'read_only_fields', None)
        if read_only_fields is not None:
            if not isinstance(read_only_fields, (list, tuple)):
                raise TypeError(
                    'The `read_only_fields` option must be a list or tuple. '
                    'Got %s.' % type(read_only_fields).__name__
                )
            for field_name in read_only_fields:
                kwargs = extra_kwargs.get(field_name, {})
                kwargs['read_only'] = True
                extra_kwargs[field_name] = kwargs

        else:
            # Guard against the possible misspelling `readonly_fields` (used
            # by the Django admin and others).
            assert not hasattr(self.Meta, 'readonly_fields'), (
                'Serializer `%s.%s` has field `readonly_fields`; '
                'the correct spelling for the option is `read_only_fields`.' %
                (self.__class__.__module__, self.__class__.__name__)
            )

        return extra_kwargs
    
    async def get_uniqueness_extra_kwargs(self, field_names, declared_fields, extra_kwargs):
        """
        Return any additional field options that need to be included as a
        result of uniqueness constraints on the model. This is returned as
        a two-tuple of:

        ('dict of updated extra kwargs', 'mapping of hidden fields')
        """
        if await getattr(self.Meta, 'validators', None) is not None:
            return (extra_kwargs, {})

        model = await getattr(self.Meta, 'model')
        model_fields = await self._get_model_fields(
            field_names, declared_fields, extra_kwargs
        )
        model_fields = {**model_fields['attributes'], **model_fields['relationships']}

        # Determine if we need any additional `HiddenField` or extra keyword
        # arguments to deal with `unique_for` dates that are required to
        # be in the input data in order to validate it.
        unique_constraint_names = set()

        for model_field in model_fields.values():
            # Include each of the `unique_for_*` field names.
            unique_constraint_names |= {model_field.unique_for_date, model_field.unique_for_month,
                                        model_field.unique_for_year}

        unique_constraint_names -= {None}

        # Now we have all the field names that have uniqueness constraints
        # applied, we can add the extra 'required=...' or 'default=...'
        # arguments that are appropriate to these fields, or add a `HiddenField` for it.
        hidden_fields = {}
        uniqueness_extra_kwargs = {}

        for unique_constraint_name in unique_constraint_names:
            # Get the model field that is referred too.
            unique_constraint_field = model._meta.get_field(unique_constraint_name)

            if await getattr(unique_constraint_field, 'auto_now_add', None):
                default = CreateOnlyDefault(timezone.now)
            elif await getattr(unique_constraint_field, 'auto_now', None):
                default = timezone.now
            elif unique_constraint_field.has_default():
                default = unique_constraint_field.default
            else:
                default = empty

            if unique_constraint_name in model_fields:
                # The corresponding field is present in the serializer
                if default is empty:
                    uniqueness_extra_kwargs[unique_constraint_name] = {'required': True}
                else:
                    uniqueness_extra_kwargs[unique_constraint_name] = {'default': default}
            elif default is not empty:
                # The corresponding field is not present in the
                # serializer. We have a default to use for it, so
                # add in a hidden field that populates it.
                hidden_fields[unique_constraint_name] = HiddenField(default=default)

        # Update `extra_kwargs` with any new options.
        for key, value in uniqueness_extra_kwargs.items():
            if key in extra_kwargs:
                value.update(extra_kwargs[key])
            extra_kwargs[key] = value

        return extra_kwargs, hidden_fields

    async def _get_model_fields(self, field_names, declared_fields, extra_kwargs):
        """
        Returns all the model fields that are being mapped to by fields
        on the serializer class.
        Returned as a dict of 'model field name' -> 'model field'.
        Used internally by `get_uniqueness_field_options`.
        """
        model = await getattr(self.Meta, 'model')
        attributes, relationships = {}, {}
        for field_name in field_names:
            if field_name in declared_fields:
                field = declared_fields[field_name]
                source = field.source or field_name
            else:
                try:
                    source = extra_kwargs[field_name]['source']
                except KeyError:
                    source = field_name
            if '.' in source or source == '*':
                continue
            with contextlib.suppress(FieldDoesNotExist):
                field = model._meta.get_field(source)
                if isinstance(field, DjangoModelField):
                    if field.remote_field:
                        relationships[source] = field
                    else:
                        attributes[source] = field
        model_fields = {'attributes': attributes, 
                        'relationships': relationships}
        return model_fields

    async def get_validators(self):
        """
        Determine the set of validators to use when instantiating serializer.
        """
        # If the validators have been declared explicitly then use that.
        validators = await getattr(await getattr(self, 'Meta', None), 'validators', None)
        if validators is not None:
            return list(validators)

        # Otherwise use the default set of validators.
        return await self.get_unique_for_date_validators()

    async def get_unique_for_date_validators(self):
        """
        Determine a default set of validators for the following constraints:

        * unique_for_date
        * unique_for_month
        * unique_for_year
        """
        info = model_meta.get_field_info(self.Meta.model)
        default_manager = self.Meta.model._default_manager
        field_names = [field.source for field in 
                       [field async for field in self._writable_fields]]

        validators = {}

        for field_name, field in info.fields_and_pk.items():
            if field.unique_for_date and field_name in field_names:
                validator = UniqueForDateValidator(
                    queryset=default_manager,
                    field=field_name,
                    date_field=field.unique_for_date
                )
                validators[field_name] = validator

            if field.unique_for_month and field_name in field_names:
                validator = UniqueForMonthValidator(
                    queryset=default_manager,
                    field=field_name,
                    date_field=field.unique_for_month
                )
                validators[field_name] = validator

            if field.unique_for_year and field_name in field_names:
                validator = UniqueForYearValidator(
                    queryset=default_manager,
                    field=field_name,
                    date_field=field.unique_for_year
                )
                validators[field_name] = validator

        return validators

    async def to_representation(self, instance):
        """
        Object instance -> Dict of primitive datatypes.
        """
        url = await getattr(self, self.url_field_name, None)
        if url and not url.endswith(str(instance.id) + '/'):
            url = f"{url}{str(instance.id)}/"
        fields, included = await self.fields, {}
        relationships = {key: {'data': await getattr(instance, key)} for key in fields['relationships'].keys()}
        for key, val in relationships.items():
            val = val['data'] if type(val) == dict and 'data' in val else val
            validated_data, is_many = {}, hasattr(val, 'all')
            if is_many:
                objects = [obj async for obj in val.all()]
            else:
                objects = [val] if val else []
            data = await JSONAPIObjectIdSerializer(objects, many=True).data
            objects = data.get('data') if 'data' in data.keys() else data
            if objects and not is_many:
                objects, validated_data = objects[0], objects[0]
            elif objects:
                validated_data = objects
            elif not is_many:
                objects = None
            relationships[key]['data'] = validated_data
        for key in fields['relationships'].keys():
            links = {'self': f"{url}relationships/{key}/"}
            if relationships[key]['data']:
                links['related'] = f"{url}{key}/"
            relationships[key]['links'] = links
            if type(validated_data) == list:
                relationships[key]['links']['included'] = validated_data[0].get('type')
            else:
                relationships[key]['links']['included'] = validated_data
        is_included = not self._context.get('is_included_disabled', False)
        if is_included:
            await self._get_included(instance, relationships, included, not is_included)
        data = {'data': {
            'type': await get_type_from_model(instance.__class__),
            'id': await getattr(instance, 'id'),
            'attributes': {
                key: await getattr(instance, key) 
                for key in fields['attributes'].keys()
            }, 
            'relationships': relationships,
            'links': {'self': url}
        }, 'included': list(included.values())}
        if not data.get('relationships') and 'relationships' in data:
            del data['relationships']
        return data

    async def to_internal_value(self, data):
        try:
            fields = await self.fields
        except TypeError:
            fields = self.fields
        meta = await getattr(self, 'Meta', None)
        read_only_fields = await getattr(meta, 'read_only_fields', [])
        ret = {}
        errors = {}
        data = data.get('data') if 'data' in data.keys() else data
        if data.get('relationships'):
            for name, field in data['relationships'].items():
                error = ['please specify a valid dictionary with id and type keys.']
                try:
                    if fields['relationships'][name].__class__ == self.serializer_related_field:
                        data['relationships'][name].keys()
                        data['relationships'][name] = int(data['relationships'][name]['data']['id'])
                except (AttributeError, KeyError, TypeError) as exc:
                    errors[name] = error
        for name, field in list(fields.items()):
            if type(field) == dict:
                for name, field in list(fields.pop(name).items()):
                    if hasattr(field, 'child_relation'):
                        continue
                    fields[name] = field
        for name, field in list(data.items()):
            if type(field) == dict:
                for name, field in list(data.pop(name).items()):
                    if type(field) == dict and type(field.get('data')) == list:
                        continue
                    elif name == 'self':
                        continue
                    else:
                        data[name] = field
        for name, field in fields.items():
            if field.read_only or name in read_only_fields:
                continue
            value = data.get(name)
            value = value.pop('data', value) if type(value) == dict and 'data' in value.keys() else value
            value = [value]
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

    def create(self, validated_data):
        raise_errors_on_nested_writes('create', self, validated_data)

        ModelClass = self.Meta.model

        # Remove many-to-many relationships from validated_data.
        # They are not valid arguments to the default `.create()` method,
        # as they require that the instance has already been saved.
        info = model_meta.get_field_info(ModelClass)
        many_to_many = {}
        for field_name, relation_info in info.relations.items():
            if relation_info.to_many and (field_name in validated_data):
                many_to_many[field_name] = validated_data.pop(field_name)

        try:
            instance = ModelClass._default_manager.create(**validated_data)
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

        # Save many-to-many relationships after the instance is created.
        if many_to_many:
            for field_name, value in many_to_many.items():
                field = getattr(instance, field_name)
                field.set(value)

        return instance

    def update(self, instance, validated_data):
        raise_errors_on_nested_writes('update', self, validated_data)
        info = model_meta.get_field_info(instance)

        # Simply set each attribute on the instance, and then save it.
        # Note that unlike `.create()` we don't need to treat many-to-many
        # relationships as being a special case. During updates we already
        # have an instance pk for the relationships to be associated with.
        m2m_fields = []
        for attr, value in validated_data.items():
            if attr in info.relations and info.relations[attr].to_many:
                m2m_fields.append((attr, value))
            else:
                setattr(instance, attr, value)

        instance.save()

        # Note that many-to-many fields are set after updating instance.
        # Setting m2m fields triggers signals which could potentially change
        # updated instance and we do not want it to collide with .update()
        for attr, value in m2m_fields:
            field = getattr(instance, attr)
            field.set(value)

        return instance

    # Determine the fields to apply...
