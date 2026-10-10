from django.shortcuts import render


def travel_search(request):
    results = []
    searched = False
    error_message = ""

    # Store form values
    source = ""
    destination = ""
    travel_date = ""
    transport = "all"

    # Available transport categories
    transport_options = {
        "bus": {
            "name": "Bus",
            "description": "Explore bus travel options",
            "icon": "🚌",
        },
        "train": {
            "name": "Train",
            "description": "Explore train travel options",
            "icon": "🚆",
        },
        "flight": {
            "name": "Flight",
            "description": "Explore flight travel options",
            "icon": "✈️",
        },
        "cab": {
            "name": "Cab",
            "description": "Explore cab travel options",
            "icon": "🚕",
        },
    }

    if request.method == "POST":
        searched = True

        source = request.POST.get("source", "").strip()
        destination = request.POST.get("destination", "").strip()
        travel_date = request.POST.get("travel_date", "").strip()
        transport = request.POST.get("transport", "all")

        # Validate form fields
        if not source or not destination or not travel_date:
            error_message = "Please fill in all fields before searching."

        elif source.casefold() == destination.casefold():
            error_message = "Source and destination must be different cities."

        elif transport != "all" and transport not in transport_options:
            error_message = "Please select a valid transport type."

        else:
            # Show all categories or only the selected category
            if transport == "all":
                selected_options = transport_options.items()
            else:
                selected_options = [
                    (transport, transport_options[transport])
                ]

            # Create result cards
            for key, option in selected_options:
                results.append({
                    "type": key,
                    "name": option["name"],
                    "description": option["description"],
                    "icon": option["icon"],
                    "source": source,
                    "destination": destination,
                    "travel_date": travel_date,
                })

    context = {
        "results": results,
        "searched": searched,
        "error_message": error_message,
        "source": source,
        "destination": destination,
        "travel_date": travel_date,
        "transport": transport,
    }

    return render(request, "travel_search.html", context)