from django.db import models


class CountryReference(models.Model):
    comtrade_code = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    iso_alpha2 = models.CharField(max_length=2, blank=True)

    def __str__(self):
        return f"{self.name} ({self.comtrade_code})"


class HSProduct(models.Model):
    product_code = models.CharField(max_length=10, primary_key=True)
    product_label = models.CharField(max_length=500)

    def __str__(self):
        return f"{self.product_code}: {self.product_label[:60]}"


class HSSITCConcordance(models.Model):
    """HS6 → SITC Rev.4 mapping, keyed by HS revision (vintage-aware).

    Used for the Yang (2023) SITC-section cross-validation. The trade panel
    spans multiple HS revisions (HS2007/2012/2017/2022); the same HS6 code can
    map to different SITC codes across revisions, so a row is identified by
    (product_code, hs_revision). The SITC section assigned to a year's HS6 row
    is the one from the revision active that year (see
    `trade_data_loader.hs_revision_for_year`). Loaded per revision by
    `load_hs_sitc_concordance --revision <YYYY>`."""
    product_code = models.CharField(max_length=10)   # HS6
    hs_revision = models.CharField(max_length=4)      # '2007' | '2012' | '2017' | '2022'
    sitc_code = models.CharField(max_length=10)       # full SITC Rev.4 code
    sitc_section = models.CharField(max_length=1)     # first digit, 0-9

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['product_code', 'hs_revision'],
                name='unique_hs6_per_revision',
            ),
        ]
        indexes = [
            models.Index(fields=['product_code', 'hs_revision']),
            models.Index(fields=['sitc_section']),
        ]

    def __str__(self):
        return (f"{self.product_code} (HS{self.hs_revision}) → "
                f"SITC {self.sitc_code} (section {self.sitc_section})")


class CountryExportToWorld(models.Model):
    reporter = models.CharField(max_length=100)
    product_code = models.CharField(max_length=10)  # HS6 or "TOTAL"
    year = models.IntegerField()
    value_usd_thousands = models.FloatField()

    class Meta:
        unique_together = ('reporter', 'product_code', 'year')
        indexes = [models.Index(fields=['reporter', 'year'])]

    def __str__(self):
        return f"{self.reporter} → World | {self.product_code} | {self.year}"


class CountryExportToPartner(models.Model):
    reporter = models.CharField(max_length=100)
    partner = models.CharField(max_length=20)   # "China" or "US"
    product_code = models.CharField(max_length=10)  # HS6 or "TOTAL"
    year = models.IntegerField()
    value_usd_thousands = models.FloatField()

    class Meta:
        unique_together = ('reporter', 'partner', 'product_code', 'year')
        indexes = [models.Index(fields=['partner', 'reporter'])]

    def __str__(self):
        return f"{self.reporter} → {self.partner} | {self.product_code} | {self.year}"


class PartnerImportFromWorld(models.Model):
    partner = models.CharField(max_length=20)   # "China" or "US"
    product_code = models.CharField(max_length=10)  # HS6 or "TOTAL"
    year = models.IntegerField()
    value_usd_thousands = models.FloatField()

    class Meta:
        unique_together = ('partner', 'product_code', 'year')
        indexes = [models.Index(fields=['partner', 'year'])]

    def __str__(self):
        return f"{self.partner} ← World | {self.product_code} | {self.year}"


class WorldExport(models.Model):
    product_code = models.CharField(max_length=10)  # HS6 or "TOTAL"
    year = models.IntegerField()
    value_usd_thousands = models.FloatField()

    class Meta:
        unique_together = ('product_code', 'year')
        indexes = [models.Index(fields=['year'])]

    def __str__(self):
        return f"World | {self.product_code} | {self.year}"
