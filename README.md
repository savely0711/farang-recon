# Разведка рынка — парсер барахолок Паттайи (Направление 3)

Читает барахолки Паттайи техническим Telegram-аккаунтом и складывает
объявления (ссылка + категория + дата + цена) в Google-таблицу.
Личные данные не собираются. Работает аккуратно: медленное чтение, паузы,
не больше одного нового вступления в группу за запуск.

## Файлы
- `parser.py` — главный скрипт (один запуск = один прогон).
- `login.py` — разовый вход аккаунтом, выдаёт строку сессии.
- `channels.py` — список каналов (старт: топ-3 лидера).
- `categories.py` — категории для ИИ (наши 10 + разведочные).
- `classify.py` — ИИ-разбор поста (объявление? категория? цена?).
- `sheets.py` — запись в Google-таблицу (POST в Apps Script Web App).
- `state.py` — память «докуда дочитали» (`state.json`).
- `.env` — секреты и настройки (НЕ в git).

## Установка на сервер (Ubuntu, кратко)
```bash
sudo apt update && sudo apt install -y python3-pip git
git clone <репозиторий> recon && cd recon      # или скопировать файлы
pip3 install -r requirements.txt
cp .env.example .env                            # затем заполнить .env
```

### Что нужно заполнить в `.env`
1. `TG_API_ID` / `TG_API_HASH` — один раз на https://my.telegram.org → API development tools.
2. `ANTHROPIC_API_KEY` — ключ ИИ (тот же, что на сайте).
3. `SHEET_WEBHOOK_URL` / `SHEET_TOKEN` — запись в таблицу через Apps Script Web App.
   К таблице привязан скрипт-приёмник (`apps_script.gs`), развёрнутый как Web App;
   URL вида `https://script.google.com/macros/s/.../exec` кладём в `SHEET_WEBHOOK_URL`,
   а общий пароль-токен (та же строка, что вшита в скрипт) — в `SHEET_TOKEN`.
   Пока `SHEET_WEBHOOK_URL` пуст — парсер работает в тестовом режиме (в таблицу не пишет).
4. `TG_SESSION` — получить так:
   ```bash
   python3 login.py      # ввести номер → код из Telegram → пароль (если есть)
   ```
   Скрипт напечатает строку сессии — вставить её в `.env`.

## Запуск вручную
```bash
python3 parser.py
```

## Ежедневное расписание (cron)
```bash
crontab -e
# каждый день в 09:00 по времени сервера:
0 9 * * * cd /root/recon && /usr/bin/python3 parser.py >> recon.log 2>&1
```
