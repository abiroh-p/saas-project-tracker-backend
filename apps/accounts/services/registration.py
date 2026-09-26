from django.contrib.auth import get_user_model


User = get_user_model()


def register_user(*, username, email, password):
    return User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )