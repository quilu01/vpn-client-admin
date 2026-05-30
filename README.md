# VPN Client Admin

Закрытая web-админка для ручной выдачи Happ-подключений через 3x-ui. Клиент не получает публичный бот или форму активации: подключение создается только администратором, после чего админка показывает зашифрованную Happ-ссылку, QR-код и Telegram share-ссылку.

## Что уже есть

- FastAPI + server-rendered Jinja UI.
- Логин администратора, signed cookie session и IP allowlist.
- PostgreSQL в продакшене, SQLite по умолчанию для локального запуска.
- SQLAlchemy models и Alembic migration.
- Создание клиента в одном или нескольких 3x-ui inbound.
- Приватный `/sub/{token}`, который отдает подписку только активному и не заблокированному клиенту.
- Шифрование ссылки через Happ Crypto API.
- Копирование ссылки, QR-код и `t.me/share/url` для ручной отправки в Telegram.
- Продление, блокировка, перевыпуск ссылки и синхронизация трафика.

## Быстрый локальный запуск

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Для локальной проверки без настоящих 3x-ui/Happ можно поставить в `.env`:

```env
DATABASE_URL="sqlite:///./vpn_admin.sqlite3"
COOKIE_SECURE="false"
HAPP_CRYPTO_MODE="passthrough"
```

Миграции и запуск:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

Откройте `http://localhost:8000/admin`.

## Настройка для VPS

1. Создайте `.env` из `.env.example`.
2. Сгенерируйте пароль администратора:

```powershell
python -m app.core.security hash-password "your-strong-password"
```

3. Заполните:

```env
APP_SECRET_KEY="long-random-secret"
PUBLIC_APP_URL="https://admin.example.com"
POSTGRES_DB="vpn_admin"
POSTGRES_USER="vpn_admin"
POSTGRES_PASSWORD="long-random-db-password"
DATABASE_URL="postgresql+psycopg://vpn_admin:long-random-db-password@postgres:5432/vpn_admin"
APP_BIND_HOST="127.0.0.1"
APP_PORT="8000"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD_HASH="pbkdf2_sha256$..."
ADMIN_PASSWORD=""
ADMIN_IP_ALLOWLIST="your.public.ip.address/32"
COOKIE_SECURE="true"
TRUST_PROXY_HEADERS="true"

XUI_BASE_URL="https://xui.example.com"
XUI_API_TOKEN="3x-ui-api-token"
XUI_INBOUND_ID="1"
XUI_INBOUNDS="1:Default"
XUI_SUBSCRIPTION_BASE_URL="https://xui.example.com/sub"
XUI_TLS_VERIFY="true"
HAPP_CRYPTO_MODE="api"
HAPP_PROFILE_TITLE="VPN"
HAPP_SUPPORT_URL="https://t.me/kmplzzz"
HAPP_PROFILE_WEB_PAGE_URL="https://t.me/kmplzzz"
```

4. Для production-запуска используйте deploy-скрипт:

```bash
bash scripts/deploy.sh --check
bash scripts/deploy.sh
```

5. Поставьте reverse proxy с HTTPS перед приложением. IP allowlist можно держать и на reverse proxy, и в приложении.

## Деплой через GitHub Actions

Production-секреты не хранятся в GitHub. На сервере один раз создается структура:

```bash
sudo mkdir -p /opt/vpn-client-admin/releases /opt/vpn-client-admin/shared
sudo chown -R deploy:deploy /opt/vpn-client-admin
```

Файл окружения должен лежать только на VPS:

```bash
nano /opt/vpn-client-admin/shared/.env
chmod 600 /opt/vpn-client-admin/shared/.env
```

Создайте отдельного пользователя для деплоя:

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo mkdir -p /home/deploy/.ssh
sudo nano /home/deploy/.ssh/authorized_keys
sudo chown -R deploy:deploy /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

В GitHub repository secrets добавьте:

```text
VPS_HOST=your.server.ip.or.domain
VPS_PORT=22
VPS_USER=deploy
VPS_SSH_KEY=private SSH key for deploy user
DEPLOY_PATH=/opt/vpn-client-admin
```

После push в ветку `main` workflow `.github/workflows/deploy.yml` загрузит архив релиза на VPS, обновит symlink `/opt/vpn-client-admin/current` и запустит:

```bash
bash scripts/deploy.sh
```

Первый ручной запуск на сервере:

```bash
cd /opt/vpn-client-admin/current
bash scripts/deploy.sh --check
bash scripts/deploy.sh
```

Если Docker или Docker Compose plugin не установлены, скрипт остановится с понятной ошибкой и ничего не будет устанавливать автоматически.

## Nginx reverse proxy

Пример для отдельного поддомена `admin.example.com`. Приложение слушает только `127.0.0.1:8000`, поэтому наружу его открывает Nginx:

```nginx
server {
    listen 80;
    server_name admin.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

После выпуска HTTPS-сертификата через Certbot оставьте в `.env`:

```env
PUBLIC_APP_URL="https://admin.example.com"
COOKIE_SECURE="true"
TRUST_PROXY_HEADERS="true"
ADMIN_IP_ALLOWLIST="your.public.ip.address/32"
```

`docker-compose.yml` использует отдельное имя проекта `vpn_client_admin`, поэтому контейнеры этого приложения не должны пересекаться с контейнерами 3x-ui.

## 3x-ui требования

- В 3x-ui должен быть создан inbound, id которого указан в `XUI_INBOUND_ID`.
- Админка автоматически подтягивает активные inbounds из 3x-ui API. `XUI_INBOUNDS`, например `6:Amsterdam,7:Helsinki`, используется как fallback, если API списка серверов временно недоступен.
- Для API используйте Bearer token 3x-ui.
- Подписочный URL должен быть доступен backend-приложению. Обычно это `https://xui.example.com/sub/{subId}`, а в `.env` указывается базовая часть `XUI_SUBSCRIPTION_BASE_URL`.

## Happ

MVP использует Happ Crypto API и сохраняет только зашифрованную ссылку вида `happ://crypt5/...`. Endpoint `/sub/{token}` дополнительно отдает Happ-compatible headers:

- `profile-title`: имя профиля в Happ, по умолчанию `VPN`.
- `subscription-userinfo`: трафик и Unix timestamp окончания доступа, чтобы Happ показывал срок подписки не через название сервера.
- `support-url` и `profile-web-page-url`: ссылка поддержки/аккаунта, по умолчанию `https://t.me/kmplzzz`.

Device limit через Happ limited links не включен, потому что для него нужны `provider_code` и `auth_key`. Когда они появятся, следующий шаг: создать `InstallID`, добавить его в subscription URL и шифровать уже итоговую ссылку.

## Проверки

```powershell
pytest
```

Тесты покрывают пароль/сессии/IP allowlist, создание клиента, отказ Happ Crypto API, Happ headers для подписки, закрытие подписки для blocked/expired клиентов и перевыпуск токена.
