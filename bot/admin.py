from django.contrib import admin
from .models import User, Player, GameClass, PlayerClass, Activity, ActivityParticipant, ActivityClassCoefficient

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('user_name', 'user_tg_name', 'is_admin', 'created_at')
    search_fields = ('user_name', 'user_tg_name', 'telegram_id')
    list_filter = ('is_admin',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'selected_class', 'created_at')
    search_fields = ('name',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(GameClass)
class GameClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(PlayerClass)
class PlayerClassAdmin(admin.ModelAdmin):
    list_display = ('player', 'game_class', 'level', 'created_at')
    search_fields = ('player__name', 'game_class__name')
    list_filter = ('game_class',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

class ActivityClassCoefficientInline(admin.TabularInline):
    model = ActivityClassCoefficient
    extra = 1
    verbose_name = 'Коэффициент класса'
    verbose_name_plural = 'Коэффициенты классов'

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'is_active', 'base_coefficient', 'created_at')
    search_fields = ('name', 'description', 'created_by__user_name')
    list_filter = ('is_active', 'created_by')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ActivityClassCoefficientInline]
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'is_active')
        }),
        ('Коэффициенты', {
            'fields': ('base_coefficient', 'level_coefficient'),
            'description': 'Настройка базовых коэффициентов для расчета баллов'
        }),
        ('Создатель', {
            'fields': ('created_by',)
        }),
        ('Временные метки', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['level_coefficient'].help_text = (
            'Дополнительный коэффициент за каждый уровень персонажа. '
            'Например, при значении 0.1, персонаж 10 уровня получит множитель 1.9 (1 + 9 * 0.1)'
        )
        return form

@admin.register(ActivityClassCoefficient)
class ActivityClassCoefficientAdmin(admin.ModelAdmin):
    list_display = ('activity', 'game_class', 'coefficient', 'created_at')
    list_filter = ('activity', 'game_class')
    search_fields = ('activity__name', 'game_class__name')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(ActivityParticipant)
class ActivityParticipantAdmin(admin.ModelAdmin):
    list_display = ('player', 'activity', 'player_class', 'joined_at', 'completed_at', 'points_earned')
    search_fields = ('player__name', 'activity__name', 'player_class__game_class__name')
    list_filter = ('activity', 'player_class__game_class')
    ordering = ('-joined_at',)
    readonly_fields = ('joined_at', 'points_earned')
    fieldsets = (
        ('Основная информация', {
            'fields': ('activity', 'player', 'player_class')
        }),
        ('Время участия', {
            'fields': ('joined_at', 'completed_at')
        }),
        ('Результаты', {
            'fields': ('points_earned',),
            'description': 'Баллы рассчитываются автоматически при завершении активности'
        }),
    )

    def has_add_permission(self, request):
        return False  # Запрещаем создание записей вручную

    def has_change_permission(self, request, obj=None):
        if obj and obj.completed_at:
            return False  # Запрещаем изменение завершенных активностей
        return super().has_change_permission(request, obj)
