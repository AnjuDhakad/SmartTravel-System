from django.db import models
from django.contrib.auth.models import User


class Booking(models.Model):

    TRANSPORT_CHOICES = [
        ("Bus", "Bus"),
        ("Train", "Train"),
        ("Flight", "Flight"),
        ("Cab", "Cab"),
    ]

    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Confirmed", "Confirmed"),
        ("Cancelled", "Cancelled"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="travel_bookings"
    )

    transport_type = models.CharField(
        max_length=20,
        choices=TRANSPORT_CHOICES
    )

    source = models.CharField(max_length=100)

    destination = models.CharField(max_length=100)

    travel_date = models.DateField()

    booking_date = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    def __str__(self):
        return f"{self.transport_type}: {self.source} to {self.destination}"
