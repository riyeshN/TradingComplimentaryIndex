from . import views
from django.urls import path

urlpatterns = [
    path("update_reference_for_country_id", views.update_reference_for_country_id, name="update_reference_for_country_id"),
    path("fetch_trade_data", views.fetch_trade_data, name="fetch_trade_data"),
    path("calculate_tci", views.calculate_tci, name="calculate_tci"),
    path("load_trade_data_to_db", views.load_trade_data_to_db, name="load_trade_data_to_db"),
]