# Vintage-aware HSSITCConcordance: key on (product_code, hs_revision).
# The table is a reloadable lookup (repopulated by load_hs_sitc_concordance),
# so the cleanest schema change is to drop and recreate it. Existing rows are
# discarded — reload all four revisions afterwards.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loadFiles', '0002_hssitcconcordance'),
    ]

    operations = [
        migrations.DeleteModel(
            name='HSSITCConcordance',
        ),
        migrations.CreateModel(
            name='HSSITCConcordance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('product_code', models.CharField(max_length=10)),
                ('hs_revision', models.CharField(max_length=4)),
                ('sitc_code', models.CharField(max_length=10)),
                ('sitc_section', models.CharField(max_length=1)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(
                        fields=['product_code', 'hs_revision'],
                        name='unique_hs6_per_revision',
                    ),
                ],
                'indexes': [
                    models.Index(fields=['product_code', 'hs_revision'], name='loadFiles_h_product_8d08e7_idx'),
                    models.Index(fields=['sitc_section'], name='loadFiles_h_sitc_se_8657a5_idx'),
                ],
            },
        ),
    ]
