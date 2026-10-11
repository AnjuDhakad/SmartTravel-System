from django.conf import settings
from django.db import models


class SavedTrip(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_trips",
    )
    source = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    travel_date = models.DateField(null=True, blank=True)
    travel_time = models.TimeField(null=True, blank=True)
    passengers = models.PositiveSmallIntegerField(default=1)
    transport = models.CharField(max_length=30)
    distance_km = models.DecimalField(
        max_digits=10, decimal_places=2
    )
    duration = models.CharField(max_length=50)
    estimated_total_fare = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.source} to {self.destination}"
