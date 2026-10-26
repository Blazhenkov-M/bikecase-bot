# Telegram-бот веломастерской

Описание проекта, функционал и модель данных: @README.md

## Технические правила
- Запуск: `python main.py`; зависимости в `requirements.txt` (версии фиксировать)
- Конфиг через `.env` (BOT_TOKEN, DATABASE_URL, ADMIN_IDS), читать в `config.py`
- DATABASE_URL в формате `postgresql+asyncpg://user:password@localhost:5432/dbname`
- SQLAlchemy 2.0 async, PostgreSQL (драйвер asyncpg), миграции через Alembic
- Диалоги через aiogram FSM, один роутер на модуль в `handlers/`
- Тексты на русском
- Отчёт: openpyxl, файл формируется в памяти и отправляется документом
- Админы определяются по ADMIN_IDS
- Секреты (токен, пароли БД) только в `.env`, `.env` в `.gitignore`, в код и чат не вставлять

## Рабочий процесс
- Сначала план и вопросы, потом код
- Одна фича за раз, после каждой запуск и проверка
- Схему БД менять только через миграции Alembic