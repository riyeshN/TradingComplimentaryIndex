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
