from django.contrib import admin
from .models import Player, GameClass, PlayerClass, Activity, ActivityParticipant, ActivityClassCoefficient, ActivityClassLevelCoefficient

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('game_nickname', 'tg_name', 'is_admin', 'is_our_player', 'created_at')
    search_fields = ('game_nickname', 'tg_name', 'telegram_id')
    list_filter = ('is_admin', 'is_our_player')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'telegram_id')
    list_editable = ('is_our_player',)

@admin.register(GameClass)
class GameClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(PlayerClass)
class PlayerClassAdmin(admin.ModelAdmin):
    list_display = ('get_player_nickname', 'game_class', 'level', 'created_at')
    search_fields = ('player__game_nickname', 'game_class__name')
    list_filter = ('game_class',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')

    def get_player_nickname(self, obj):
        return obj.player.game_nickname
    get_player_nickname.short_description = 'Игровой никнейм игрока'

class ActivityClassCoefficientInline(admin.TabularInline):
    model = ActivityClassCoefficient
    extra = 1
    verbose_name = 'Коэффициент класса'
    verbose_name_plural = 'Коэффициенты классов'

class ActivityClassLevelCoefficientInline(admin.TabularInline):
    model = ActivityClassLevelCoefficient
    extra = 3
    fields = ('game_class', 'level_min', 'level_max', 'coefficient')
    verbose_name = 'Коэффициент класса и уровня'
    verbose_name_plural = 'Коэффициенты классов и уровней'

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'is_active', 'ignore_odds', 'base_coefficient', 'created_at')
    search_fields = ('name', 'description', 'created_by__user_name')
    list_filter = ('is_active', 'ignore_odds', 'created_by')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ActivityClassLevelCoefficientInline]
    list_editable = ('is_active',)
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'is_active', 'ignore_odds')
        }),
        ('Коэффициенты', {
            'fields': ('base_coefficient',),
            'description': 'Настройка коэффициентов для расчета баллов'
        }),
        ('Создатель', {
            'fields': ('created_by',)
        }),
        ('Временные метки', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

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
