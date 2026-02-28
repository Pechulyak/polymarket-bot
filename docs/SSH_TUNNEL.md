# SSH Tunnel для подключения к PostgreSQL

## Вариант 1: SSH туннель через командную строку

### Шаг 1: Создать SSH туннель

```bash
ssh -L 5433:localhost:5432 -N -f -i ~/.ssh/id_ed25519 root@212.192.11.92
```

### Шаг 2: Подключение в DBeaver

```
Host: localhost
Port: 5433
Database: polymarket
Username: postgres
Password: <ваш_пароль_БД>
```

## Вариант 2: SSH туннель через DBeaver (рекомендуется)

1. New Connection → PostgreSQL
2. Вкладка "SSH" → включить
3. Настройки:
   - Host: 212.192.11.92
   - Port: 22
   - Username: root
   - Authentication: Password
   - Password: <ваш_пароль_SSH>
4. Вкладка "Main":
   - Host: localhost
   - Port: 5433
   - Database: polymarket
   - Username: postgres
   - Password: <ваш_пароль_БД>

## Вариант 3: С SSH ключом в DBeaver

1. New Connection → PostgreSQL
2. Вкладка "SSH" → включить
3. Настройки:
   - Host: 212.192.11.92
   - Port: 22
   - Username: root
   - Authentication: Key
   - Key: (нажмите Browse и выберите файл)
4. Вкладка "Main":
   - Host: localhost
   - Port: 5433
   - Database: polymarket
   - Username: postgres
   - Password: <ваш_пароль_БД>

## Проверка

```bash
# Проверить туннель
ss -tulpn | grep 5433
```
