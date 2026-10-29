from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction

def home(request):
    return render(request, 'home.html')


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not all([name, username, email, password, confirm_password]):
            messages.error(request, 'Please fill in all fields.')

        elif password != confirm_password:
            messages.error(request, 'Passwords do not match.')

        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')

        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Email is already registered.')

        elif len(password) < 8:
            messages.error(
                request,
                'Password must be at least 8 characters.'
            )

        else:
            try:
                with transaction.atomic():
                    User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=name
                    )

                messages.success(
                    request,
                    'Account created successfully. Please log in.'
                )
                return redirect('login')

            except IntegrityError:
                messages.error(
                    request,
                    'Username or email already exists. Please try different details.'
                )

    return render(request, 'signup.html')

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            login(request, user)
            return redirect('dashboard')

        messages.error(request, 'Invalid username or password.')

    return render(request, 'login.html')


@login_required
def dashboard(request):
    return render(request, 'dashboard.html')


@login_required
def profile(request):
    return render(
        request,
        'profile.html',
        {'user': request.user}
    )


@login_required
def logout_view(request):
    logout(request)
    messages.success(
        request,
        'You have logged out successfully.'
    )
    return redirect('home')

@login_required
def saved_trips(request):
    return render(request, 'saved_trips.html')