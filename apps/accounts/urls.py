from django.urls import path

from .views import (
    LoginView,
    LogoutView,
    MeView,
    ProfileView,
    RegistrationView,
)



urlpatterns = [
    path(
        "register/",
        RegistrationView.as_view(),
        name="register",
    ),
    path(
        "login/",
        LoginView.as_view(),
        name="login",
    ),
    path(
        "me/",
        MeView.as_view(),
        name="me",
    ),
    path(
        "profile/",
        ProfileView.as_view(),
        name="profile",
    ),
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
]