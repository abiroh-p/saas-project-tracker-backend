from django.contrib import admin

from .models import Activity


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """Read-only: activity is written only by the application workflows."""

    list_display = (
        'created_at',
        'project',
        'user',
        'action',
        'entity_type',
    )
    list_filter = ('action', 'entity_type')
    list_select_related = ('project', 'user')
    search_fields = ('description', 'project__key', 'user__username')
    date_hierarchy = 'created_at'
    ordering = ('-created_at', '-id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
