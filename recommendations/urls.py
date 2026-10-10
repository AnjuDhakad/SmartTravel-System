from django.urls import path
from . import views

app_name = "recommendations"

urlpatterns = [
    path("", views.recommendations_home, name="home"),
]