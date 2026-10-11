from django.contrib import admin

from .models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """Comments are written through the API. The admin can read them and
    hard-delete one (for example on a legal erasure request), but cannot
    create or rewrite what someone said."""

    list_display = (
        'id',
        'issue',
        'author',
        'created_at',
        'edited_at',
        'deleted_at',
    )
    list_filter = ('deleted_at',)
    list_select_related = ('issue', 'author')
    search_fields = ('body', 'author__username')
    date_hierarchy = 'created_at'
    ordering = ('-created_at', '-id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
