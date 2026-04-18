from . import views
from django.urls import path

urlpatterns = [
    path("update_reference_for_country_id", views.update_reference_for_country_id, name="update_reference_for_country_id"),
    path("fetch_trade_data", views.fetch_trade_data, name="fetch_trade_data"),
    path("extract_data_from_trade_map_excel",
         views.extract_data_from_trade_map_excel,name="extract_data_from_trade_map_excel"),
]