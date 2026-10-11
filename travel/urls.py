from django.urls import path
from . import views

app_name = "travel"

urlpatterns = [
    path("", views.travel_search, name="travel_search"),
    path("book-ticket/", views.book_ticket, name="book_ticket"),
    path("save-trip/", views.save_trip, name="save_trip"),
    path("saved-trips/", views.saved_trips, name="saved_trips"),
    path("saved-trips/<int:trip_id>/delete/", views.delete_saved_trip, name="delete_saved_trip"),
    path("book-ticket/", views.book_ticket, name="book_ticket"),
]