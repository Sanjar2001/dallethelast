import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters.command import Command
from aiogram.types import FSInputFile
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import openai
import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=os.getenv('TELEGRAM_BOT_TOKEN'))

# Настройка OpenAI
openai.api_key = os.getenv('OPENAI_API_KEY')

# Настройка базы данных
Base = declarative_base()
engine = create_engine('sqlite:///bot_database.db')
Session = sessionmaker(bind=engine)

class UserRequest(Base):
    __tablename__ = 'user_requests'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    request_time = Column(DateTime, default=datetime.utcnow)
    request_type = Column(String)

Base.metadata.create_all(engine)

# Функция для проверки ограничений
def check_rate_limit(user_id: int, request_type: str) -> bool:
    session = Session()
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    count = session.query(UserRequest).filter(
        UserRequest.user_id == user_id,
        UserRequest.request_type == request_type,
        UserRequest.request_time > one_hour_ago
    ).count()
    session.close()
    return count < 5  # Ограничение: 5 запросов в час

# Функция для сохранения запроса в БД
def save_request(user_id: int, request_type: str):
    session = Session()
    new_request = UserRequest(user_id=user_id, request_type=request_type)
    session.add(new_request)
    session.commit()
    session.close()

# Функция для генерации изображения
async def generate_image(prompt: str) -> str:
    response = openai.Image.create(
        prompt=prompt,
        n=1,
        size="1024x1024"
    )
    return response['data'][0]['url']

# Функция для генерации ответа с помощью GPT-4
async def generate_gpt4_response(prompt: str) -> dict:
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Вы - полезный ассистент, который может отвечать на вопросы и определять, нужно ли сгенерировать изображение для ответа."},
            {"role": "user", "content": prompt}
        ],
        functions=[
            {
                "name": "generate_image",
                "description": "Генерирует изображение на основе описания",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_description": {
                            "type": "string",
                            "description": "Описание изображения для генерации"
                        }
                    },
                    "required": ["image_description"]
                }
            }
        ],
        function_call="auto"
    )

    return response['choices'][0]['message']

# Обработчик текстовых сообщений
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    
    if not check_rate_limit(user_id, 'text'):
        await message.answer("Вы достигли лимита запросов. Пожалуйста, попробуйте позже.")
        return

    save_request(user_id, 'text')

    # Генерация ответа с помощью GPT-4
    gpt_response = await generate_gpt4_response(message.text)

    if gpt_response.get("function_call"):
        if not check_rate_limit(user_id, 'image'):
            await message.answer("Вы достигли лимита запросов на изображения. Пожалуйста, попробуйте позже.")
            return

        save_request(user_id, 'image')
        image_description = gpt_response["function_call"]["arguments"]["image_description"]
        image_url = await generate_image(image_description)
        await message.answer_photo(photo=image_url, caption=gpt_response["content"])
    else:
        await message.answer(gpt_response["content"])

# Инициализация диспетчера
dp = Dispatcher()

# Регистрация обработчиков
dp.message.register(handle_message)

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
