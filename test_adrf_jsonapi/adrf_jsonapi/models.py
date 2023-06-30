from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.utils.translation import gettext_lazy as _


class TestIncludedRelation(models.Model):
    text_included_relation = models.CharField(max_length=128)
    int_included_relation = models.IntegerField()
    bool_included_relation = models.BooleanField()
    choice_int_included_relation = models.IntegerField(choices=((1, 'One'), (2, 'Two')))
    choice_str_included_relation = models.CharField(max_length=9, choices=(
        ('UK', 'United Kingdom'), ('US', 'United States')
    ))
    array_included_relation = ArrayField(models.IntegerField(), size=2, default=list)
    
    class Meta:
        verbose_name = _('Test Included Relation')
        verbose_name_plural = _('Test Included Relations')
    
    def __str__(self):
        return self.text_included_relation


class TestIncluded(models.Model):
    text_included = models.CharField(max_length=128)
    int_included = models.IntegerField()
    bool_included = models.BooleanField()
    choice_int_included = models.IntegerField(choices=((1, 'One'), (2, 'Two')))
    choice_str_included = models.CharField(max_length=9, choices=(
        ('UK', 'United Kingdom'), ('US', 'United States')
    ))
    array_included = ArrayField(models.IntegerField(), size=2, default=list)
    foreign_key_included = models.ForeignKey(TestIncludedRelation, on_delete=models.SET_NULL, null=True, blank=True)
    many_to_many_included = models.ManyToManyField(TestIncludedRelation, blank=True, related_name='test_included_relation_many')
    
    class Meta:
        verbose_name = _('Test Included')
        verbose_name_plural = _('Test Included')
    
    def __str__(self):
        return self.text_included

# TODO: create the MultipleChoiceField from the module or the ArrayField
class Test(models.Model):
    text = models.CharField(max_length=128)
    int = models.IntegerField()
    bool = models.BooleanField()
    choice_int = models.IntegerField(choices=((1, 'One'), (2, 'Two')))
    choice_str = models.CharField(max_length=9, choices=(
        ('UK', 'United Kingdom'), ('US', 'United States')
    ))
    array = ArrayField(models.IntegerField(), size=2, default=list)
    foreign_key = models.ForeignKey(TestIncluded, on_delete=models.SET_NULL, null=True, blank=True)
    many_to_many = models.ManyToManyField(TestIncluded, blank=True, related_name='test_included_many')
    class Meta:
        verbose_name = _('Test')
        verbose_name_plural = _('Tests')
    
    def __str__(self):
        return self.text
