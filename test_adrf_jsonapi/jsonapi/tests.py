from re import findall
from django.test import TestCase
from django.test.client import RequestFactory
from asgiref.sync import sync_to_async

from jsonapi.model_serializers import JSONAPIModelSerializer
from adrf_jsonapi.models import Test, TestIncluded, TestIncludedRelation, TestDirectCon
from jsonapi.serializer_model_async import ModelSerializerAsync
from jsonapi.helpers import get_type_from_model

import asyncio

# TODO: test uniquness
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
        # Set asyncio loop on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
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

    async def test_retrieve(self):
        serializer = self.get_serializer()
        model_type = serializer.Meta.model_type
        fields = self.test_fields
        obj = await self.main_query.afirst()
        await obj.many_to_many.aadd(await TestIncluded.objects.afirst())
        obj.foreign_key = await TestIncluded.objects.afirst()
        await obj.asave()
        data = await serializer(obj).data
        # Test "data" key
        data_included, data = data.get('included'), data.get('data')
        self.assertIsInstance(data, dict)
        self.assertEqual(data['type'], model_type)
        # Test "data.attributes" key
        self.assertIsInstance(data.get('attributes'), dict)
        [self.assertIn(field, data.get('attributes').keys()) for field in fields]
        # Test "data.relationships" foreign key
        self.assertIsInstance(data.get('relationships'), dict)
        [self.assertIn(field, data.get('relationships').keys()) 
         for field in self.test_relationships.keys()]
        [self.assertIn('id', data.get('relationships').get(field).get('data').keys())
         for field in self.test_relationships.keys()]
        [self.assertIsInstance(data.get('relationships').get(field).get('data').get('id'), int)
         for field in self.test_relationships.keys()]
        [self.assertIsInstance(data.get('relationships').get(field).get('data').get('type'), str)
         for field in self.test_relationships.keys()]
        # Test "data.relationships" many-to-many key
        self.assertIn('many_to_many', data['relationships'].keys())
        self.assertIsInstance(data['relationships']['many_to_many'], dict)
        self.assertIn('data', data['relationships']['many_to_many'].keys())
        self.assertIsInstance(data['relationships']['many_to_many']['data'], list)
        self.assertEqual(len(data['relationships']['many_to_many']['data']), 1)
        self.assertIn('type', data['relationships']['many_to_many']['data'][0])
        self.assertEqual(data['relationships']['many_to_many']['data'][0].get('type'), 
                         await get_type_from_model(obj.foreign_key.__class__))
        self.assertEqual(data['relationships']['many_to_many']['data'][0].get('id'), 
                         obj.foreign_key.id)
        # Test "included" key
        del data_included[0]['links']
        self.assertEqual(self.test_relationships['foreign_key'], data_included[0])
        [self.assertIn(self.test_relationships[rel_name], data_included) for 
         rel_name in self.test_relationships]

    async def test_list(self):
        list_serializer = self.get_serializer()
        model_type = list_serializer.Meta.model_type
        fields = self.test_fields
        objs = [obj async for obj in self.main_query]
        related = await TestIncluded.objects.afirst()
        for obj in objs:
            obj.foreign_key = related
            await obj.many_to_many.aadd(related)
            await obj.asave()
        data = await list_serializer(
            self.main_query, many=True
        ).data
        data_included, data = data.get('included'), data.get('data')
        del data_included[0]['links']
        # Test "data" key
        self.assertIsInstance(data, list)
        [self.assertEqual(obj.get('type'), model_type) for obj in data]
        # Test "data.attributes" key
        [self.assertIsInstance(obj.get('attributes'), dict) for obj in data]
        [self.assertIn(field, obj.get('attributes').keys())
         for obj in data for field in fields]
        # Test "data.relationships" foreign key
        [self.assertIsInstance(obj.get('relationships'), dict) for obj in data]
        [self.assertIn(field, obj.get('relationships').keys())
         for obj in data for field in self.test_relationships.keys()]
        [self.assertIn('id', obj.get('relationships').get(field).get('data').keys())
         for obj in data for field in self.test_relationships.keys()]
        [self.assertIsInstance(obj.get('relationships').get(field).get('data').get('id'), int)
         for obj in data for field in self.test_relationships.keys()]
        [self.assertIsInstance(obj.get('relationships').get(field).get('data').get('type'), str)
         for obj in data for field in self.test_relationships.keys()]
        # Test "data.relationships" many-to-many key
        [self.assertIn('many_to_many', obj['relationships'].keys()) and 
         self.assertIn('data', obj['relationships']['many_to_many'].keys()) and
         self.assertIn('type', obj['relationships']['many_to_many']['data'][0]) 
         for obj in data]
        [self.assertIsInstance(obj['relationships']['many_to_many'], dict) and 
         self.assertIsInstance(obj['relationships']['many_to_many']['data'], list) 
         for obj in data]
        [self.assertEqual(len(obj['relationships']['many_to_many']['data']), 1)
         and self.assertEqual(obj['relationships']['many_to_many']['data'][0].get('type'), 
                              await get_type_from_model(obj.foreign_key.__class__)) 
         and self.assertEqual(obj['relationships']['many_to_many']['data'][0].get('id'), 
                              obj.foreign_key.id) for obj in data]
        # Test "included" key
        self.assertEqual(data[0]['relationships']['many_to_many']['data'][0]['id'], data_included[0]['id'])
        self.assertEqual(data[0]['relationships']['many_to_many']['data'][0]['type'], data_included[0]['type'])
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
        self.assertTrue(await serializer.is_valid()), self.assertFalse(await serializer.errors)
        validated_data = await serializer.validated_data
        self.assertTrue(validated_data), self.assertIsInstance(validated_data, dict)
        [self.assertIn(x, data) for x in validated_data]

    async def test_validation_fail(self):
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

    async def test_create(self):
        obj = await self.main_query.afirst()
        
        class Serializer(ModelSerializerAsync):
            class Meta:
                fields = '__all__'
                model = self.main_model
        
        data = await Serializer(obj).data
        data['text'], data['foreign_key'] = 'The new object text', await TestIncluded.objects.afirst()
        del data['id']
        serializer = Serializer(data=data)
        await serializer.is_valid()
        obj = await serializer.create(await serializer.data)
        self.assertIsInstance(
            obj.foreign_key, 
            self.main_model.foreign_key.field.related_model
        )
        self.assertIsInstance(await self.main_model.objects.aget(text=data['text']), self.main_model)
        del data['foreign_key']
        del data['many_to_many']
        [self.assertEqual(getattr(obj, key), data[key]) for key in data.keys()]
        
    async def test_create_list(self):
        objs = [obj async for obj in self.main_query.all()]
        
        class Serializer(ModelSerializerAsync):
            class Meta:
                fields = '__all__'
                model = self.main_model
        serializer = Serializer(objs, many=True)
        data = await serializer.data
        data_new = []
        for obj in data:
            obj['text'] = 'The new object text'
            obj['foreign_key'] = await TestIncluded.objects.afirst()
            del obj['id']
            data_new.append(dict(obj))
        objs = await serializer.create(data_new)
        [[self.assertEqual(getattr(obj, key), data_new[0][key]) for key in data[0].keys() 
          if key not in ('id', 'many_to_many')] for obj in objs]
    
    async def test_acreate(self):
        obj = await self.main_query.afirst()
        
        class Serializer(ModelSerializerAsync):
            class Meta:
                fields = '__all__'
                model = TestDirectCon
                
        data = dict(await Serializer(obj).data)
        data['text'] = 'The new object text'
        del data['id']
        obj = await Serializer(data=data).acreate(data)
        [self.assertEqual(getattr(obj, key), data[key]) for key in data.keys()]
        self.assertIsInstance(await TestDirectCon.objects.aget(text=data['text']), TestDirectCon)

    async def test_acreate_list(self):
        obj = [x async for x in self.main_query.all()]
        
        class Serializer(ModelSerializerAsync):
            class Meta:
                fields = '__all__'
                model = TestDirectCon
                
        data = await Serializer(obj, many=True).data
        objs = await Serializer(data=data).acreate(data)
        
        [[self.assertEqual(getattr(obj, key), data[0][key]) for key in data[0].keys() if key != 'id'] for obj in objs]
        #self.assertIsInstance(await TestDirectCon.objects.aget(text=data['text']), TestDirectCon)

    async def test_update(self):
        obj = await self.main_query.afirst()
        
        class SerializerNested(ModelSerializerAsync):
            class Meta:
                fields = '__all__'
                model = TestIncluded
        
        class Serializer(ModelSerializerAsync):
            foreign_key = SerializerNested()
            class Meta:
                fields = '__all__'
                model = self.main_model
        
        data = await Serializer(obj).data
        self.assertEqual(data['foreign_key']['id'], 1)
        data['foreign_key'] = None
        data['text'] = 'The new object text'
        serializer = Serializer(data=data)
        await serializer.is_valid()
        await serializer.update(obj, data)
        try:
            obj_updated = await self.main_model.objects.aget(
                text__startswith=data['text']
            )
        except obj.__class__.DoesNotExist:
            raise AssertionError('Not saved.')
        self.assertEqual(str(obj), data['text'])
        self.assertEqual(str(obj_updated), data['text'])
        self.assertIsNone(obj.foreign_key)
        self.assertIsNone(obj_updated.foreign_key)
        del data['foreign_key']
        del data['many_to_many']
        [self.assertEqual(getattr(obj, key), data[key]) for key in data.keys()]
        [self.assertEqual(getattr(obj_updated, key), data[key]) for key in data.keys()]
