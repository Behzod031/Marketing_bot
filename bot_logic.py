import datetime
import logging
import gspread

from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ========================
# 1. FSM — Машина состояний
# ========================
class UserState(StatesGroup):
    waiting_for_language = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_catalog = State()

class AdminState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_catalog = State()


# ========================
# 2. Работа с Google Sheets
# ========================
def get_setting(worksheet, bot_name: str, key: str) -> str:
    """
    Получает значение из Google Sheets для конкретного бота.
    """
    data = worksheet.get_all_values()
    for row in data:
        if len(row) >= 3 and row[0] == bot_name and row[1] == key:
            return row[2]
    return ""

def set_setting(worksheet, bot_name: str, key: str, value: str):
    """
    Сохраняет или обновляет значение в Google Sheets.
    """
    data = worksheet.get_all_values()
    for i, row in enumerate(data):
        if len(row) >= 3 and row[0] == bot_name and row[1] == key:
            worksheet.update_cell(i + 1, 3, value)
            return
    worksheet.append_row([bot_name, key, value])


# ========================
# 3. Основные хендлеры
# ========================
def setup_bot_handlers(dp: Dispatcher, bot_config: dict):
    router = Router()

    # Конфигурация
    ADMIN_ID = bot_config["ADMIN_ID"]
    PROJECT_DESCRIPTION = bot_config["PROJECT_DESCRIPTION"]
    LANGUAGES = bot_config["LANGUAGES"]
    bot_name_in_sheet = bot_config.get("BOT_NAME_IN_SHEET", "bot1")

    # Google Sheets
    creds = Credentials.from_service_account_file(
        bot_config["SERVICE_ACCOUNT_FILE"],
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open(bot_config["SPREADSHEET_NAME"])
    worksheet_users = sh.worksheet(bot_config["USERS_WORKSHEET"])
    worksheet_settings = sh.worksheet(bot_config["SETTINGS_WORKSHEET"])

    # Считываем photo_id и catalog_id
    FILE_ID = get_setting(worksheet_settings, bot_name_in_sheet, "photo_id")
    CATALOG_FILE_ID = get_setting(worksheet_settings, bot_name_in_sheet, "catalog_id")


    # ==========/start команда============
    @router.message(Command("start"))
    async def start_handler(message: types.Message, state: FSMContext):
        """
        Пользователь начинает общение. Предлагаем выбрать язык.
        """
        await state.set_state(UserState.waiting_for_language)

        # Кнопки выбора языка
        language_keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [
                    KeyboardButton(text="🇺🇿 O'zbekcha"),
                    KeyboardButton(text="🇷🇺 Русский")
                ]
            ],
            resize_keyboard=True
        )
        # Можно вывести краткое приветствие на двух языках или одно общее
        text = (
            "Assalomu alaykun😊:\n\n"
            "🇺🇿 Iltimos, tilni tanlang\n"
            "🇷🇺 Пожалуйста, выберите язык"
        )
        await message.answer(text, reply_markup=language_keyboard)


    # =============Выбор языка==============
    @router.message(UserState.waiting_for_language, F.text.in_(["🇺🇿 O'zbekcha", "🇷🇺 Русский"]))
    async def language_selection(message: types.Message, state: FSMContext):
        selected_language = message.text
        await state.update_data(language=selected_language)

        # Переходим к вводу имени
        await state.set_state(UserState.waiting_for_name)
        await message.answer(
            LANGUAGES[selected_language]["name_prompt"],
            reply_markup=ReplyKeyboardRemove()
        )


    @router.message(UserState.waiting_for_language)
    async def invalid_language(message: types.Message, state: FSMContext):
        """
        Обработчик для неправильного ввода языка
        """
        text = (
            "Пожалуйста, выберите язык, нажав соответствующую кнопку.\n"
            "Iltimos, tugmani bosing."
        )
        await message.answer(text)


    # =============Ввод имени==============
    @router.message(UserState.waiting_for_name)
    async def name_handler(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        language = user_data["language"]

        # Сохраняем имя
        await state.update_data(name=message.text)

        # Готовим кнопку для отправки контакта
        contact_keyboard = ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(
                    text=LANGUAGES[language]["contact_button"],
                    request_contact=True
                )
            ]],
            resize_keyboard=True
        )

        # Переходим к состоянию ожидания телефона
        await state.set_state(UserState.waiting_for_phone)
        await message.answer(
            LANGUAGES[language]["contact_prompt"],
            reply_markup=contact_keyboard
        )


    # =============Контакт==============
    @router.message(UserState.waiting_for_phone, F.contact)
    async def contact_handler(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        language = user_data["language"]
        name = user_data["name"]
        phone = message.contact.phone_number

        # 1) Сохраняем данные пользователя в Google Sheets
        worksheet_users.append_row([
            name,
            phone,
            datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        ])

        # 2) Отправляем сообщение «Благодарим за интерес…» из конфигурации
        thank_you_text = LANGUAGES[language].get(
            "thank_you_text",
            # fallback — если почему-то нет ключа
            "☺️ Благодарим за проявленный интерес к проекту!\n"
            "📞 Наши менеджеры свяжутся с вами в скором времени!\n\n"
            "🤩 Предлагаем пока ознакомиться с преимуществами проекта и скачать онлайн-каталог."
        )
        await message.answer(thank_you_text)

        # 3) Отправляем фото (если есть), иначе сообщаем об отсутствии
        photo_id = get_setting(worksheet_settings, bot_name_in_sheet, "photo_id")
        if photo_id:
            # caption берём из PROJECT_DESCRIPTION (по выбранному языку)
            project_text = PROJECT_DESCRIPTION.get(
                language,
                "Описание проекта недоступно на выбранном языке."
            )
            await message.answer_photo(photo_id, caption=project_text)
        else:
            await message.answer(
                "❌ Фото не загружено.\nИспользуйте /upload_photo для загрузки."
            )
            await state.clear()
            return

        # 4) Предлагаем получить каталог
        catalog_keyboard = ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(text=LANGUAGES[language]["get_catalog_button"])
            ]],
            resize_keyboard=True
        )
        await state.set_state(UserState.waiting_for_catalog)
        await message.answer(
            LANGUAGES[language]["get_catalog_prompt"],
            reply_markup=catalog_keyboard
        )


    @router.message(UserState.waiting_for_phone)
    async def handle_no_contact(message: types.Message, state: FSMContext):
        """
        Если пользователь не прислал контакт, а прислал текст — напоминаем, что нужен контакт.
        """
        user_data = await state.get_data()
        language = user_data.get("language", "🇷🇺 Русский")  # fallback — русский
        reminder_text = LANGUAGES[language].get("phone_reminder", "Нужно отправить контакт.")
        await message.answer(reminder_text)


    # =============Каталог==============
    @router.message(UserState.waiting_for_catalog)
    async def send_catalog(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        language = user_data["language"]

        # Проверяем, нажал ли пользователь правильную кнопку
        if message.text == LANGUAGES[language]["get_catalog_button"]:
            catalog_id = get_setting(worksheet_settings, bot_name_in_sheet, "catalog_id")
            if catalog_id:
                # Отправляем каталог
                await message.answer_document(catalog_id)
                # Отправляем дополнительное информационное сообщение
                catalog_info = LANGUAGES[language].get(
                    "catalog_info",
                    "Ushbu onlayn katalog orqali o’zingizga mos xonadon rejasini tanlashingiz mumkin."
                )
                await message.answer(catalog_info)
            else:
                await message.answer("❌ Каталог не загружен.")
            await state.clear()
        else:
            await message.answer("Пожалуйста, нажмите кнопку для получения каталога.")


    # =============АДМИНСКИЕ КОМАНДЫ==============

    # 1) Команда /upload_photo
    @router.message(Command("upload_photo"))
    async def upload_photo_cmd(message: types.Message, state: FSMContext):
        if message.from_user.id == ADMIN_ID:
            # Переводим админа в состояние ожидания фото
            await state.set_state(AdminState.waiting_for_photo)
            await message.answer("📷 Отправьте фото для загрузки.")
        else:
            await message.answer("❌ У вас нет доступа к этой команде.")

    @router.message(AdminState.waiting_for_photo, F.photo)
    async def handle_admin_photo(message: types.Message, state: FSMContext):
        """
        Сохранение фото (file_id) в Google Sheets, если пользователь в состоянии ожидания фото и он админ.
        """
        if message.from_user.id == ADMIN_ID:
            file_id = message.photo[-1].file_id
            set_setting(worksheet_settings, bot_name_in_sheet, "photo_id", file_id)
            await message.answer("✅ Фото успешно загружено.")
        else:
            await message.answer("❌ У вас нет доступа.")

        # Сбрасываем состояние после загрузки
        await state.clear()

    @router.message(AdminState.waiting_for_photo)
    async def handle_not_photo(message: types.Message, state: FSMContext):
        """
        Если в состоянии ожидания фото отправили что-то не то.
        """
        if message.from_user.id == ADMIN_ID:
            await message.answer("Нужно отправить **фото**. Попробуйте ещё раз.")


    # 2) Команда /upload_catalog
    @router.message(Command("upload_catalog"))
    async def upload_catalog_cmd(message: types.Message, state: FSMContext):
        if message.from_user.id == ADMIN_ID:
            await state.set_state(AdminState.waiting_for_catalog)
            await message.answer("📁 Отправьте документ (каталог) для загрузки.")
        else:
            await message.answer("❌ У вас нет доступа к этой команде.")

    @router.message(AdminState.waiting_for_catalog, F.document)
    async def handle_admin_catalog_document(message: types.Message, state: FSMContext):
        if message.from_user.id == ADMIN_ID:
            doc_id = message.document.file_id
            set_setting(worksheet_settings, bot_name_in_sheet, "catalog_id", doc_id)
            await message.answer("✅ Каталог успешно загружен.")
        else:
            await message.answer("❌ У вас нет доступа.")

        # Сбрасываем состояние
        await state.clear()

    @router.message(AdminState.waiting_for_catalog)
    async def handle_not_document(message: types.Message, state: FSMContext):
        """
        Если в состоянии ожидания каталога отправили что-то не то.
        """
        if message.from_user.id == ADMIN_ID:
            await message.answer("Нужно отправить **документ** (PDF или другое). Попробуйте ещё раз.")


    # Подключаем роутер
    dp.include_router(router)
