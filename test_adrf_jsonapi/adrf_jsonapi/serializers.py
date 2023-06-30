from rest_framework import serializers
#from django.core.validators import MaxValueValidator, MaxLengthValidator
from jsonapi.serializers import JSONAPISerializer
from adrf_jsonapi.models import Test, TestIncluded, TestIncludedRelation

class TestIncludedRelationSerializer(JSONAPISerializer):
    
    class Attributes(JSONAPISerializer.Attributes):
        text_included_relation = serializers.CharField(max_length=128)
        int_included_relation = serializers.IntegerField()
        bool_included_relation = serializers.BooleanField()
        choice_int_included_relation = serializers.ChoiceField(((1, 'One'), (2, 'Two')))
        choice_str_included_relation = serializers.ChoiceField((
            ('UK', 'United Kingdom'), ('US', 'United States')
        ))
        array_included_relation = serializers.ListField(child=serializers.IntegerField(), max_length=2)
    
    class Meta:
        model_type = 'test-included-relation'
        #model = TestIncludedRelation
        #validators = {
        #    'id': MaxValueValidator(0),
        #    'attributes.text': MaxLengthValidator(0),
        #    'relationships.country': MaxLengthValidator(0)
        #    }


class TestIncludedSerializer(JSONAPISerializer):
    
    class Attributes(JSONAPISerializer.Attributes):
        text_included = serializers.CharField(max_length=128)
        int_included = serializers.IntegerField()
        bool_included = serializers.BooleanField()
        choice_int_included = serializers.ChoiceField(((1, 'One'), (2, 'Two')))
        choice_str_included = serializers.ChoiceField((
            ('UK', 'United Kingdom'), ('US', 'United States')
        ))
        array_included = serializers.ListField(child=serializers.IntegerField(), max_length=2)
    
    class Relationships(JSONAPISerializer.Relationships):
        foreign_key_included = JSONAPISerializer.ObjectId(required=False)
        many_to_many_included = serializers.ListField(
            required=False, child=JSONAPISerializer.ObjectId()
        )
    
    class Meta:
        model, model_type = TestIncluded, 'test-included'
        #
        #validators = {
        #    'id': MaxValueValidator(0),
        #    'attributes.text': MaxLengthValidator(0),
        #    'relationships.country': MaxLengthValidator(0)
        #    }


class TestSerializer(JSONAPISerializer):
    
    class Attributes(JSONAPISerializer.Attributes):
        text = serializers.CharField(max_length=128)
        int = serializers.IntegerField()
        bool = serializers.BooleanField()
        choice_int = serializers.ChoiceField(((1, 'One'), (2, 'Two')))
        choice_str = serializers.ChoiceField((
            ('UK', 'United Kingdom'), ('US', 'United States')
        ))
        array = serializers.ListField(child=serializers.IntegerField(), max_length=2)
    
    class Relationships(JSONAPISerializer.Relationships):
        foreign_key = JSONAPISerializer.ObjectId(required=False)
        many_to_many = serializers.ListField(
            required=False, child=JSONAPISerializer.ObjectId()
        )
    
    class Meta:
        model, model_type = Test, 'test'
        #validators = {
        #    'id': MaxValueValidator(0),
        #    'attributes.text': MaxLengthValidator(0),
        #    'relationships.many_to_many': MaxLengthValidator(0)
        #    }