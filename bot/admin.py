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
        """Общее количество баллов"""
        return obj.total_points
    total_points.short_description = 'Итоговые баллы'
    
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False  # Запрещаем удаление участников
    
    def save_model(self, request, obj, form, change):
        """Автообновление Google Sheets при изменении участника"""
        super().save_model(request, obj, form, change)
        
        # Если родительская активность экспортирована, обновляем Google Sheets
        if obj.activity_history.is_exported:
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
    readonly_fields = ('created_at', 'updated_at', 'telegram_id', 'activity_message_ids', 'completion_message_ids')
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
    list_display = ('name', 'created_by', 'is_active', 'ignore_odds', 'base_coefficient', 'participants_count', 'created_at', 'export_button')
    search_fields = ('name', 'description', 'created_by__user_name')
    list_filter = ('is_active', 'ignore_odds', 'created_by')
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
        ('Создатель', {
            'fields': ('created_by',)
        }),
        ('Временные метки', {
            'fields': ('created_at', 'activated_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def participants_count(self, obj):
        """Количество уникальных участников по игровому имени"""
        unique_players = obj.participants.values('player__game_nickname').distinct().count()
        return unique_players
    participants_count.short_description = 'Уникальных участников'

    def get_inline_instances(self, request, obj=None):
        inlines = []
        # Добавляем inline для участников
        inlines.append(ActivityParticipantInline(self.model, self.admin_site))
        # Добавляем inline для коэффициентов классов
        for game_class in GameClass.objects.all():
            inline = make_class_level_inline(game_class)
            inlines.append(inline(self.model, self.admin_site))
        return inlines

    def export_button(self, obj):
        """Кнопка экспорта в Google Sheets"""
        if obj.is_active:
            url = reverse('admin:export_active_activity', args=[obj.pk])
            return mark_safe(
                f'<a href="{url}" class="button" '
                f'title="При экспорте будут удалены все сообщения об активности у пользователей">'
                f'📊 Экспорт в Google Sheets</a>'
            )
        else:
            return mark_safe('<span style="color: gray;">Неактивна</span>')
    export_button.short_description = 'Экспорт'

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:activity_id>/export/',
                self.admin_site.admin_view(self.export_to_google_sheets),
                name='export_active_activity',
            ),
        ]
        return custom_urls + urls

    def export_to_google_sheets(self, request, activity_id):
        """Экспорт данных активной активности в Google Sheets"""
        try:
            activity = Activity.objects.get(id=activity_id)
            
            if not activity.is_active:
                messages.error(request, 'Можно экспортировать только активные активности')
                return HttpResponseRedirect(reverse('admin:bot_activity_changelist'))
            
            # Экспортируем данные в один лист
            from .models import export_active_activity_to_google_sheets
            result = export_active_activity_to_google_sheets(activity)
            
            if result:
                # Отправляем уведомление админам
                from .models import Player
                admins = Player.objects.filter(is_admin=True)
                
                for admin in admins:
                    try:
                        text = (
                            f"📊 *Данные активной активности экспортированы в Google Sheets*\n\n"
                            f"Активность: {activity.name}\n"
                            f"Время экспорта: {timezone.now().strftime('%d.%m.%Y %H:%M')}\n"
                            f"Лист: Лист1\n\n"
                            f"Ссылка на таблицу: {result['url']}\n\n"
                            f"✅ Сообщения об активности удалены у всех пользователей"
                        )
                        
                        from . import bot
                        bot.send_message(
                            chat_id=admin.telegram_id,
                            text=text,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        print(f"Ошибка при отправке уведомления админу {admin.telegram_id}: {str(e)}")
                
                messages.success(request, f'Данные активности "{activity.name}" успешно экспортированы в Google Sheets. Лист: Лист1. Сообщения об активности удалены у всех пользователей.')
                
            else:
                messages.error(request, 'Ошибка при экспорте данных в Google Sheets')
                
        except Activity.DoesNotExist:
            messages.error(request, 'Активность не найдена')
        except Exception as e:
            messages.error(request, f'Ошибка: {str(e)}')
        
        return HttpResponseRedirect(reverse('admin:bot_activity_changelist'))

@admin.register(ActivityHistory)
class ActivityHistoryAdmin(admin.ModelAdmin):
    """Представление для просмотра истории всех активностей"""
    list_display = ('name', 'created_by', 'activity_started_at', 'activity_ended_at', 'participants_count', 'is_exported', 'export_button')
    search_fields = ('name', 'description', 'created_by__game_nickname')
    list_filter = ('is_exported', 'created_by', 'activity_started_at')
    ordering = ('-activity_ended_at',)
    readonly_fields = ('original_activity', 'created_at', 'updated_at')
    list_editable = ('is_exported',)
    inlines = [ActivityHistoryParticipantInline]
    
    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'description', 'base_coefficient', 'ignore_odds')
        }),
        ('Время активности', {
            'fields': ('activity_started_at', 'activity_ended_at')
        }),
        ('Создатель', {
            'fields': ('created_by',)
        }),
        ('Техническая информация', {
            'fields': ('original_activity', 'is_exported', 'created_at', 'updated_at'),
            'classes': ('collapse',),
            'description': 'При установке галочки "Экспортировано в Google Sheets" автоматически удаляются все сообщения об этой активности у пользователей. При любом редактировании данных происходит автообновление в Google Sheets (Лист1). При снятии галочки можно редактировать данные, а при повторной установке - обновить в таблице. Существующие записи с одинаковыми пользователем, событием и временем будут заменены новыми данными.'
        }),
    )

    def participants_count(self, obj):
        """Количество участников"""
        return obj.participants.count()
    participants_count.short_description = 'Участников'

    def export_button(self, obj):
        """Кнопка экспорта в Google Sheets"""
        if obj.is_exported:
            return mark_safe('<span style="color: green;">✓ Экспортировано</span>')
        else:
            url = reverse('admin:export_activity_history', args=[obj.pk])
            return mark_safe(
                f'<a href="{url}" class="button" '
                f'title="При экспорте будут удалены все сообщения об активности у пользователей">'
                f'📊 Экспорт в Google Sheets</a>'
            )
    export_button.short_description = 'Экспорт'

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:activity_history_id>/export/',
                self.admin_site.admin_view(self.export_to_google_sheets),
                name='export_activity_history',
            ),
        ]
        return custom_urls + urls

    def export_to_google_sheets(self, request, activity_history_id):
        """Экспорт данных в Google Sheets"""
        try:
            activity_history = ActivityHistory.objects.get(id=activity_history_id)
            
            # Экспортируем данные в один лист
            result = export_activity_history_to_google_sheets(activity_history)
            
            if result:
                # Отмечаем как экспортированное
                activity_history.is_exported = True
                activity_history.save()
                
                # Удаляем сообщения о завершении активности у всех пользователей
                from .models import delete_completion_messages_for_all_users
                if activity_history.original_activity:
                    delete_completion_messages_for_all_users(activity_history.original_activity.id)
                
                # Удаляем сообщения об активности у всех пользователей
                from .models import delete_activity_messages_for_all_users
                if activity_history.original_activity:
                    delete_activity_messages_for_all_users(activity_history.original_activity.id)
                
                # Отправляем уведомление админам
                from .models import Player
                admins = Player.objects.filter(is_admin=True)
                
                for admin in admins:
                    try:
                        text = (
                            f"📊 *Данные экспортированы в Google Sheets*\n\n"
                            f"Активность: {activity_history.name}\n"
                            f"Время экспорта: {timezone.now().strftime('%d.%m.%Y %H:%M')}\n"
                            f"Лист: Лист1\n\n"
                            f"Ссылка на таблицу: {result['url']}\n\n"
                            f"✅ Сообщения об активности удалены у всех пользователей"
                        )
                        
                        from . import bot
                        bot.send_message(
                            chat_id=admin.telegram_id,
                            text=text,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        print(f"Ошибка при отправке уведомления админу {admin.telegram_id}: {str(e)}")
                
                messages.success(request, f'Данные успешно экспортированы в Google Sheets. Лист: Лист1. Сообщения об активности удалены у всех пользователей.')
                
            else:
                messages.error(request, 'Ошибка при экспорте данных в Google Sheets')
                
        except ActivityHistory.DoesNotExist:
            messages.error(request, 'Запись истории не найдена')
        except Exception as e:
            messages.error(request, f'Ошибка: {str(e)}')
        
        return HttpResponseRedirect(reverse('admin:bot_activityhistory_changelist'))

    def save_model(self, request, obj, form, change):
        """Переопределяем сохранение модели для обработки изменения галочки экспорта и автообновления"""
        if change:  # Если это изменение существующей записи
            try:
                old_obj = ActivityHistory.objects.get(pk=obj.pk)
                # Если галочка была снята и стала активной
                if not old_obj.is_exported and obj.is_exported:
                    # Удаляем сообщения об активности у всех пользователей
                    from .models import delete_activity_messages_for_all_users, delete_completion_messages_for_all_users
                    if obj.original_activity:
                        delete_activity_messages_for_all_users(obj.original_activity.id)
                        delete_completion_messages_for_all_users(obj.original_activity.id)
                    
                    # Добавляем сообщение об успешном удалении
                    messages.success(request, 'Сообщения об активности удалены у всех пользователей.')
                
                # Автообновление Google Sheets при установке галочки
                if obj.is_exported:
                    from .models import export_activity_history_to_google_sheets
                    result = export_activity_history_to_google_sheets(obj)
                    if result:
                        messages.success(request, 'Данные автоматически обновлены в Google Sheets (Лист1).')
                    else:
                        messages.warning(request, 'Не удалось обновить данные в Google Sheets.')
                        
            except ActivityHistory.DoesNotExist:
                pass
        
        super().save_model(request, obj, form, change)

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
