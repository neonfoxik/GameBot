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
from bot.keyboards import START_MARKUP, PROFILE_BUTTONS
from .registration import start_registration
from functools import wraps


def start(message: Message) -> None:
    """Обработчик команды /start"""
    start_registration(message)

def main_menu(message: Message):
    user_id = message.from_user.id
    bot.send_message(
        chat_id=user_id,
        reply_markup=START_MARKUP,
        text="Выберите действие",
    )

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
def main_menu_call(call: CallbackQuery):
    user_id = call.from_user.id
    message_id = call.message.message_id
    bot.edit_message_text(
        chat_id=user_id,
        message_id=message_id,
        reply_markup=START_MARKUP,
        text="Выберите действие",
    )

@only_our_player
def profile(call: CallbackQuery):
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    try:
        player = Player.objects.get(telegram_id=user_id)
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
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=user_info,
            parse_mode='Markdown',
            reply_markup=PROFILE_BUTTONS
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
            text="Произошла ошибка при получении информации о профиле."
        )
        print(f"Ошибка при получении профиля: {str(e)}")

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

def select_class(call: CallbackQuery):
    """Обработка выбора класса"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем ID выбранного класса из callback_data
        class_id = int(call.data.split('_')[2])
        
        # Получаем пользователя и игрока
        player = Player.objects.get(telegram_id=str(call.from_user.id))
        
        # Получаем выбранный класс
        game_class = GameClass.objects.get(id=class_id)
        
        # Проверяем, есть ли уже этот класс у игрока
        player_class, created = PlayerClass.objects.get_or_create(
            player=player,
            game_class=game_class,
            defaults={'level': 1}
        )
        
        # Устанавливаем выбранный класс
        player.selected_class = player_class
        player.save()
        

        
        # Отправляем сообщение об успешном выборе
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=f"Вы успешно выбрали класс:\n"
                 f"{game_class.name} (Уровень {player_class.level})",
            reply_markup=START_MARKUP
        )
        
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
        
        # Возвращаемся в профиль
        profile(call)
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
                text="Эта активность в данный момент неактивна.",
                reply_markup=START_MARKUP
            )
            return
        
        # Проверяем, не участвует ли уже игрок
        if ActivityParticipant.objects.filter(activity=activity, player=player).exists():
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Вы уже участвуете в этой активности!"
            )
            return
        
        # Получаем доступные классы игрока
        player_classes = player.get_available_classes()
        if not player_classes:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="У вас нет доступных классов для участия в активности."
            )
            return
        
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
                    callback_data=f"select_activity_class_{activity_id}_{class_info['class_name']}"
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

def show_activities(call: CallbackQuery, page: int = 1):
    """Показать список активных активностей с пагинацией"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    
    try:
        # Получаем все активные активности
        active_activities = Activity.objects.filter(is_active=True).order_by('-created_at')
        
        # Настройки пагинации
        activities_per_page = 3
        total_activities = active_activities.count()
        total_pages = (total_activities + activities_per_page - 1) // activities_per_page
        
        if total_activities == 0:
            try:
                bot.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text="На данный момент нет активных активностей.",
                    reply_markup=START_MARKUP
                )
            except Exception as e:
                if 'message is not modified' in str(e):
                    pass
                else:
                    raise
            return
        
        # Получаем активности для текущей страницы
        start_idx = (page - 1) * activities_per_page
        end_idx = start_idx + activities_per_page
        current_page_activities = active_activities[start_idx:end_idx]
        
        # Создаем клавиатуру с активностями
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        # Добавляем кнопки активностей
        for activity in current_page_activities:
            keyboard.add(
                InlineKeyboardButton(
                    text=f"{activity.name}",
                    callback_data=f"join_activity_{activity.id}"
                )
            )
        
        # Добавляем кнопки навигации
        nav_buttons = []
        
        # Добавляем кнопки пагинации
        if page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="⬅️ Предыдущая",
                    callback_data=f"activities_page_{page-1}"
                )
            )

        # Кнопка "Назад" всегда присутствует
        nav_buttons.append(
            InlineKeyboardButton(text="🔽Главное меню🔽", callback_data="main_menu")
        )
        
        if page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    text="Следующая ➡️",
                    callback_data=f"activities_page_{page+1}"
                )
            )
        
        keyboard.row(*nav_buttons)
        
        # Формируем текст сообщения
        text = f"*Активные активности* (Страница {page} из {total_pages}):\n\n"
        for activity in current_page_activities:
            text += f"*{activity.name}*\n"
            if activity.description:
                text += f"{activity.description}\n"
            text += f"Создана: {activity.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        
        try:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except Exception as edit_error:
            if "message is not modified" in str(edit_error):
                # Если сообщение не изменилось, просто отвечаем на callback
                bot.answer_callback_query(call.id)
            else:
                # Если произошла другая ошибка, пробрасываем её дальше
                raise edit_error
        
    except Exception as e:
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text="Произошла ошибка при получении списка активностей."
        )
        print(f"Ошибка при получении списка активностей: {str(e)}")

def handle_activities_pagination(call: CallbackQuery):
    """Обработка пагинации списка активностей"""
    try:
        # Получаем номер страницы из callback_data
        page = int(call.data.split('_')[2])
        show_activities(call, page)
    except Exception as e:
        bot.edit_message_text(
            chat_id=call.from_user.id,
            message_id=call.message.message_id,
            text="Произошла ошибка при переключении страницы."
        )
        print(f"Ошибка при пагинации активностей: {str(e)}")

def show_my_activities(call: CallbackQuery):
    """Показать список активностей, в которых участвует игрок"""
    user_id = str(call.from_user.id)
    message_id = call.message.message_id
    try:
        player = Player.objects.get(telegram_id=user_id)
        active_participations = ActivityParticipant.objects.filter(
            player=player,
            completed_at__isnull=True
        ).select_related('activity', 'player_class')
        if not active_participations.exists():
            try:
                bot.edit_message_text(
                    chat_id=user_id,
                    message_id=message_id,
                    text="У вас нет активных активностей.",
                    reply_markup=START_MARKUP
                )
            except Exception as e:
                if 'message is not modified' in str(e):
                    pass
                else:
                    raise
            return
        
        # Создаем клавиатуру с активностями
        keyboard = InlineKeyboardMarkup(row_width=1)
        
        for participation in active_participations:
            duration = timezone.now() - participation.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int(duration.total_seconds() % 60)
            
            keyboard.add(
                InlineKeyboardButton(
                    text=f"{participation.activity.name} ({hours}ч {minutes}м {seconds}с)",
                    callback_data=f"complete_activity_{participation.id}"
                )
            )
        
        # Добавляем кнопку возврата
        keyboard.add(InlineKeyboardButton(text="🔽Главное меню🔽", callback_data="main_menu"))
        
        # Формируем текст сообщения
        text = "*Ваши активные активности:*\n\n"
        for participation in active_participations:
            duration = timezone.now() - participation.joined_at
            hours = int(duration.total_seconds() // 3600)
            minutes = int((duration.total_seconds() % 3600) // 60)
            seconds = int(duration.total_seconds() % 60)
            
            text += f"*{participation.activity.name}*\n"
            text += f"Класс: {participation.player_class.game_class.name} (Уровень {participation.player_class.level})\n"
            text += f"Участвует: {hours}ч {minutes}м {seconds}с\n\n"
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
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
            text="Произошла ошибка при получении списка активностей."
        )
        print(f"Ошибка при получении списка активностей: {str(e)}")

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
        
        # Формируем сообщение о завершении
        duration = participation.completed_at - participation.joined_at
        hours = int(duration.total_seconds() // 3600)
        minutes = int((duration.total_seconds() % 3600) // 60)
        seconds = int(duration.total_seconds() % 60)
        
        text = (
            f"*Участие в активности завершено!*\n\n"
            f"Активность: {participation.activity.name}\n"
            f"Класс: {participation.player_class.game_class.name} (Уровень {participation.player_class.level})\n"
            f"Время участия: {hours}ч {minutes}м {seconds}с\n"
            f"Заработано баллов: {points}\n"
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            parse_mode='Markdown',
            reply_markup=START_MARKUP
        )
        
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
        class_name = parts[4]
        
        # Получаем пользователя и игрока
        player = Player.objects.get(telegram_id=str(call.from_user.id))
        
        # Получаем активность и класс
        activity = Activity.objects.get(id=activity_id)
        
        # Проверяем, активна ли активность
        if not activity.is_active:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Эта активность в данный момент неактивна.",
                reply_markup=START_MARKUP
            )
            return
            
        game_class = GameClass.objects.get(name=class_name)
        player_class = PlayerClass.objects.get(player=player, game_class=game_class)
        
        # Проверяем, не участвует ли уже игрок
        if ActivityParticipant.objects.filter(activity=activity, player=player).exists():
            bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text="Вы уже участвуете в этой активности!",
                reply_markup=START_MARKUP
            )
            return
        
        # Создаем запись об участии
        participation = ActivityParticipant.objects.create(
            activity=activity,
            player=player,
            player_class=player_class
        )
        
        # Формируем сообщение об успешном присоединении
        text = (
            f"*Вы успешно присоединились к активности!*\n\n"
            f"Активность: {activity.name}\n"
            f"Класс: {game_class.name} (Уровень {player_class.level})\n\n"
            f"Время начала: {participation.joined_at.strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Вы можете завершить участие в любой момент через меню 'Мои активности'"
        )
        
        bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=text,
            parse_mode='Markdown',
            reply_markup=START_MARKUP
        )
        
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
            text="Произошла ошибка при выборе класса для активности."
        )
        print(f"Ошибка при выборе класса для активности: {str(e)}")

