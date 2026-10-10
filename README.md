# Base Telegram Bot

Базовый шаблон Telegram бота с интеграцией PostgreSQL.

## Требования

- Python 3.9+
- Docker
- Poetry (опционально, но рекомендуется)

## Быстрый старт для нового проекта

> **Рекомендация:** Если вы используете этот проект как шаблон для нового бота, НЕ копируйте содержимое папки `alembic/versions/` (оставьте её пустой). Это позволит вам сгенерировать свою первую миграцию под ваши модели.

1. Клонируйте репозиторий или скопируйте структуру проекта:
```bash
git clone <your-repo-url>
cd base_bot
# или скопируйте файлы вручную
```

2. Создайте и активируйте виртуальное окружение (если не используете Poetry):
```bash
python -m venv venv
source venv/bin/activate  # для Linux/macOS
# или
.\venv\Scripts\activate  # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
# или с Poetry
poetry install
```

4. Создайте файл `.env` в корневой директории проекта:
```bash
BOT_TOKEN=your_bot_token_here
DB_HOST=db  # если запускаете через docker-compose
DB_PORT=5432
DB_NAME=bot_db
DB_USER=postgres
DB_PASS=postgres
```

5. Запустите PostgreSQL и бота через Docker Compose:
```bash
docker-compose up --build
```

6. Сгенерируйте первую миграцию и примените её:
```bash
docker-compose run --rm bot alembic revision --autogenerate -m "init"
docker-compose run --rm bot alembic upgrade head
```

7. После этого бот готов к работе с базой данных!

## Структура проекта

```
base_bot/
├── app/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── bot_instance.py
│   │   ├── config.py
│   │   └── database.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── database.py
│   │   └── models.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── start.py
│   ├── keyboards/
│   │   ├── __init__.py
│   │   └── reply.py
│   ├── main.py
│   └── services/
│       ├── __init__.py
│       └── user.py
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   ├── README
│   └── versions/  # <--- папка для миграций, должна быть пуста в шаблоне
├── alembic.ini
├── .env
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Основные возможности

- Асинхронная работа с Telegram API (aiogram)
- Интеграция с PostgreSQL через SQLAlchemy
- Система миграций с Alembic
- Конфигурация через переменные окружения
- Базовая структура для масштабирования проекта

## Разработка

1. Для создания новых миграций:
```bash
alembic revision --autogenerate -m "описание изменений"
```

2. Для применения миграций:
```bash
alembic upgrade head
```

## Важно
- **Не копируйте файлы миграций из шаблона в новый проект!**
- **Перед первым запуском всегда создавайте и применяйте свою первую миграцию.**
- **Папка `alembic/versions/` должна быть пуста при старте нового проекта.**
