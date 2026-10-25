from django.urls import path

from . import views


urlpatterns = [
    path("", views.agent_home, name="agent_home"),
    path("api/city/", views.city_api, name="city_api"),
    path("api/chat/", views.chat_api, name="chat_api"),
]