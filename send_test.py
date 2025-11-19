import requests
from bs4 import BeautifulSoup
import datetime
import re
import time
import os
import json

# --- 1. Импорт конфигураций ---
script_dir = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, script_dir)
try:
    import telegram_config as config
    # import adr_config as adr  # Больше не нужен, всё в config
except ImportError:
    print("ОШИБКА: Не найден файл telegram_config.py.")
    print(f"Убедитесь, что все .py файлы находятся в одной папке: {script_dir}")
    exit()

# --- 2. Настройки ---
CRITICAL_TIME_MINUTES = 30
DTEK_BASE_URL = "https://www.dtek-dnem.com.ua"
DTEK_FORM_URL = f"{DTEK_BASE_URL}/ua/shutdowns"
DTEK_POST_URL = f"{DTEK_BASE_URL}/ua/ajax"

# --- 3. Функции ---

def load_users_from_file():
    """Загружает список chat_id пользователей из файла."""
    users_file = os.path.join(script_dir, "test_users_list.txt")
    user_ids = set()
    try:
        with open(users_file, "r", encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.isdigit():  # Проверяем, что строка — это число
                    user_ids.add(int(line))
        print(f"INFO: Загружено {len(user_ids)} пользователей из 'users_list.txt'.")
    except FileNotFoundError:
        print("INFO: Файл 'users_list.txt' не найден. Список пользователей пуст.")
    except Exception as e:
        print(f"ОШИБКА при загрузке пользователей из файла: {e}")
    return user_ids

def send_telegram_message(message: str):
    """Отправляет сообщение через Telegram Bot API ВСЕМ пользователям из файла users_list.txt."""
    if not config.TELEGRAM_BOT_TOKEN:
        print("Ошибка: Токен Telegram не настроен.")
        return False

    # Загружаем пользователей каждый раз перед отправкой
    user_ids = load_users_from_file()

    if not user_ids:
        print("Предупреждение: Список пользователей пуст. Некуда отправлять.")
        return False

    success_count = 0
    for chat_id in user_ids:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown',
        }
        try:
            response = requests.post(url, data=payload, timeout=10, verify=False)
            response.raise_for_status()
            print(f"INFO: Оповещение успешно отправлено пользователю {chat_id}.")
            success_count += 1
        except requests.exceptions.RequestException as e:
            print(f"Ошибка при отправке в Telegram пользователю {chat_id}: {e}")
            # Не возвращаем False, продолжаем для следующих пользователей
    print(f"INFO: Отправлено {success_count} из {len(user_ids)} пользователей.")
    return success_count > 0

def save_schedule_to_txt(parsed_schedule: dict):
    """
    Сохраняет 24-часовой график в svet.txt с русскими статусами и табуляцией.
    """
    # Карта статусов, как ты просил
    status_map = {
        'yes': 'есть свет',
        'no': 'нет света',
        'maybe': 'возможно',
        'first': 'нет света первые полчаса',
        'mfirst': 'возможно нет света первые полчаса',
        'second': 'нет света вторые полчаса',
        'msecond': 'возможно нет света вторые полчаса',
        'n/a': 'Н/Д'
    }
    try:
        filepath = os.path.join(script_dir, "svet.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("Интервал\tСостояние\n") # Заголовок с табуляцией
            if not parsed_schedule:
                f.write("График не найден или пуст.\n")
                return
            for interval, status_key in parsed_schedule.items():
                # Получаем русский статус, или используем 'as-is' если статус новый
                status_text = status_map.get(status_key, status_key)
                f.write(f"{interval}\t{status_text}\n")
        print("INFO: Результаты графика сохранены в 'svet.txt' (с табуляцией).")
    except Exception as e:
        print(f"ОШИБКА: Не удалось записать файл 'svet.txt': {e}")

def get_dtek_schedule(session: requests.Session) -> dict | None:
    """
    Выполняет полный цикл запросов к ДТЭК и возвращает "сырой" JSON-ответ.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Referer': DTEK_FORM_URL,
        'Origin': DTEK_BASE_URL,
        'X-Requested-With': 'XMLHttpRequest',
    }
    try:
        # --- Шаг 1: Получение CSRF-токена и куки ---
        print(f"DEBUG: Шаг 1: Запрос {DTEK_FORM_URL} для CSRF-токена...")
        response_form = session.get(DTEK_FORM_URL, headers=headers, timeout=15, verify=False)
        response_form.raise_for_status()
        soup = BeautifulSoup(response_form.text, 'html.parser')
        token_tag = soup.find('input', {'name': '_csrf-dtek-dnem'})
        if not token_tag or not token_tag.get('value'):
            print("ОШИБКА: Не удалось найти CSRF-токен на странице ДТЭК.")
            return None
        csrf_token = token_tag.get('value')
        print(f"DEBUG: CSRF-токен получен: ...{csrf_token[-10:]}")

        # --- Шаг 2: POST-запрос за данными ---
        now_local = datetime.datetime.now()
        update_time_str = now_local.strftime("%d.%m.%Y %H:%M")
        post_data = {
            '_csrf-dtek-dnem': csrf_token,
            'method': 'getHomeNum',
            'data[0][name]': 'city',
            'data[0][value]': config.CITY,
            'data[1][name]': 'street',
            'data[1][value]': config.STREET,
            'data[2][name]': 'house',
            'data[2][value]': config.HOUSE,
            'data[3][name]': 'updateFact',
            'data[3][value]': update_time_str,
        }

        print(f"DEBUG: Шаг 2: POST-запрос на {DTEK_POST_URL} с временем {update_time_str}...")
        response_ajax = session.post(DTEK_POST_URL, headers=headers, data=post_data, timeout=15, verify=False)
        response_ajax.raise_for_status()
        json_data = response_ajax.json()

        if not json_data or not json_data.get('fact') or not json_data.get('preset'):
            print(f"ОШИБКА: ДТЭК вернул пустой или некорректный JSON.")
            return None

        print("INFO: Данные ДТЭК успешно получены.")
        return json_data
    except requests.exceptions.RequestException as e:
        print(f"ОШИБКА: Сбой сети при запросе к ДТЭК: {e}")
        return None
    except json.JSONDecodeError:
        print(f"ОШИБКА: ДТЭК вернул не JSON. Ответ: {response_ajax.text[:100]}...")
        return None
    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА при запросе ДТЭК: {e}")
        return None

def parse_full_schedule(schedule_data: dict) -> dict | None:
    """
    Извлекает 24-часовой график (Интервал -> Статус) из "сырого" JSON ДТЭК.
    """
    try:
        fact = schedule_data['fact']['data']
        preset = schedule_data['preset']
        today_key = list(fact.keys())[0] # Первый ключ - обычно 'today'

        # $hours в PHP
        schedule_intervals = preset.get('time_zone')
        # $data в PHP
        queue_data = fact[today_key].get(config.MY_QUEUE)

        if not queue_data or not schedule_intervals:
            print(f"ОШИБКА: Очередь '{config.MY_QUEUE}' или 'time_zone' не найдены в JSON.")
            return None

        parsed_schedule = {}
        # schedule_intervals - это {"00:00-01:00": ["00-01"], "01:00-02:00": ["01-02"], ...}
        # Мы итерируем по нему, чтобы сохранить правильный порядок и метки
        sorted_keys = sorted(schedule_intervals.keys(), key=lambda x: int(x.split(':')[0]))
        for time_key in sorted_keys: # Используем отсортированные ключи для гарантии порядка
            label_list = schedule_intervals[time_key]
            label = label_list[0] # Это "00-01"
            status_key = queue_data.get(time_key, 'n/a') # Это "yes", "no", и т.д.
            parsed_schedule[label] = status_key # {"00-01": "no", "01-02": "yes", ...}

        return parsed_schedule
    except Exception as e:
        print(f"ОШИБКА: Не удалось разобрать полный график: {e}")
        return None

def is_power_on_at_current_time(parsed_schedule: dict) -> bool:
    """
    Проверяет, включен ли свет в *текущий момент* времени, учитывая получасовые статусы.
    """
    try:
        current_status = get_current_status(parsed_schedule)
        if current_status is None:
            print("DEBUG: Не удалось определить текущий статус для проверки включения света.")
            return False # Если не можем определить, считаем, что нет

        now_local = datetime.datetime.now()
        current_hour = now_local.hour
        current_minute = now_local.minute

        # Статусы, при которых свет *всегда* включен в интервале
        if current_status == 'yes':
            return True

        # Статусы, при которых свет *всегда* отключен в интервале
        if current_status in ['no', 'maybe']:
            return False

        # Статусы, при которых свет отключен только в первой половине часа (00-29)
        if current_status in ['first', 'mfirst']:
            # Свет отключен в первой половине (до 30 минут включительно)
            # Значит, свет *включен*, если текущая минута >= 30
            return current_minute >= 30

        # Статусы, при которых свет отключен только во второй половине часа (30-59)
        if current_status in ['second', 'msecond']:
            # Свет отключен во второй половине (с 30 минуты)
            # Значит, свет *включен*, если текущая минута < 30
            return current_minute < 30

        # Неизвестный статус - по умолчанию считаем, что свет выключен
        print(f"WARNING: Неизвестный статус '{current_status}' при проверке текущего времени. Считаю свет выключенным.")
        return False
    except Exception as e:
        print(f"ОШИБКА: Не удалось определить статус света в текущий момент: {e}")
        return False # Если ошибка, считаем свет выключенным для безопасности

def get_current_status(parsed_schedule: dict) -> str | None:
    """
    Возвращает статус (ключ из JSON, например 'yes', 'no', 'first' и т.д.) для текущего часа.
    """
    try:
        now_local = datetime.datetime.now()
        current_hour = now_local.hour
        current_interval_label = f"{current_hour:02d}-{(current_hour + 1) % 24:02d}" # "08-09", "23-00"
        # print(f"DEBUG: Текущий интервал: {current_interval_label}") # Для отладки
        current_status = parsed_schedule.get(current_interval_label)
        # print(f"DEBUG: Статус в текущий интервал: {current_status}") # Для отладки
        return current_status
    except Exception as e:
        print(f"ОШИБКА: Не удалось получить статус для текущего часа: {e}")
        return None

def find_imminent_outage(parsed_schedule: dict) -> dict | None:
    """
    Анализирует 24-часовой график на предмет ближайшего отключения и его продолжительности.
    """
    try:
        now_local = datetime.datetime.now()
        current_time_minutes = now_local.hour * 60 + now_local.minute

        # Список интервалов в порядке их следования за сегодня, отсортированный
        sorted_intervals = sorted(parsed_schedule.keys(), key=lambda x: int(x.split('-')[0]))

        nearest_cut_off = None
        min_delta = float('inf')

        # 1. Найти ближайшее отключение в будущем
        for interval_label in sorted_intervals:
            status = parsed_schedule[interval_label]
            if status in ['no', 'maybe', 'first', 'mfirst', 'second', 'msecond']:
                match = re.search(r'^(\d{1,2})-(\d{1,2})', interval_label)
                if not match:
                    continue
                start_hour = int(match.group(1))
                start_minute = 0
                duration_minutes = 60 # Стандартный интервал 1 час
                if status in ['second', 'msecond']:
                    start_minute = 30
                    duration_minutes = 30
                elif status in ['first', 'mfirst']:
                    duration_minutes = 30 # Только первые 30 минут часа

                cut_off_minutes = start_hour * 60 + start_minute
                time_difference = cut_off_minutes - current_time_minutes

                if 0 < time_difference < min_delta:
                    min_delta = time_difference
                    nearest_cut_off = {
                        'start_hour': start_hour,
                        'start_minute': start_minute,
                        'status': status,
                        'initial_duration': duration_minutes
                    }

        if not nearest_cut_off:
            return None

        start_h = nearest_cut_off['start_hour']
        start_m = nearest_cut_off['start_minute']
        initial_dur_m = nearest_cut_off['initial_duration']
        status = nearest_cut_off['status']

        # 2. Определить начало отключения
        cut_off_start_hour = start_h
        cut_off_start_minute = start_m

        # 3. Найти время *окончательного* включения (ожидаемое окончание отключения)
        # Начинаем искать с интервала, следующего за начальным (или с начального, если отключение внутри часа)
        cut_off_end_minutes = (cut_off_start_hour * 60 + cut_off_start_minute + initial_dur_m) % (24 * 60) # % (24 * 60) на случай переполнения в 23-24
        start_searching = False
        expected_on_hour = 24 # По умолчанию - до конца дня
        expected_on_minute = 0
        found_power_on = False
        for interval_label in sorted_intervals:
             match_int = re.search(r'^(\d{1,2})-(\d{1,2})', interval_label)
             if not match_int:
                 continue
             interval_start_hour = int(match_int.group(1))
             interval_start_minute = 0 # Интервалы всегда начинаются с 00 минут
             interval_start_total_mins = interval_start_hour * 60 + interval_start_minute
             # Пропускаем интервалы, которые заканчиваются до или в момент окончания отключения
             if interval_start_total_mins < cut_off_end_minutes:
                 continue
             next_status = parsed_schedule[interval_label]
             # Статус 'yes' означает, что свет включён с начала интервала и до конца.
             if next_status == 'yes':
                 expected_on_hour = interval_start_hour
                 expected_on_minute = 0
                 found_power_on = True
                 break # Нашли включение, выходим
             # Статус 'second'/'msecond' означает, что свет включён в первой половине интервала.
             if next_status in ['second', 'msecond']:
                 expected_on_hour = interval_start_hour
                 expected_on_minute = 0
                 found_power_on = True
                 break # Нашли включение, выходим
             # Статус 'first'/'mfirst' означает, что свет выключен в первой половине интервала (HH:00 - HH:30)
             # и включён во второй половине (HH:30 - HH+1:00).
             if next_status in ['first', 'mfirst']:
                 # Время включения после HH:00-HH:30 -> HH:30
                 expected_on_hour = interval_start_hour
                 expected_on_minute = 30
                 found_power_on = True
                 break # Нашли включение после HH:30, выходим

        # Если не нашли включения, время включения - 24:00
        if not found_power_on:
            expected_on_hour = 24
            expected_on_minute = 0

        return {
            'cut_off_start_hour': cut_off_start_hour,
            'cut_off_start_minute': cut_off_start_minute,
            'expected_on_hour': expected_on_hour,
            'expected_on_minute': expected_on_minute,
            'status': status,
            'minutes_until_cut_off': min_delta
        }
    except Exception as e:
        print(f"ОШИБКА: Не удалось найти ближайшее отключение: {e}")
        return None

def main():
        message = f"⚡️ Проверка.🏠\n"
        print(f" Отправляю оповещение.")
        send_telegram_message(message)


if __name__ == "__main__":
    main()