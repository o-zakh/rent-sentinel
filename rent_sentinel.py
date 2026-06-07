#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Rent Sentinel - Автоматический фильтр квартир на Телефоне
Сгенерировано в консоли: 06.06.2026

Данный скрипт запускает телеграм-юзербота, который слушает входящие сообщения
в выбранных группах, фильтрует по бюджету, разрешению на питомцев и вашим
ключевым словам, после чего пересылает отобранные варианты в ваш приватный канал.
"""

import os
import re
import json
import asyncio
from telethon import TelegramClient, events

# ================= НАСТРОЙКИ С ПАНЕЛИ УПРАВЛЕНИЯ =================

# Для работы вам понадобятся API_ID и API_HASH (получите их на my.telegram.org)
API_ID = int(os.getenv("TELEGRAM_API_ID", "38013664"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "f8fd7ef3c0cc1d5bac4859d3ae106448")
SESSION_NAME = "rent_sentinel_session"

# Список отслеживаемых групп и каналов (только активные)
TRACKED_CHATS = ['@Relocation_Erevan', '@arendaVyerevanee', '@Arenda_kvartir_yerevan', '@arenda_erevan_kvartira_evn', '@kvartiry_yerevan']

# Целевой чат/канал для отправки одобренных предложений
FORWARD_TARGET_CHAT = '@myOwnGroup4651'

# Параметры фильтрации
MAX_RENT_PRICE = 250000
TARGET_CURRENCY = 'AMD'

# Ключевые слова для питомцев
PETS_ALLOW_WORDS = ['можно с животными', 'pet-friendly', 'можно с кошкой', 'можно с собакой', 'животные обсуждаются', 'можно с питомцами', 'pets allowed', 'котик', 'с животными - по договоренности', 'Питомцы — по договорённости']
PETS_DENY_WORDS = ['без животных', 'строго без животных', 'no pets', 'без собак', 'без кошек', 'никаких животных', 'strict no pets', 'Питомцы — нет', 'с животными - нет']

# Дополнительные ключевые фразы
MUST_HAVE_KEYWORDS = []
AVOID_KEYWORDS = []

    # Опционально: Использование ИИ модели Gemini для сверхгибкой фильтрации
    # (если в настройках включен Smart AI)
AI_ENABLED = False
if AI_ENABLED:
    try:
        from google import genai
        from google.genai import types
        # Инициализация клиента. API ключ подтягивается из переменной окружения GEMINI_API_KEY
        ai = genai.Client()
    except ImportError:
        print("Предупреждение: библиотека google-genai не установлена. Используйте: pip install google-genai")
        AI_ENABLED = False
    

def parse_with_gemini(text: str):
    """
    Вызов API Gemini для детального извлечения параметров
    """
    if not AI_ENABLED:
        return None
    try:
        prompt = f"Проанализируй текст объявления об аренде жилья и извлеки параметры в формате JSON:\n{text}"
        
        # Задаем строгую схему ответа
        response_schema = {
            "type": "OBJECT",
            "properties": {
                "price": {"type": "INTEGER", "description": "Месячная стоимость в виде числа (например, 250000)"},
                "currency": {"type": "STRING", "description": "Символ или буквенный код валюты"},
                "pets_allowed": {"type": "BOOLEAN", "description": "Возвращайте False ТОЛЬКО если проживание с животными явно и строго запрещено. Возвращайте True, если животные явно разрешены, либо если в объявлении вообще не упоминаются правила касательно животных (неявное допущение)."},
                "pets_justification": {"type": "STRING", "description": "Фраза или обоснование из текста касательно животных (например, 'явно запрещено', 'явно разрешено', или 'не упомянуто, неявно разрешено')"}
            },
            "required": ["price", "currency", "pets_allowed", "pets_justification"]
        }

        response = ai.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="Ты экспертный парсер аренды жилья. Извлекай точную стоимость аренды и анализируй статус питомцев. Важно: отмечай pets_allowed как True, если в тексте нет явного упоминания запрета животных (неявное допущение). Если животные явно запрещены в любой форме - отмечай pets_allowed как False.",
                response_mime_type="application/json",
                response_schema=response_schema
            )
        )
        # Получаем очищенный результат
        return json.loads(response.text)
    except Exception as e:
        print(f"[ИИ Ошибка] Не удалось распарсить ИИ: {e}. Откат на ключевые слова.")
        return None
    

def extract_amd_price(text: str) -> int:
    """
    Поиск сумм в объявлении без учета валют. Ищет любые числа в тексте.
    """
    norm_text = text.lower()
    # Находим все числовые последовательности с возможными разделителями (пробел, точка, запятая), поддерживая слитное написание с буквами (например, 350.000АМД)
    candidates = re.findall(r'(?<!\d)(?:\d{1,3}(?:[\s.,]\d{3})+|\d{5,6})(?!\d)', norm_text)
    
    all_vals = []
    for cand in candidates:
         val_str = cand.replace(" ", "").replace(".", "").replace(",", "")
         if val_str.isdigit():
             all_vals.append(int(val_str))
             
    if not all_vals:
        return 0
        
    # Ищем подходящую под диапазон 100000 - 250000 последнюю сумму
    range_candidates = [v for v in all_vals if 100000 <= v <= 250000]
    if range_candidates:
         return range_candidates[-1]
         
    # Если нет подходящих сумм, возвращаем последнюю найденную сумму в тексте (например, 300000), 
    # чтобы отфильтровать ее с детальным выводом ошибки
    return all_vals[-1]

def check_listing_by_rules(text: str):
    """
    Классический парсер на основе регулярных выражений и ключевых слов
    """
    norm_text = text.lower()
    
    # Сначала проверяем стоп-слова из черного списка
    for stop_word in AVOID_KEYWORDS:
        if stop_word.lower() in norm_text:
            return False, f"Стоп-слово: '{stop_word}'"
            
    # Проверяем обязательные ключевые слова (если заданы)
    if MUST_HAVE_KEYWORDS:
        found_must = any(must.lower() in norm_text for must in MUST_HAVE_KEYWORDS)
        if not found_must:
            return False, "Нет ни одного обязательного ключевого слова"

    # Извлечение цены при помощи умной функции
    parsed_price = extract_amd_price(norm_text)
    
    if parsed_price == 0:
        return False, "Цена в объявлении не распознана"
    
    if not (100000 <= parsed_price <= MAX_RENT_PRICE):
        return False, f"Цена {parsed_price} вне допустимого диапазона (100000 - {MAX_RENT_PRICE})"

    # Фильтрация по питомцам
    has_deny = any(deny.lower() in norm_text for deny in PETS_DENY_WORDS)

    if has_deny:
        return False, f"В объявлении найден явный запрет на животных"

    # Если явного запрета нет, квартира подходит (неявно разрешено или явно подтверждено)
    return True, f"Одобрено (Цена: {parsed_price}, нет запрета на животных)"


# Создаем инстанс Telegram Client (Userbot)
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

@client.on(events.NewMessage(chats=TRACKED_CHATS))
async def incoming_message_handler(event):
    message_text = event.raw_text
    
    # Сразу игнорируем пустые сообщения или фотографии без подписи
    if not message_text or not message_text.strip() or len(message_text.strip()) < 10:
        print("⏭ Пропускаем пост: пустой текст или только фото без описания.")
        return

    sender_chat = await event.get_chat()
    sender_title = getattr(sender_chat, 'title', 'Неизвестный чат')
    sender_username = f"@{sender_chat.username}" if getattr(sender_chat, 'username', None) else "private"
    
    print(f"\n[===] Новое сообщение из {sender_title} ({sender_username}) [===]")
    
    is_valid = False
    reason = ""

    # Применяем ИИ для расширенного парсинга, если он включен
    if AI_ENABLED:
        ai_data = parse_with_gemini(message_text)
        if ai_data:
            price = ai_data.get("price", 0)
            pets_allowed = ai_data.get("pets_allowed", False)
            justification = ai_data.get("pets_justification", "")
            
            # Логика принятия решений
            if price == 0:
                reason = "Цена не распознана ИИ (равна 0)"
            elif not (100000 <= price <= MAX_RENT_PRICE):
                reason = f"Цена ИИ {price} вне диапазона 100000 - {MAX_RENT_PRICE}"
            elif not pets_allowed:
                reason = f"Запрет на питомцев по ИИ: {justification}"
            else:
                is_valid = True
                reason = f"Одобрено ИИ (Цена: {price}, животные: {justification})"
        else:
            # Откатываемся на правила в случае фиаско сети
            is_valid, reason = check_listing_by_rules(message_text)
    else:
        # Проверка по классическим ключевым словам
        is_valid, reason = check_listing_by_rules(message_text)

    # Пересылка, если логика подтвердила валидность
    if is_valid:
        print(f"✅ Фильтр Пройден! Причина: {reason}")
        print(f"Пересылаем объявление в канал {FORWARD_TARGET_CHAT}...")
        
        # Строим ссылку на исходное сообщение в Telegram
        message_id = event.message.id
        if getattr(sender_chat, 'username', None):
            msg_link = f"https://t.me/{sender_chat.username}/{message_id}"
        else:
            clean_chat_id = str(event.chat_id)
            if clean_chat_id.startswith("-100"):
                clean_chat_id = clean_chat_id[4:]
            elif clean_chat_id.startswith("-"):
                clean_chat_id = clean_chat_id[1:]
            msg_link = f"https://t.me/c/{clean_chat_id}/{message_id}"
            
        # Наводим красоту: добавляем источник к отправляемому сообщению
        formatted_forward_text = (
            f"🎯 **НАЙДЕНО ОБЪЯВЛЕНИЕ ПО ФИЛЬТРУ!**\n"
            f"📢 Источник: {sender_title} ({sender_username})\n"
            f"🔗 Ссылка на пост: {msg_link}\n"
            f"🔔 Вердикт: {reason}\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n"
            f"{message_text}"
        )
        
        try:
            await client.send_message(FORWARD_TARGET_CHAT, formatted_forward_text)
            print("🚀 Сообщение успешно переслано!")
        except Exception as e:
            print(f"❌ Ошибка пересылки сообщения: {e}")
    else:
        print(f"🚫 Проигнорировано. Причина: {reason}")

async def main():
    print("🤖 Запуск Telegram Rent Sentinel Userbot...")
    await client.start()
    print("✅ Юзербот успешно авторизован и запущен!")
    print(f"📡 Прослушивание чатов: {', '.join(TRACKED_CHATS)}")
    await client.run_until_disconnected()

if __name__ == "__main__":
    if not API_ID or API_HASH == "ваш_api_hash_из_telegram":
        print("❌ Ошибка! Пожалуйста, укажите TELEGRAM_API_ID и TELEGRAM_API_HASH в коде или в переменных окружения.")
    else:
        asyncio.run(main())
