from re import findall
from django.test import TestCase
from django.test.client import RequestFactory

from jsonapi.model_serializers import JSONAPIModelSerializer
from adrf_jsonapi.models import Test, TestIncluded, TestIncludedRelation


class TestModelSerializer(TestCase):
    main_model = Test
    main_query = main_model.objects.all()
    
    @classmethod
    def setUpTestData(cls):
        # Generate fixtures
        test_included_relation_data, cls.test_included_relation_relationships = cls.get_obj_map(TestIncludedRelation)
        test_included_data, cls.test_included_relationships = cls.get_obj_map(TestIncluded)
        test_data, cls.test_relationships = cls.get_obj_map(cls.main_model)
        # Create objects
        create_objects = lambda model, data: [
            model.objects.create(**{
                k: v if not k.endswith('_id') else _ + 1
                for k, v in data.items()
            }) for _ in range(10)
        ]
        create_objects(TestIncludedRelation, test_included_relation_data)
        create_objects(TestIncluded, test_included_data)
        create_objects(Test, test_data)
    
    @classmethod
    def get_serializer(cls):
        class Serializer(JSONAPIModelSerializer):
            class Meta:
                model, model_type = cls.main_model, 'test'
                fields = ['__all__']
        return Serializer
    
    @classmethod
    def get_obj_map(cls, model, has_included=True):
        fields, forward_relations = {}, {}
        for field in model._meta.fields:
            data = fields if not field.remote_field else forward_relations
            data[field.name] = field
        fields = {key: fields[key] for key in list(filter(
            lambda x: x != 'id', fields.keys()
        ))}
        if has_included:
            cls.test_fields = fields
        data = {key: fields[key].default for key in fields}
        data = {key: val() if type(val) == type else val for key, val in data.items()}
        if has_included:
            get_model_type_map = lambda field: {
                'type': '-'.join(
                    findall('[A-Z][^A-Z]*', field.related_model.__name__)
                ).lower(), 'id': 1
            }
            for key, field in tuple(forward_relations.items()):
                data[key + '_id'] = 1
                forward_relations[key] = get_model_type_map(field)
                rel_obj_map, rels = cls.get_obj_map(field.related_model, False)
                forward_relations[key].update({'attributes': rel_obj_map})
                forward_relations[key].update({'relationships': {}})
                for key_rel, field in tuple(rels.items()):
                    forward_relations[key]['relationships'][key_rel] = {
                        'data': get_model_type_map(field)
                    }
        return data, forward_relations

    # TODO: test manytomany and links
    async def test_retrieve(self):
        serializer = self.get_serializer()
        model_type = serializer.Meta.model_type
        fields = self.test_fields
        obj = await self.main_query.afirst()
        data = await serializer(obj).data
        # Test "data" key
        data_included, data = data.get('included'), data.get('data')
        self.assertIsInstance(data, dict)
        self.assertEqual(data['type'], model_type)
        # Test "data.attributes" key
        self.assertIsInstance(data.get('attributes'), dict)
        [self.assertIn(field, data.get('attributes').keys()) for field in fields]
        # Test "data.relationships" key
        self.assertIsInstance(data.get('relationships'), dict)
        [self.assertIn(field, data.get('relationships').keys()) 
         for field in self.test_relationships.keys()]
        [self.assertIn('id', data.get('relationships').get(field).get('data').keys())
         for field in self.test_relationships.keys()]
        [self.assertIsInstance(data.get('relationships').get(field).get('data').get('id'), int)
         for field in self.test_relationships.keys()]
        [self.assertIsInstance(data.get('relationships').get(field).get('data').get('type'), str)
         for field in self.test_relationships.keys()]
        # Test "included" key
        self.assertEqual(self.test_relationships['foreign_key'], data_included[0])
        [self.assertIn(self.test_relationships[rel_name], data_included) for 
         rel_name in self.test_relationships]

    async def test_list(self):
        list_serializer = self.get_serializer()
        model_type = list_serializer.Meta.model_type
        fields = self.test_fields
        data = await list_serializer(
            self.main_query, many=True
        ).data
        data_included, data = data.get('included'), data.get('data')
        # Test "data" key
        self.assertIsInstance(data, list)
        [self.assertEqual(obj.get('type'), model_type) for obj in data]
        # Test "data.attributes" key
        [self.assertIsInstance(obj.get('attributes'), dict) for obj in data]
        [self.assertIn(field, obj.get('attributes').keys())
         for obj in data for field in fields]
        # Test "data.relationships" key
        [self.assertIsInstance(obj.get('relationships'), dict) for obj in data]
        [self.assertIn(field, obj.get('relationships').keys())
         for obj in data for field in self.test_relationships.keys()]
        [self.assertIn('id', obj.get('relationships').get(field).get('data').keys())
         for obj in data for field in self.test_relationships.keys()]
        [self.assertIsInstance(obj.get('relationships').get(field).get('data').get('id'), int)
         for obj in data for field in self.test_relationships.keys()]
        [self.assertIsInstance(obj.get('relationships').get(field).get('data').get('type'), str)
         for obj in data for field in self.test_relationships.keys()]
        # Test "included" key
        self.assertEqual(self.test_relationships['foreign_key'], data_included[0])
        [self.assertIn(self.test_relationships[rel_name], data_included) for 
         rel_name in self.test_relationships]
    
    async def test_validation(self):
        serializer = self.get_serializer()
        obj = await self.main_query.afirst()
        data = await serializer(obj).data
        data = data['data']
        rel_type = data['relationships']['foreign_key']['data']['type']
        rel_id = data['relationships']['foreign_key']['data']['id']
        # Test validation
        data['attributes']['text'], data['attributes']['array'] = 'test', [1]
        serializer = serializer(data=data, context={
            'request': RequestFactory().get('/' + rel_type + '/' + str(rel_id) + '/')
        })
        self.assertTrue(await serializer.is_valid())
        validated_data = await serializer.validated_data
        self.assertTrue(validated_data), self.assertIsInstance(validated_data, dict)
        [self.assertIn(x, data) for x in validated_data]

    async def test_validation_fail(self):
        # Test validation fail
        serializer = self.get_serializer()
        obj = await self.main_query.afirst()
        data = await serializer(obj).data
        data = data['data']
        rel_type = data['relationships']['foreign_key']['data']['type']
        rel_id = data['relationships']['foreign_key']['data']['id']
        serializer = serializer(data=data, context={
            'request': RequestFactory().get('/' + rel_type + '/' + str(rel_id) + '/')
        })
        self.assertFalse(await serializer.is_valid())
        errors = await serializer.errors
        self.assertIsInstance(errors, dict), self.assertIn('errors', errors), 
        self.assertIsInstance(errors['errors'], list)
        [self.assertIn('code', x) and self.assertIn('source', x) for x in errors['errors']]
        [self.assertIn('The JSON field ', x['detail']) for x in errors['errors']]
        [self.assertIn('http', x['source']['pointer']) for x in errors['errors']]
