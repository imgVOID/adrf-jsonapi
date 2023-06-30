# Generated by Django 4.2.2 on 2023-06-23 16:47

import django.contrib.postgres.fields
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='TestIncludedRelation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text_included_relation', models.CharField(max_length=128)),
                ('int_included_relation', models.IntegerField()),
                ('bool_included_relation', models.BooleanField()),
                ('choice_int_included_relation', models.IntegerField(choices=[(1, 'One'), (2, 'Two')])),
                ('choice_str_included_relation', models.CharField(choices=[('UK', 'United Kingdom'), ('US', 'United States')], max_length=9)),
                ('array_included_relation', django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), size=2)),
            ],
            options={
                'verbose_name': 'Test Included Relation',
                'verbose_name_plural': 'Test Included Relations',
            },
        ),
        migrations.CreateModel(
            name='TestIncluded',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text_included', models.CharField(max_length=128)),
                ('int_included', models.IntegerField()),
                ('bool_included', models.BooleanField()),
                ('choice_int_included', models.IntegerField(choices=[(1, 'One'), (2, 'Two')])),
                ('choice_str_included', models.CharField(choices=[('UK', 'United Kingdom'), ('US', 'United States')], max_length=9)),
                ('array_included', django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), size=2)),
                ('foreign_key_included', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='adrf_jsonapi.testincludedrelation')),
                ('many_to_many_included', models.ManyToManyField(blank=True, related_name='test_included_relation_many', to='adrf_jsonapi.testincludedrelation')),
            ],
            options={
                'verbose_name': 'Test Included',
                'verbose_name_plural': 'Test Included',
            },
        ),
        migrations.CreateModel(
            name='Test',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.CharField(max_length=128)),
                ('int', models.IntegerField()),
                ('bool', models.BooleanField()),
                ('choice_int', models.IntegerField(choices=[(1, 'One'), (2, 'Two')])),
                ('choice_str', models.CharField(choices=[('UK', 'United Kingdom'), ('US', 'United States')], max_length=9)),
                ('array', django.contrib.postgres.fields.ArrayField(base_field=models.IntegerField(), size=2)),
                ('foreign_key', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='adrf_jsonapi.testincluded')),
                ('many_to_many', models.ManyToManyField(blank=True, related_name='test_included_many', to='adrf_jsonapi.testincluded')),
            ],
            options={
                'verbose_name': 'Test',
                'verbose_name_plural': 'Tests',
            },
        ),
    ]
