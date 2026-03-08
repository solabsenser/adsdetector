import asyncio
import hashlib
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from groq import Groq

BOT_TOKEN = "BOT_TOKEN"
GROQ_KEY = "GROQ_API_KEY"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

client = Groq(api_key=GROQ_KEY)

# --------- DATA ---------

whitelist = {}
antispam_enabled = {}
cache = {}
user_activity = {}

SUSPICIOUS = [
    "http",
    "https",
    "t.me",
    "@",
    "заработок",
    "инвестиции",
    "ставки",
    "казино",
    "пишите",
    "канал",
    "crypto",
    "bet"
]

# --------- HELPERS ---------

def is_suspicious(text: str):
    text = text.lower()
    return any(word in text for word in SUSPICIOUS)

def message_hash(text: str):
    return hashlib.md5(text.encode()).hexdigest()

def check_flood(chat_id, user_id):

    key = f"{chat_id}:{user_id}"

    now = asyncio.get_event_loop().time()

    timestamps = user_activity.get(key, [])
    timestamps = [t for t in timestamps if now - t < 5]

    timestamps.append(now)

    user_activity[key] = timestamps

    return len(timestamps) >= 3

async def ai_check(text):

    prompt = f"""
Ты антиспам фильтр Telegram.

Сообщение:
{text}

Это реклама или спам?

Ответь только одним словом:

SPAM
или
OK
"""

    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role":"user","content":prompt}],
    )

    return response.choices[0].message.content.strip()

# --------- PANEL ---------

def panel_keyboard(chat_id):

    enabled = antispam_enabled.get(chat_id, True)

    status = "🟢 ON" if enabled else "🔴 OFF"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Antispam {status}", callback_data="toggle")],
        ]
    )

@dp.message(Command("panel"))
async def panel(message: Message):

    chat_id = message.chat.id

    if message.chat.type == "private":
        return

    if not message.from_user:
        return

    member = await bot.get_chat_member(chat_id, message.from_user.id)

    if member.status not in ["administrator","creator"]:
        return

    await message.reply("Antispam panel", reply_markup=panel_keyboard(chat_id))

@dp.callback_query(F.data == "toggle")
async def toggle_antispam(call: CallbackQuery):

    chat_id = call.message.chat.id

    current = antispam_enabled.get(chat_id, True)

    antispam_enabled[chat_id] = not current

    await call.message.edit_reply_markup(reply_markup=panel_keyboard(chat_id))

# --------- WHITELIST ---------

@dp.message(Command("whitelist"))
async def whitelist_add(message: Message):

    if not message.reply_to_message:
        return

    chat_id = message.chat.id

    member = await bot.get_chat_member(chat_id, message.from_user.id)

    if member.status not in ["administrator","creator"]:
        return

    user_id = message.reply_to_message.from_user.id

    whitelist.setdefault(chat_id,set()).add(user_id)

# --------- FILTER ---------

@dp.message()
async def filter_message(message: Message):

    chat_id = message.chat.id

    if message.chat.type == "private":
        return

    if not antispam_enabled.get(chat_id, True):
        return

    if not message.from_user:
        return

    user_id = message.from_user.id

    if user_id in whitelist.get(chat_id,set()):
        return

    text = message.text or message.caption or ""

    if not text:
        return

    suspicious = is_suspicious(text)

    flood = check_flood(chat_id,user_id)

    bot_sender = message.from_user.is_bot

    if not suspicious and not flood and not bot_sender:
        return

    h = message_hash(text)

    if h in cache:
        result = cache[h]
    else:
        result = await ai_check(text)
        cache[h] = result

    if result == "SPAM":

        try:
            await message.delete()
        except:
            pass

# --------- MAIN ---------

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
