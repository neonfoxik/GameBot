from bot.models import Player, GameClass, PlayerClass
from bot import bot
from django.conf import settings
from telebot.types import Message, CallbackQuery

registration_states = {}

def start_registration(message: Message):
    """
    Начало процесса регистрации пользователя
    """
    try:
        from bot.handlers.common import profile
        telegram_id = str(message.from_user.id)
        # Проверяем, существует ли игрок
        player = Player.objects.filter(telegram_id=telegram_id).first()
        if player:
            if player.is_our_player:
                # Показываем только профиль
                fake_call = type('FakeCall', (), {'from_user': message.from_user, 'message': message})
                profile(fake_call)
            else:
                bot.send_message(message.chat.id, 'Доступ запрещён. Вы не являетесь нашим игроком.')
            return
        registration_states[telegram_id] = {}
        bot.send_message(message.chat.id, "Введите ваш игровой никнейм:")
        bot.register_next_step_handler(message, process_nickname_step)
    except Exception as e:
        bot.send_message(
            message.chat.id,
            "Произошла ошибка при регистрации. Пожалуйста, попробуйте позже."
        )
        print(f"Ошибка при регистрации: {str(e)}")

def process_name_step(message: Message):
    telegram_id = str(message.from_user.id)
    registration_states[telegram_id]['user_name'] = message.text.strip()
    bot.send_message(message.chat.id, "Введите ваш игровой никнейм:")
    bot.register_next_step_handler(message, process_nickname_step)

def process_nickname_step(message: Message):
    telegram_id = str(message.from_user.id)
    registration_states[telegram_id]['game_nickname'] = message.text.strip()
    tg_name = message.from_user.username or "none"
    game_nickname = registration_states[telegram_id]['game_nickname']
    from django.conf import settings
    # Создаём Player
    player = Player.objects.create(
        telegram_id=telegram_id,
        tg_name=tg_name,
        game_nickname=game_nickname,
        is_admin=telegram_id in settings.OWNER_ID
    )
    # sync_player_classes(player)  # Удалено, теперь классы назначаются только админом
    registration_states.pop(telegram_id, None)
    from bot.handlers.common import profile
    fake_call = type('FakeCall', (), {'from_user': message.from_user, 'message': message})
    profile(fake_call)

# Исправить синхронизацию классов: удалять PlayerClass, если GameClass больше не существует
# (этот код был в else, теперь он всегда выполняется при старте)
def sync_player_classes(player):
    available_classes = set(GameClass.objects.all())
    player_classes = set(pc.game_class for pc in player.player_classes.all())
    # Добавляем новые классы
    for game_class in available_classes - player_classes:
        PlayerClass.objects.create(
            player=player,
            game_class=game_class,
            level=1
        )
    # Удаляем неактуальные классы
    for game_class in player_classes - available_classes:
        PlayerClass.objects.filter(
            player=player,
            game_class=game_class
        ).delete()
    # Проверяем выбранный класс
    if player.selected_class and player.selected_class.game_class not in available_classes:
        if available_classes:
            new_selected_class = PlayerClass.objects.filter(
                player=player,
                game_class__in=available_classes
            ).first()
            player.selected_class = new_selected_class
            player.save()
        else:
            player.selected_class = None
            player.save()


