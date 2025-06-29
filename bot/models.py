from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from bot import bot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from asgiref.sync import sync_to_async
import json
from datetime import datetime
import os
from django.conf import settings
from .google_sheets import GoogleSheetsManager

def export_activity_participants_to_google_sheets(activity):
    """Экспорт данных участников активности в Google таблицу в один лист"""
    try:
        # Получаем всех участников активности
        participants = ActivityParticipant.objects.filter(activity=activity).select_related(
            'player', 'player_class__game_class'
        )
        
        if not participants.exists():
            return None
        
        # Подготавливаем данные для Google Sheets в нужном формате
        data = []
        for participant in participants:
            # Если активность была деактивирована, а участник все еще был в ней
            if not activity.is_active and not participant.completed_at:
                participant.completed_at = activity.updated_at
                participant.calculate_points()  # Пересчитываем очки
                participant.save()
            
            duration = participant.completed_at - participant.joined_at if participant.completed_at else timezone.now() - participant.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int((duration.total_seconds() % 60))
            
            # Рассчитываем коэффициент в секунду
            total_coefficient = activity.base_coefficient
            if not activity.ignore_odds:
                class_coefficient = activity.class_level_coefficients.filter(
                    game_class=participant.player_class.game_class,
                    min_level__lte=participant.player_class.level,
                    max_level__gte=participant.player_class.level
                ).first()
                if class_coefficient:
                    total_coefficient *= class_coefficient.coefficient
            
            # Формат: Дата активации | Участник | Класс | Уровень | Время начала | Время конца | Расчетное время | Коэффициент | Кол-во поинтов | Доп поинты | Активность
            data.append({
                'Дата создания': (activity.activated_at or activity.created_at).strftime('%d.%m.%Y %H:%M:%S'),
                'Участник': participant.player.game_nickname,
                'Класс': participant.player_class.game_class.name,
                'Уровень': participant.player_class.level,
                'Время начала': participant.joined_at.strftime('%H:%M:%S'),
                'Время конца': participant.completed_at.strftime('%H:%M:%S') if participant.completed_at else 'Не завершено',
                'Расчетное время': f"{hours}ч {minutes}м {seconds}с",
                'Коэффициент': round(total_coefficient, 2),
                'Кол-во поинтов': participant.points_earned,
                'Доп поинты': participant.additional_points,
                'Активность': activity.name
            })
        
        # Создаем экземпляр Google Sheets Manager
        sheets_manager = GoogleSheetsManager()
        
        # Записываем данные в Лист1
        success = sheets_manager.write_activity_data_to_sheet1(data)
        
        if success:
            # Удаляем сообщения о завершении активности у всех пользователей
            delete_completion_messages_for_all_users(activity.id)
            
            # Удаляем сообщения об активности у всех пользователей
            delete_activity_messages_for_all_users(activity.id)
            
            print(f"Данные активности '{activity.name}' успешно экспортированы в Google Sheets (Лист1)")
            return {
                'url': sheets_manager.get_spreadsheet_url(),
                'sheet_title': 'Лист1'
            }
        
        return None
        
    except Exception as e:
        print(f"Ошибка при экспорте данных в Google Sheets: {str(e)}")
        return None


class GameClass(models.Model):
    name = models.CharField(
        max_length=50,
        verbose_name='Название класса',
        unique=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Игровой класс'
        verbose_name_plural = 'Игровые классы'

    def get_base_coefficient_for_level(self, level):
        condition = self.base_coefficient_conditions.filter(min_level__lte=level, max_level__gte=level).first()
        if condition:
            return condition.coefficient
        return 1.0  # по умолчанию

class PlayerClass(models.Model):
    player = models.ForeignKey('Player', on_delete=models.CASCADE, related_name='player_classes', verbose_name='Игрок')
    game_class = models.ForeignKey(GameClass, on_delete=models.CASCADE, related_name='players', verbose_name='Игровой класс')
    level = models.IntegerField(default=1, verbose_name='Уровень')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Класс игрока'
        verbose_name_plural = 'Классы игроков'
        unique_together = ['player', 'game_class']

    def __str__(self):
        return f"{self.player} - {self.game_class} (уровень {self.level})"

class Player(models.Model):
    game_nickname = models.CharField(
        max_length=50,
        verbose_name='Имя игрока в игре',
        unique=True
    )
    telegram_id = models.CharField(
        max_length=50
    )
    tg_name = models.CharField(
        max_length=50,
        verbose_name='Имя игрока в телеграмм',
    )
    selected_class = models.ForeignKey(
        'PlayerClass',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='selected_by_players',
        verbose_name='Выбранный класс'
    )
    is_our_player = models.BooleanField(
        default=False,
        verbose_name='Является ли нашим игроком'
    )
    is_admin = models.BooleanField(default=False)
    activity_message_ids = models.JSONField(
        default=dict,
        verbose_name='ID сообщений об активностях',
        help_text='Словарь {activity_id: message_id} для отслеживания сообщений'
    )
    completion_message_ids = models.JSONField(
        default=dict,
        verbose_name='ID сообщений о завершении активностей',
        help_text='Словарь {activity_id: message_id} для отслеживания сообщений о завершении'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.game_nickname

    def get_all_classes(self):
        """Получить все классы игрока с их уровнями"""
        return self.player_classes.all()

    def get_selected_class(self):
        """Получить текущий выбранный класс игрока"""
        if self.selected_class:
            return {
                'class_name': self.selected_class.game_class.name,
                'level': self.selected_class.level
            }
        return None

    def get_available_classes(self):
        """Получить список всех доступных классов игрока"""
        return [{
            'class_name': pc.game_class.name,
            'level': pc.level
        } for pc in self.player_classes.all()]

    def add_activity_message(self, activity_id, message_id):
        """Добавить ID сообщения об активности"""
        if not self.activity_message_ids:
            self.activity_message_ids = {}
        self.activity_message_ids[str(activity_id)] = message_id
        self.save()

    def remove_activity_message(self, activity_id):
        """Удалить ID сообщения об активности"""
        if self.activity_message_ids and str(activity_id) in self.activity_message_ids:
            del self.activity_message_ids[str(activity_id)]
            self.save()

    def get_activity_message_id(self, activity_id):
        """Получить ID сообщения об активности"""
        return self.activity_message_ids.get(str(activity_id))

    def clear_all_activity_messages(self):
        """Очистить все ID сообщений об активностях"""
        self.activity_message_ids = {}
        self.save()

    def add_completion_message(self, activity_id, message_id):
        """Добавить ID сообщения о завершении активности"""
        if not self.completion_message_ids:
            self.completion_message_ids = {}
        self.completion_message_ids[str(activity_id)] = message_id
        self.save()

    def remove_completion_message(self, activity_id):
        """Удалить ID сообщения о завершении активности"""
        if self.completion_message_ids and str(activity_id) in self.completion_message_ids:
            del self.completion_message_ids[str(activity_id)]
            self.save()

    def get_completion_message_id(self, activity_id):
        """Получить ID сообщения о завершении активности"""
        return self.completion_message_ids.get(str(activity_id))

    def clear_all_completion_messages(self):
        """Очистить все ID сообщений о завершении активностей"""
        self.completion_message_ids = {}
        self.save()

    class Meta:
        verbose_name = 'Игрок'
        verbose_name_plural = 'Игроки'


class Activity(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name='Название активности'
    )
    description = models.TextField(
        verbose_name='Описание активности',
        null=True,
        blank=True
    )
    is_active = models.BooleanField(
        default=False,
        verbose_name='Активна'
    )
    ignore_odds = models.BooleanField(
        default=False,
        verbose_name='Игнорировать все коэфы кроме базового'
    )   
    base_coefficient = models.FloatField(
        default=1.0,
        verbose_name='Базовый коэффициент'
    )
    created_by = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='created_activities',
        verbose_name='Создатель'
    )
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Время активации активности'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    

    def __str__(self):
        return self.name

    def calculate_points(self, player_class, duration_seconds):
        """Расчет баллов за участие в активности с учетом коэффициентов класса и уровня"""
        # Начинаем с базового коэффициента активности
        total_coefficient = self.base_coefficient
        
        # Если не игнорируем коэффициенты, добавляем коэффициент класса и уровня
        if not self.ignore_odds:
            # Ищем коэффициент для данного класса и уровня в этой активности
            class_coefficient = self.class_level_coefficients.filter(
                game_class=player_class.game_class,
                min_level__lte=player_class.level,
                max_level__gte=player_class.level
            ).first()
            
            if class_coefficient:
                total_coefficient *= class_coefficient.coefficient
        
        return round(total_coefficient * duration_seconds, 2)

    class Meta:
        verbose_name = 'Активность'
        verbose_name_plural = 'Активности'

class ActivityParticipant(models.Model):
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name='Активность'
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='activities',
        verbose_name='Игрок'
    )
    player_class = models.ForeignKey(
        PlayerClass,
        on_delete=models.CASCADE,
        related_name='activity_participations',
        verbose_name='Класс игрока'
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    points_earned = models.FloatField(
        default=0,
        verbose_name='Заработанные баллы'
    )
    additional_points = models.FloatField(
        default=0,
        verbose_name='Дополнительные баллы'
    )

    def calculate_points(self):
        """Расчет баллов за участие"""
        if self.completed_at:
            duration = (self.completed_at - self.joined_at).total_seconds()
            self.points_earned = round(self.activity.calculate_points(self.player_class, duration), 2)
            self.save()
            return self.points_earned
        return 0

    @property
    def total_points(self):
        """Общее количество баллов (заработанные + дополнительные)"""
        return self.points_earned + self.additional_points

    @property
    def user(self):
        """Получить пользователя, связанного с игроком"""
        return self.player

    class Meta:
        verbose_name = 'Участник активности'
        verbose_name_plural = 'Участники активности'

    def __str__(self):
        return f"{self.player.game_nickname} - {self.activity.name}"

class ActivityHistory(models.Model):
    """Модель для хранения истории завершенных активностей"""
    original_activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name='history_records',
        verbose_name='Оригинальная активность'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='Название активности'
    )
    description = models.TextField(
        verbose_name='Описание активности',
        null=True,
        blank=True
    )
    base_coefficient = models.FloatField(
        default=1.0,
        verbose_name='Базовый коэффициент'
    )
    ignore_odds = models.BooleanField(
        default=False,
        verbose_name='Игнорировать все коэфы кроме базового'
    )
    created_by = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='created_activity_histories',
        verbose_name='Создатель'
    )
    activity_started_at = models.DateTimeField(
        verbose_name='Время начала активности'
    )
    activity_ended_at = models.DateTimeField(
        verbose_name='Время окончания активности'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_exported = models.BooleanField(
        default=False,
        verbose_name='Экспортировано в Google Sheets'
    )

    def __str__(self):
        return f"{self.name} ({self.activity_started_at.strftime('%d.%m.%Y %H:%M')})"

    class Meta:
        verbose_name = 'История активности'
        verbose_name_plural = 'История активностей'
        ordering = ['-activity_ended_at']

class ActivityHistoryParticipant(models.Model):
    """Участники в истории активности с возможностью редактирования"""
    activity_history = models.ForeignKey(
        ActivityHistory,
        on_delete=models.CASCADE,
        related_name='participants',
        verbose_name='История активности'
    )
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name='activity_history_participations',
        verbose_name='Игрок'
    )
    player_class = models.ForeignKey(
        PlayerClass,
        on_delete=models.CASCADE,
        related_name='activity_history_participations',
        verbose_name='Класс игрока'
    )
    joined_at = models.DateTimeField(
        verbose_name='Время начала участия'
    )
    completed_at = models.DateTimeField(
        verbose_name='Время окончания участия'
    )
    points_earned = models.FloatField(
        default=0,
        verbose_name='Заработанные баллы'
    )
    additional_points = models.FloatField(
        default=0,
        verbose_name='Дополнительные баллы'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_points(self):
        """Общее количество баллов (заработанные + дополнительные)"""
        return self.points_earned + self.additional_points

    @property
    def duration(self):
        """Длительность участия"""
        return self.completed_at - self.joined_at

    def __str__(self):
        return f"{self.player.game_nickname} - {self.activity_history.name}"

    class Meta:
        verbose_name = 'Участник истории активности'
        verbose_name_plural = 'Участники истории активности'

@receiver(post_save, sender=Activity)
def notify_users_about_activity(sender, instance, created, **kwargs):
    """Удаление старых сообщений об активности при создании новой активности"""
    if created and instance.is_active:  # Только при создании новой активной активности
        def delete_old_messages():
            players = Player.objects.all()
            for player in players:
                try:
                    # Удаляем старые сообщения об активности, если они есть
                    old_message_id = player.get_activity_message_id(instance.id)
                    if old_message_id:
                        try:
                            bot.delete_message(chat_id=player.telegram_id, message_id=old_message_id)
                            print(f"Удалено старое сообщение об активности {old_message_id} для игрока {player.game_nickname}")
                        except Exception as e:
                            print(f"Ошибка при удалении старого сообщения об активности {old_message_id} для игрока {player.game_nickname}: {e}")
                        finally:
                            player.remove_activity_message(instance.id)
                except Exception as e:
                    print(f"Ошибка при обработке игрока {player.game_nickname}: {str(e)}")
        
        # Запускаем удаление старых сообщений
        delete_old_messages()

@receiver(pre_save, sender=Activity)
def handle_activity_status_change(sender, instance, **kwargs):
    """Обработчик изменения статуса активности"""
    if instance.pk:  # Проверяем, что это существующая запись
        try:
            old_instance = Activity.objects.get(pk=instance.pk)
            
            # Если активность была неактивна и стала активной
            if not old_instance.is_active and instance.is_active:
                # Устанавливаем время активации
                instance.activated_at = timezone.now()
                
                def delete_old_messages():
                    players = Player.objects.all()
                    for player in players:
                        try:
                            # Удаляем старые сообщения об активности, если они есть
                            old_message_id = player.get_activity_message_id(instance.id)
                            if old_message_id:
                                try:
                                    bot.delete_message(chat_id=player.telegram_id, message_id=old_message_id)
                                    print(f"Удалено старое сообщение об активности {old_message_id} для игрока {player.game_nickname}")
                                except Exception as e:
                                    print(f"Ошибка при удалении старого сообщения об активности {old_message_id} для игрока {player.game_nickname}: {e}")
                                finally:
                                    player.remove_activity_message(instance.id)
                        except Exception as e:
                            print(f"Ошибка при обработке игрока {player.game_nickname}: {str(e)}")
                
                # Запускаем удаление старых сообщений
                delete_old_messages()
            
            # Если активность была активна и стала неактивной
            elif old_instance.is_active and not instance.is_active:
                # Удаляем сообщения об активности у всех игроков
                def delete_activity_messages():
                    players = Player.objects.all()
                    for player in players:
                        try:
                            # Получаем ID сообщения об активности
                            message_id = player.get_activity_message_id(instance.id)
                            if message_id:
                                try:
                                    # Удаляем сообщение через Telegram API
                                    bot.delete_message(chat_id=player.telegram_id, message_id=message_id)
                                    print(f"Удалено сообщение об активности {message_id} для игрока {player.game_nickname}")
                                except Exception as e:
                                    print(f"Ошибка при удалении сообщения об активности {message_id} для игрока {player.game_nickname}: {e}")
                                finally:
                                    # Удаляем ID из базы данных
                                    player.remove_activity_message(instance.id)
                        except Exception as e:
                            print(f"Ошибка при обработке игрока {player.game_nickname}: {str(e)}")
                
                # Запускаем удаление сообщений
                delete_activity_messages()
                
                try:
                    # Обновляем время завершения для всех активных участников
                    active_participants = ActivityParticipant.objects.filter(
                        activity=instance,
                        completed_at__isnull=True
                    )
                    
                    # Устанавливаем время завершения и пересчитываем очки
                    for participant in active_participants:
                        participant.completed_at = timezone.now()
                        participant.calculate_points()
                        participant.save()
                    
                    # Создаем запись в истории активностей
                    create_activity_history_record(instance)
                    
                except Exception as e:
                    print(f"Ошибка при создании записи истории: {str(e)}")
                
                # Удаляем все записи об участии
                ActivityParticipant.objects.filter(activity=instance).delete()
                
        except Activity.DoesNotExist:
            pass

def create_activity_history_record(activity):
    """Создание записи в истории активностей при завершении активности"""
    try:
        # Создаем запись истории активности с уникальным временем завершения
        history_record = ActivityHistory.objects.create(
            original_activity=activity,
            name=activity.name,
            description=activity.description,
            base_coefficient=activity.base_coefficient,
            ignore_odds=activity.ignore_odds,
            created_by=activity.created_by,
            activity_started_at=activity.activated_at or activity.created_at,
            activity_ended_at=timezone.now()
        )
        
        # Копируем всех участников в историю
        participants = ActivityParticipant.objects.filter(activity=activity)
        for participant in participants:
            ActivityHistoryParticipant.objects.create(
                activity_history=history_record,
                player=participant.player,
                player_class=participant.player_class,
                joined_at=participant.joined_at,
                completed_at=participant.completed_at or timezone.now(),
                points_earned=participant.points_earned,
                additional_points=participant.additional_points
            )
        
        print(f"Создана запись истории для активности {activity.name}")
        
    except Exception as e:
        print(f"Ошибка при создании записи истории: {str(e)}")

def export_activity_history_to_google_sheets(activity_history):
    """Экспорт данных участников истории активности в Google таблицу в один лист"""
    try:
        # Получаем всех участников истории активности
        participants = ActivityHistoryParticipant.objects.filter(
            activity_history=activity_history
        ).select_related('player', 'player_class__game_class')
        
        if not participants.exists():
            return None
        
        # Подготавливаем данные для Google Sheets в нужном формате
        data = []
        for participant in participants:
            duration = participant.completed_at - participant.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int((duration.total_seconds() % 60))
            
            # Рассчитываем коэффициент в секунду
            total_coefficient = activity_history.base_coefficient
            if not activity_history.ignore_odds:
                # Получаем оригинальную активность для доступа к коэффициентам классов
                if activity_history.original_activity:
                    class_coefficient = activity_history.original_activity.class_level_coefficients.filter(
                        game_class=participant.player_class.game_class,
                        min_level__lte=participant.player_class.level,
                        max_level__gte=participant.player_class.level
                    ).first()
                    if class_coefficient:
                        total_coefficient *= class_coefficient.coefficient
            
            # Формат: Дата активации | Участник | Класс | Уровень | Время начала | Время конца | Расчетное время | Коэффициент | Кол-во поинтов | Доп поинты | Активность
            data.append({
                'Дата создания': activity_history.activity_started_at.strftime('%d.%m.%Y %H:%M:%S'),
                'Участник': participant.player.game_nickname,
                'Класс': participant.player_class.game_class.name,
                'Уровень': participant.player_class.level,
                'Время начала': participant.joined_at.strftime('%H:%M:%S'),
                'Время конца': participant.completed_at.strftime('%H:%M:%S'),
                'Расчетное время': f"{hours}ч {minutes}м {seconds}с",
                'Коэффициент': round(total_coefficient, 2),
                'Кол-во поинтов': participant.points_earned,
                'Доп поинты': participant.additional_points,
                'Активность': activity_history.name
            })
        
        # Создаем экземпляр Google Sheets Manager
        sheets_manager = GoogleSheetsManager()
        
        # Записываем данные в Лист1
        success = sheets_manager.write_activity_data_to_sheet1(data)
        
        if success:
            # Удаляем сообщения о завершении активности у всех пользователей
            if activity_history.original_activity:
                delete_completion_messages_for_all_users(activity_history.original_activity.id)
            
            # Удаляем сообщения об активности у всех пользователей
            if activity_history.original_activity:
                delete_activity_messages_for_all_users(activity_history.original_activity.id)
            
            print(f"Данные активности '{activity_history.name}' успешно экспортированы в Google Sheets (Лист1)")
            return {
                'url': sheets_manager.get_spreadsheet_url(),
                'sheet_title': 'Лист1'
            }
        
        return None
        
    except Exception as e:
        print(f"Ошибка при экспорте данных в Google Sheets: {str(e)}")
        return None
    

class GameClassBaseCoefficientCondition(models.Model):
    game_class = models.ForeignKey(GameClass, on_delete=models.CASCADE, related_name='base_coefficient_conditions', verbose_name='Игровой класс')
    min_level = models.IntegerField(verbose_name='Минимальный уровень')
    max_level = models.IntegerField(verbose_name='Максимальный уровень')
    coefficient = models.FloatField(verbose_name='Коэффициент')

    class Meta:
        verbose_name = 'Условие базового коэффициента'
        verbose_name_plural = 'Условия базового коэффициента'
        unique_together = ['game_class', 'min_level', 'max_level']

    def __str__(self):
        return f"{self.game_class.name}: {self.min_level}-{self.max_level} -> {self.coefficient}"  

class ActivityClassLevelCoefficient(models.Model):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='class_level_coefficients', verbose_name='Активность')
    game_class = models.ForeignKey(GameClass, on_delete=models.CASCADE, verbose_name='Игровой класс')
    min_level = models.IntegerField(verbose_name='Минимальный уровень')
    max_level = models.IntegerField(verbose_name='Максимальный уровень')
    coefficient = models.FloatField(verbose_name='Коэффициент')

    class Meta:
        verbose_name = 'Коэффициент класса для активности'
        verbose_name_plural = 'Коэффициенты классов для активности'
        unique_together = ['activity', 'game_class', 'min_level', 'max_level']

    def __str__(self):
        return f"{self.activity.name} | {self.game_class.name}: {self.min_level}-{self.max_level} -> {self.coefficient}"

# Сигнал для автоматического копирования коэффициентов при создании активности
@receiver(post_save, sender=Activity)
def create_activity_class_level_coefficients(sender, instance, created, **kwargs):
    if created:
        for game_class in GameClass.objects.all():
            for cond in game_class.base_coefficient_conditions.all():
                ActivityClassLevelCoefficient.objects.create(
                    activity=instance,
                    game_class=game_class,
                    min_level=cond.min_level,
                    max_level=cond.max_level,
                    coefficient=cond.coefficient
                )
    
def delete_activity_messages_for_all_users(activity_id):
    """Удалить сообщения об активности у всех пользователей"""
    try:
        players = Player.objects.all()
        for player in players:
            message_id = player.get_activity_message_id(activity_id)
            if message_id:
                try:
                    bot.delete_message(chat_id=player.telegram_id, message_id=message_id)
                except Exception as e:
                    print(f"Ошибка при удалении сообщения {message_id} для пользователя {player.telegram_id}: {e}")
                finally:
                    player.remove_activity_message(activity_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщений об активности {activity_id}: {e}")

def delete_completion_messages_for_all_users(activity_id):
    """Удалить сообщения о завершении активности у всех пользователей"""
    try:
        players = Player.objects.all()
        for player in players:
            message_id = player.get_completion_message_id(activity_id)
            if message_id:
                try:
                    bot.delete_message(chat_id=player.telegram_id, message_id=message_id)
                except Exception as e:
                    print(f"Ошибка при удалении сообщения о завершении {message_id} для пользователя {player.telegram_id}: {e}")
                finally:
                    player.remove_completion_message(activity_id)
    except Exception as e:
        print(f"Ошибка при удалении сообщений о завершении активности {activity_id}: {e}")

def delete_activity_history_from_google_sheets(activity_history):
    """Удаление данных активности из Google Sheets"""
    try:
        # Создаем экземпляр Google Sheets Manager
        sheets_manager = GoogleSheetsManager()
        
        # Удаляем данные активности из Лист1
        success = sheets_manager.delete_activity_data_from_sheet1(activity_history)
        
        return success
        
    except Exception as e:
        print(f"Ошибка при удалении данных из Google Sheets: {str(e)}")
        return False
    
def export_active_activity_to_google_sheets(activity):
    """Экспорт данных активной активности в Google таблицу с удалением сообщений"""
    try:
        # Получаем всех участников активности
        participants = ActivityParticipant.objects.filter(activity=activity).select_related(
            'player', 'player_class__game_class'
        )
        
        if not participants.exists():
            return None
        
        # Подготавливаем данные для Google Sheets в нужном формате
        data = []
        for participant in participants:
            # Если участник не завершил активность, завершаем её принудительно
            if not participant.completed_at:
                participant.completed_at = timezone.now()
                participant.calculate_points()  # Пересчитываем очки
                participant.save()
            
            duration = participant.completed_at - participant.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int((duration.total_seconds() % 60))
            
            # Рассчитываем коэффициент в секунду
            total_coefficient = activity.base_coefficient
            if not activity.ignore_odds:
                class_coefficient = activity.class_level_coefficients.filter(
                    game_class=participant.player_class.game_class,
                    min_level__lte=participant.player_class.level,
                    max_level__gte=participant.player_class.level
                ).first()
                if class_coefficient:
                    total_coefficient *= class_coefficient.coefficient
            
            # Формат: Дата активации | Участник | Класс | Уровень | Время начала | Время конца | Расчетное время | Коэффициент | Кол-во поинтов | Доп поинты | Активность
            data.append({
                'Дата создания': (activity.activated_at or activity.created_at).strftime('%d.%m.%Y %H:%M:%S'),
                'Участник': participant.player.game_nickname,
                'Класс': participant.player_class.game_class.name,
                'Уровень': participant.player_class.level,
                'Время начала': participant.joined_at.strftime('%H:%M:%S'),
                'Время конца': participant.completed_at.strftime('%H:%M:%S'),
                'Расчетное время': f"{hours}ч {minutes}м {seconds}с",
                'Коэффициент': round(total_coefficient, 2),
                'Кол-во поинтов': participant.points_earned,
                'Доп поинты': participant.additional_points,
                'Активность': activity.name
            })
        
        # Создаем экземпляр Google Sheets Manager
        sheets_manager = GoogleSheetsManager()
        
        # Записываем данные в Лист1
        success = sheets_manager.write_activity_data_to_sheet1(data)
        
        if success:
            # Удаляем сообщения о завершении активности у всех пользователей
            delete_completion_messages_for_all_users(activity.id)
            
            # Удаляем сообщения об активности у всех пользователей
            delete_activity_messages_for_all_users(activity.id)
            
            print(f"Данные активности '{activity.name}' успешно экспортированы в Google Sheets (Лист1)")
            return {
                'url': sheets_manager.get_spreadsheet_url(),
                'sheet_title': 'Лист1'
            }
        
        return None
        
    except Exception as e:
        print(f"Ошибка при экспорте данных в Google Sheets: {str(e)}")
        return None
    