from datetime import datetime, timezone, timedelta


def current_time():
    utc_offset = 3  # Смещение на 3 часа
    return (datetime.now(timezone.utc) + timedelta(hours=utc_offset)).strftime('%d.%m. %H:%M')


print(current_time())
