from django.contrib import admin, messages


class SoftDeleteAdmin(admin.ModelAdmin):
    readonly_fields = ("deleted_at",)
    actions = ("archive_selected", "unarchive_selected")

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    @admin.action(description="Архивировать выбранные записи", permissions=["delete"])
    def archive_selected(self, request, queryset):
        active = queryset.filter(deleted_at__isnull=True)
        count = active.count()
        self.delete_queryset(request, active)
        self.message_user(
            request,
            f"Архивировано записей: {count}. Данные сохранены в базе.",
            messages.SUCCESS,
        )

    @admin.action(description="Разархивировать выбранные записи", permissions=["change"])
    def unarchive_selected(self, request, queryset):
        archived = queryset.filter(deleted_at__isnull=False)
        count = archived.update(deleted_at=None)
        self.message_user(
            request,
            f"Разархивировано записей: {count}.",
            messages.SUCCESS,
        )

    def get_deleted_objects(self, objs, request):
        # Django's default collector describes a physical cascade and may block
        # PROTECT relations. Soft deletion changes only the selected records.
        labels = [str(obj) for obj in objs]
        return labels, {str(self.model._meta.verbose_name_plural): len(labels)}, set(), []

    def delete_model(self, request, obj):
        obj.delete()

    def delete_queryset(self, request, queryset):
        queryset.delete()
