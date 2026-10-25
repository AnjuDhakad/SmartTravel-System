from django.urls import path

from . import views

app_name = "comparison"

urlpatterns = [
    path("", views.compare_transport, name="compare"),
    path("api/", views.compare_api, name="api"),
]
