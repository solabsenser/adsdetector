import asyncio
import hashlib
import os
import asyncpg

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

from groq import Groq


BOT_TOKEN = os.getenv("BOT_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
DB_URL = os.getenv("DATABASE_URL")


bot = Bot(BOT_TOKEN)
dp = Dispatcher()

groq_client = Groq(api_key=GROQ_KEY)

db = None


# -------- LOCAL CACHE --------

message_cache = {}
user_activity = {}


# -------- SUSPICIOUS WORDS --------

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
    "bet",
    "ref"
]


# -------- DATABASE --------

async def init_db():
    global db

    db = await asyncpg.create_pool(
        DB_URL,
        min_size=1,
        max_size=5,
        command_timeout=60,
        statement_cache_size=0
    )

async def is_whitelisted(chat_id,user_id):

    row = await db.fetchrow(
        "select 1 from whitelist where chat_id=$1 and user_id=$2",
        chat_id,
        user_id
    )

    return bool(row)


async def add_whitelist(chat_id,user_id):

    await db.execute(
        "insert into whitelist(chat_id,user_id) values($1,$2) on conflict do nothing",
        chat_id,
        user_id
    )


async def antispam_enabled(chat_id):

    row = await db.fetchrow(
        "select enabled from chats where chat_id=$1",
        chat_id
    )

    if not row:
        await db.execute(
            "insert into chats(chat_id,enabled) values($1,true)",
            chat_id
        )
        return True

    return row["enabled"]


async def toggle_antispam(chat_id):

    await db.execute(
        "update chats set enabled = not enabled where chat_id=$1",
        chat_id
    )


# -------- HELPERS --------

def suspicious(text):

    text = text.lower()

    return any(word in text for word in SUSPICIOUS)


def msg_hash(text):

    return hashlib.md5(text.encode()).hexdigest()


def check_flood(chat_id,user_id):

    key = f"{chat_id}:{user_id}"

    now = asyncio.get_event_loop().time()

    timestamps = user_activity.get(key,[])

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

Ответь только:

SPAM
или
OK
"""

    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role":"user","content":prompt}]
    )

    return response.choices[0].message.content.strip()


# -------- PANEL --------

def panel():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Toggle Antispam",callback_data="toggle")]
        ]
    )


@dp.message(Command("panel"))
async def panel_cmd(message: Message):

    if message.chat.type == "private":
        return

    member = await bot.get_chat_member(message.chat.id,message.from_user.id)

    if member.status not in ["administrator","creator"]:
        return

    await message.reply("Antispam control",reply_markup=panel())


@dp.callback_query(F.data=="toggle")
async def toggle(call: CallbackQuery):

    await toggle_antispam(call.message.chat.id)

    await call.answer()


# -------- WHITELIST --------

@dp.message(Command("whitelist"))
async def whitelist(message: Message):

    if not message.reply_to_message:
        return

    member = await bot.get_chat_member(message.chat.id,message.from_user.id)

    if member.status not in ["administrator","creator"]:
        return

    user_id = message.reply_to_message.from_user.id

    await add_whitelist(message.chat.id,user_id)


# -------- FILTER --------

@dp.message()
async def filter_msg(message: Message):

    if message.chat.type == "private":
        return

    if not message.from_user:
        return

    chat_id = message.chat.id
    user_id = message.from_user.id

    if not await antispam_enabled(chat_id):
        return

    if await is_whitelisted(chat_id,user_id):
        return

    text = message.text or message.caption or ""

    if not text:
        return

    suspect = suspicious(text)
    flood = check_flood(chat_id,user_id)
    bot_sender = message.from_user.is_bot

    if not suspect and not flood and not bot_sender:
        return

    h = msg_hash(text)

    if h in message_cache:

        result = message_cache[h]

    else:

        result = await ai_check(text)

        message_cache[h] = result

    if result == "SPAM":

        try:
            await message.delete()
        except:
            pass


# -------- START --------

async def main():

    await init_db()

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
