from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

START_MARKUP = InlineKeyboardMarkup()
profile = InlineKeyboardButton("Профиль🕴", callback_data="profile")
activities = InlineKeyboardButton("Активности🎮", callback_data="show_activities")
my_activities = InlineKeyboardButton("Мои активности⏱", callback_data="my_activities")
START_MARKUP.add(profile).add(activities).add(my_activities)

PROFILE_BUTTONS = InlineKeyboardMarkup()
changeClassMarkup = InlineKeyboardButton("Сменить класс", callback_data="show_classes")
changeLvlClassMarkup = InlineKeyboardButton("Редактировать уровень класса", callback_data="changeLvlClassMarkup")
main_menu_btn = InlineKeyboardButton("Главное меню", callback_data="main_menu")
PROFILE_BUTTONS.add(changeClassMarkup).add(changeLvlClassMarkup).add(main_menu_btn)

ADMIN_MARKUP = InlineKeyboardMarkup()
createActivity = InlineKeyboardButton("Создать активность", callback_data="create_Activity")
ADMIN_MARKUP.add(createActivity)