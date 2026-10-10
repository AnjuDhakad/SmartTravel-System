from django.urls import path
from . import views

app_name = "travel"

urlpatterns = [
    path("", views.travel_search, name="travel_search"),
]