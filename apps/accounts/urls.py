from django.urls import path

from .views import LoginView, MeView, RegistrationView ,LogoutView


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
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
]