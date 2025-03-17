import datetime
import logging
import gspread

from google.oauth2.service_account import Credentials
from aiogram import Bot, Dispatcher, types, Router
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
    waiting_for_name = State()
    waiting_for_phone = State()
    waiting_for_catalog = State()

# ========== Google Sheets ==========

def get_setting(worksheet, bot_name: str, key: str) -> str:
    data = worksheet.get_all_values()
    for row in data:
        if len(row) >= 3 and row[0] == bot_name and row[1] == key:
            return row[2]
    return ""

# ========== Основная логика ==========

def setup_bot_handlers(dp: Dispatcher, bot_config: dict):
    router = Router()

    MESSAGES = list(bot_config["LANGUAGES"].values())[0]  # Только узбекский
    PROJECT_DESCRIPTION = list(bot_config["PROJECT_DESCRIPTION"].values())[0]
    bot_name_in_sheet = bot_config["BOT_NAME_IN_SHEET"]
    START_TEXT = bot_config.get("start_text", "Assalomu alaykum!")

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
        # Приветствие
        await message.answer(START_TEXT)

        # Фото + описание проекта
        photo_id = get_setting(worksheet_settings, bot_name_in_sheet, "photo_id")
        if photo_id:
            await message.answer_photo(photo_id, caption=PROJECT_DESCRIPTION)
        else:
            await message.answer("❌ Foto topilmadi.")

        await state.set_state(UserState.waiting_for_name)
        await message.answer(MESSAGES["name_prompt"], reply_markup=ReplyKeyboardRemove())

    @router.message(UserState.waiting_for_name)
    async def name_handler(message: types.Message, state: FSMContext):
        await state.update_data(name=message.text)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=MESSAGES["contact_button"], request_contact=True)]],
            resize_keyboard=True
        )
        await state.set_state(UserState.waiting_for_phone)
        await message.answer(MESSAGES["contact_prompt"], reply_markup=keyboard)

    @router.message(UserState.waiting_for_phone)
    async def handle_phone(message: types.Message, state: FSMContext):
        user_data = await state.get_data()
        name = user_data["name"]
        phone = ""

        if message.contact:
            phone = message.contact.phone_number
        elif message.text:
            raw_input = message.text.strip()
            cleaned = raw_input.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            number_only = cleaned.lstrip("+")
            if not number_only.isdigit() or not (9 <= len(number_only) <= 15):
                example = "<code>998901234567</code> yoki <code>330391330</code>"
                await message.answer(
                    f"📢 Iltimos, faqat raqam yuboring. Misol: {example}",
                    parse_mode="HTML"
                )
                return
            phone = cleaned if cleaned.startswith("+") else f"+{number_only}"
        else:
            example = "<code>998901234567</code> yoki <code>330391330</code>"
            await message.answer(
                f"📢 Iltimos, telefon raqamingizni to'g'ri yuboring:\nMisol: {example}",
                parse_mode="HTML"
            )
            return

        worksheet_users.append_row([
            name,
            phone,
            datetime.datetime.utcnow().strftime("%m-%d")
        ])

        await message.answer(MESSAGES["thank_you_text"])

        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=MESSAGES["get_catalog_button"])]],
            resize_keyboard=True
        )
        await state.set_state(UserState.waiting_for_catalog)
        await message.answer(MESSAGES["get_catalog_prompt"], reply_markup=keyboard)

    @router.message(UserState.waiting_for_catalog)
    async def send_catalog(message: types.Message, state: FSMContext):
        if message.text == MESSAGES["get_catalog_button"]:
            catalog_id = get_setting(worksheet_settings, bot_name_in_sheet, "catalog_id")
            if catalog_id:
                await message.answer_document(catalog_id)
                await message.answer(MESSAGES["catalog_info"])
            else:
                await message.answer("❌ Katalog topilmadi.")
            await state.clear()
        else:
            await message.answer("📁 Katalogni olish uchun tugmani bosing.")

    dp.include_router(router)
