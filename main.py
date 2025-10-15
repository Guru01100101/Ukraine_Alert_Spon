import os
import json
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Optional, Set
from dotenv import load_dotenv
from pathlib import Path

# Завантаження змінних середовища
load_dotenv()

# --- Конфігурація ---
ALERT_TOKEN = os.getenv("ALERT_TOKEN")
REGION_IDS = json.loads(os.getenv("REGION_ID", "[23]"))
SPON_IP = os.getenv("SPON_IP")
SPON_USER = os.getenv("SPON_USER", "admin")
SPON_PASSWORD = os.getenv("SPON_PASSWORD", "admin") # Наразі не використовується
FILE_ON = os.getenv("FILE_ON", "START_ALARM.mp3")
FILE_OFF = os.getenv("FILE_OFF", "END_ALARM.mp3")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))

# --- URL Конфігурація ---
ALERT_API_URL = "https://api.ukrainealarm.com/api/v3"
SPON_BASE_URL = f"http://{SPON_IP}"

# --- Глобальні змінні ---
STATE_FILE = Path("alert_state.json")


class AlertMonitor:
    """
    Клас для моніторингу повітряних тривог та керування системою оповіщення SPON XC-9000.
    """
    
    def __init__(self):
        # Перевірка токену при ініціалізації
        if not ALERT_TOKEN or ALERT_TOKEN == "your_token_here":
            print("❌ КРИТИЧНА ПОМИЛКА: Токен ALERT_TOKEN не налаштований у .env файлі!")
            print(f"   Поточне значення: {ALERT_TOKEN}")
            raise ValueError("ALERT_TOKEN must be set in .env file")

        print(f"✅ Токен завантажено: {ALERT_TOKEN[:10]}...{ALERT_TOKEN[-5:]}")
        self.alert_headers = {"Authorization": ALERT_TOKEN}
        self.state = self._load_state()
        self.session: Optional[aiohttp.ClientSession] = None
        self.uploaded_files: Set[str] = set()

    def _load_state(self) -> Dict:
        """Завантажує стан з файлу або створює новий, якщо файл відсутній/пошкоджений."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"⚠️  Помилка завантаження стану ({e}). Створюю новий файл.")
        
        return {
            "last_action_index": 0,
            "regions": {str(region_id): {
                "alert_status": False, 
                "last_update": None,
                "active_task_id": None
            } for region_id in REGION_IDS},
            "first_run": True
        }
    
    def _save_state(self):
        """Зберігає поточний стан у файл."""
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"❌ Помилка збереження стану: {e}")
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Створює або повертає існуючу aiohttp сесію."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _format_spon_data(self, payload: Dict) -> Dict:
        """Форматує дані для запитів до SPON API у формат jsondata[key]=value."""
        return {f"jsondata[{key}]": str(value) for key, value in payload.items()}

    async def _spon_request(self, endpoint: str, payload: Dict) -> Optional[Dict]:
        """Уніфікований метод для запитів до SPON API."""
        try:
            session = await self._get_session()
            url = f"{SPON_BASE_URL}{endpoint}"
            data = self._format_spon_data(payload)
            
            async with session.post(url, data=data) as response:
                response.raise_for_status()
                text_response = await response.text()
                return json.loads(text_response)
        except Exception as e:
            print(f"❌ Помилка запиту до {endpoint}: {e}")
            return None

    async def check_file_exists_on_server(self, filename: str) -> bool:
        """Перевіряє наявність файлу на сервері XC-9000."""
        if filename in self.uploaded_files:
            return True
            
        payload = {"pageIndex": 0, "pageCount": 100, "filter": filename, "subPath": ""}
        result = await self._spon_request("/php/getmediadata.php", payload)
        
        if result and int(result.get("res")) == 1 and int(result.get("total", 0)) > 0:
            for row in result.get("rows", []):
                if row.get("name") == filename:
                    self.uploaded_files.add(filename)
                    return True
        return False
    
    async def upload_file_to_server(self, local_filename: str) -> bool:
        """Завантажує аудіофайл на сервер XC-9000."""
        local_path = Path(local_filename)
        if not local_path.exists():
            print(f"❌ Локальний файл не знайдено: {local_filename}")
            return False
            
        try:
            session = await self._get_session()
            url = f"{SPON_BASE_URL}/php/addmediadata.php"
            
            data = aiohttp.FormData()
            data.add_field('file', open(local_path, 'rb'), filename=local_filename, content_type='audio/mpeg')
            data.add_field('unformat', '1')
            data.add_field('subpath', '')
            
            print(f"📤 Завантаження файлу {local_filename} на сервер...")
            async with session.post(url, data=data) as response:
                response.raise_for_status()
                # Читаємо відповідь як текст, щоб ігнорувати неправильний mimetype
                text_response = await response.text()
                result = json.loads(text_response)

                if int(result.get("res")) == 1:
                    uploaded_name = result.get("file", local_filename).strip()
                    print(f"✅ Файл успішно завантажено: {uploaded_name}")
                    self.uploaded_files.add(local_filename)
                    return True
                else:
                    print(f"❌ Помилка завантаження файлу: {result}")
                    return False
        except Exception as e:
            print(f"❌ Помилка при завантаженні файлу {local_filename}: {e}")
            return False

    async def ensure_file_on_server(self, filename: str) -> bool:
        """Перевіряє наявність файлу на сервері та завантажує його, якщо потрібно."""
        if await self.check_file_exists_on_server(filename):
            print(f"✓ Файл '{filename}' вже є на сервері.")
            return True
        
        print(f"ℹ️  Файл '{filename}' не знайдено на сервері.")
        return await self.upload_file_to_server(filename)
    
    async def check_alerts_status(self) -> Optional[int]:
        """Отримує `lastActionIndex` з API тривог."""
        try:
            session = await self._get_session()
            url = f"{ALERT_API_URL}/alerts/status"
            
            async with session.get(url, headers=self.alert_headers) as response:
                # Детальна обробка HTTP помилок згідно з документацією API
                if response.status == 401:
                    print(f"❌ Помилка авторизації (401): перевірте токен ALERT_TOKEN у .env файлі")
                    print(self.alert_headers)
                    return None
                elif response.status == 429:
                    print(f"⚠️  Перевищено ліміт запитів (429): зачекайте перед наступним запитом")
                    return None
                elif response.status != 200:
                    print(f"❌ HTTP помилка {response.status} при перевірці статусу тривог")
                    return None

                response.raise_for_status()
                result = await response.json()

                # Валідація структури відповіді згідно з AlertModification схемою
                if not isinstance(result, dict):
                    print(f"❌ Неочікуваний формат відповіді: очікувався об'єкт, отримано {type(result)}")
                    return None

                last_action_index = result.get("lastActionIndex")
                if last_action_index is None:
                    print(f"⚠️  Відсутнє поле lastActionIndex у відповіді API")
                    return None

                return last_action_index

        except aiohttp.ClientError as e:
            print(f"❌ Помилка мережі при перевірці статусу тривог: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"❌ Помилка парсингу JSON відповіді: {e}")
            return None
        except Exception as e:
            print(f"❌ Несподівана помилка при перевірці статусу: {e}")
            return None
    
    async def get_region_status(self, region_id: int, retry_count: int = 0) -> Optional[Dict]:
        """Отримує статус тривоги для конкретного регіону з автоматичним повторенням при помилках."""
        max_retries = 3
        retry_delay = 30  # секунд

        try:
            session = await self._get_session()
            url = f"{ALERT_API_URL}/alerts/{region_id}"
            
            async with session.get(url, headers=self.alert_headers) as response:
                # Детальна обробка HTTP помилок
                if response.status == 401:
                    if retry_count < max_retries:
                        print(f"⚠️  Регіон {region_id}: помилка авторизації (401), можливо перевищено ліміт запитів")
                        print(f"   Повторна спроба {retry_count + 1}/{max_retries} через {retry_delay} секунд...")
                        await asyncio.sleep(retry_delay)
                        return await self.get_region_status(region_id, retry_count + 1)
                    else:
                        print(f"❌ Регіон {region_id}: не вдалося отримати дані після {max_retries} спроб")
                        return None

                elif response.status == 429:
                    if retry_count < max_retries:
                        print(f"⚠️  Регіон {region_id}: перевищено ліміт запитів (429)")
                        print(f"   Повторна спроба {retry_count + 1}/{max_retries} через {retry_delay} секунд...")
                        await asyncio.sleep(retry_delay)
                        return await self.get_region_status(region_id, retry_count + 1)
                    else:
                        print(f"❌ Регіон {region_id}: перевищено ліміт запитів після {max_retries} спроб")
                        return None

                elif response.status == 404:
                    print(f"⚠️  Регіон {region_id} не знайдено (404)")
                    return None

                elif response.status != 200:
                    response_text = await response.text()
                    print(f"❌ HTTP помилка {response.status} для регіону {region_id}: {response_text}")
                    return None

                response.raise_for_status()
                data = await response.json()
                
                # Валідація: згідно з API документацією, відповідь має бути масивом AlertRegionModel[]
                if not isinstance(data, list):
                    print(f"❌ Неочікуваний формат відповіді для регіону {region_id}: очікувався масив, отримано {type(data)}")
                    return None

                # Перевірка що масив не порожній
                if len(data) == 0:
                    print(f"⚠️  API повернув порожній масив для регіону {region_id}")
                    return None

                region_data = data[0]

                # Валідація обов'язкових полів згідно з AlertRegionModel схемою
                if not isinstance(region_data, dict):
                    print(f"❌ Елемент масиву не є об'єктом для регіону {region_id}")
                    return None

                # Перевірка наявності ключових полів
                region_id_from_api = region_data.get("regionId")
                if not region_id_from_api:
                    print(f"⚠️  Відсутнє поле regionId у відповіді для регіону {region_id}")

                has_alert = bool(region_data.get("activeAlerts"))
                region_name = region_data.get("regionName", "Невідомо")

                # Вивід поточного статусу після перевірки
                status_icon = "🚨" if has_alert else "✅"
                status_text = "ТРИВОГА" if has_alert else "Спокійно"
                print(f"{status_icon} {region_name}: {status_text}")

                return {
                    "region_id": region_id,
                    "region_name": region_name,
                    "has_alert": has_alert,
                    "last_update": region_data.get("lastUpdate"),
                    "active_alerts": region_data.get("activeAlerts", [])
                }

        except aiohttp.ClientError as e:
            if retry_count < max_retries:
                print(f"⚠️  Помилка мережі при перевірці регіону {region_id}: {e}")
                print(f"   Повторна спроба {retry_count + 1}/{max_retries} через {retry_delay} секунд...")
                await asyncio.sleep(retry_delay)
                return await self.get_region_status(region_id, retry_count + 1)
            else:
                print(f"❌ Помилка мережі для регіону {region_id} після {max_retries} спроб: {e}")
                return None

        except json.JSONDecodeError as e:
            print(f"❌ Помилка парсингу JSON для регіону {region_id}: {e}")
            return None
        except (IndexError, KeyError) as e:
            print(f"❌ Помилка доступу до даних для регіону {region_id}: {e}")
            return None
        except Exception as e:
            print(f"❌ Несподівана помилка для регіону {region_id}: {e}")
            return None
    
    def _generate_task_triggers(self) -> str:
        """Генерує тригер для негайного запуску задачі."""
        return "|1*0*1<2<*1|"
    
    def _generate_task_commands(self, audio_file: str) -> str:
        """Генерує рядок команд для відтворення аудіофайлу."""
        # Документація вимагає подвійний зворотний слеш
        file_path = f"\\\\{audio_file}"
        return f"|3*0*0*0*{file_path}*'*1*0*1|"

    async def create_and_run_task(
        self, 
        task_name: str, 
        audio_file: str, 
        region_name: str = ""
    ) -> Optional[str]:
        """Створює, запускає та повертає ID задачі."""
        if not await self.ensure_file_on_server(audio_file):
            print(f"❌ Неможливо створити задачу - файл {audio_file} недоступний.")
            return None
            
        # ВАЖЛИВО: Не передаємо taskId - сервер генерує його сам
        task_data = {
            "taskname": task_name,
            "isdisable": "0",
            "level": "15",
            "creator": SPON_USER,
            "triggers": self._generate_task_triggers(),
            "commands": self._generate_task_commands(audio_file),
            "dirname": ""
        }
        
        create_result = await self._spon_request("/php/addtaskinfo.php", task_data)
        if not (create_result and create_result.get("res") == '1'):
            print(f"❌ Не вдалося створити задачу: {create_result}")
            return None

        # ВИПРАВЛЕННЯ: Використовуємо taskId, який повернув сервер, а не наш згенерований
        server_task_id = create_result.get("taskId")
        if not server_task_id:
            print(f"❌ Сервер не повернув taskId: {create_result}")
            return None

        run_payload = {"taskCommand": "runtaskinfo", "taskId": server_task_id}
        run_result = await self._spon_request("/php/exetaskcmd.php", run_payload)
        
        if run_result and (run_result.get("res") == '1' or run_result.get("res") == 1):
            task_type = "🚨 ТРИВОГА" if audio_file == FILE_ON else "✅ ВІДБІЙ"
            print(f"✅ Задача '{task_type}' [{region_name}] створена та запущена (ID: {server_task_id[:8]}...)")
            return server_task_id
        else:
            print(f"⚠️  Задача створена (ID: {server_task_id[:8]}...), але не запущена: {run_result}")
            # Все одно повертаємо ID для подальшого видалення
            return server_task_id

    async def delete_task(self, task_id: str, region_name: str = "") -> bool:
        """Видаляє задачу з системи XC-9000."""
        payload = {"taskCommand": "deltaskinfo", "taskId": task_id}
        result = await self._spon_request("/php/exetaskcmd.php", payload)
        
        if result and result.get("res") == 1:
            print(f"🗑️  Задача [{region_name}] видалена (ID: {task_id[:8]}...).")
            return True
        else:
            print(f"⚠️  Не вдалося видалити задачу: {result}")
            return False
    
    async def handle_region_alert(self, region_data: Dict):
        """Обробляє зміну статусу тривоги для регіону."""
        region_id_str = str(region_data["region_id"])
        region_name = region_data["region_name"]
        
        audio_file = FILE_ON if region_data["has_alert"] else FILE_OFF
        task_name_suffix = "ALERT_ON" if region_data["has_alert"] else "ALERT_OFF"
        task_name = f"AutoAlert_{region_name}_{datetime.now():%H%M%S}"
        
        task_id = await self.create_and_run_task(task_name, audio_file, region_name)
        
        if task_id:
            await asyncio.sleep(2)
            await self.delete_task(task_id, region_name)
        
        self.state["regions"][region_id_str].update({
            "alert_status": region_data["has_alert"],
            "last_update": region_data["last_update"],
            "active_task_id": None
        })
    
    async def check_all_regions(self):
        """Перевіряє статус всіх регіонів та обробляє зміни."""
        print(f"\n🔍 Перевірка статусу регіонів ({datetime.now():%H:%M:%S}):")
        print("─" * 50)

        # ВАЖЛИВО: Робимо запити ПОСЛІДОВНО з затримкою, щоб не перевищити rate limit API
        results = []
        request_delay = 2  # секунди між запитами

        for i, region_id in enumerate(REGION_IDS):
            # Додаємо затримку між запитами (крім першого)
            if i > 0:
                await asyncio.sleep(request_delay)

            result = await self.get_region_status(region_id)
            if result:
                results.append(result)

        print("─" * 50)

        changes_detected = False

        for result in results:
            region_id_str = str(result["region_id"])
            old_status = self.state["regions"].get(region_id_str, {}).get("alert_status", False)
            
            if self.state["first_run"] or old_status != result["has_alert"]:
                changes_detected = True
                status_icon = "🚨" if result["has_alert"] else "✅"
                status_text = "ТРИВОГА" if result["has_alert"] else "ВІДБІЙ"
                
                print(f"\n🔔 ЗМІНА СТАТУСУ:")
                print(f"{status_icon} [{datetime.now():%Y-%m-%d %H:%M:%S}] {result['region_name']}")
                print(f"   Статус: {status_text} (був: {'ТРИВОГА' if old_status else 'ВІДБІЙ'})")
                print(f"   Оновлено: {result['last_update']}")
                
                await self.handle_region_alert(result)
        
        if not changes_detected and not self.state["first_run"]:
            print("ℹ️  Змін не виявлено")

        return changes_detected
    
    async def initialize(self):
        """Ініціалізація монітора: перевірка файлів."""
        print("🚀 Запуск моніторингу повітряних тривог...")
        print(f"📍 Відстежувані регіони: {REGION_IDS}")
        print(f"ℹ️  Запити до API виконуються послідовно з затримкою для уникнення rate limiting")
        print("🔍 Перевірка наявності аудіофайлів на сервері...")
        for filename in [FILE_ON, FILE_OFF]:
            await self.ensure_file_on_server(filename)
        print("✅ Перевірка файлів завершена\n")
    
    async def monitor_loop(self):
        """Основний цикл моніторингу."""
        await self.initialize()
        
        try:
            while True:
                current_action_index = await self.check_alerts_status()
                if current_action_index is None:
                    await asyncio.sleep(10)
                    continue
                
                if self.state["first_run"] or current_action_index != self.state["last_action_index"]:
                    if not self.state["first_run"]:
                        print(f"\n🔔 Виявлено зміну статусу тривог (index: {self.state.get('last_action_index', 0)} → {current_action_index})")
                    else:
                        print("🔍 Перший запуск - перевірка поточного стану...")
                    
                    if await self.check_all_regions():
                        print(f"💾 Стан збережено в {STATE_FILE}")

                    self.state["last_action_index"] = current_action_index
                    self.state["first_run"] = False
                    self._save_state()
                else:
                    print(f"[{datetime.now():%H:%M:%S}] ⏳ Моніторинг... (без змін, index: {current_action_index})", end="\r")
                
                await asyncio.sleep(CHECK_INTERVAL)
        
        except KeyboardInterrupt:
            print("\n\n⛔ Зупинка моніторингу...")
        finally:
            if self.session and not self.session.closed: await self.session.close()
            print("👋 Моніторинг завершено")

async def main():
    monitor = AlertMonitor()
    await monitor.monitor_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрограма завершена користувачем.")
