# Журнал деплоя

Сервер: `vm-12519177`, 91.149.241.113, Ubuntu 24.04, юзер `deploy` (`ssh vps`). Работа без sudo.

## 2026-11-11: первый деплой

### Состояние сервера до деплоя
- Docker пустой: контейнеров, томов и своих сетей нет. AmneziaVPN ещё не установлена.
- `ss -tulpn`: слушает только 22 (и локальный DNS 127.0.0.53/54).
- Диск: свободно 15 ГБ из 19. RAM 1.9 ГБ.

### Изменения в проекте (локально)
- `docker-compose.yml`:
  - убраны `ports: 5432:5432` и `8000:8000`. Docker обходит ufw, и Postgres был бы открыт в интернет. Бот работает через polling, входящие порты ему не нужны;
  - `name: bikecase` (явное имя проекта, том `bikecase_postgres_data`);
  - healthcheck Postgres (`pg_isready`), бот стартует после `service_healthy`;
  - ротация логов: `json-file`, 10 МБ × 3 на контейнер;
  - убран лишний `BOT_TOKEN: ${BOT_TOKEN}` из `environment` (токен приходит через `env_file`).
- `.env`: убран пробел перед `=` в строке `BOT_TOKEN`.

### Изменения на сервере
1. Создан каталог `/home/deploy/bikecase_transfer_bot`.
2. Код скопирован через `rsync` из рабочего дерева, без git. Исключены `.git`, `.venv`, `.idea`, `.claude`, `__pycache__`, `documents`, `.env`, `DEPLOY_LOG.md`.
3. `.env` скопирован отдельно через ssh, права `600`. Содержимое в журнал и чат не попадало.
4. `docker compose up -d --build`. Созданы:
   - образ `bikecase-bot`, скачан `postgres:15-alpine`;
   - том `bikecase_postgres_data`, сеть `bikecase_default`;
   - контейнеры `bikecase-postgres-1`, `bikecase-bot-1` (`restart: unless-stopped`).

### Проверка
- Миграции: `0001_init` → `0002_krylatskoe_limits`, в `alembic_version` записано `0002_krylatskoe_limits`.
- В логе: `Run polling for bot @bikecase_transfer_bot`. Перезапусков 0, Postgres `healthy`.
- `api.telegram.org` из контейнера доступен (HTTP 200).
- После запуска `ss -tulpn`: снаружи по-прежнему слушает только 22. Новых портов нет, конфликтов с будущей Amnezia по портам нет.
- ufw, SSH, fail2ban не трогали. `docker system prune` не запускали.

## 2026-11-14: обновлены PDF согласия и политики

- В `documents/` заменены оба PDF, новые имена: `Согласие_на_обработку_ПДн_bikecase_transfer_bot.pdf`, `Политика_конфиденциальности_bikecase_transfer_bot.pdf`. В `app/handlers/user/booking.py` (`CONSENT_DOCUMENTS`) прописаны новые имена.
- Найдено: `documents/` была исключена из rsync, и на сервере её не было. Значит, с первого деплоя PDF клиентам не отправлялись (ошибка ловилась и писалась в лог). Исключение убрано из команды rsync в шпаргалке.
- Миграций нет, бэкап не делали. `rsync` и `docker compose up -d --build`: пересоздан только `bikecase-bot-1`, Postgres не трогали.
- Проверка: `/app/documents` в контейнере содержит оба PDF, в логе `Run polling for bot @bikecase_transfer_bot`, перезапусков 0.

## 2026-11-18: переименование репозитория и PDF

- Локальная папка переименована в `bikecase-bot`, remote теперь `git@github.com:Blazhenkov-M/bikecase-bot.git` (пуш по SSH). Каталог на сервере не менялся: `~/bikecase_transfer_bot`.
- PDF переименованы: `Согласие_на_обработку_ПД_bikecase_bot.pdf`, `Политика_обработки_ПД_bikecase_bot.pdf`. Обновлён `CONSENT_DOCUMENTS` в `app/handlers/user/booking.py`.
- rsync без `--delete`, поэтому старые PDF на сервере удалены вручную. `docker compose up -d --build`: пересоздан только `bikecase-bot-1`, Postgres не трогали.
- Проверка: в `/app/documents` только новые PDF, в логе `Run polling for bot @bikecase_transfer_bot`, перезапусков 0.

## 2026-11-18: новый токен бота

- Бот сменился: теперь `@bikecase_bot` (id 9125866011), раньше был `@bikecase_transfer_bot`. В `.env` (локально и на сервере) заменён `BOT_TOKEN`, на сервере права `600`. Сам токен в журнал не записан.
- `docker compose up -d`: пересоздан только `bikecase-bot-1`. В логе `Run polling for bot @bikecase_bot`, перезапусков 0.
- В коде имя бота не захардкожено, правок в коде не было.

## Шпаргалка

Обновить код (с Mac, из папки проекта):
```
rsync -az --exclude='.git/' --exclude='.venv/' --exclude='.idea/' --exclude='.claude/' \
  --exclude='__pycache__/' --exclude='.env' --exclude='.DS_Store' \
  --exclude='DEPLOY_LOG.md' ./ vps:bikecase_transfer_bot/
ssh vps 'cd ~/bikecase_transfer_bot && docker compose up -d --build'
```
Миграции применяются автоматически при старте контейнера бота.

Обновить `.env`: `ssh vps 'umask 077; cat > ~/bikecase_transfer_bot/.env' < .env`, затем `ssh vps 'cd ~/bikecase_transfer_bot && docker compose up -d'`.

Логи: `ssh vps 'cd ~/bikecase_transfer_bot && docker compose logs -f bot'`
Статус: `ssh vps 'cd ~/bikecase_transfer_bot && docker compose ps'`
Остановить: `ssh vps 'cd ~/bikecase_transfer_bot && docker compose stop'`. **Не** `down -v`: `-v` удалит том с базой.
