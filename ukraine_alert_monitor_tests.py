
"""
Тестовий скрипт для перевірки роботи Ukraine Alert Monitor
"""
import asyncio
import aiohttp
import json
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

ALERT_TOKEN = os.getenv("ALERT_TOKEN")
SPON_IP = os.getenv("SPON_IP", "10.123.50.24")
REGION_IDS = json.loads(os.getenv("REGION_ID", "[23]"))


class TestSuite:
    """Набір тестів для перевірки функціональності."""
    
    def __init__(self):
        self.alert_headers = {"Authorization": ALERT_TOKEN}
        self.spon_base_url = f"http://{SPON_IP}"
        self.session = None
    
    async def get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def test_alert_api_connection(self):
        """Тест 1: Перевірка підключення до Alert API"""
        print("\n" + "="*60)
        print("ТЕСТ 1: Перевірка підключення до Ukraine Alert API")
        print("="*60)
        
        try:
            session = await self.get_session()
            url = "https://api.ukrainealarm.com/api/v3/alerts/status"
            
            async with session.get(url, headers=self.alert_headers) as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ Підключення успішне!")
                    print(f"   lastActionIndex: {data.get('lastActionIndex')}")
                    return True
                else:
                    print(f"❌ Помилка: HTTP {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Помилка підключення: {e}")
            return False
    
    async def test_alert_api_regions(self):
        """Тест 2: Перевірка отримання даних по регіонах"""
        print("\n" + "="*60)
        print("ТЕСТ 2: Перевірка отримання даних по регіонах")
        print("="*60)
        
        try:
            session = await self.get_session()
            
            for region_id in REGION_IDS:
                url = f"https://api.ukrainealarm.com/api/v3/alerts/{region_id}"
                
                async with session.get(url, headers=self.alert_headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        if isinstance(data, list) and len(data) > 0:
                            region_data = data[0]
                            region_name = region_data.get("regionName", "Невідомо")
                            has_alert = len(region_data.get("activeAlerts", [])) > 0
                            last_update = region_data.get("lastUpdate", "Невідомо")

                            status_icon = "" if has_alert else "✅"
                            status_text = "ТРИВОГА" if has_alert else "БЕЗ ТРИВОГИ"

                            print(f"\n{status_icon} Регіон ID: {region_id}")
                            print(f"   Назва: {region_name}")
                            print(f"   Статус: {status_text}")
                            print(f"   Оновлено: {last_update}")
                        else:
                            print(f"❌ Регіон {region_id}: Некоректні дані")
                    else:
                        print(f"❌ Регіон {region_id}: HTTP {response.status}")
            
            return True
        except Exception as e:
            print(f"❌ Помилка: {e}")
            return False
    
    async def test_spon_connection(self):
        """Тест 3: Перевірка підключення до SPON сервера"""
        print("\n" + "="*60)
        print("ТЕСТ 3: Перевірка підключення до SPON сервера")
        print("="*60)
        
        try:
            session = await self.get_session()
            url = f"{self.spon_base_url}/php/getversiondata.php"

            async with session.post(url) as response:
                if response.status == 200:
                    result = await response.json()
                    if "sipver" in result:
                        print(f"✅ Підключення до SPON успішне!")
                        print(f"   Версія SIP: {result.get('sipver', 'Невідомо')}")
                        return True
                    else:
                        print(f"⚠️  Сервер відповів, але формат не відповідає очікуваному: {result}")
                        return False
                else:
                    print(f"❌ Помилка: HTTP {response.status}")
                    return False
        except Exception as e:
            print(f"❌ Помилка підключення до SPON: {e}")
            print(f"   Перевірте:")
            print(f"   - Чи правильний IP адрес: {SPON_IP}")
            print(f"   - Чи сервер доступний у мережі")
            print(f"   - Чи немає блокування firewall")
            return False
    
    async def test_local_files(self):
        """Тест 4: Перевірка наявності локальних аудіофайлів"""
        print("\n" + "="*60)
        print("ТЕСТ 4: Перевірка наявності локальних аудіофайлів")
        print("="*60)
        
        file_on = os.getenv("FILE_ON", "START_ALARM.mp3")
        file_off = os.getenv("FILE_OFF", "END_ALARM.mp3")
        
        files = [file_on, file_off]
        all_ok = True
        
        for filename in files:
            file_path = Path(filename)
            if file_path.exists():
                file_size = file_path.stat().st_size
                print(f"✅ {filename}")
                print(f"   Розмір: {file_size:,} байт ({file_size/1024:.1f} KB)")
            else:
                print(f"❌ {filename} - ФАЙЛ НЕ ЗНАЙДЕНО!")
                all_ok = False
        
        return all_ok
    
    async def test_state_file(self):
        """Тест 5: Перевірка файлу стану"""
        print("\n" + "="*60)
        print("ТЕСТ 5: Перевірка файлу стану")
        print("="*60)
        
        state_file = Path("alert_state.json")
        
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                
                print(f"✅ Файл стану знайдено")
                print(f"   Last Action Index: {state.get('last_action_index')}")
                print(f"   First Run: {state.get('first_run')}")
                print(f"   Регіонів відстежується: {len(state.get('regions', {}))}")
                
                return True
            except Exception as e:
                print(f"⚠️  Файл існує, але помилка читання: {e}")
                return False
        else:
            print(f"ℹ️  Файл стану не існує (буде створений при першому запуску)")
            return True
    
    async def test_env_config(self):
        """Тест 6: Перевірка конфігурації .env"""
        print("\n" + "="*60)
        print("ТЕСТ 6: Перевірка конфігурації .env")
        print("="*60)
        
        required_vars = {
            "ALERT_TOKEN": ALERT_TOKEN,
            "SPON_IP": SPON_IP,
            "REGION_ID": REGION_IDS,
            "SPON_USER": os.getenv("SPON_USER", "admin"),
            "FILE_ON": os.getenv("FILE_ON", "START_ALARM.mp3"),
            "FILE_OFF": os.getenv("FILE_OFF", "END_ALARM.mp3"),
            "CHECK_INTERVAL": os.getenv("CHECK_INTERVAL", "30")
        }
        
        all_ok = True
        
        for var_name, var_value in required_vars.items():
            if var_value:
                # Приховуємо частину токена
                if "TOKEN" in var_name and isinstance(var_value, str):
                    display_value = var_value[:10] + "..." if len(var_value) > 10 else var_value
                else:
                    display_value = var_value
                
                print(f"✅ {var_name}: {display_value}")
            else:
                print(f"❌ {var_name}: НЕ ВСТАНОВЛЕНО!")
                all_ok = False
        
        return all_ok
    
    async def run_all_tests(self):
        """Запуск всіх тестів"""
        print("\n" + " " * 30)
        print("ЗАПУСК ТЕСТІВ UKRAINE ALERT MONITOR")
        print(" " * 30)

        results = []

        # Тест конфігурації
        results.append(("Конфігурація .env", await self.test_env_config()))

        # Тест локальних файлів
        results.append(("Локальні аудіофайли", await self.test_local_files()))

        # Тест Alert API
        results.append(("Ukraine Alert API - підключення", await self.test_alert_api_connection()))
        results.append(("Ukraine Alert API - регіони", await self.test_alert_api_regions()))

        # Тест SPON сервера
        results.append(("SPON сервер", await self.test_spon_connection()))

        # Тест файлу стану
        results.append(("Файл стану", await self.test_state_file()))

        # Підсумок
        print("\n" + "=" * 60)
        print("ПІДСУМОК ТЕСТУВАННЯ")
        print("=" * 60)

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for test_name, result in results:
            icon = "✅" if result else "❌"
            print(f"{icon} {test_name}")

        print(f"\nПройдено: {passed}/{total}")

        if passed == total:
            print("\n Всі тести пройдено успішно! Скрипт готовий до роботи.")
            return True
        else:
            print(f"\n⚠️  Деякі тести не пройдено. Перевірте конфігурацію.")
            return False
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


async def main():
    test_suite = TestSuite()
    try:
        await test_suite.run_all_tests()
    finally:
        await test_suite.close()


if __name__ == "__main__":
    print("\n" + "⚡" * 30)
    print("ТЕСТУВАННЯ СКРИПТА МОНІТОРИНГУ ТРИВОГ")
    print("⚡" * 30)

    asyncio.run(main())
