from django.test import TestCase
from adrf_jsonapi.models import Test, TestIncluded, TestIncludedRelation
from jsonapi.model_serializers import JSONAPIModelSerializer


class TestModelSerializer(TestCase):
    @classmethod
    def setUpTestData(cls):
        test_data = cls.get_data_map(Test)
        [Test.objects.create(**test_data) for _ in range(10)]
        cls.test_included_relation_query = Test.objects.all()
    
    @staticmethod
    def get_test_serializer():
        class TestSerializer(JSONAPIModelSerializer):
            class Meta:
                model, model_type = Test, 'test'
                fields = ['__all__']
        return TestSerializer
    
    @classmethod
    def get_data_map(cls, model):
        fields, forward_relations = {}, {}
        for field in model._meta.fields:
            data = fields if not field.remote_field else forward_relations
            data[field.name] = field
        cls.test_fields = fields = {key: fields[key] for key in list(filter(
            lambda x: x != 'id', fields.keys()
        ))}
        data = {key: fields[key].default for key in fields}
        data = {key: val() if type(val) == type else val for key, val in data.items()}
        return data

    async def test_list(self):
        list_serializer = self.get_test_serializer()
        model_type = list_serializer.Meta.model_type
        fields = self.test_fields
        data = await list_serializer(
            self.test_included_relation_query, many=True
        ).data
        data = data.get('data')
        self.assertIsInstance(data, list)
        [self.assertEqual(obj.get('type'), model_type) for obj in data]
        [self.assertIsInstance(obj.get('attributes'), dict) for obj in data]
        [self.assertIn(field, obj.get('attributes').keys()) 
         for obj in data for field in fields]
        
    async def test_get(self):
        list_serializer = self.get_test_serializer()
        model_type = list_serializer.Meta.model_type
        fields = self.test_fields
        data = await list_serializer(
            await self.test_included_relation_query.afirst()
        ).data
        data = data.get('data')
        self.assertIsInstance(data, dict)
        self.assertEqual(data['type'], model_type)
        self.assertIsInstance(data.get('attributes'), dict)
        [self.assertIn(field, data.get('attributes').keys()) for field in fields]
