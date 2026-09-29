# Deploying the backend

Docker Compose, on one server. Three containers: the API, MySQL and Redis.

The frontend is not part of this. It can be added later behind the same reverse proxy
without changing anything here.

---

## 1. What the server needs

- Docker Engine with the Compose plugin
- A domain pointing at the server, and a reverse proxy (nginx / Caddy) terminating TLS
- Outbound HTTPS, for the SMS provider and Firebase

## 2. Get the code there

```sh
git clone <repo-url> /srv/mbga
cd /srv/mbga/backend
git checkout gaurav-development
```

## 3. Write the environment file

```sh
cp .env.production.example .env
```

Fill in every value marked `CHANGE-ME`:

| Setting | How to get it |
|---|---|
| `JWT_SIGNING_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DOCUMENT_ENCRYPTION_SECRET` | same command. **Back it up** - losing it makes stored KYC identifiers unreadable |
| `DATABASE_URL` | the password you set in step 4 |
| `ALLOWED_CORS_ORIGINS` | the panel's real origin, e.g. `'["https://panel.example.com"]'` |
| `HANUOTP_*` | from the SMS provider |

The app **refuses to start** on a production-unsafe value rather than starting and quietly
behaving like a dev box. If boot fails, read the error - it names the setting.

## 4. Set the database passwords

`docker-compose.yml` ships with `change_me`. Edit both, and make `DATABASE_URL` match:

```yaml
MYSQL_PASSWORD: <the same password as in DATABASE_URL>
MYSQL_ROOT_PASSWORD: <a different one>
```

## 5. Put the Firebase keys in place

Not in git, not in the image - mounted at run time:

```sh
mkdir -p secrets
# copy fcm-merchant.json, fcm-customer.json, fcm-delivery.json into ./secrets
chmod 600 secrets/*.json
```

Without these, every other feature works and push notifications silently do not.

## 6. Start

```sh
docker compose up -d --build
docker compose logs -f api
```

The API container runs `alembic upgrade head` before serving. Alembic is idempotent, so
restarts are safe and a database already at head is a no-op.

Check it is up:

```sh
curl http://127.0.0.1:8000/health      # {"status":"ok"}
```

## 7. Put the reverse proxy in front

Only the API is exposed; MySQL and Redis stay on the compose network.

```nginx
server {
    listen 443 ssl http2;
    server_name api.example.com;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

Set `TRUSTED_PROXY_IPS` to the proxy's address. Left empty, the client IP recorded on rate
limits and audit rows is the proxy's, and OTP throttling becomes global instead of per-caller.

Once TLS is on, close port 8000 to the outside - the proxy reaches it over loopback.

---

## Updating

```sh
cd /srv/mbga && git pull
cd backend && docker compose up -d --build
```

Migrations run on start.

## Backups

Two things carry data that cannot be rebuilt:

```sh
docker compose exec mysql mysqldump -u root -p mbga > mbga-$(date +%F).sql
docker run --rm -v backend_documents:/d -v "$PWD":/out alpine \
    tar czf /out/documents-$(date +%F).tar.gz -C /d .
```

Plus `DOCUMENT_ENCRYPTION_SECRET`, kept somewhere other than the server. The document
archive is useless without it.

## Base URL for the app developers

```
https://api.example.com/api/v1/{merchant|customer|delivery|admin}/...
```

The channel prefix decides which app a route belongs to, and a token minted on one channel
is rejected on another.

---

## Things to check before going live

- [ ] `APP_ENV=production`, `DEBUG=false`, `API_DOCS_ENABLED=false`
- [ ] `JWT_SIGNING_SECRET` and `DOCUMENT_ENCRYPTION_SECRET` are random, and backed up
- [ ] MySQL passwords changed from `change_me` in both compose and `DATABASE_URL`
- [ ] **Firebase service-account keys rotated.** The current three were pasted into a chat
      window, so they must be treated as compromised. Keep the same filenames and `.env`
      needs no change
- [ ] `ALLOWED_CORS_ORIGINS` is the real panel origin, not localhost
- [ ] TLS is on, and port 8000 is closed to the outside
- [ ] A backup has been taken and restored once, before it is needed

---

## The delivery app's response envelope

The delivery app unwraps every response itself: `{"success": true, "data": ...}` on the way in,
`{"success": false, "error": {code, message, statusCode}}` on an error. The platform's own shape
is `{"detail": {...}}`, which the merchant and customer apps are built against.

`DELIVERY_RESPONSE_ENVELOPE=true` re-shapes `/api/v1/delivery/*` into the app's envelope. It
ships **off**, and that default is deliberate: the delivery app is already signed in against the
raw shapes on the auth and notification routes. Turning this on wraps those too - `request_id`
moves from the body to the `X-Request-Id` header, and `data` appears around every payload - so it
is flipped only once the app's developer expects it, and the change is reversible in one line.
