# Подключение к PostgreSQL

## Вариант 1: Прямое подключение (с сервера)

```
Host: localhost
Port: 5433
Database: polymarket
Username: postgres
Password: <ваш_пароль_БД>
```

## Вариант 2: Через SSH туннель (удалённо)

### Командная строка:
```bash
ssh -L 5433:localhost:5433 -N -f root@212.192.11.92
```

### DBeaver:
1. New Connection → PostgreSQL
2. Вкладка "SSH" → включить
3. Настройки:
   - Host: 212.192.11.92
   - Port: 22
   - Username: root
   - Authentication: Password
4. Вкладка "Main":
   - Host: localhost
   - Port: 5433
   - Database: polymarket
   - Username: postgres
   - Password: <ваш_пароль_БД>

## Проверка

```bash
# С сервера
ss -tulpn | grep 5433
```
