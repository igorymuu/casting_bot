import logging
import json
import datetime
from sqlalchemy import insert
from openai import AsyncOpenAI
import ast

from config import settings
from database.session import async_session
from database.models import Casting
from matcher.service import match_casting_with_actors

logger = logging.getLogger(__name__)

# Допустимые категории:
PROJECT_TYPES = [
    "Кино и сериалы", "Реклама", "Некоммерч./короткометражные фильмы", 
    "Международные проекты", "Клипы", "Театр", "Озвучка/дубляж", "Другое"
]

CITIES = ["Москва", "Санкт-Петербург", "Все города"]

SYSTEM_PROMPT = f"""
Ты — профессиональный ассистент по парсингу кастингов. Твоя задача: извлечь критерии из текста кастинга и вернуть их в строгом JSON-формате. Никакого другого текста, только чистый JSON - никаких markdown-блоков (```json ... ```).

Структура JSON-ответа должна быть такой:
{{
    "genders": ["Мужской", "Женский"], 
    "age_min": 0,
    "age_max": 100,
    "cities": ["Москва"], 
    "project_types": ["Реклама"], 
    "fee": 5000, 
    "is_ams": false,
    "slavic_only": false
}}

Правила:
- age_min / age_max: целые числа (по умолчанию 0 и 100).
- cities: список городов. Разрешенные значения: {", ".join(CITIES)}. Если не указано или удаленка, пиши "Все города".
- project_types: тип проекта, разрешены только {", ".join(PROJECT_TYPES)}. В случае сомнений ставь "Другое". Максимум 3 варианта!
- fee: Если не указано, "тфп" или "без оплаты", ставь 0. Иначе целое число рублей за смену.
- is_ams: true если массовка/АМС.
- slavic_only: true если требуется строго славянская/европейская внешность.
"""

# Инициализируем клиента OpenAI с Base URL от ClaudeHub
# Используем тот же самый GEMINI_API_KEY — в .env лежит ключ от OpenRouter,
# и нужно добавить новый ключ CLAUDEHUB_API_KEY для ClaudeHub
client = AsyncOpenAI(
    base_url="https://api.deepseek.com/v1",
    api_key=settings.GEMINI_API_KEY or "",
)

def _is_valid_casting_criteria(criteria: dict, original_text: str = "") -> bool:
    """
    Проверяет, содержат ли критерии осмысленные данные кастинга.
    """
    if not criteria:
        return False

    # Если в тексте есть пометка #реклама — игнорируем полностью (реклама товаров/услуг)
    if "#реклама" in original_text.lower() or "#реклама" in original_text.lower().replace(" ", ""):
        return False

    age_min = criteria.get("age_min", 0)
    age_max = criteria.get("age_max", 100)
    genders = criteria.get("genders", [])
    cities = criteria.get("cities", [])
    project_types = criteria.get("project_types", [])
    fee = criteria.get("fee", 0) or 0

    age_is_default = (age_min == 0 and age_max == 100)
    gender_is_default = (len(genders) == 2 or len(genders) == 0)
    city_is_default = (cities == [] or cities == ["Все города"])
    type_is_default = (project_types == [] or project_types == ["Другое"])
    fee_is_default = (fee == 0)

    # Если ВСЁ дефолтное — это не кастинг
    if age_is_default and gender_is_default and city_is_default and type_is_default and fee_is_default:
        return False

    # Если тип проекта "Другое" И больше ничего конкретного (возраст, пол, fee) — не кастинг (реклама/объявление)
    if type_is_default and age_is_default and gender_is_default and fee_is_default:
        return False

    # Реклама — игнорируем полностью, не кастинг
    if "Реклама" in project_types:
        return False

    return True

async def parse_casting_text(text: str) -> dict:
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "YOUR_BOT_TOKEN_HERE":
        logger.error("API_KEY is not set! Using default {}")
        return {}

    # Минимальная длина — слишком короткий текст точно не кастинг
    if len(text.strip()) < 30:
        logger.info(f"Text too short to be a casting ({len(text)} chars), skipping.")
        return {}
        
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ]
        )
        
        result_text = response.choices[0].message.content.strip()
        # OpenRouter иногда возвращает markdown блоки даже с json_object
        if result_text.startswith("```json"):
            result_text = result_text[7:-3].strip()
        elif result_text.startswith("```"):
            result_text = result_text[3:-3].strip()
            
        data = json.loads(result_text)
        return data
    except Exception as e:
        logger.error(f"Error parsing casting via OpenRouter: {e}")
        return {}

async def process_new_casting(text: str, title: str = None, source_url: str = None) -> None:
    logger.info(f"Processing new casting. Title: {title}")
    
    if not title:
        title = text[:50] + "..." if len(text) > 50 else text
        
    # Разбираем текст через LLM (OpenRouter)
    criteria = await parse_casting_text(text)

    # Если критерии пустые или полностью дефолтные — это не кастинг, пропускаем
    if not _is_valid_casting_criteria(criteria, original_text=text):
        logger.info(f"Skipped: LLM returned default/empty criteria — not a real casting. Text: {text[:80]!r}")
        return
        
    # Сохраняем в БД
    async with async_session() as session:
        casting = Casting(
            title=title.replace("\n", " ").strip(),
            description=text,
            criteria=criteria,
            source_url=source_url,
            published_at=datetime.datetime.utcnow()
        )
        session.add(casting)
        await session.commit()
        await session.refresh(casting)
        
        casting_id = casting.id
        
    logger.info(f"Saved casting_id={casting_id}")
    
    # Запускаем матчер
    await match_casting_with_actors(casting_id)

