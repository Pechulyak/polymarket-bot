SECURITY BASELINE — Polymarket Trading Infrastructure

Этот документ определяет обязательные правила безопасности для проекта.
Нарушение любого пункта считается критической ошибкой безопасности.

1. Основной принцип

Торговая инфраструктура должна работать по модели:

NO PUBLIC SURFACE

То есть:

бот не имеет внешних портов

инфраструктура не предоставляет HTTP интерфейсы

проектная директория никогда не доступна по сети

Сервер должен работать как закрытый compute node, а не как веб-сервер.

2. Категорически запрещено

Следующие практики запрещены без исключений.

2.1 Раздача файлов проекта по HTTP

Запрещено:

python3 -m http.server
python -m http.server
nginx autoindex
file browser pointing to project root
any HTTP service exposing project directory

Особенно запрещено раздавать:

/root/polymarket-bot

или любую директорию, содержащую:

.env
config
private keys
api tokens
2.2 Публичные порты

Запрещено открывать внешние порты для:

dashboards
task boards
monitoring
logs
debug interfaces
file viewers

Если порт слушает:

0.0.0.0

это считается уязвимостью.

2.3 Доступ к .env через любой сервис

.env должен быть доступен только локально процессу бота.

Запрещено:

HTTP доступ

веб-сервер

API

file sharing

2.4 Хранение ключей в git

Никогда нельзя коммитить:

PRIVATE_KEY
API_SECRET
PASSPHRASE

Если ключ попал в git хоть один раз — он навсегда считается скомпрометированным.

3. Правильная модель сети

Сервер должен выглядеть так:

Internet
   |
Firewall
   |
SSH (22)
   |
Trading Server
   |
Bot processes

Никаких других портов.

4. Разрешённые способы доступа
4.1 SSH

Единственный стандартный вход:

SSH

С обязательными правилами:

key authentication only
password login disabled
4.2 Просмотр файлов

Если нужно посмотреть HTML / отчёты:

разрешены только:

вариант 1 — SCP
scp server:/path/file.html .
вариант 2 — SSH tunnel
ssh -L 8000:localhost:8000 server
вариант 3 — локальное открытие

скачать файл и открыть в браузере.

5. Правила хранения секретов
.env
chmod 600 .env

Права должны быть:

owner: read/write
others: none
Структура секретов

Рекомендуется разделять кошельки:

wallet_storage
wallet_trading

Бот работает только с trading wallet.

6. Ограничение доступа бота к средствам

Бот не должен контролировать крупные суммы.

Практика:

operational wallet balance limit

Например:

< $1000

Основные средства хранятся отдельно.

7. Firewall политика

На сервере должны быть открыты только:

22 (SSH)

Все остальные порты:

DENY

Пример:

ufw default deny incoming
ufw allow 22
8. Проверка bind address

Все локальные сервисы должны слушать:

127.0.0.1

Никогда:

0.0.0.0
9. Проверка перед запуском нового сервиса

Перед запуском любой службы нужно проверить:

1. bind address
2. firewall rules
3. directory exposure
4. secrets exposure
10. Incident response правило

Если секрет скомпрометирован:

1. rotate wallet
2. rotate API keys
3. revoke approvals
4. rotate tokens

Никогда нельзя повторно использовать скомпрометированные ключи.

11. Логирование

Логи никогда не должны содержать:

private keys
API secrets
passphrases
12. Минимальный security checklist

Перед любым деплоем:

no open ports
.env not exposed
no secrets in git
firewall active
wallet separated