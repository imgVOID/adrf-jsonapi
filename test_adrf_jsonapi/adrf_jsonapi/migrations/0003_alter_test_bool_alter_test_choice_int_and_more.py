# Generated by Django 4.2.2 on 2023-07-16 18:06

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('adrf_jsonapi', '0002_alter_test_array_alter_testincluded_array_included_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='test',
            name='bool',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='test',
            name='choice_int',
            field=models.IntegerField(choices=[(1, 'One'), (2, 'Two')], default=1),
        ),
        migrations.AlterField(
            model_name='test',
            name='choice_str',
            field=models.CharField(choices=[('UK', 'United Kingdom'), ('US', 'United States')], default='UK', max_length=9),
        ),
        migrations.AlterField(
            model_name='test',
            name='int',
            field=models.IntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='test',
            name='text',
            field=models.CharField(default='', max_length=128),
        ),
        migrations.AlterField(
            model_name='testincluded',
            name='bool_included',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='testincluded',
            name='choice_int_included',
            field=models.IntegerField(choices=[(1, 'One'), (2, 'Two')], default=1),
        ),
        migrations.AlterField(
            model_name='testincluded',
            name='choice_str_included',
            field=models.CharField(choices=[('UK', 'United Kingdom'), ('US', 'United States')], default='UK', max_length=9),
        ),
        migrations.AlterField(
            model_name='testincluded',
            name='int_included',
            field=models.IntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='testincluded',
            name='text_included',
            field=models.CharField(default='', max_length=128),
        ),
        migrations.AlterField(
            model_name='testincludedrelation',
            name='bool_included_relation',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='testincludedrelation',
            name='choice_int_included_relation',
            field=models.IntegerField(choices=[(1, 'One'), (2, 'Two')], default=1),
        ),
        migrations.AlterField(
            model_name='testincludedrelation',
            name='choice_str_included_relation',
            field=models.CharField(choices=[('UK', 'United Kingdom'), ('US', 'United States')], default='UK', max_length=9),
        ),
        migrations.AlterField(
            model_name='testincludedrelation',
            name='int_included_relation',
            field=models.IntegerField(default=1),
        ),
        migrations.AlterField(
            model_name='testincludedrelation',
            name='text_included_relation',
            field=models.CharField(default='', max_length=128),
        ),
    ]
