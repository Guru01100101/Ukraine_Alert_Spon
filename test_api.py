#!/usr/bin/env python3
"""Тестовий скрипт для перевірки API тривог"""
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

ALERT_TOKEN = os.getenv("ALERT_TOKEN")
print(f"🔍 Токен з .env: {ALERT_TOKEN}")
print(f"🔍 Токен тип: {type(ALERT_TOKEN)}")
print(f"🔍 Токен є None: {ALERT_TOKEN is None}")
print(f"🔍 Довжина токену: {len(ALERT_TOKEN) if ALERT_TOKEN else 0}")

async def test_api():
    headers = {"Authorization": ALERT_TOKEN}
    url = "https://api.ukrainealarm.com/api/v3/alerts/status"
    
    print(f"\n📡 Запит до: {url}")
    print(f"📋 Headers: {headers}")
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            print(f"\n✅ Статус відповіді: {response.status}")
            print(f"📋 Response Headers: {dict(response.headers)}")
            
            if response.status == 200:
                data = await response.json()
                print(f"✅ Успіх! Дані: {data}")
            else:
                text = await response.text()
                print(f"❌ Помилка! Тіло відповіді: {text}")

if __name__ == "__main__":
    asyncio.run(test_api())

