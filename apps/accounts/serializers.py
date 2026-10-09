from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .services.password import change_password
from .services.registration import EmailAlreadyRegistered, register_user

User = get_user_model()


EMAIL_TAKEN_MESSAGE = "An account with this email already exists."


def _email_is_taken(email, *, exclude_user=None):
    users = User.objects.filter(email__iexact=email)

    if exclude_user is not None:
        users = users.exclude(pk=exclude_user.pk)

    return users.exists()


class UserSerializer(serializers.ModelSerializer):
    """The user payload shared by register, login and me."""

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "full_name",
            "role",
        )
        read_only_fields = fields


class RegistrationSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True,
        min_length=8,
    )
    # Optional: clients that confirm the password themselves can omit it.
    password_confirm = serializers.CharField(
        write_only=True,
        required=False,
    )

    def validate_email(self, value):
        value = value.strip().lower()

        if _email_is_taken(value):
            raise serializers.ValidationError(EMAIL_TAKEN_MESSAGE)

        return value

    def validate(self, attrs):
        password_confirm = attrs.pop("password_confirm", None)

        if (
            password_confirm is not None
            and password_confirm != attrs["password"]
        ):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}
            )

        return attrs

    def create(self, validated_data):
        try:
            return register_user(**validated_data)
        except EmailAlreadyRegistered:
            raise serializers.ValidationError(
                {"email": EMAIL_TAKEN_MESSAGE}
            )


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False)
    # Deprecated alias for `identifier`, kept so existing clients keep working.
    username = serializers.CharField(required=False, write_only=True)
    password = serializers.CharField(
        write_only=True,
    )

    def validate(self, attrs):
        identifier = attrs.get("identifier") or attrs.get("username")

        if not identifier:
            raise serializers.ValidationError(
                {"identifier": "This field is required."}
            )

        password = attrs.get("password")

        # Accept either a username or an email address.
        found = (
            User.objects.filter(username=identifier).first()
            or User.objects.filter(email__iexact=identifier).order_by("id").first()
        )

        # Always call authenticate(), even when nobody matched, so a wrong
        # identifier costs the same as a wrong password.
        user = authenticate(
            username=found.username if found else identifier,
            password=password,
        )

        if user is None:
            raise serializers.ValidationError(
                "Invalid email/username or password."
            )

        if not user.is_active:
            raise serializers.ValidationError(
                "This account is inactive."
            )

        refresh = RefreshToken.for_user(user)

        attrs["user"] = user
        attrs["refresh"] = str(refresh)
        attrs["access"] = str(refresh.access_token)

        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, attrs):
        try:
            refresh_token = RefreshToken(attrs["refresh"])
            refresh_token.blacklist()
        except Exception:
            raise serializers.ValidationError(
                "Invalid or already blacklisted refresh token."
            )

        return attrs


class ProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "full_name",
            "role",
        )
        read_only_fields = (
            "id",
            "username",
            "role",
        )

    def validate_email(self, value):
        value = value.strip().lower()

        if _email_is_taken(value, exclude_user=self.instance):
            raise serializers.ValidationError(EMAIL_TAKEN_MESSAGE)

        return value


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(
        write_only=True,
    )
    new_password = serializers.CharField(
        write_only=True,
        min_length=8,
    )
    new_password_confirm = serializers.CharField(
        write_only=True,
        min_length=8,
    )

    def validate(self, attrs):
        user = self.context["request"].user

        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError(
                {
                    "current_password": "Current password is incorrect."
                }
            )

        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {
                    "new_password_confirm": "Passwords do not match."
                }
            )

        return attrs

    def save(self):
        user = self.context["request"].user

        change_password(
            user=user,
            new_password=self.validated_data["new_password"],
        )

        return user