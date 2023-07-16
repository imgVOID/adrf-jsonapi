import random
import string
from django.test import TestCase
from adrf_jsonapi.models import Test, TestIncluded, TestIncludedRelation
from jsonapi.model_serializers import JSONAPIModelSerializer

class TestModelSerializer(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.test_included_relation_fields = tuple(filter(
            lambda x: not x.startswith('_') and x != 'id', list([
                TestIncludedRelation.objects.create(
                    **cls.test_included_relation_data()
                ) for _ in range(10)
            ][0].__dict__.keys())
        ))
        cls.test_included_relation_query = TestIncludedRelation.objects.all()
    
    @staticmethod
    def get_test_included_relation_serializer():
        class TestIncludedSerializer(JSONAPIModelSerializer):
            class Meta:
                model, model_type = TestIncludedRelation, 'test-included-relation'
                fields = ['__all__']
        
        return TestIncludedSerializer
    
    @staticmethod
    def test_included_relation_data():
        return {
            'text_included_relation': ''.join(
                random.choice(string.ascii_lowercase + string.digits) for _ in range(
                    TestIncludedRelation.text_included_relation.field.max_length
                )
            ),
            'int_included_relation': random.choice(range(256)),
            'bool_included_relation': random.choice((True, False)),
            'choice_int_included_relation': random.choice([
                choice[0] for choice in 
                TestIncludedRelation.choice_int_included_relation.field.choices
            ]),
            'choice_str_included_relation': random.choice([
                choice[0] for choice in 
                TestIncludedRelation.choice_str_included_relation.field.choices
            ]),
            'array_included_relation': [
                random.choice(range(0, 256)) for _ in 
                range(TestIncludedRelation.array_included_relation.field.size)
            ]
        }

    async def test_list(self):
        list_serializer = self.get_test_included_relation_serializer()
        model_type = list_serializer.Meta.model_type
        fields = self.test_included_relation_fields
        list_serializer = list_serializer(self.test_included_relation_query, many=True)
        data = await list_serializer.data
        data = data.get('data')
        assert_equal = (
            *((obj.get('type'), model_type) for obj in data),
        )
        assert_type = (
            (data, list),
            *((obj.get('attributes'), dict) for obj in data),
        )
        #assert_in = (
        #    (obj.get(field), ) for obj in data for field in fields
        #)
        assert_dict_contains_subset = (
            *(self.assertIn(field, obj.get('attributes').keys()) for obj in data for field in fields),
        )
        for assertion in assert_equal:
            self.assertEqual(*assertion)
        for assertion in assert_type:
            self.assertIsInstance(*assertion)
        
    async def test_get(self):
        list_serializer = self.get_test_included_relation_serializer()
        model_type = list_serializer.Meta.model_type
        list_serializer = list_serializer(await self.test_included_relation_query.afirst())
        data = await list_serializer.data
        data = data.get('data')
        assert_equal = (
            (type(data), dict),
            (data['type'], model_type),
            (type(data.get('attributes')), dict)
        )
        for assertion in assert_equal:
            self.assertEqual(*assertion)
