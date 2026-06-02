import requests
from bs4 import BeautifulSoup
import json
import time
import os
import random
from datetime import datetime

# ============================================================
#  НАСТРОЙКИ — заполни свои данные здесь
# ============================================================
TELEGRAM_TOKEN = "8874613881:AAEQmQmEhDYYbApelMlWcpj6D4NS0S964HA"    
TELEGRAM_CHAT_ID = ["725909398","340179284"]      # твой chat_id

# Фильтры поиска
CITY = "aktobe"
ROOMS = [1, 2]          # 1 и 2-комнатные
PRICE_MIN = 15_000_000  # 15 млн тенге
PRICE_MAX = 25_000_000  # 25 млн тенге

# Как часто проверять (в секундах). 1800 = 30 минут
CHECK_INTERVAL = 1800

# Файл для хранения уже виденных объявлений
SEEN_FILE = "seen_ads.json"
# ============================================================


def load_seen_ids():
    """Загружает список уже виденных объявлений"""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(seen_ids):
    """Сохраняет список виденных объявлений"""
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_ids), f)


def send_telegram(message):
    ids = TELEGRAM_CHAT_ID if isinstance(TELEGRAM_CHAT_ID, list) else [TELEGRAM_CHAT_ID]
    for chat_id in ids:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        try:
            resp = requests.post(url, data=data, timeout=10)
            if resp.status_code == 200:
                print(f"✅ Уведомление отправлено: {chat_id}")
            else:
                print(f"❌ Ошибка для {chat_id}: {resp.text}")
        except Exception as e:
            print(f"❌ Не удалось отправить {chat_id}: {e}")
        time.sleep(1)


def get_headers():
    """Возвращает случайный User-Agent чтобы не блокировали"""
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    ]
    return {
        "User-Agent": random.choice(agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def fetch_url(url, retries=3):
    """Делает запрос с повторными попытками при ошибке"""
    for attempt in range(retries):
        try:
            # Случайная пауза 3-8 секунд — имитируем живого пользователя
            pause = random.uniform(3, 8)
            print(f"   ⏳ Пауза {pause:.1f} сек перед запросом...")
            time.sleep(pause)

            resp = requests.get(url, headers=get_headers(), timeout=20)

            if resp.status_code == 403:
                print(f"   ⚠️  Сайт заблокировал запрос (попытка {attempt+1}/{retries})")
                time.sleep(30)  # ждём дольше при блокировке
                continue
            elif resp.status_code == 200:
                return resp
            else:
                print(f"   ⚠️  Статус {resp.status_code} (попытка {attempt+1}/{retries})")
                time.sleep(10)
        except requests.exceptions.Timeout:
            print(f"   ⚠️  Таймаут (попытка {attempt+1}/{retries})")
            time.sleep(10)
        except Exception as e:
            print(f"   ❌ Ошибка: {e} (попытка {attempt+1}/{retries})")
            time.sleep(10)

    return None


def parse_krisha():
    """Парсит объявления с krisha.kz и возвращает список объявлений"""
    found_ads = []

    for rooms in ROOMS:
        url = (
            f"https://krisha.kz/prodazha/kvartiry/{CITY}/"
            f"?das[live.rooms]={rooms}"
            f"&das[price][from]={PRICE_MIN}"
            f"&das[price][to]={PRICE_MAX}"
        )

        print(f"🔍 Проверяю {rooms}-комнатные квартиры...")
        resp = fetch_url(url)

        if resp is None:
            print(f"   ❌ Не удалось получить страницу, пропускаю")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # Пробуем разные селекторы (сайт иногда меняет структуру)
        listings = (
            soup.select("a.a-card__title") or
            soup.select(".a-card__header-left a") or
            soup.select("[class*='card'] a[href*='/show/']")
        )

        print(f"   Найдено объявлений: {len(listings)}")

        if len(listings) == 0:
            # Диагностика: сохраним HTML чтобы понять что пришло
            with open(f"debug_page_{rooms}rooms.html", "w", encoding="utf-8") as f:
                f.write(resp.text)
            print(f"   ⚠️  Объявления не найдены. Сохранил debug_page_{rooms}rooms.html для проверки")

        for item in listings:
            href = item.get("href", "")
            if not href:
                continue

            ad_id = href.strip("/").split("/")[-1].split("?")[0]
            if not ad_id.isdigit():
                continue

            title = item.get_text(strip=True)
            link = f"https://krisha.kz{href}" if href.startswith("/") else href

            card = item.find_parent(class_=lambda x: x and "a-card" in x)
            price_text = ""
            if card:
                price_el = card.select_one(".a-card__price")
                if price_el:
                    price_text = price_el.get_text(strip=True)

            found_ads.append({
                "id": ad_id,
                "title": title,
                "price": price_text,
                "link": link,
                "rooms": rooms,
            })

    return found_ads


def format_message(ad):
    """Форматирует сообщение для Telegram"""
    rooms_emoji = "🛏" * ad["rooms"]
    msg = (
        f"🏠 <b>Новая квартира на Krisha.kz!</b>\n\n"
        f"{rooms_emoji} <b>{ad['rooms']}-комнатная</b>\n"
        f"💰 <b>Цена:</b> {ad['price'] or 'не указана'}\n"
        f"📋 {ad['title']}\n\n"
        f"🔗 <a href='{ad['link']}'>Открыть объявление</a>\n\n"
        f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    return msg


def check_new_ads():
    """Основная функция проверки новых объявлений"""
    print(f"\n{'='*50}")
    print(f"⏰ Проверка в {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print(f"{'='*50}")

    seen_ids = load_seen_ids()
    all_ads = parse_krisha()

    new_ads = [ad for ad in all_ads if ad["id"] not in seen_ids]

    if new_ads:
        print(f"🎉 Найдено новых объявлений: {len(new_ads)}")
        for ad in new_ads:
            msg = format_message(ad)
            send_telegram(msg)
            seen_ids.add(ad["id"])
            time.sleep(1)
        save_seen_ids(seen_ids)
    else:
        print("😴 Новых объявлений нет")

    # Если это первый запуск — сохраняем все текущие как "виденные"
    if not os.path.exists(SEEN_FILE) and all_ads:
        all_ids = {ad["id"] for ad in all_ads}
        save_seen_ids(all_ids)
        print(f"💾 Первый запуск: сохранено {len(all_ids)} текущих объявлений")


def main():
    print("🚀 Krisha.kz Monitor запущен!")
    print(f"🏙  Город: Актобе")
    print(f"🛏  Комнаты: {ROOMS}")
    print(f"💰 Бюджет: {PRICE_MIN:,} — {PRICE_MAX:,} тенге")
    print(f"⏱  Проверка каждые {CHECK_INTERVAL // 60} минут")
    print()

    # Отправляем приветственное сообщение
    send_telegram(
        "✅ <b>Krisha Monitor запущен!</b>\n\n"
        f"🏙 Город: Актобе\n"
        f"🛏 Комнаты: 1 и 2-комнатные\n"
        f"💰 Бюджет: 15–25 млн тенге\n"
        f"⏱ Проверка каждые 30 минут\n\n"
        "Буду присылать новые объявления сюда 👇"
    )

    while True:
        try:
            check_new_ads()
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")

        print(f"\n💤 Следующая проверка через {CHECK_INTERVAL // 60} минут...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
