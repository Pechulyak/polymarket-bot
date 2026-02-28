# SSH Tunnel для подключения к PostgreSQL

## Вариант 1: SSH туннель с пробросом порта (рекомендуется)

### На локальном компьютере:

```bash
# Создать SSH туннель
ssh -L 5433:localhost:5433 -N -f user@your-server-ip

# Или с кастомным портом SSH
ssh -L 5433:localhost:5433 -p 22 -N -f user@your-server-ip
```

### Подключение в DBeaver:

```
Host: localhost
Port: 5433
Database: polymarket
Username: postgres
Password: <ваш_пароль>
```

## Вариант 2: Подключение через docker exec (временное)

```bash
# Проброс порта через docker
docker compose exec -p 5433:5432 postgres bash
```

## Вариант 3: SSH туннель с ключом

```bash
# С SSH ключом
ssh -i ~/.ssh/id_rsa -L 5433:localhost:5433 -N -f user@your-server-ip
```

## Проверка туннеля

```bash
# Проверить, что порт открыт локально
ss -tulpn | grep 5433

# Тест подключения
psql -h localhost -p 5433 -U postgres -d polymarket
```

## Закрытие туннеля

```bash
# Найти и убить процесс
pkill -f "ssh -L 5433"
```
