from traceback import format_exc

from asgiref.sync import sync_to_async
from bot.handlers import *
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from telebot.apihelper import ApiTelegramException
from telebot.types import Update

from bot import bot, logger



@require_GET
def set_webhook(request: HttpRequest) -> JsonResponse:
    """Setting webhook."""
    bot.set_webhook(url=f"{settings.HOOK}/bot/{settings.BOT_TOKEN}")
    bot.send_message(settings.OWNER_ID, "webhook set")
    return JsonResponse({"message": "OK"}, status=200)


@require_GET
def status(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"message": "OK"}, status=200)


@csrf_exempt
@require_POST
@sync_to_async
def index(request: HttpRequest) -> JsonResponse:
    if request.META.get("CONTENT_TYPE") != "application/json":
        return JsonResponse({"message": "Bad Request"}, status=403)

    json_string = request.body.decode("utf-8")
    update = Update.de_json(json_string)
    try:
        bot.process_new_updates([update])
    except ApiTelegramException as e:
        logger.error(f"Telegram exception. {e} {format_exc()}")
    except ConnectionError as e:
        logger.error(f"Connection error. {e} {format_exc()}")
    except Exception as e:
        bot.send_message(settings.OWNER_ID, f'Error from index: {e}')
        logger.error(f"Unhandled exception. {e} {format_exc()}")
    return JsonResponse({"message": "OK"}, status=200)


"""Common"""

start = bot.message_handler(commands=["start"])(start_registration)


profile = bot.callback_query_handler(lambda c: c.data == "profile")(profile)
show_classes = bot.callback_query_handler(lambda c: c.data == "show_classes")(show_classes)
classes_pagination = bot.callback_query_handler(lambda c: c.data.startswith("classes_page_"))(handle_classes_pagination)
changeLvlClassMarkup = bot.callback_query_handler(lambda c: c.data == "changeLvlClassMarkup")(changeLvlClassMarkup)
change_level = bot.callback_query_handler(lambda c: c.data.startswith("change_lvl_"))(handle_change_level)
change_level_pagination = bot.callback_query_handler(lambda c: c.data.startswith("change_page_lvl_"))\
    (handle_change_level_pagination)
cancel_level = bot.callback_query_handler(lambda c: c.data == "cancel_level_change")(cancel_level_change)

#обработчики активностей

join_activity = bot.callback_query_handler(lambda c: c.data.startswith("join_activity_"))(handle_join_activity)
activity_classes_pagination = bot.callback_query_handler(lambda c: c.data.startswith("activity_classes_page_"))\
    (handle_activity_classes_pagination)
cancel_activity = bot.callback_query_handler(lambda c: c.data.startswith("cancel_activity_"))(cancel_activity_join)
complete_activity_handler = bot.callback_query_handler(lambda c: c.data.startswith("complete_activity_"))\
    (complete_activity)
select_activity_class = bot.callback_query_handler(lambda c: c.data.startswith("select_activity_class_"))\
    (handle_select_activity_class)

# Новые обработчики для участия в активности
join_activity_button = bot.callback_query_handler(lambda c: c.data.startswith("join_activity_"))(handle_join_activity_button)
leave_activity_button = bot.callback_query_handler(lambda c: c.data.startswith("leave_activity_"))(handle_leave_activity_button)

