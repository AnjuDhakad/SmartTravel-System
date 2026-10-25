from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("travel/", include("travel.urls")),
    path("recommendations/", include("recommendations.urls")),
    path("bookings/", include("bookings.urls")),
    path("assistant/", include("assistant.urls")),
    path("get_flight_routes/", include("travel.urls")),
    path("compare/", include("comparison.urls")),
    path("agent/", include("travel_agent.urls")),
]
