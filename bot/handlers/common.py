import os
import json
import random
from datetime import timedelta
from django.utils import timezone
from bot import bot
from django.conf import settings
from telebot.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)
from bot.models import Player, GameClass, PlayerClass, Activity, ActivityParticipant
from bot.keyboards import PROFILE_BUTTONS
from .registration import start_registration
from functools import wraps
from telebot.apihelper import ApiTelegramException
from telebot import TeleBot

# Хранилище последних сообщений пользователя (user_id: [message_id, ...])
user_last_messages = {}

# Получаем id бота для проверки, кто отправил сообщение
BOT_ID = None

# Хранилище id сообщения об активности для каждого пользователя
user_active_activity_message = {}

def get_bot_id():
    global BOT_ID
    if BOT_ID is None:
        BOT_ID = bot.get_me().id
    return BOT_ID

# Удаление предыдущих сообщений пользователя
def delete_previous_messages(user_id, exclude_message_id=None):
    ids = user_last_messages.get(user_id, [])
    for mid in ids:
        if exclude_message_id and mid == exclude_message_id:
            continue
        try:
            bot.delete_message(chat_id=user_id, message_id=mid)
        except ApiTelegramException as e:
            if 'message to delete not found' in str(e):
                continue
            else:
                print(f"Ошибка при удалении сообщения: {e}")
    user_last_messages[user_id] = []

# Обновление id последнего сообщения
def remember_message(user_id, message_id):
    if user_id not in user_last_messages:
        user_last_messages[user_id] = []
    user_last_messages[user_id].append(message_id)

def start(message: Message) -> None:
    """Обработчик команды /start"""
    user_id = message.from_user.id
    fake_call = type('FakeCall', (), {'from_user': message.from_user, 'message': message})
    profile(fake_call)


def only_our_player(func):
    @wraps(func)
    def wrapper(call, *args, **kwargs):
        user_id = str(call.from_user.id)
        try:
            player = Player.objects.get(telegram_id=user_id)
            if not player.is_our_player:
                bot.send_message(user_id, 'Доступ запрещён. Вы не являетесь нашим игроком.')
                return
        except Player.DoesNotExist:
            bot.send_message(user_id, 'Вы не зарегистрированы. Используйте /start.')
            return
        return func(call, *args, **kwargs)
    return wrapper


@only_our_player
def profile(call: CallbackQuery):
    user_id = str(call.from_user.id)
    try:
        player = Player.objects.get(telegram_id=user_id)
        # Профиль
        user_info = (
            f"👤 *Информация о пользователе*\n\n"
            f"Игровой никнейм: {player.game_nickname}\n"
            f"Telegram: @{player.tg_name}\n"
            f"Статус: {'Администратор' if player.is_admin else 'Игрок'}\n"
            f"Дата регистрации: {player.created_at.strftime('%d.%m.%Y')}\n\n"
        )
        player_classes = player.get_available_classes()
        if player_classes:
            user_info += "*Ваши классы:*\n"
            for class_info in player_classes:
                user_info += (
                    f"• {class_info['class_name']} (Уровень {class_info['level']})\n"
                )
        else:
            user_info += "У вас пока нет классов\n"
        selected_class = player.get_selected_class()
        if selected_class:
            user_info += f"\n*Текущий выбранный класс:*\n"
            user_info += (
                f"• {selected_class['class_name']} (Уровень {selected_class['level']})\n"
            )
        msg = bot.send_message(
            chat_id=user_id,
            text=user_info,
            parse_mode='Markdown',
            reply_markup=PROFILE_BUTTONS
        )
        # Активности (активная и завершённые) - показываем каждое участие отдельно
        participations = ActivityParticipant.objects.filter(player=player).select_related('activity', 'player_class').order_by('-joined_at')
        
        # Показываем каждое участие отдельно
        for part in participations:
            activity = part.activity
            
            if not part.completed_at:
                # Активное участие
                duration = timezone.now() - part.joined_at
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int((duration.total_seconds() % 60))
                text = (
                    f"🟢 *Активная активность*\n"
                    f"{activity.name}\n"
                    f"Время старта активности: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"Класс: {part.player_class.game_class.name} (Уровень {part.player_class.level})\n"
                    f"Время участия: {hours}ч {minutes}м {seconds}с\n"
                    f"Время начала участия: {part.joined_at.strftime('%d.%m.%Y %H:%M')}\n"
                )
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🔴 Завершить участие", callback_data=f"leave_activity_{activity.id}_{part.player_class.id}"))
                msg = bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            else:
                # Завершенное участие
                duration = part.completed_at - part.joined_at
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int((duration.total_seconds() % 60))
                text = (
                    f"🔴 *Участие завершено*\n\n"
                    f"Активность: {activity.name}\n"
                    f"Время старта активности: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"Класс: {part.player_class.game_class.name} (Уровень {part.player_class.level})\n"
                    f"Время участия: {hours}ч {minutes}м {seconds}с\n"
                    f"Заработано баллов: {part.points_earned}\n\n"
                    f"📊 *Детали участия:*\n"
                    f"• Время начала: {part.joined_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"• Время завершения: {part.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"• Общая длительность: {hours}ч {minutes}м {seconds}с\n"
                    f"• Баллы за участие: {part.points_earned}"
                )
                
                # Если активность еще активна, предлагаем продолжить участие
                if activity.is_active:
                    text += f"\n\n🔄 *Хотите участвовать еще раз?*"
                    keyboard = InlineKeyboardMarkup()
                    keyboard.add(InlineKeyboardButton("🟢 Участвовать снова", callback_data=f"join_activity_{activity.id}"))
                    msg = bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                else:
                    # Активность завершена администратором
                    text += f"\n\n🔴 *Активность была завершена администратором*"
                    msg = bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode='Markdown'
                    )
        
        # Показываем доступные активности (все активные активности)
        for activity in Activity.objects.filter(is_active=True):
            text = (
                f"⚪ *Доступная активность*\n"
                f"{activity.name}\n"
                f"Доступно классов для участия: {player.player_classes.count()}"
            )
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🟢 Принять участие", callback_data=f"join_activity_{activity.id}"))
            msg = bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
    except Exception as e:
        # Ошибки не создают новых сообщений
        pass

def show_classes(call: CallbackQuery, page: int = 1):
    """Показать список всех доступных классов с пагинацией (только те, что есть у игрока)"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    try:
        player = Player.objects.get(telegram_id=user_id)
        player_classes = player.player_classes.select_related('game_class').all()
        classes_per_page = 4
        total_classes = player_classes.count()
        total_pages = (total_classes + classes_per_page - 1) // classes_per_page
        start_idx = (page - 1) * classes_per_page
        end_idx = start_idx + classes_per_page
        current_page_classes = player_classes[start_idx:end_idx]
        keyboard = InlineKeyboardMarkup(row_width=2)
        for pc in current_page_classes:
            keyboard.add(
                InlineKeyboardButton(
                    text=pc.game_class.name,
                    callback_data=f"select_class_{pc.game_class.id}"
                )
            )
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Предыдущая",
                    callback_data=f"classes_page_{page-1}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text="🔽Профиль🔽", callback_data="profile")
        )
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Следующая ➡️",
                    callback_data=f"classes_page_{page+1}"
                )
            )
        keyboard.row(*nav_buttons)
        text = f"Выберите класс (Страница {page} из {total_pages}):"
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard
        )
    except Player.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при получении списка классов."
        )
        print(f"Ошибка при получении списка классов: {str(e)}")

def handle_classes_pagination(call: CallbackQuery):
    """Обработка пагинации списка классов"""
    try:
        # Получаем номер страницы из callback_data
        page = int(call.data.split('_')[2])
        show_classes(call, page)
    except Exception as e:
        bot.edit_message_text(
            chat_id=call.from_user.id,
            message_id=call.message.message_id,
            text="Произошла ошибка при переключении страницы."
        )
        print(f"Ошибка при пагинации классов: {str(e)}")


def changeLvlClassMarkup(call: CallbackQuery, page: int = 1):
    """Показать список классов для изменения уровня с пагинацией"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    try:
        player = Player.objects.get(telegram_id=user_id)
        # Получаем только PlayerClass игрока
        player_classes = player.player_classes.select_related('game_class').all()
        classes_per_page = 4
        total_classes = player_classes.count()
        total_pages = (total_classes + classes_per_page - 1) // classes_per_page
        start_idx = (page - 1) * classes_per_page
        end_idx = start_idx + classes_per_page
        current_page_classes = player_classes[start_idx:end_idx]
        keyboard = InlineKeyboardMarkup(row_width=2)
        for pc in current_page_classes:
            keyboard.add(
                InlineKeyboardButton(
                    text=pc.game_class.name,
                    callback_data=f"change_lvl_{pc.game_class.id}"
                )
            )
        nav_buttons = []
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Предыдущая",
                    callback_data=f"change_page_lvl_{page-1}"
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(text="🔽Профиль🔽", callback_data="profile")
        )
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Следующая ➡️",
                    callback_data=f"change_page_lvl_{page+1}"
                )
            )
        keyboard.row(*nav_buttons)
        text = f"Выберите класс для изменения уровня (Страница {page} из {total_pages}):"
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard
        )
    except Player.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при получении списка классов."
        )
        print(f"Ошибка при получении списка классов: {str(e)}")

def handle_change_level_pagination(call: CallbackQuery):
    """Обработка пагинации списка классов при изменении уровня"""
    try:
        # Получаем номер страницы из callback_data
        page = int(call.data.split('_')[3])
        changeLvlClassMarkup(call, page)
    except Exception as e:
        bot.edit_message_text(
            chat_id=call.from_user.id,
            message_id=call.message.message_id,
            text="Произошла ошибка при переключении страницы."
        )
        print(f"Ошибка при пагинации классов: {str(e)}")

def handle_change_level(call: CallbackQuery):
    """Обработка выбора класса для изменения уровня"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем ID выбранного класса из callback_data
        class_id = int(call.data.split('_')[2])
        
        # Получаем пользователя и игрока
        player = Player.objects.get(telegram_id=str(call.from_user.id))
        
        # Получаем выбранный класс
        game_class = GameClass.objects.get(id=class_id)
        player_class = PlayerClass.objects.get(player=player, game_class=game_class)
        
        # Создаем клавиатуру для возврата
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton(text="◀️ Отмена", callback_data="cancel_level_change"))
        
        # Отправляем сообщение с запросом нового уровня
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=f"Текущий уровень класса {game_class.name}: {player_class.level}\n"
                 f"Введите новый уровень (целое число):",
            reply_markup=keyboard
        )
        
        # Сохраняем ID класса в состоянии бота для последующей обработки
        bot.register_next_step_handler(call.message, process_new_level, class_id)
        
    except Player.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except GameClass.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Ошибка: выбранный класс не найден."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при выборе класса."
        )
        print(f"Ошибка при выборе класса: {str(e)}")

def process_new_level(message: Message, class_id: int):
    """Обработка введенного нового уровня"""
    user_id = str(message.from_user.id)
    
    try:
        # Проверяем, что введено целое число
        try:
            new_level = int(message.text)
            if new_level < 1:
                raise ValueError("Уровень должен быть положительным числом")
        except ValueError:
            bot.send_message(
                chat_id=user_id,
                text="Пожалуйста, введите корректное целое число больше 0.",
                reply_markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")
                )
            )
            return
        
        # Получаем пользователя и игрока
        player = Player.objects.get(telegram_id=str(message.from_user.id))
        
        # Получаем класс игрока
        game_class = GameClass.objects.get(id=class_id)
        player_class = PlayerClass.objects.get(player=player, game_class=game_class)
        
        # Обновляем уровень
        player_class.level = new_level
        player_class.save()
        
        # Отправляем сообщение об успешном обновлении
        bot.send_message(
            chat_id=user_id,
            text=f"Уровень класса {game_class.name} успешно изменен на {new_level}",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton(text="◀️ Назад в профиль", callback_data="profile")
            )
        )
        
    except Player.DoesNotExist:
        bot.send_message(
            chat_id=user_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except GameClass.DoesNotExist:
        bot.send_message(
            chat_id=user_id,
            text="Ошибка: выбранный класс не найден."
        )
    except Exception as e:
        bot.send_message(
            chat_id=user_id,
            text="Произошла ошибка при изменении уровня класса."
        )
        print(f"Ошибка при изменении уровня класса: {str(e)}")

def cancel_level_change(call: CallbackQuery):
    """Отмена изменения уровня класса"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Сбрасываем обработчик следующего шага
        bot.clear_step_handler(call.message)
        
        # Получаем игрока
        player = Player.objects.get(telegram_id=user_id)
        
        # Формируем информацию профиля
        user_info = (
            f"👤 *Информация о пользователе*\n\n"
            f"Игровой никнейм: {player.game_nickname}\n"
            f"Telegram: @{player.tg_name}\n"
            f"Статус: {'Администратор' if player.is_admin else 'Игрок'}\n"
            f"Дата регистрации: {player.created_at.strftime('%d.%m.%Y')}\n\n"
        )
        player_classes = player.get_available_classes()
        if player_classes:
            user_info += "*Ваши классы:*\n"
            for class_info in player_classes:
                user_info += (
                    f"• {class_info['class_name']} (Уровень {class_info['level']})\n"
                )
        else:
            user_info += "У вас пока нет классов\n"
        selected_class = player.get_selected_class()
        if selected_class:
            user_info += f"\n*Текущий выбранный класс:*\n"
            user_info += (
                f"• {selected_class['class_name']} (Уровень {selected_class['level']})\n"
            )
        
        # Обновляем сообщение на профиль
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=user_info,
            parse_mode='Markdown',
            reply_markup=PROFILE_BUTTONS
        )
        
        # Показываем активности с новой логикой
        participations = ActivityParticipant.objects.filter(player=player).select_related('activity', 'player_class').order_by('-joined_at')
        
        # Показываем каждое участие отдельно
        for part in participations:
            activity = part.activity
            
            if not part.completed_at:
                # Активное участие
                duration = timezone.now() - part.joined_at
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int((duration.total_seconds() % 60))
                text = (
                    f"🟢 *Активная активность*\n"
                    f"{activity.name}\n"
                    f"Время старта активности: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"Класс: {part.player_class.game_class.name} (Уровень {part.player_class.level})\n"
                    f"Время участия: {hours}ч {minutes}м {seconds}с\n"
                    f"Время начала участия: {part.joined_at.strftime('%d.%m.%Y %H:%M')}\n"
                )
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🔴 Завершить участие", callback_data=f"leave_activity_{activity.id}_{part.player_class.id}"))
                msg = bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            else:
                # Завершенное участие
                duration = part.completed_at - part.joined_at
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                seconds = int((duration.total_seconds() % 60))
                text = (
                    f"🔴 *Участие завершено*\n\n"
                    f"Активность: {activity.name}\n"
                    f"Время старта активности: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"Класс: {part.player_class.game_class.name} (Уровень {part.player_class.level})\n"
                    f"Время участия: {hours}ч {minutes}м {seconds}с\n"
                    f"Заработано баллов: {part.points_earned}\n\n"
                    f"📊 *Детали участия:*\n"
                    f"• Время начала: {part.joined_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"• Время завершения: {part.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
                    f"• Общая длительность: {hours}ч {minutes}м {seconds}с\n"
                    f"• Баллы за участие: {part.points_earned}"
                )
                
                # Если активность еще активна, предлагаем продолжить участие
                if activity.is_active:
                    text += f"\n\n🔄 *Хотите участвовать еще раз?*"
                    keyboard = InlineKeyboardMarkup()
                    keyboard.add(InlineKeyboardButton("🟢 Участвовать снова", callback_data=f"join_activity_{activity.id}"))
                    msg = bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode='Markdown',
                        reply_markup=keyboard
                    )
                else:
                    # Активность завершена администратором
                    text += f"\n\n🔴 *Активность была завершена администратором*"
                    msg = bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode='Markdown'
                    )
        
        # Показываем доступные активности (все активные активности)
        for activity in Activity.objects.filter(is_active=True):
            text = (
                f"⚪ *Доступная активность*\n"
                f"{activity.name}\n"
                f"Доступно классов для участия: {player.player_classes.count()}"
            )
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🟢 Принять участие", callback_data=f"join_activity_{activity.id}"))
            msg = bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        
    except Player.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при отмене изменения уровня."
        )
        print(f"Ошибка при отмене изменения уровня: {str(e)}")


def handle_join_activity(call: CallbackQuery, page: int = 1):
    """Обработка нажатия кнопки 'Принять участие'"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем ID активности из callback_data
        activity_id = int(call.data.split('_')[2])
        
        # Получаем пользователя и игрока
        player = Player.objects.get(telegram_id=str(call.from_user.id))
        
        # Получаем активность
        activity = Activity.objects.get(id=activity_id)
        
        # Проверяем, активна ли активность
        if not activity.is_active:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Эта активность в данный момент неактивна."
            )
            return
        
        # Получаем доступные классы игрока (теперь показываем все классы)
        available_player_classes = player.player_classes.all()
        
        if not available_player_classes.exists():
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="У вас нет доступных классов для участия."
            )
            return
        
        # Преобразуем в список для пагинации
        player_classes = []
        for pc in available_player_classes:
            player_classes.append({
                'class_name': pc.game_class.name,
                'level': pc.level,
                'player_class_id': pc.id
            })
        
        # Настройки пагинации
        classes_per_page = 4
        total_classes = len(player_classes)
        total_pages = (total_classes + classes_per_page - 1) // classes_per_page
        
        # Получаем классы для текущей страницы
        start_idx = (page - 1) * classes_per_page
        end_idx = start_idx + classes_per_page
        current_page_classes = player_classes[start_idx:end_idx]
        
        # Создаем клавиатуру с классами
        keyboard = InlineKeyboardMarkup(row_width=2)
        
        # Добавляем кнопки классов
        for class_info in current_page_classes:
            keyboard.add(
                InlineKeyboardButton(
                    text=f"{class_info['class_name']} (Уровень {class_info['level']})",
                    callback_data=f"select_activity_class_{activity_id}_{class_info['player_class_id']}"
                )
            )
        
        # Добавляем кнопки навигации
        nav_buttons = []
        
        # Добавляем кнопки пагинации
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Предыдущая",
                    callback_data=f"activity_classes_page_{activity_id}_{page-1}"
                )
            )

        # Кнопка "Назад" всегда присутствует
        nav_buttons.append(
            InlineKeyboardButton(text="🔽Отмена🔽", callback_data=f"cancel_activity_{activity_id}")
        )
        
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Следующая ➡️",
                    callback_data=f"activity_classes_page_{activity_id}_{page+1}"
                )
            )
        
        keyboard.row(*nav_buttons)
        
        # Формируем текст сообщения
        text = f"Выберите класс для участия в активности '{activity.name}' (Страница {page} из {total_pages}):"
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            reply_markup=keyboard
        )
        
    except Player.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except Activity.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Ошибка: активность не найдена."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при попытке присоединиться к активности."
        )
        print(f"Ошибка при присоединении к активности: {str(e)}")

def handle_activity_classes_pagination(call: CallbackQuery):
    """Обработка пагинации списка классов при присоединении к активности"""
    try:
        # Получаем данные из callback_data
        parts = call.data.split('_')
        activity_id = int(parts[3])  # activity_classes_page_{activity_id}_{page}
        page = int(parts[4])
        
        # Создаем новый callback_data для handle_join_activity
        call.data = f"join_activity_{activity_id}"
        
        # Вызываем handle_join_activity с нужной страницей
        handle_join_activity(call, page)
    except Exception as e:
        bot.edit_message_text(
            chat_id=call.from_user.id,
            message_id=call.message.message_id,
            text="Произошла ошибка при переключении страницы."
        )
        print(f"Ошибка при пагинации классов активности: {str(e)}")

def cancel_activity_join(call: CallbackQuery):
    """Отмена присоединения к активности"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем ID активности из callback_data
        activity_id = int(call.data.split('_')[2])
        
        # Получаем активность
        activity = Activity.objects.get(id=activity_id)
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=f"Вы отменили присоединение к активности '{activity.name}'"
        )
        
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при отмене присоединения к активности."
        )
        print(f"Ошибка при отмене присоединения к активности: {str(e)}")


def complete_activity(call: CallbackQuery):
    """Завершить участие в активности"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем ID участия из callback_data
        participation_id = int(call.data.split('_')[2])
        
        # Получаем участие
        participation = ActivityParticipant.objects.get(id=participation_id)
        
        # Проверяем, что это действительно участие текущего игрока
        player = Player.objects.get(telegram_id=str(call.from_user.id))
        if participation.player.game_nickname != player.game_nickname:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Ошибка: это не ваша активность."
            )
            return
        
        # Завершаем участие
        participation.completed_at = timezone.now()
        participation.save()
        
        # Рассчитываем баллы
        points = participation.calculate_points()
        
        # Формируем сообщение о завершении с полной информацией
        duration = participation.completed_at - participation.joined_at
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        seconds = int(duration.total_seconds() % 60)
        
        text = (
            f"🔴 *Участие в активности завершено!*\n\n"
            f"Активность: {participation.activity.name}\n"
            f"Время старта активности: {participation.activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"Класс: {participation.player_class.game_class.name} (Уровень {participation.player_class.level})\n"
            f"Время участия: {hours}ч {minutes}м {seconds}с\n"
            f"Заработано баллов: {points}\n\n"
            f"📊 *Детали участия:*\n"
            f"• Время начала: {participation.joined_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"• Время завершения: {participation.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"• Общая длительность: {hours}ч {minutes}м {seconds}с\n"
            f"• Баллы за участие: {points}"
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            parse_mode='Markdown'
        )
        
        # Удаляем ID сообщения из базы данных
        player.remove_activity_message(participation.activity.id)
        
        # Сохраняем ID сообщения о завершении активности
        player.add_completion_message(participation.activity.id, message_id)
        
    except ActivityParticipant.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Ошибка: активность не найдена."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при завершении активности."
        )
        print(f"Ошибка при завершении активности: {str(e)}")

def handle_select_activity_class(call: CallbackQuery):
    """Обработка выбора класса для участия в активности"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем данные из callback_data
        parts = call.data.split('_')
        activity_id = int(parts[3])
        player_class_id = int(parts[4])  # Изменено: теперь передаем player_class_id
        
        # Получаем пользователя и игрока
        player = Player.objects.get(telegram_id=str(call.from_user.id))
        
        # Получаем активность и класс
        activity = Activity.objects.get(id=activity_id)
        
        # Проверяем, активна ли активность
        if not activity.is_active:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Эта активность в данный момент неактивна."
            )
            return
            
        player_class = PlayerClass.objects.get(id=player_class_id, player=player)
        
        # Создаем запись об участии (теперь можно участвовать несколько раз)
        participation = ActivityParticipant.objects.create(
            activity=activity,
            player=player,
            player_class=player_class
        )
        
        # Формируем сообщение об успешном присоединении с информацией об участии
        text = (
            f"🟢 *Вы участвуете в активности!*\n\n"
            f"Активность: {activity.name}\n"
            f"Время старта активности: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"Класс: {player_class.game_class.name} (Уровень {player_class.level})\n"
            f"Время начала участия: {participation.joined_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"✅ Вы успешно присоединились к активности!"
        )
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🔴 Завершить участие", callback_data=f"leave_activity_{activity.id}_{player_class.id}"))
        
        # Отправляем сообщение и сохраняем его ID
        msg = bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        
        # Сохраняем ID сообщения в базе данных
        player.add_activity_message(activity.id, msg.message_id)
    except Player.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Вы еще не зарегистрированы. Используйте команду /start для регистрации."
        )
    except PlayerClass.DoesNotExist:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Ошибка: выбранный класс не найден."
        )
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при выборе класса для активности."
        )
        print(f"Ошибка при выборе класса для активности: {str(e)}")

def show_active_activity_message(user_id):
    try:
        player = Player.objects.get(telegram_id=str(user_id))
        # Получаем активную активность (например, последнюю активную)
        activity = Activity.objects.filter(is_active=True).order_by('-created_at').first()
        if not activity:
            # Нет активной активности — удаляем старое сообщение, если есть
            if user_id in user_active_activity_message:
                try:
                    bot.delete_message(chat_id=user_id, message_id=user_active_activity_message[user_id])
                except Exception:
                    pass
                user_active_activity_message.pop(user_id, None)
            return
        
        # Проверяем, участвует ли пользователь
        participation = ActivityParticipant.objects.filter(activity=activity, player=player, completed_at__isnull=True).select_related('player_class').first()
        
        # Формируем текст активности
        text = (
            f"🟢 *Активная активность!*\n\n"
            f"Активность: {activity.name}\n"
            f"Описание: {activity.description or 'Нет описания'}\n"
            f"Время старта: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        )
        keyboard = InlineKeyboardMarkup()
        
        if participation:
            # Участвует — показываем класс, время, галочки и красную кнопку "Завершить участие"
            player_class = participation.player_class
            duration = timezone.now() - participation.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int((duration.total_seconds() % 60))
            text += (
                f"Класс: {player_class.game_class.name} (Уровень {player_class.level})\n"
                f"Время старта активности: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"Время участия: {hours}ч {minutes}м {seconds}с\n"
                f"\n✅✅✅ Вы участвуете в этой активности!\n"
            )
            keyboard.add(InlineKeyboardButton("🔴 Завершить участие", callback_data=f"leave_activity_{activity.id}_{player_class.id}"))
        else:
            # Не участвует — зеленая кнопка "Принять участие"
            keyboard.add(InlineKeyboardButton("🟢 Принять участие", callback_data=f"join_activity_{activity.id}"))
        
        # Если сообщение уже есть — обновляем
        if user_id in user_active_activity_message:
            try:
                bot.edit_message_text(
                    chat_id=user_id,
                    message_id=user_active_activity_message[user_id],
                    text=text,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                return
            except Exception:
                pass  # Если не удалось — отправим новое
        
        # Отправляем новое сообщение
        msg = bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        user_active_activity_message[user_id] = msg.message_id
        
        # Сохраняем ID сообщения в базе данных
        player.add_activity_message(activity.id, msg.message_id)
        
    except Exception as e:
        print(f"Ошибка при показе активной активности: {e}")

# Обработчик для кнопки "Принять участие"
def handle_join_activity_button(call):
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    from bot.models import Player, Activity, PlayerClass, ActivityParticipant
    try:
        player = Player.objects.get(telegram_id=user_id)
        activity_id = int(call.data.split('_')[2])
        activity = Activity.objects.get(id=activity_id)
        
        # Проверяем, активна ли активность
        if not activity.is_active:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Эта активность в данный момент неактивна."
            )
            return
        
        # Берём выбранный класс игрока (или первый доступный)
        player_class = player.selected_class or player.player_classes.first()
        if not player_class:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="У вас нет доступных классов для участия."
            )
            return
        
        # Создаём участие (теперь можно участвовать несколько раз)
        participation = ActivityParticipant.objects.create(
            activity=activity,
            player=player,
            player_class=player_class
        )
        
        # Сохраняем ID сообщения об активности
        player.add_activity_message(activity.id, message_id)
        
        # Показываем обновленный профиль
        profile(call)
        
    except Exception as e:
        print(f"Ошибка при присоединении к активности: {str(e)}")
        profile(call)

# Обработчик для кнопки "Прекратить участие"
def handle_leave_activity_button(call):
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    from bot.models import Player, Activity, ActivityParticipant
    try:
        player = Player.objects.get(telegram_id=user_id)
        parts = call.data.split('_')
        activity_id = int(parts[2])
        player_class_id = int(parts[3])  # Добавлен player_class_id
        
        activity = Activity.objects.get(id=activity_id)
        participation = ActivityParticipant.objects.filter(
            activity=activity, 
            player=player, 
            player_class_id=player_class_id,
            completed_at__isnull=True
        ).first()
        
        if not participation:
            profile(call)
            return
        
        # Завершаем участие
        participation.completed_at = timezone.now()
        participation.save()
        
        # Рассчитываем баллы
        points = participation.calculate_points()
        
        # Формируем сообщение о завершении с полной информацией
        duration = participation.completed_at - participation.joined_at
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        seconds = int((duration.total_seconds() % 60))
        
        text = (
            f"🔴 *Участие в активности завершено!*\n\n"
            f"Активность: {participation.activity.name}\n"
            f"Время старта активности: {participation.activity.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"Класс: {participation.player_class.game_class.name} (Уровень {participation.player_class.level})\n"
            f"Время участия: {hours}ч {minutes}м {seconds}с\n"
            f"Заработано баллов: {points}\n\n"
            f"📊 *Детали участия:*\n"
            f"• Время начала: {participation.joined_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"• Время завершения: {participation.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"• Общая длительность: {hours}ч {minutes}м {seconds}с\n"
            f"• Баллы за участие: {points}"
        )
        
        # Если активность еще активна, предлагаем продолжить участие
        if activity.is_active:
            text += f"\n\n🔄 *Хотите участвовать еще раз?*"
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🟢 Участвовать снова", callback_data=f"join_activity_{activity.id}"))
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        else:
            # Активность завершена администратором
            text += f"\n\n🔴 *Активность была завершена администратором*"
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                parse_mode='Markdown'
            )
        
        # Удаляем ID сообщения об активности из базы данных
        player.remove_activity_message(activity.id)
        
        # Сохраняем ID сообщения о завершении активности
        player.add_completion_message(activity.id, message_id)
        
    except Exception as e:
        profile(call)

