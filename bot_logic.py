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

# ========== Состояния ==========
class UserState(StatesGroup):
    waiting_for_language = State()
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_catalog = State()

class AdminState(StatesGroup):
    waiting_for_photo = State()
    waiting_for_catalog = State()

# ========== Google Sheets ==========
def get_setting(worksheet, bot_name: str, key: str) -> str:
    data = worksheet.get_all_values()
    for row in data:
        if len(row) >= 3 and row[0] == bot_name and row[1] == key:
            return row[2]
    return ""

def set_setting(worksheet, bot_name: str, key: str, value: str):
    data = worksheet.get_all_values()
    for i, row in enumerate(data):
        if len(row) >= 3 and row[0] == bot_name and row[1] == key:
            worksheet.update_cell(i + 1, 3, value)
            return
    worksheet.append_row([bot_name, key, value])

# ========== Основная логика ==========
def setup_bot_handlers(dp: Dispatcher, bot_config: dict):
    router = Router()

    ADMIN_ID = bot_config["ADMIN_ID"]
    PROJECT_DESCRIPTION = bot_config["PROJECT_DESCRIPTION"]
    LANGUAGES = bot_config["LANGUAGES"]
    bot_name_in_sheet = bot_config.get("BOT_NAME_IN_SHEET", "bot1")

    creds = Credentials.from_service_account_file(
        bot_config["SERVICE_ACCOUNT_FILE"],
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open(bot_config["SPREADSHEET_NAME"])
    worksheet_users = sh.worksheet(bot_config["USERS_WORKSHEET"])
    worksheet_settings = sh.worksheet(bot_config["SETTINGS_WORKSHEET"])

    @router.message(Command("start"))
    async def start_handler(message: types.Message, state: FSMContext):
        await state.set_state(UserState.waiting_for_language)
        language_keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🇺🇿 O'zbekcha"), KeyboardButton(text="🇷🇺 Русский")]],
            resize_keyboard=True
        )
        text = "Assalomu alaykum!\n\n🇺🇿 Iltimos, tilni tanlang\n🇷🇺 Пожалуйста, выберите язык"
        await message.answer(text, reply_markup=language_keyboard)

    @router.message(UserState.waiting_for_language, F.text.in_(["🇺🇿 O'zbekcha", "🇷🇺 Русский"]))
    async def language_selection(message: types.Message, state: FSMContext):
        selected_language = message.text
        await state.update_data(language=selected_language)

        # Отправка фото
        photo_id = get_setting(worksheet_settings, bot_name_in_sheet, "photo_id")
        project_text = PROJECT_DESCRIPTION.get(selected_language, "Описание проекта недоступно.")
        if photo_id:
            await message.answer_photo(photo_id, caption=project_text)
        else:
            await message.answer("❌ Фото не загружено.")

        await state.set_state(UserState.waiting_for_name)
        await message.answer(
            LANGUAGES[selected_language]["name_prompt"],
            reply_markup=ReplyKeyboardRemove()
        )

    @router.message(UserState.waiting_for_language)
    async def invalid_language(message: types.Message, state: FSMContext):
        text = "❗ Iltimos, tilni tugma orqali tanlang.\nПожалуйста, выберите язык кнопкой."
        await message.answer(text)

    @router.message(UserState.waiting_for_name)
    async def name_handler(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        language = user_data["language"]
        await state.update_data(name=message.text)

        contact_keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=LANGUAGES[language]["contact_button"], request_contact=True)]],
            resize_keyboard=True
        )
        await state.set_state(UserState.waiting_for_phone)
        await message.answer(LANGUAGES[language]["contact_prompt"], reply_markup=contact_keyboard)

    @router.message(UserState.waiting_for_phone)
    async def handle_phone(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        language = user_data.get("language", "🇺🇿 O'zbekcha")
        name = user_data["name"]

        phone = ""

        # Контакт через кнопку
        if message.contact:
            phone = message.contact.phone_number

        # Ввод вручную
        elif message.text:
            raw_input = message.text.strip()
            cleaned = raw_input.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            number_only = cleaned.lstrip("+")

            if not number_only.isdigit() or not (9 <= len(number_only) <= 15):
                example = "<code>998901234567</code> yoki <code>330391330</code>"
                await message.answer(
                    f"📢 Iltimos, faqat raqam yuboring. Belgilarsiz, smajliksiz.\nMisol uchun: {example}",
                    parse_mode="HTML"
                )
                return

            phone = cleaned if cleaned.startswith("+") else f"+{number_only}"

        else:
            example = "<code>998901234567</code> yoki <code>330391330</code>"
            await message.answer(
                f"📢 Iltimos, telefon raqamingizni to'g'ri yuboring:\nMisol uchun: {example}",
                parse_mode="HTML"
            )
            return

        # Сохраняем в таблицу
        worksheet_users.append_row([
            name,
            phone,
            datetime.datetime.utcnow().strftime("%m-%d")
        ])

        thank_you_text = LANGUAGES[language].get("thank_you_text", "Спасибо за интерес!")
        await message.answer(thank_you_text)

        # Кнопка получения каталога
        catalog_keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=LANGUAGES[language]["get_catalog_button"])]],
            resize_keyboard=True
        )
        await state.set_state(UserState.waiting_for_catalog)
        await message.answer(LANGUAGES[language]["get_catalog_prompt"], reply_markup=catalog_keyboard)

    @router.message(UserState.waiting_for_catalog)
    async def send_catalog(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        language = user_data["language"]

        if message.text == LANGUAGES[language]["get_catalog_button"]:
            catalog_id = get_setting(worksheet_settings, bot_name_in_sheet, "catalog_id")
            if catalog_id:
                await message.answer_document(catalog_id)
                catalog_info = LANGUAGES[language].get("catalog_info", "Онлайн каталог.")
                await message.answer(catalog_info)
            else:
                await message.answer("❌ Каталог не загружен.")
            await state.clear()
        else:
            await message.answer("📁 Пожалуйста, нажмите кнопку для получения каталога.")

    dp.include_router(router)
