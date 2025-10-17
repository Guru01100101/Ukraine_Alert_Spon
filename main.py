import logging
import os
import json
import asyncio
import aiohttp
from datetime import datetime
from typing import Dict, Optional, Set
from dotenv import load_dotenv
from pathlib import Path
from logging.handlers import RotatingFileHandler


# Завантаження змінних оточення з .env файлу
base_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(base_dir, '.env')
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    logging.warning("⚠️ .env файл не знайдено, використовуються значення за замовчуванням.")
    # print("⚠️ .env файл не знайдено, використовуються значення за замовчуванням.")
    print("Щоб створити .env файл, скопіюйте .env.example і налаштуйте змінні.")

ALERT_TOKEN = os.getenv("ALERT_TOKEN")
REGION_IDS = json.loads(os.getenv("REGION_ID", "[23]"))
SPON_IP = os.getenv("SPON_IP")
SPON_USER = os.getenv("SPON_USER", "admin")
SPON_PASSWORD = os.getenv("SPON_PASSWORD", "admin")  # Наразі не використовується
FILE_ON = os.getenv("FILE_ON", "START_ALARM.mp3")
FILE_OFF = os.getenv("FILE_OFF", "END_ALARM.mp3")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))

ALERT_API_URL = "https://api.ukrainealarm.com/api/v3"
SPON_BASE_URL = f"http://{SPON_IP}"
STATE_FILE = Path("alert_state.json")

# --- Налаштування логування ---
# LOG_FILE = "alert_monitor.log"
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     datefmt="%d.%m.%Y %H:%M:%S",
#     handlers=[
#         logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
#         logging.StreamHandler()
#     ]
# )

LOG_FILE_INFO = "alert_info.log"
LOG_FILE_ERROR = "alert_error.log"

# Налаштування логування для INFO+ рівня
logger = logging.getLogger()
logger.setLevel(logging.INFO)

info_handler = RotatingFileHandler(LOG_FILE_INFO, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
info_handler.setLevel(logging.INFO)
info_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%d.%m.%Y %H:%M:%S")
info_handler.setFormatter(info_formatter)

# Налаштування логування для ERROR+ рівня
error_handler = logging.FileHandler(LOG_FILE_ERROR, encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%d.%m.%Y %H:%M:%S")
error_handler.setFormatter(error_formatter)

# Консольний хендлер для INFO і вище рівнів
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(info_formatter)

logger.addHandler(info_handler)
logger.addHandler(error_handler)
logger.addHandler(console_handler)
# -----------------------------


class AlertMonitor:
    def __init__(self):
        if not ALERT_TOKEN or ALERT_TOKEN == "your_token_here":
            logging.critical("❌ ALERT_TOKEN не встановлено в .env файлі")
            raise ValueError("ALERT_TOKEN must be set in .env file")

        self.alert_headers = {"Authorization": ALERT_TOKEN}
        self.state = self._load_state()
        self.session: Optional[aiohttp.ClientSession] = None
        self.uploaded_files: Set[str] = set()

    def _load_state(self) -> Dict:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
                    if "main_trigger" not in state:
                        state["main_trigger"] = False
                    return state
            except Exception as e:
                print(f"⚠️ Помилка читання файлу стану: {e}.")
        return {
            "last_action_index": 0,
            "regions": {str(region_id): {"alert_status": False, "last_update": None, "active_task_id": None} for region_id in REGION_IDS},
            "first_run": True,
            "main_trigger": False
        }

    def _save_state(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def _format_spon_data(self, payload: Dict) -> Dict:
        return {f"jsondata[{k}]": str(v) for k, v in payload.items()}

    async def _spon_request(self, endpoint: str, payload: Dict) -> Optional[Dict]:
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

    async def check_alerts_status(self) -> Optional[int]:
        try:
            session = await self._get_session()
            url = f"{ALERT_API_URL}/alerts/status"
            async with session.get(url, headers=self.alert_headers) as response:
                if response.status == 401:
                    print("❌ Помилка авторизації (401): перевірте токен ALERT_TOKEN у .env файлі")
                    return None
                elif response.status == 429:
                    print("⚠️ Перевищено ліміт запитів (429): зачекайте")
                    return None
                elif response.status != 200:
                    print(f"❌ HTTP помилка {response.status} при перевірці статусу тривог")
                    return None
                response.raise_for_status()
                result = await response.json()
                if not isinstance(result, dict):
                    print(f"❌ Очікувався об'єкт, отримано {type(result)}")
                    return None
                last_action_index = result.get("lastActionIndex")
                if last_action_index is None:
                    print("⚠️ Відсутнє поле lastActionIndex у відповіді API")
                    return None
                print(f"[{datetime.now():%H:%M:%S}] 🔔 lastActionIndex: {last_action_index}")
                return last_action_index
        except Exception as e:
            print(f"❌ Помилка мережі при перевірці статусу тривог: {e}")
            return None

    async def check_file_exists_on_server(self, filepath: str) -> bool:
        if filepath in self.uploaded_files:
            return True
        directory, filename = os.path.split(filepath)
        payload = {"pageIndex":0, "pageCount":100, "filter":"", "subPath":directory}
        result = await self._spon_request("/php/getmediadata.php", payload)
        if result and int(result.get("res",0)) == 1 and int(result.get("total",0)) > 0:
            for row in result.get("rows", []):
                if row.get("name") == filename:
                    self.uploaded_files.add(filepath)
                    return True
        return False

    async def ensure_file_on_server(self, filename: str) -> bool:
        if await self.check_file_exists_on_server(filename):
            print(f"✓ Файл '{filename}' вже є на сервері.")
            return True
        print(f"❌ Файл '{filename}' не знайдено на сервері. Завантаження файлів виконується вручну.")
        return False

    async def get_file_duration(self, filepath: str) -> str:
        directory, filename = os.path.split(filepath)
        payload = {"pageIndex":0, "pageCount":100, "filter":"", "subPath":directory}
        result = await self._spon_request("/php/getmediadata.php", payload)
        if result and int(result.get("res",0)) == 1:
            for media in result.get("rows", []):
                if media.get("name") == filename:
                    return media.get("durations", "00:00:00")
        return "00:00:00"

    def durations_to_seconds(self, duration_str: str) -> int:
        h, m, s = map(int, duration_str.split(":"))
        return h*3600 + m*60 + s

    async def get_online_terminals(self) -> list:
        payload = {
            "pageIndex":0, "pageCount":100, "groupName":"*", "showType":1,
            "user": SPON_USER, "simple": 1
        }
        result = await self._spon_request("/php/getzoneterminaldata.php", payload)
        if result and int(result.get("res",0)) == 1:
            terminals = result.get("rows", [])
            return [t["id"] for t in terminals if t.get("state","0") == "0"]
        return []

    async def run_task(self, audio_file: str, region_name: str = "") -> Optional[str]:
        if not await self.ensure_file_on_server(audio_file):
            print(f"❌ Неможливо створити задачу - файл {audio_file} недоступний.")
            return None

        task_name = f"AutoAlert_{region_name}_{datetime.now():%H%M%S}"
        terminals = await self.get_online_terminals()
        terminals_str = "<".join(terminals) if terminals else "1"

        task_data = {
            "taskname": task_name,
            "isdisable": "0",
            "level": "15",
            "creator": SPON_USER,
            "triggers": "",
            "commands": f"3*0*0*0*{audio_file}*{terminals_str}*0*0",
            "dirname": ""
        }
        create_result = await self._spon_request("/php/addtaskinfo.php", task_data)

        if not (create_result and create_result.get("res") == '1'):
            print(f"❌ Не вдалося створити задачу: {create_result}")
            return None

        task_id = create_result.get("taskId")
        if not task_id:
            print(f"❌ Сервер не повернув taskId: {create_result}")
            return None

        run_payload = {"taskCommand": "runtaskinfo", "taskId": task_id}
        run_result = await self._spon_request("/php/exetaskcmd.php", run_payload)
        if run_result and (run_result.get("res") == '1' or run_result.get("res") == 1):
            print(f"✅ Задача [{region_name}] створена, запущена (ID: {task_id[:8]}...)")
            duration_str = await self.get_file_duration(audio_file)
            duration_sec = self.durations_to_seconds(duration_str)
            print(f"⏳ Очікуємо завершення задачі {duration_sec + 1} секунд")
            await asyncio.sleep(duration_sec + 1)
        else:
            print(f"⚠️ Задача створена (ID: {task_id[:8]}...), але не запущена: {run_result}")

        # Видаляємо таску завжди
        del_payload = {"taskCommand": "deltaskinfo", "taskId": task_id}
        del_result = await self._spon_request("/php/exetaskcmd.php", del_payload)
        if del_result and del_result.get("res") == 1:
            print(f"🗑️ Задача [{region_name}] видалена (ID: {task_id[:8]}...)")
        else:
            print(f"⚠️ Не вдалося видалити задачу: {del_result}")

        return task_id

    async def handle_region_alert(self, region_data: Dict):
        region_id_str = str(region_data["region_id"])
        self.state["regions"][region_id_str].update({
            "alert_status": region_data["has_alert"],
            "last_update": region_data["last_update"],
            "active_task_id": None
        })

    async def check_region_status(self, region_id: int, retry_count: int = 0) -> Optional[Dict]:
        max_retries = 3
        retry_delay = 30  # seconds
        try:
            session = await self._get_session()
            url = f"{ALERT_API_URL}/alerts/{region_id}"
            async with session.get(url, headers=self.alert_headers) as response:
                if response.status == 401 or response.status == 429:
                    if retry_count < max_retries:
                        await asyncio.sleep(retry_delay)
                        return await self.check_region_status(region_id, retry_count + 1)
                    else:
                        print(f"❌ Регіон {region_id}: вичерпано кількість спроб")
                        return None
                elif response.status == 404:
                    print(f"⚠️ Регіон {region_id} не знайдено (404)")
                    return None
                elif response.status != 200:
                    print(f"❌ HTTP помилка {response.status} для регіону {region_id}")
                    return None

                response.raise_for_status()
                data = await response.json()
                if not isinstance(data, list) or len(data) == 0:
                    print(f"❌ Неочікуваний формат даних для регіону {region_id}")
                    return None

                region_data = data[0]
                status_icon = "🚨" if bool(region_data.get("activeAlerts")) else "✅"
                status_text = "ТРИВОГА" if bool(region_data.get("activeAlerts")) else "Спокійно"
                print(f"{status_icon} {region_data.get('regionName', 'Невідомо')}: {status_text}")

                return {
                    "region_id": region_id,
                    "region_name": region_data.get("regionName", "Невідомо"),
                    "has_alert": bool(region_data.get("activeAlerts")),
                    "last_update": region_data.get("lastUpdate"),
                    "active_alerts": region_data.get("activeAlerts", [])
                }

        except Exception as e:
            print(f"❌ Помилка при отриманні статусу регіону {region_id}: {e}")
            return None

    async def check_all_regions(self) -> bool:
        print(f"\n🔍 Перевірка статусу регіонів ({datetime.now():%H:%M:%S}):")
        changes_detected = False
        any_alert = False

        for i, region_id in enumerate(REGION_IDS):
            if i > 0:
                await asyncio.sleep(2)
            result = await self.check_region_status(region_id)
            if result is None:
                continue
            region_id_str = str(region_id)
            old_status = self.state["regions"].get(region_id_str, {}).get("alert_status", False)

            if self.state["first_run"] is False and old_status != result["has_alert"]:
                changes_detected = True
                print(f"\n🔔 ЗМІНА СТАТУСУ: Region {region_id} {result['region_name']}")
                print(f"   Статус: {'ТРИВОГА' if result['has_alert'] else 'ВІДБІЙ'}")
                print(f"   Оновлено: {result['last_update']}")
            elif self.state["first_run"]:
                # На першому запуску не тригерити зміни статусу
                print(f"🔔 Перший запуск: оновлення статусу регіону {region_id} без запуску тасок")

            self.state["regions"][region_id_str].update({
                "alert_status": result["has_alert"],
                "last_update": result["last_update"],
                "active_task_id": None
            })

            if result["has_alert"]:
                any_alert = True

        # поновлюємо main_trigger
        previous_main = self.state.get("main_trigger", False)
        self.state["main_trigger"] = any_alert

        if previous_main != any_alert:
            print(f"\n🔄 Головний тригер оновлено: {any_alert}")

        return changes_detected

    async def monitor_loop(self):
        print("🚀 Запуск моніторингу повітряних тривог...")
        print(f"📍 Відстежувані регіони: {REGION_IDS}")
        print("ℹ️ Запити до API виконуються послідовно з затримкою для уникнення rate limiting")

        for filename in [FILE_ON, FILE_OFF]:
            await self.ensure_file_on_server(filename)

        print("✅ Перевірка файлів завершена\n")

        last_main_trigger = self.state.get("main_trigger", False)

        if self.state["first_run"]:
            # Перший запуск: оновлюємо статус, потім запускаємо одну глобальну таску
            await self.check_all_regions()
            if self.state.get("main_trigger"):
                print("🚨 Перший запуск: головний тригер активний, запускаємо тривогу")
                await self.run_task(FILE_ON, "Глобальна тривога")
            else:
                print("✅ Перший запуск: головний тригер неактивний, запускаємо відбій")
                await self.run_task(FILE_OFF, "Глобальний відбій")
            self.state["first_run"] = False
            self._save_state()

        try:
            while True:
                current_action_index = await self.check_alerts_status()
                if current_action_index is None:
                    await asyncio.sleep(10)
                    continue

                if current_action_index != self.state.get("last_action_index", 0):
                    print(f"\n🔔 Виявлено зміну статусу тривог (index: {self.state.get('last_action_index', 0)} → {current_action_index})")
                    changes = await self.check_all_regions()
                    if changes:
                        print(f"💾 Стан збережено в {STATE_FILE}")

                    self.state["last_action_index"] = current_action_index
                    self._save_state()

                    new_main_trigger = self.state.get("main_trigger", False)
                    if new_main_trigger != last_main_trigger:
                        if new_main_trigger:
                            print("🚨 Головний тригер активувався — запускаємо тривогу")
                            await self.run_task(FILE_ON, "Глобальна тривога")
                        else:
                            print("✅ Головний тригер деактивувався — запускаємо відбій")
                            await self.run_task(FILE_OFF, "Глобальний відбій")
                        last_main_trigger = new_main_trigger
                else:
                    print(f"[{datetime.now():%H:%M:%S}] ⏳ Моніторинг... (без змін, index: {current_action_index})", end="\r")

                await asyncio.sleep(CHECK_INTERVAL)
        except asyncio.CancelledError:
            print("\n⛔ Моніторинг скасовано")
        except KeyboardInterrupt:
            print("\n\n⛔ Зупинка моніторингу...")
        finally:
            if self.session and not self.session.closed:
                await self.session.close()
            print("👋 Моніторинг завершено")

async def main():
    monitor = AlertMonitor()
    await monitor.monitor_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрограма завершена користувачем.")
