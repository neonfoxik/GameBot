from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)


PROFILE_BUTTONS = InlineKeyboardMarkup()
changeLvlClassMarkup = InlineKeyboardButton("Редактировать уровень класса", callback_data="changeLvlClassMarkup")
PROFILE_BUTTONS.add(changeLvlClassMarkup)

