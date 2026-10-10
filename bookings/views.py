from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import Booking


@login_required
def bookings_home(request):
    bookings = Booking.objects.filter(
        user=request.user
    ).order_by("-booking_date")

    context = {
        "bookings": bookings,
        "total_bookings": bookings.count(),
        "pending_bookings": bookings.filter(status="Pending").count(),
        "confirmed_bookings": bookings.filter(status="Confirmed").count(),
        "cancelled_bookings": bookings.filter(status="Cancelled").count(),
    }

    return render(request, "bookings.html", context)