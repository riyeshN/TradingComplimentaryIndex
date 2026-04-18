from django.db import models

# Create your models here.
class Product(models.Model):
    productCode = models.CharField(max_length=18)
    productLabel = models.CharField(max_length=350)
    infoJson = models.JSONField(default=dict, blank=True)
