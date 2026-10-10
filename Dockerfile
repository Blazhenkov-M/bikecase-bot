FROM python:3.12.0-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем requirements.txt в рабочую директорию
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект в рабочую директорию
COPY . .

# Устанавливаем переменную окружения для корректной импортации модулей
ENV PYTHONPATH=/app

# Указываем команду для запуска вашего приложения
CMD ["python", "app/main.py"]
