def change_password(*, user, new_password):
    user.set_password(new_password)
    user.save(update_fields=["password"])