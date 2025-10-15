import asyncio
import aiohttp
import json
import os

from dotenv import load_dotenv

load_dotenv()

SPON_IP = os.getenv("SPON_IP", "10.123.0.228")
SPON_USER = os.getenv("SPON_USER", "admin")
FILE_ON = os.getenv("FILE_ON", "Оповіщення/Повітряна_тривога.mp3")
FILE_OFF = os.getenv("FILE_OFF", "Оповіщення/Відбій_тривоги.mp3")
SPON_BASE_URL = f"http://{SPON_IP}"

def format_spon_data(payload: dict) -> dict:
    return {f"jsondata[{key}]": str(value) for key, value in payload.items()}

async def get_file_duration(session, filepath):
    directory, filename = os.path.split(filepath)
    url = f"{SPON_BASE_URL}/php/getmediadata.php"
    payload = {
        "pageIndex": 0,
        "pageCount": 100,
        "filter": "",
        "subPath": directory
    }
    data = format_spon_data(payload)
    async with session.post(url, data=data) as response:
        response_text = await response.text()
        response_json = json.loads(response_text)
        if response_json.get("res") == "1":
            for media in response_json.get("rows", []):
                if media.get("name", "") == filename:
                    return media.get("durations", "00:00:00")
        return "00:00:00"

def durations_to_seconds(duration_str):
    h, m, s = map(int, duration_str.split(":"))
    return h * 3600 + m * 60 + s

async def get_online_terminals(session):
    url = f"{SPON_BASE_URL}/php/getzoneterminaldata.php"
    payload = {
        "pageIndex": 0,
        "pageCount": 100,
        "groupName": "*",
        "showType": 1,
        "user": SPON_USER,
        "simple": 1
    }
    data = format_spon_data(payload)
    async with session.post(url, data=data) as response:
        response_text = await response.text()
        response_json = json.loads(response_text)
        if response_json.get("res") == "1":
            terminals = response_json.get("rows", [])
            online_ids = [t["id"] for t in terminals if t.get("state", "0") == "0"]
            return online_ids
        else:
            return []

async def create_task(session, terminal_ids, file_to_play):
    task_name = f"Test_Task"

    terminals_str = "<".join(terminal_ids) if terminal_ids else "1"

    task_data = {
        "taskname": task_name,
        "isdisable": 0,
        "level": 15,
        "creator": SPON_USER,
        "triggers": "",
        "commands": f"3*0*0*0*{file_to_play}*{terminals_str}*0*0",
        "dirname": ""
    }
    data = format_spon_data(task_data)
    url = f"{SPON_BASE_URL}/php/addtaskinfo.php"
    async with session.post(url, data=data) as response:
        resp_text = await response.text()
        resp_json = json.loads(resp_text)
        if resp_json.get("res") == "1":
            task_id = resp_json.get("taskId")
            print(f"✅ Задача створена: {task_name} (ID: {task_id})")
            return task_id
        else:
            print(f"❌ Помилка створення задачі: {resp_text}")
            return None

async def run_task(session, task_id):
    url = f"{SPON_BASE_URL}/php/exetaskcmd.php"
    payload = {
        "taskCommand": "runtaskinfo",
        "taskId": task_id
    }
    data = format_spon_data(payload)
    async with session.post(url, data=data) as response:
        resp_text = await response.text()
        resp_json = json.loads(resp_text)
        if resp_json.get("res") == "1":
            print(f"▶️ Задача {task_id} успішно запущена")
            return True
        else:
            print(f"❌ Помилка запуску задачі: {resp_text}")
            return False

async def delete_task(session, task_id):
    url = f"{SPON_BASE_URL}/php/exetaskcmd.php"
    payload = {
        "taskCommand": "deltaskinfo",
        "taskId": task_id
    }
    data = format_spon_data(payload)
    async with session.post(url, data=data) as response:
        resp_text = await response.text()
        resp_json = json.loads(resp_text)
        if resp_json.get("res") == "1":
            print(f"🗑️ Задача {task_id} успішно видалена")
            return True
        else:
            print(f"❌ Помилка видалення задачі: {resp_text}")
            return False

async def execute_task_flow(file_to_play):
    async with aiohttp.ClientSession() as session:
        terminals = await get_online_terminals(session)
        if not terminals:
            print("❌ Не вдалося отримати онлайн термінали або їх немає")
            return

        print(f"📡 Знайдені онлайн термінали: {terminals}")

        duration_str = await get_file_duration(session, file_to_play)
        duration_sec = durations_to_seconds(duration_str)
        print(f"⏱️ Тривалість файлу '{file_to_play}': {duration_str} ({duration_sec} секунд)")

        task_id = await create_task(session, terminals, file_to_play)
        if not task_id:
            return

        started = await run_task(session, task_id)
        if not started:
            print("⚠️ Запуск таски не вдався, продовжуємо видалення...")
        else:
            print(f"⏳ Очікуємо завершення задачі {duration_sec + 1} секунд")
            await asyncio.sleep(duration_sec + 1)

        await delete_task(session, task_id)

def print_menu():
    print("\nВиберіть дію:")
    print("1 - Перевірка початку тривоги")
    print("2 - Перевірка відбою тривоги")
    print("0 - Вихід")

async def main():
    while True:
        print_menu()
        choice = input("Введіть номер дії: ").strip()
        if choice == "1":
            print("🔔 Перевірка початку тривоги")
            await execute_task_flow(FILE_ON)
        elif choice == "2":
            print("🔕 Перевірка відбою тривоги")
            await execute_task_flow(FILE_OFF)
        elif choice == "0":
            print("Вихід з програми.")
            break
        else:
            print("Невірна команда. Спробуйте ще раз.")

if __name__ == '__main__':
    asyncio.run(main())
