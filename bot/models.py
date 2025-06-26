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
    """Экспорт данных участников активности в Google таблицу"""
    try:
        # Получаем всех участников активности
        participants = ActivityParticipant.objects.filter(activity=activity).select_related(
            'player', 'player_class__game_class'
        )
        
        if not participants.exists():
            return None
        
        # Подготавливаем данные для Google Sheets
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
            seconds = int(duration.total_seconds() % 60)
            
            data.append({
                'Игрок': participant.player.game_nickname,
                'Класс': f"{participant.player_class.game_class.name} (Уровень {participant.player_class.level})",
                'Время начала': participant.joined_at.strftime('%d.%m.%Y %H:%M'),
                'Время окончания': participant.completed_at.strftime('%d.%m.%Y %H:%M') if participant.completed_at else 'Не завершено',
                'Длительность': f"{hours}ч {minutes}м {seconds}с",
                'Заработано баллов': participant.points_earned
            })
        
        # Создаем экземпляр Google Sheets Manager
        sheets_manager = GoogleSheetsManager()
        # Создаем новый лист для активности с датой
        sheet_title = sheets_manager.create_activity_sheet(f"{activity.name}")
        
        if not sheet_title:
            return None
        
        # Записываем данные в таблицу
        success = sheets_manager.write_activity_data(sheet_title, data)
        
        if success:
            return {
                'url': sheets_manager.get_spreadsheet_url(),
                'sheet_title': sheet_title
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    

    def __str__(self):
        return self.name

    def calculate_points(self, player_class, duration_seconds):
        """Расчет баллов за участие в активности с учётом условий и флага ignore_odds"""
        if self.ignore_odds:
            return round(self.base_coefficient * duration_seconds, 2)
        # Ищем условие для класса и уровня
        condition = player_class.game_class.base_coefficient_conditions.filter(
            level_min__lte=player_class.level,
            level_max__gte=player_class.level
        ).first()
        coef = condition.coefficient if condition else 1.0
        return round(self.base_coefficient * coef * duration_seconds, 2)

    def notify_participants_about_completion(self):
        """Отправка уведомлений участникам о принудительном завершении активности"""
        active_participants = ActivityParticipant.objects.filter(
            activity=self,
            completed_at__isnull=True
        ).select_related('player', 'player_class')

        for participant in active_participants:
            try:
                # Завершаем участие
                participant.completed_at = timezone.now()
                participant.save()
                
                # Рассчитываем баллы
                points = participant.calculate_points(participant.player_class, (timezone.now() - participant.joined_at).total_seconds())
                
                # Формируем сообщение
                duration = participant.completed_at - participant.joined_at
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int(duration.total_seconds() % 60)
                
                text = (
                    f"*Активность была деактивирована администратором*\n\n"
                    f"Активность: {self.name}\n"
                    f"Класс: {participant.player_class.game_class.name} (Уровень {participant.player_class.level})\n"
                    f"Время участия: {hours}ч {minutes}м {seconds}с\n"
                    f"Заработано баллов: {points}\n"
                )
                
                # Отправляем сообщение
                bot.send_message(
                    chat_id=participant.player.telegram_id,
                    text=text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                print(f"Ошибка при отправке уведомления участнику {participant.player.game_nickname}: {str(e)}")

    class Meta:
        verbose_name = 'Активность'
        verbose_name_plural = 'Активности'

class ActivityClassCoefficient(models.Model):
    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name='class_coefficients',
        verbose_name='Активность'
    )
    game_class = models.ForeignKey(
        GameClass,
        on_delete=models.CASCADE,
        related_name='activity_coefficients',
        verbose_name='Игровой класс'
    )
    coefficient = models.FloatField(
        default=1.0,
        verbose_name='Коэффициент'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Коэффициент класса активности'
        verbose_name_plural = 'Коэффициенты классов активности'
        unique_together = ['activity', 'game_class']

    def __str__(self):
        return f"{self.activity.name} - {self.game_class.name}: {self.coefficient}"

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

    def calculate_points(self):
        """Расчет баллов за участие"""
        if self.completed_at:
            duration = (self.completed_at - self.joined_at).total_seconds()
            self.points_earned = self.activity.calculate_points(self.player_class, duration)
            self.save()
            return self.points_earned
        return 0

    @property
    def user(self):
        """Получить пользователя, связанного с игроком"""
        return self.player

    class Meta:
        verbose_name = 'Участник активности'
        verbose_name_plural = 'Участники активности'
        unique_together = ['activity', 'player']

    def __str__(self):
        return f"{self.player.game_nickname} - {self.activity.name}"

@receiver(post_save, sender=Activity)
def notify_users_about_activity(sender, instance, created, **kwargs):
    """Отправка уведомлений всем пользователям при создании новой активности"""
    if created and instance.is_active:  # Отправляем уведомления только при создании новой активной активности
        def send_notifications():
            players = Player.objects.all()
            for player in players:
                try:
                    keyboard = InlineKeyboardMarkup()
                    keyboard.add(
                        InlineKeyboardButton(
                            text="Принять участие",
                            callback_data=f"join_activity_{instance.id}"
                        )
                    )
                    
                    bot.send_message(
                        chat_id=player.telegram_id,
                        text=f"🎮 *Новая активность!*\n\n"
                             f"*{instance.name}*\n"
                             f"{instance.description or 'Нет описания'}\n\n"
                             f"Нажмите кнопку ниже, чтобы принять участие!",
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                except Exception as e:
                    print(f"Ошибка при отправке уведомления пользователю {player.telegram_id}: {str(e)}")
        
        # Запускаем отправку уведомлений
        send_notifications()

@receiver(pre_save, sender=Activity)
def handle_activity_status_change(sender, instance, **kwargs):
    """Обработчик изменения статуса активности"""
    if instance.pk:  # Проверяем, что это существующая запись
        try:
            old_instance = Activity.objects.get(pk=instance.pk)
            
            # Если активность была неактивна и стала активной
            if not old_instance.is_active and instance.is_active:
                def send_activation_notifications():
                    players = Player.objects.all()
                    for player in players:
                        try:
                            keyboard = InlineKeyboardMarkup()
                            keyboard.add(
                                InlineKeyboardButton(
                                    text="Принять участие",
                                    callback_data=f"join_activity_{instance.id}"
                                )
                            )
                            
                            bot.send_message(
                                chat_id=player.telegram_id,
                                text=f"🎮 *Активность активирована!*\n\n"
                                     f"*{instance.name}*\n"
                                     f"{instance.description or 'Нет описания'}\n\n"
                                     f"Нажмите кнопку ниже, чтобы принять участие!",
                                parse_mode='Markdown',
                                reply_markup=keyboard
                            )
                        except Exception as e:
                            print(f"Ошибка при отправке уведомления пользователю {player.telegram_id}: {str(e)}")
                
                # Запускаем отправку уведомлений
                send_activation_notifications()
            
            # Если активность была активна и стала неактивной
            elif old_instance.is_active and not instance.is_active:
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
                    
                    # Экспортируем данные в Google Sheets
                    google_sheets_data = export_activity_participants_to_google_sheets(instance)
                    
                    if google_sheets_data:
                        # Получаем всех админов
                        admins = Player.objects.filter(is_admin=True)
                        
                        # Отправляем ссылку на Google таблицу всем админам
                        for admin in admins:
                            try:
                                text = (
                                    f"📊 *Отчет по активности '{instance.name}'*\n\n"
                                    f"Время деактивации: {timezone.now().strftime('%d.%m.%Y %H:%M')}\n"
                                    f"Лист: {google_sheets_data['sheet_title']}\n\n"
                                    f"Ссылка на таблицу: {google_sheets_data['url']}"
                                )
                                
                                bot.send_message(
                                    chat_id=admin.telegram_id,
                                    text=text,
                                    parse_mode='Markdown'
                                )
                            except Exception as e:
                                print(f"Ошибка при отправке ссылки на Google таблицу админу {admin.telegram_id}: {str(e)}")
                            
                except Exception as e:
                    print(f"Ошибка при экспорте данных в Google Sheets: {str(e)}")
                
                # Уведомляем участников о завершении
                instance.notify_participants_about_completion()
                
                # Удаляем все записи об участии
                ActivityParticipant.objects.filter(activity=instance).delete()
                
        except Activity.DoesNotExist:
            pass
    

class ActivityClassLevelCoefficient(models.Model):
    activity = models.ForeignKey('Activity', on_delete=models.CASCADE, related_name='class_level_coefficients', verbose_name='Активность')
    game_class = models.ForeignKey(GameClass, on_delete=models.CASCADE, verbose_name='Игровой класс')
    level_min = models.PositiveIntegerField(verbose_name='Минимальный уровень (включительно)')
    level_max = models.PositiveIntegerField(verbose_name='Максимальный уровень (включительно)')
    coefficient = models.FloatField(verbose_name='Коэффициент для активности')

    class Meta:
        verbose_name = 'Коэффициент класса и уровня для активности'
        verbose_name_plural = 'Коэффициенты классов и уровней для активности'
        unique_together = ['activity', 'game_class', 'level_min', 'level_max']
        ordering = ['game_class', 'level_min']

    def __str__(self):
        return f"{self.game_class.name}: {self.level_min}-{self.level_max} (коэф. {self.coefficient})"
    
