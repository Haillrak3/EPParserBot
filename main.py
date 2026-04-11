import os
import asyncio
import logging
import re
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# --- НАСТРОЙКИ ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
USERS_FILE = "users.txt"
# ID канала, из которого нужно брать заказы
SOURCE_CHANNEL_ID = -1003769319642 

if not TOKEN:
    exit("Ошибка: Токен не найден в .env!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

subscribed_users = set()

STORES = {
    "ул. Новомарьинская, 14/15": "1️⃣",
    "ул. Краснодонская, 39": "2️⃣",
    "ул. Братиславская, 13": "3️⃣",
    "ул. Братиславская, 29": "4️⃣",
    "ул. Новочеркасский бульвар, 13": "5️⃣",
    "ул. Домодедовская, 15": "6️⃣",
    "ул. Паромная, 11/31": "7️⃣",
    "ул. Перерва, 43": "8️⃣",
    "ул. Кантемировская, 31а": "9️⃣"
}

# --- РАБОТА С ПОДПИСЧИКАМИ ---
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            for line in f:
                if line.strip():
                    subscribed_users.add(int(line.strip()))

def save_user(user_id):
    if user_id not in subscribed_users:
        subscribed_users.add(user_id)
        with open(USERS_FILE, "a") as f:
            f.write(f"{user_id}\n")

# --- ЛОГИКА ПАРСИНГА ---
def parse_order(text: str) -> str:
    # 1. Номер заказа
    order_match = re.search(r'#(\d+)', text)
    order_id = order_match.group(1) if order_match else "???"

    # 2. Номер клиента
    phone_match = re.search(r'Клиент\s*([\+\d\s\-\(\)]+)', text)
    if phone_match:
        digits = re.sub(r'\D', '', phone_match.group(1))
        clean_phone = digits[-10:] if len(digits) >= 10 else digits
    else:
        clean_phone = "не найден"

    # 3. Сумма заказа
    amount_match = re.search(r'Сумма заказа:\s*([\d\s ]+)₽', text)
    amount = amount_match.group(1).strip() + " ₽" if amount_match else "не найдена"
    
    # 4. Обработка комментария (убираем \)
    comment_match = re.search(r'Комментарий от клиента:\s*(.*)', text, re.DOTALL)
    if comment_match:
        comment_raw = comment_match.group(1).replace('\\', '').strip()
    else:
        comment_raw = ""
    
    if not comment_raw:
        order_display = f"{order_id} нп"
        has_comment = False
    else:
        order_display = f"{order_id}"
        has_comment = True

    # 5. Проверка на Рыбу
    has_weight_item = re.search(r'\d+\s*(?:г|кг)\.', text)
    fish_status = " 🐟 *РЫБА!*" if (has_weight_item and has_comment) else ""

    # 6. Адрес
    address_match = re.search(r'(ул\.[^\n]+)', text)
    if address_match:
        full_address = address_match.group(1).strip()
        store_icon = STORES.get(full_address, "❓")
        display_address = f"{store_icon} {full_address}"
    else:
        display_address = "❌ адрес не указан"

    # 7. Сборка сообщения
    result = (
        f"*{display_address}*\n\n"
        f"*ЗАКАЗ:* #`{order_display}`\n\n"
        f"*КЛИЕНТ:* +7`{clean_phone}`\n\n"
        f"*СУММА:* {amount}{fish_status}"
    )

    if has_comment:
        result += f"\n\n💬 *КОММЕНТАРИЙ:* {comment_raw}"

    return result

# --- ОБРАБОТЧИКИ СООБЩЕНИЙ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    await message.answer("✅ Подписка оформлена! Вы будете получать уведомления из целевого канала.")

@dp.channel_post(F.text)
async def handle_channel_post(message: types.Message):
    # ПРОВЕРКА ID КАНАЛА
    if message.chat.id != SOURCE_CHANNEL_ID:
        return

    # Дополнительная проверка на содержание
    if "заказ" not in message.text.lower():
        return

    clean_info = parse_order(message.text)
    
    for user_id in subscribed_users:
        try:
            await bot.send_message(chat_id=user_id, text=clean_info)
        except Exception as e:
            logging.error(f"Ошибка отправки пользователю {user_id}: {e}")

@dp.message(F.text)
async def handle_private_test(message: types.Message):
    """Оставляем возможность тестировать в личке бота вручную"""
    clean_info = parse_order(message.text)
    await message.answer(f"*Результат теста:*\n\n{clean_info}")

async def main():
    load_users()
    print(f"Бот запущен. Слушает канал: {SOURCE_CHANNEL_ID}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass