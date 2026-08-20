import os
import asyncio
import logging
import re
import math
import json
import hashlib
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
SOURCE_CHAT_IDS = {
    -1003769319642,  # канал "ЁП App (новый)" — старый источник
    -1004443006213,  # группа "ЕП v2" — новый источник
}
LAST_ID_FILE = "last_ids.json"    # {chat_id: last_message_id} — отдельно по каждому источнику
SEEN_FILE = "seen_orders.json"    # ключи уже разосланных заказов
SEEN_LIMIT = 1000

if not TOKEN:
    exit("Ошибка: Токен не найден в .env!")

logging.basicConfig(level=logging.INFO)
session = AiohttpSession(proxy=PROXY_URL)
bot = Bot(token=TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()
subscribed_users = set()
seen_orders = []      # ключи в порядке поступления, хвост длиной SEEN_LIMIT
seen_keys = set()     # он же для быстрой проверки

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


def escape_md(text: str) -> str:
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text

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

def load_last_ids() -> dict:
    if os.path.exists(LAST_ID_FILE):
        try:
            with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
                return {int(k): int(v) for k, v in json.load(f).items()}
        except Exception as e:
            logging.error(f"Не читается {LAST_ID_FILE}: {e}")
    return {}

def save_last_id(chat_id: int, message_id: int):
    data = load_last_ids()
    data[chat_id] = message_id
    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in data.items()}, f)

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                seen_orders.extend(json.load(f))
        except Exception as e:
            logging.error(f"Не читается {SEEN_FILE}: {e}")
    seen_keys.update(seen_orders)

def mark_seen(key: str):
    seen_orders.append(key)
    seen_keys.add(key)
    del seen_orders[:-SEEN_LIMIT]
    seen_keys.intersection_update(seen_orders)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_orders, f, ensure_ascii=False)

def order_key(text: str) -> str:
    # Один и тот же заказ приходит из двух источников — ключом служит номер #N.
    match = re.search(r'#(\d+)', text)
    if match:
        return match.group(1)
    # Номера нет — опираемся на текст; пробелы между источниками могут отличаться.
    return "h:" + hashlib.sha1(" ".join(text.split()).encode("utf-8")).hexdigest()

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

    NON_FISH_KEYWORDS = [
        'миндаль', 'фисташки', 'фисташка', 'арахис',
    ]
    weight_pattern = re.compile(r'\d+\s*(?:г|кг)\.')
    has_fish_item = any(
        weight_pattern.search(line)
        and not any(kw in line.lower() for kw in NON_FISH_KEYWORDS)
        for line in text.splitlines()
    )
    fish_status = " 🐟 *РЫБА!*" if (has_fish_item and has_comment) else ""

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
        result += f"\n\n💬 *КОММЕНТАРИЙ:* {escape_md(comment_raw)}"

    return result

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    save_user(message.from_user.id)
    await message.answer("✅ Подписка оформлена!")

@dp.channel_post(F.chat.id.in_(SOURCE_CHAT_IDS), F.text)
@dp.message(F.chat.id.in_(SOURCE_CHAT_IDS), F.text)
async def handle_source_post(message: types.Message):
    # Посты канала приходят как channel_post, сообщения группы — как message.
    if "заказ" not in message.text.lower():
        return

    chat_id = message.chat.id
    current_id = message.message_id
    last_id = load_last_ids().get(chat_id, 0)

    # ПРОВЕРКА НА ПРОПУСКИ:
    if last_id > 0 and current_id > last_id + 1:
        missed_count = (current_id - last_id) - 1
        warning_text = (
            f"⚠️ *ВНИМАНИЕ! ВОЗМОЖЕН ПРОПУСК!*\n\n"
            f"Бот зафиксировал скачок в «{escape_md(message.chat.title or str(chat_id))}». Пропущено: *{missed_count} шт.*\n"
            f"Пожалуйста, зайдите туда и проверьте заказы вручную!"
        )
        for user_id in subscribed_users:
            try:
                await bot.send_message(chat_id=user_id, text=warning_text)
            except Exception as e:
                logging.error(f"Ошибка отправки предупреждения {user_id}: {e}")

    # Сохраняем текущий ID как последний успешный (у каждого источника свой)
    save_last_id(chat_id, current_id)

    # ЗАЩИТА ОТ ДУБЛЕЙ: один и тот же заказ приходит и из канала, и из группы —
    # рассылаем только тот, что пришёл первым.
    key = order_key(message.text)
    if key in seen_keys:
        logging.info(f"Заказ {key} уже разослан, дубль из чата {chat_id} пропущен")
        return
    mark_seen(key)

    # Стандартная логика
    clean_info = parse_order(message.text)
    
    # Отправка подписчикам
    for user_id in subscribed_users:
        try:
            await bot.send_message(chat_id=user_id, text=clean_info)
        except Exception as e:
            logging.error(f"Ошибка отправки {user_id}: {e}")

@dp.message(F.chat.type == "private", F.text)
async def handle_private_test(message: types.Message):
    clean_info = parse_order(message.text)
    await message.answer(f"*Результат теста:*\n\n{clean_info}")

async def main():
    load_users()
    load_seen()
    print(f"Бот запущен. Источники: {sorted(SOURCE_CHAT_IDS)}; известных заказов: {len(seen_keys)}")
    
    # drop_pending_updates изменено на False
    await bot.delete_webhook(drop_pending_updates=False) 
    
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Ошибка: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass