import os
import asyncio
import logging
import re
import math
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.client.session.aiohttp import AiohttpSession 

# --- НАСТРОЙКИ ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = "http://Er9gyp:nkoVX3@190.185.109.182:9552" 
USERS_FILE = "users.txt"
SOURCE_CHANNEL_ID = -1003769319642

if not TOKEN:
    exit("Ошибка: Токен не найден в .env!")

logging.basicConfig(level=logging.INFO)
session = AiohttpSession(proxy=PROXY_URL)
bot = Bot(token=TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
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
    order_match = re.search(r'#(\d+)', text)
    order_id = order_match.group(1) if order_match else "???"

    phone_match = re.search(r'Клиент\s*([\+\d\s\-\(\)]+)', text)
    if phone_match:
        digits = re.sub(r'\D', '', phone_match.group(1))
        clean_phone = digits[-10:] if len(digits) >= 10 else digits
    else:
        clean_phone = "не найден"

    amount_match = re.search(r'Сумма заказа:\s*([\d\s ]+)₽', text)
    amount = amount_match.group(1).strip() + " ₽" if amount_match else "не найдена"
    
    comment_match = re.search(r'Комментарий от клиента:\s*(.*)', text, re.DOTALL)
    comment_raw = comment_match.group(1).replace('\\', '').strip() if comment_match else ""
    
    has_comment = bool(comment_raw)
    order_display = order_id if has_comment else f"{order_id}"

    # --- ЛОГИКА ПАКЕТОВ ---
    items_part = text.split("Тара:")[0]
    volumes = re.findall(r'(\d?[\d\.]+)\s*л\.', items_part)
    total_liters = sum(float(v) for v in volumes)
    
    # Считаем пакеты: каждые 7 литров = +1 пакет. Округление вверх.
    if total_liters > 0:
        bags_count = math.ceil(total_liters / 7)
    else:
        bags_count = 1

    has_weight_item = re.search(r'\d+\s*(?:г|кг)\.', text)
    fish_status = " 🐟 *РЫБА!*" if (has_weight_item and has_comment) else ""

    address_match = re.search(r'(ул\.[^\n]+)', text)
    if address_match:
        full_address = address_match.group(1).strip()
        store_icon = STORES.get(full_address, "❓")
        display_address = f"{store_icon} {full_address}"
    else:
        display_address = "❌ адрес не указан"

    result = (
        f"*{display_address}*\n\n"
        f"*ЗАКАЗ:* #`{order_display}`\n\n"
        f"*КЛИЕНТ:* +7`{clean_phone}`\n\n"
        f"*СУММА:* {amount}{fish_status}"
    )

    # Вывод только при наличии комментария
    if has_comment:
        result += f"\n\n*ПАКЕТОВ:* {bags_count}шт."
        result += f"\n\n💬 *КОММЕНТАРИЙ:* {comment_raw}"

    return result

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    await message.answer("✅ Подписка оформлена!")

@dp.channel_post(F.text)
async def handle_channel_post(message: types.Message):
    # Мониторим только указанный канал
    if message.chat.id != SOURCE_CHANNEL_ID or "заказ" not in message.text.lower():
        return
    clean_info = parse_order(message.text)
    for user_id in subscribed_users:
        try:
            await bot.send_message(chat_id=user_id, text=clean_info)
        except Exception as e:
            logging.error(f"Ошибка отправки {user_id}: {e}")

@dp.message(F.text)
async def handle_private_test(message: types.Message):
    clean_info = parse_order(message.text)
    await message.answer(f"*Результат теста:*\n\n{clean_info}")

async def main():
    load_users()
    print(f"Бот запущен. Канал: {SOURCE_CHANNEL_ID}")
    await bot.delete_webhook(drop_pending_updates=True)
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Ошибка: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main()) # Просто вызываем функцию
    except KeyboardInterrupt:
        pass