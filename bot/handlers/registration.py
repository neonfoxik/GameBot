from bot.models import User, Player, GameClass, PlayerClass
from bot import bot
from django.conf import settings
from telebot.types import Message, CallbackQuery

def start_registration(message: Message):
    """
    Начало процесса регистрации пользователя
    """
    try:
        from bot.handlers.common import main_menu
        # Получаем данные из сообщения
        telegram_id = str(message.from_user.id)
        user_tg_name = message.from_user.username
        user_name = message.from_user.first_name

        # Проверяем, существует ли пользователь
        user, created = User.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                'user_tg_name': user_tg_name or "none",
                'user_name': user_name,
                'is_admin': telegram_id in settings.OWNER_ID
            }
        )

        # Получаем все доступные классы
        available_classes = set(GameClass.objects.all())

        if created:
            # Если пользователь новый, создаем для него игрока
            player = Player.objects.create(name=user_name)
            
            # Создаем все доступные классы для игрока
            for game_class in available_classes:
                PlayerClass.objects.create(
                    player=player,
                    game_class=game_class,
                    level=1
                )
            
            # Устанавливаем первый класс как выбранный
            if available_classes:
                first_class = PlayerClass.objects.filter(player=player).first()
                player.selected_class = first_class
                player.save()
        else:
            # Если пользователь уже существует, синхронизируем его классы
            player = Player.objects.get(name=user.user_name)
            
            # Получаем текущие классы игрока
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
            
            # Проверяем, существует ли выбранный класс
            if player.selected_class and player.selected_class.game_class not in available_classes:
                # Если выбранный класс больше не существует, выбираем первый доступный
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

        main_menu(message)

    except Exception as e:
        bot.send_message(
            message.chat.id,
            "Произошла ошибка при регистрации. Пожалуйста, попробуйте позже."
        )
        print(f"Ошибка при регистрации: {str(e)}")


