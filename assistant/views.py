from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def assistant_home(request):
    response = ""
    user_message = ""

    if request.method == "POST":
        user_message = request.POST.get("message", "").strip()
        message = user_message.lower()

        if not user_message:
            response = "Please enter a question first."

        elif any(word in message for word in ["hello", "hi", "hey"]):
            response = (
                "Hello! Welcome to SmartTravel Assistant. "
                "How can I help you plan your journey today?"
            )

        elif "bus" in message:
            response = (
                "Bus travel can be a budget-friendly option. "
                "Open Search Routes to explore bus travel options."
            )

        elif "train" in message:
            response = (
                "Train travel can be comfortable for long journeys. "
                "Visit Search Routes to explore train travel options."
            )

        elif "flight" in message or "plane" in message:
            response = (
                "Flights can save time on long-distance journeys. "
                "Open Search Routes to explore flight travel options."
            )

        elif "cab" in message or "taxi" in message:
            response = (
                "Cabs can provide convenient door-to-door travel. "
                "Visit Search Routes to explore cab travel options."
            )

        elif "book" in message or "booking" in message:
            response = (
                "You can visit My Bookings from your dashboard "
                "to view your saved travel bookings."
            )

        elif (
            "route" in message
            or "destination" in message
            or "travel" in message
        ):
            response = (
                "I can help you explore travel options. "
                "Open Search Routes and enter your source, "
                "destination, and travel date."
            )

        elif "thank" in message:
            response = (
                "You're welcome! Have a safe and happy journey."
            )

        elif "help" in message:
            response = (
                "You can ask me about buses, trains, flights, cabs, "
                "travel routes, or bookings."
            )

        else:
            response = (
                "I'm still learning! You can ask me about buses, "
                "trains, flights, cabs, travel routes, or bookings."
            )

    return render(
        request,
        "assistant.html",
        {
            "response": response,
            "user_message": user_message,
        },
    )
