# SSH Tunnel для подключения к PostgreSQL

## Настройка DBeaver

### Шаг 1: Создать SSH туннель на локальном компьютере

```bash
ssh -L 5433:localhost:5432 -N -f root@212.192.11.92
```

При первом подключении подтвердите ключ (yes).

### Шаг 2: Подключение в DBeaver

```
Host: localhost
Port: 5433
Database: polymarket
Username: postgres
Password: <ваш_пароль>
```

### Альтернатива: SSH туннель через DBeaver

В DBeaver можно настроить SSH туннель напрямую:

1. New Connection → PostgreSQL
2. Вкладка "SSH" → включить
3. Настройки:
   - Host: 212.192.11.92
   - Port: 22
   - Username: root
   - Authentication: Password или Key
4. Вкладка "Main":
   - Host: localhost
   - Port: 5433
   - Database: polymarket
   - Username: postgres
   - Password: <ваш_пароль>

## Проверка

```bash
# Проверить туннель
ss -tulpn | grep 5433
```
