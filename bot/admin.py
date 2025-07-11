from django.contrib import admin
from .models import (
    Player, GameClass, PlayerClass, Activity, ActivityParticipant, 
    GameClassBaseCoefficientCondition, ActivityClassLevelCoefficient,
    ActivityHistory, ActivityHistoryParticipant
)
from django.utils.translation import gettext_lazy as _
from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.contrib import messages
from django.utils.safestring import mark_safe
from .models import export_activity_history_to_google_sheets
from django.utils import timezone
from django.urls import path

class PlayerClassInline(admin.TabularInline):
    model = PlayerClass
    extra = 1
    fields = ('game_class', 'level', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')
    verbose_name = 'Класс игрока'
    verbose_name_plural = 'Классы игрока'

class GameClassBaseCoefficientConditionInline(admin.TabularInline):
    model = GameClassBaseCoefficientCondition
    extra = 1
    fields = ('min_level', 'max_level', 'coefficient')
    verbose_name = 'Условие коэффициента'
    verbose_name_plural = 'Условия коэффициента'

class ActivityClassLevelCoefficientForm(forms.ModelForm):
    class Meta:
        model = ActivityClassLevelCoefficient
        fields = ['min_level', 'max_level', 'coefficient', 'game_class', 'activity']
        widgets = {'game_class': forms.HiddenInput, 'activity': forms.HiddenInput}

    def clean(self):
        cleaned_data = super().clean()
        min_level = cleaned_data.get('min_level')
        max_level = cleaned_data.get('max_level')
        game_class = cleaned_data.get('game_class')
        activity = cleaned_data.get('activity')
        if min_level is not None and max_level is not None and game_class and activity:
            qs = ActivityClassLevelCoefficient.objects.filter(
                activity=activity,
                game_class=game_class,
                min_level=min_level,
                max_level=max_level
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise ValidationError('Для этого класса и диапазона уровней уже существует коэффициент!')
        return cleaned_data

# Динамический inline для коэффициентов по игровому классу
def make_class_level_inline(game_class):
    class_name = f"{game_class.name}"
    class CustomForm(ActivityClassLevelCoefficientForm):
        def save(self, commit=True):
            instance = super().save(commit=False)
            instance.game_class = game_class
            if commit:
                instance.save()
            return instance
    class Meta:
        verbose_name = f"Коэффициенты для класса: {game_class.name}"
        verbose_name_plural = f"Коэффициенты для класса: {game_class.name}"
        model = ActivityClassLevelCoefficient
        fields = ('min_level', 'max_level', 'coefficient')
        extra = 0
    attrs = {
        'model': ActivityClassLevelCoefficient,
        'form': CustomForm,
        'fields': ('min_level', 'max_level', 'coefficient'),
        'extra': 0,
        'verbose_name': f"Коэффициенты для класса: {game_class.name}",
        'verbose_name_plural': f"Коэффициенты для класса: {game_class.name}",
        'fk_name': 'activity',
        'can_delete': True,
        'Meta': Meta,
        'get_queryset': lambda self, request: super(self.__class__, self).get_queryset(request).filter(game_class=game_class),
        'formfield_overrides': {ActivityClassLevelCoefficient._meta.get_field('game_class'): {'widget': forms.HiddenInput}},
        '__module__': __name__,
    }
    return type(f"{game_class.name}ClassLevelInline", (admin.TabularInline,), attrs)

class ActivityParticipantForm(forms.ModelForm):
    """Форма для редактирования участника активности"""
    class Meta:
        model = ActivityParticipant
        fields = ['completed_at', 'additional_points']
        widgets = {
            'completed_at': forms.SplitDateTimeWidget(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Добавляем вычисляемые поля как readonly
            self.fields['calculated_duration'] = forms.CharField(
                label='Расчетное время',
                required=False,
                widget=forms.TextInput(attrs={'readonly': 'readonly'})
            )
            self.fields['total_points'] = forms.CharField(
                label='Итоговое количество баллов',
                required=False,
                widget=forms.TextInput(attrs={'readonly': 'readonly'})
            )

class ActivityParticipantInline(admin.TabularInline):
    """Inline для редактирования участников активности"""
    model = ActivityParticipant
    form = ActivityParticipantForm
    extra = 0
    readonly_fields = ('player', 'player_class', 'joined_at', 'calculated_duration', 'total_points')
    fields = ('player', 'player_class', 'joined_at', 'completed_at', 'calculated_duration', 'points_earned', 'additional_points', 'total_points')
    
    def calculated_duration(self, obj):
        """Расчетное время участия"""
        if obj.completed_at and obj.joined_at:
            duration = obj.completed_at - obj.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int(duration.total_seconds() % 60)
            return f"{hours}ч {minutes}м {seconds}с"
        return "Не завершено"
    calculated_duration.short_description = 'Расчетное время'
    
    def total_points(self, obj):
        """Общее количество баллов"""
        return obj.total_points
    total_points.short_description = 'Итоговые баллы'
    
    def has_add_permission(self, request, obj=None):
        return False

class ActivityHistoryParticipantForm(forms.ModelForm):
    """Форма для редактирования участника истории активности"""
    class Meta:
        model = ActivityHistoryParticipant
        fields = ['joined_at', 'completed_at', 'points_earned', 'additional_points']
        widgets = {
            'joined_at': forms.SplitDateTimeWidget(),
            'completed_at': forms.SplitDateTimeWidget(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            # Добавляем вычисляемые поля как readonly
            self.fields['calculated_duration'] = forms.CharField(
                label='Расчетное время',
                required=False,
                widget=forms.TextInput(attrs={'readonly': 'readonly'})
            )
            self.fields['total_points'] = forms.CharField(
                label='Итоговое количество баллов',
                required=False,
                widget=forms.TextInput(attrs={'readonly': 'readonly'})
            )

class ActivityHistoryParticipantInline(admin.TabularInline):
    """Inline для редактирования участников истории активности"""
    model = ActivityHistoryParticipant
    form = ActivityHistoryParticipantForm
    extra = 0
    readonly_fields = ('player', 'player_class', 'calculated_duration', 'total_points')
    fields = ('player', 'player_class', 'joined_at', 'completed_at', 'calculated_duration', 'points_earned', 'additional_points', 'total_points')
    
    def calculated_duration(self, obj):
        """Расчетное время участия"""
        if obj.completed_at and obj.joined_at:
            duration = obj.completed_at - obj.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int(duration.total_seconds() % 60)
            return f"{hours}ч {minutes}м {seconds}с"
        return "Не завершено"
    calculated_duration.short_description = 'Расчетное время'
    
    def total_points(self, obj):
        """Общее количество баллов (из базы)"""
        return obj.total_points
    total_points.short_description = 'Итоговые баллы (после сохранения)'
    
    def has_add_permission(self, request, obj=None):
        return False

    class Media:
        js = ('admin/js/activity_history_participant_inline.js',)
    
    def has_delete_permission(self, request, obj=None):
        return False  # Запрещаем удаление участников

    def save_model(self, request, obj, form, change):
        """Автообновление Google Sheets при изменении участника"""
        super().save_model(request, obj, form, change)
        from .models import export_activity_history_to_google_sheets
        result = export_activity_history_to_google_sheets(obj.activity_history)
        if result:
            messages.success(request, 'Данные автоматически обновлены в Google Sheets (Лист1).')
        else:
            messages.warning(request, 'Не удалось обновить данные в Google Sheets.')

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('game_nickname', 'tg_name', 'is_admin', 'is_our_player', 'created_at')
    search_fields = ('game_nickname', 'tg_name', 'telegram_id')
    list_filter = ('is_admin', 'is_our_player')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'telegram_id', 'activity_message_ids', 'completion_message_ids', 'tg_name')
    list_editable = ('is_our_player',)
    inlines = [PlayerClassInline]
    fieldsets = (
        ('Основная информация', {
            'fields': ('game_nickname', 'telegram_id', 'tg_name', 'is_our_player', 'is_admin')
        }),
        ('Классы', {
            'fields': ('selected_class',)
        }),
        ('Техническая информация', {
            'fields': ('activity_message_ids', 'completion_message_ids', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(GameClass)
class GameClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [GameClassBaseCoefficientConditionInline]

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'ignore_odds', 'base_coefficient', 'participants_count', 'created_at')
    search_fields = ('name', 'description')
    list_filter = ('is_active', 'ignore_odds')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at', 'activated_at')
    list_editable = ('is_active',)
    inlines = [ActivityParticipantInline]
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'is_active', 'ignore_odds')
        }),
        ('Коэффициенты', {
            'fields': ('base_coefficient',),
            'description': 'Настройка коэффициента для расчета баллов'
        }),
        ('Временные метки', {
            'fields': ('created_at', 'activated_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:activity_id>/sync_coeffs/',
                self.admin_site.admin_view(self.sync_class_coeffs),
                name='sync_class_coeffs',
            ),
        ]
        return custom_urls + urls
    def sync_class_coeffs(self, request, activity_id):
        from .models import Activity, GameClass, ActivityClassLevelCoefficient
        try:
            activity = Activity.objects.get(id=activity_id)
            ActivityClassLevelCoefficient.objects.filter(activity=activity).delete()
            for game_class in GameClass.objects.all():
                for cond in game_class.base_coefficient_conditions.all():
                    ActivityClassLevelCoefficient.objects.create(
                        activity=activity,
                        game_class=game_class,
                        min_level=cond.min_level,
                        max_level=cond.max_level,
                        coefficient=cond.coefficient
                    )
            self.message_user(request, 'Коэффициенты классов успешно синхронизированы!', level=messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f'Ошибка при синхронизации: {e}', level=messages.ERROR)
        return HttpResponseRedirect(reverse('admin:bot_activity_change', args=[activity_id]))
    def render_change_form(self, request, context, *args, **kwargs):
        obj = context.get('original')
        if obj:
            sync_url = reverse('admin:sync_class_coeffs', args=[obj.pk])
            context['adminform'].form.fields['base_coefficient'].help_text = mark_safe(
                f'<a class="button" style="margin-left:10px;" href="{sync_url}">🔄 Синхронизировать коэффициенты классов</a>'
            )
        return super().render_change_form(request, context, *args, **kwargs)
    def participants_count(self, obj):
        unique_players = obj.participants.values('player__game_nickname').distinct().count()
        return unique_players
    participants_count.short_description = 'Уникальных участников'
    def get_inline_instances(self, request, obj=None):
        inlines = []
        inlines.append(ActivityParticipantInline(self.model, self.admin_site))
        for game_class in GameClass.objects.all():
            inline = make_class_level_inline(game_class)
            inlines.append(inline(self.model, self.admin_site))
        return inlines

@admin.register(ActivityHistory)
class ActivityHistoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'activity_started_at', 'activity_ended_at', 'participants_count')  # убрал is_exported
    search_fields = ('name', 'description')
    list_filter = ('activity_started_at',)  # убрал is_exported
    ordering = ('-activity_ended_at',)
    readonly_fields = ('original_activity', 'created_at', 'updated_at')  # убрал is_exported
    # list_editable = ('is_exported',)  # убрал
    inlines = [ActivityHistoryParticipantInline]
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'base_coefficient', 'ignore_odds')
        }),
        ('Время активности', {
            'fields': ('activity_started_at', 'activity_ended_at')
        }),
        ('Техническая информация', {
            'fields': ('original_activity', 'is_exported', 'created_at', 'updated_at'),
            'classes': ('collapse',),
            'description': 'При изменении данных происходит автообновление в Google Sheets (Лист1).'
        }),
    )
    def participants_count(self, obj):
        return obj.participants.count()
    participants_count.short_description = 'Участников'
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Автообновление Google Sheets при изменении истории активности
        from .models import export_activity_history_to_google_sheets
        export_activity_history_to_google_sheets(obj)

    def has_add_permission(self, request):
        return False  # Запрещаем создание записей вручную

    def has_delete_permission(self, request, obj=None):
        return True  # Разрешаем удаление записей

    def delete_model(self, request, obj):
        """Обработчик удаления записи истории"""
        # Если запись была экспортирована, удаляем данные из Google Sheets
        if obj.is_exported:
            from .models import delete_activity_history_from_google_sheets
            success = delete_activity_history_from_google_sheets(obj)
            if success:
                messages.success(request, 'Данные удалены из Google Sheets (Лист1).')
            else:
                messages.warning(request, 'Не удалось удалить данные из Google Sheets.')
        
        # Удаляем запись
        super().delete_model(request, obj)
        messages.success(request, 'Запись истории активности удалена.')

    def delete_queryset(self, request, queryset):
        """Обработчик массового удаления записей истории"""
        for obj in queryset:
            # Если запись была экспортирована, удаляем данные из Google Sheets
            if obj.is_exported:
                from .models import delete_activity_history_from_google_sheets
                success = delete_activity_history_from_google_sheets(obj)
                if not success:
                    messages.warning(request, f'Не удалось удалить данные из Google Sheets для активности "{obj.name}".')
        
        # Удаляем записи
        super().delete_queryset(request, queryset)
        messages.success(request, f'Удалено записей истории: {queryset.count()}.')

@admin.register(ActivityParticipant)
class ActivityParticipantAdmin(admin.ModelAdmin):
    """Отдельное представление для участников активностей"""
    list_display = ('player', 'activity', 'player_class', 'joined_at', 'completed_at', 'points_earned', 'additional_points', 'total_points')
    search_fields = ('player__game_nickname', 'activity__name', 'player_class__game_class__name')
    list_filter = ('activity', 'player_class__game_class')
    ordering = ('-joined_at',)
    readonly_fields = ('joined_at', 'points_earned', 'calculated_duration', 'total_points')
    form = ActivityParticipantForm
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('activity', 'player', 'player_class')
        }),
        ('Время участия', {
            'fields': ('joined_at', 'completed_at', 'calculated_duration')
        }),
        ('Результаты', {
            'fields': ('points_earned', 'additional_points', 'total_points'),
            'description': 'Баллы рассчитываются автоматически при завершении активности'
        }),
    )

    def calculated_duration(self, obj):
        """Расчетное время участия"""
        if obj.completed_at and obj.joined_at:
            duration = obj.completed_at - obj.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int(duration.total_seconds() % 60)
            return f"{hours}ч {minutes}м {seconds}с"
        return "Не завершено"
    calculated_duration.short_description = 'Расчетное время'

    def total_points(self, obj):
        """Общее количество баллов"""
        return obj.total_points
    total_points.short_description = 'Итоговые баллы'

    def has_add_permission(self, request):
        return False  # Запрещаем создание записей вручную

    def has_change_permission(self, request, obj=None):
        if obj and obj.completed_at:
            return True  # Разрешаем изменение завершенных активностей для добавления дополнительных баллов
        return super().has_change_permission(request, obj)
