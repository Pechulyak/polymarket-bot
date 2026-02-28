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

### Командная строка (запустить локально):
```bash
ssh -L 5433:localhost:5433 -N -f root@212.192.11.92
```

Затем подключиться в DBeaver:
```
Host: localhost
Port: 5433
Database: polymarket
Username: postgres
Password: <ваш_пароль_БД>
```

### DBeaver со встроенным SSH:
1. New Connection → PostgreSQL
2. Вкладка "SSH" → поставить галочку "Enable"
3. Заполнить:
   - Host: 212.192.11.92
   - Port: 22
   - Username: root
   - Authentication: Password
   - Password: <ваш_SSH_пароль>
4. Вкладка "Main":
   - Host: localhost
   - Port: 5433
   - Database: polymarket
   - Username: postgres
   - Password: 156136ar

## Проверка

```bash
# С сервера
ss -tulpn | grep 5433
# Должно показать: 127.0.0.1:5433
```
