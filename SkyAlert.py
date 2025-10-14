import requests
import time
from datetime import datetime

# опитування сервера на стан тривоги в певному регіоні, остання цифра - регіон (15=Кіровоградська область)
ALERTS_URL = "https://api.ukrainealarm.com/api/v3/alerts/23"
HEADERS = {
    "authorization": "57f0f236:b616a0d7f0835411674dd63e3f1d53b5",
}
COMMAND_URL = "http://10.123.50.24/php/exetaskcmd.php"   # адрес сервера, де запущена система (192.168.15.48)
TASK_ID_ALERT = "7c4d2dff-a228-4727-a88a-df8d9eeb6089"      # task ID - C:\ICPAS\AppServer\TaskFiles
TASK_ID_NO_ALERT = "5b30e47b-dee3-4600-9242-b11d9feda0c1"   # task ID - C:\ICPAS\AppServer\TaskFiles
CHECK_INTERVAL = 30  # Інтервал перевірки статусу тривоги в секундах

def check_alert_status():
    """Запитує поточний стан тривоги з API."""
    try:
        response = requests.get(ALERTS_URL, headers=HEADERS)
        response.raise_for_status()  # Перевірка на помилки HTTP, інформує про наявність помилок
        data = response.json()

        if isinstance(data, list) and len(data) > 0:         
            alerts = data[0].get("activeAlerts", [])
            alert_status = 1 if alerts else 0  

            # Отримання регіону та часу тривоги
            region = data[0].get("regionName", "Не указано")
            alert_time = data[0].get("lastUpdate", "Не указано")

            return alert_status, region, alert_time
        else:
            print("Формат відповіді не відповідає очікуваному.")
            return None, None, None
    except requests.RequestException as e:
        print(f"Помилка під час запиту стану тривоги: {e}")
        return None, None, None

def send_command(task_id):
    """Надсилає команду на сервер."""
    payload = {
        "taskCommand": "runtaskinfo",
        "taskId": task_id
    }
    try:
        response = requests.post(COMMAND_URL, data=payload)
        response.raise_for_status()  # Перевірка помилок HTTP
        print(f"Команда відправлена: {payload}")
    except requests.RequestException as e:
        print(f"Помилка при відправці команди: {e}")

def main():
    previous_alert_status = None
    first_run = True

    while True:
        current_alert_status, region, alert_time = check_alert_status()

        if current_alert_status is None:
            print("Не вдалося перевірити статус тривоги. Спробуйте знову пізніше.")
        else:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if first_run:
                # При першому запуску виводимо дані про тривогу
                print(f"[{current_time}] Регіон: {region}")
                print(f"[{current_time}] Час тривоги: {alert_time}")
                print(f"[{current_time}] Статус тривоги при першому запуску: {'Активний' if current_alert_status == 1 else 'Не активний'}")
          
                if current_alert_status == 1:
                    send_command(TASK_ID_ALERT)
                else:
                    send_command(TASK_ID_NO_ALERT)
                previous_alert_status = current_alert_status
                first_run = False
            else:
              
                if current_alert_status != previous_alert_status:
                    print(f"[{current_time}] Регион: {region}")
                    print(f"[{current_time}] Время тревоги: {alert_time}")
                    print(f"[{current_time}] Статус тревоги изменился на: {'Активен' if current_alert_status == 1 else 'Не активен'}")

                    if current_alert_status == 1:
                        send_command(TASK_ID_ALERT)
                    else:
                        send_command(TASK_ID_NO_ALERT)
            
                    previous_alert_status = current_alert_status

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
