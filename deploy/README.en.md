# Reach Part Vision — Ubuntu Server Setup (English)

Deploy this stack on an **Ubuntu** host with **Docker**. MySQL is **external** (not started by Compose). Python/npm dependencies are installed **only during image build** — do not run `pip install` or `npm install` inside running containers.

Chinese notes: see [README.md](./README.md).

---

## 1. What you need

| Item | Notes |
|------|--------|
| OS | Ubuntu 22.04 LTS (or newer) recommended |
| Docker | Docker Engine + Docker Compose plugin (`docker compose`) |
| Git | To clone / pull the repository |
| MySQL 8 | Existing company database; create an empty schema for this app |
| Network | Outbound HTTPS to Hugging Face (first model download), PyPI, DeepSeek API |
| GPU (optional) | NVIDIA GPU + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) for fast image retrieval; CPU works but is slower |

**Published ports (defaults):**

| Port | Service |
|------|---------|
| `80` | Mobile H5 |
| `8080` | Admin console |
| `8081` | Desktop web |
| (internal) | API is behind Nginx in the `web` container; health: `/health`, `/ready` |

Open these ports in the cloud security group / `ufw` as needed.

---

## 2. Install Docker on Ubuntu (if missing)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# Log out and back in (or reboot) so the docker group applies.
docker version
docker compose version
```

### GPU hosts (optional)

1. Install a matching NVIDIA driver on the host.
2. Install the NVIDIA Container Toolkit and restart Docker.
3. Verify:

```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

If you have **no GPU**, skip this and use the CPU settings in section 4.

---

## 3. Get the code

```bash
git clone <your-repo-url> reach_part_vision4dsv
cd reach_part_vision4dsv/deploy
cp .env.example .env
```

Edit `deploy/.env` before the first start. This file is **not** in Git; `git pull` will not overwrite it.

---

## 4. Configure environment (`deploy/.env`)

Replace placeholders. At minimum set the values below.

### 4.1 Application & CORS

```env
APP_ENV=production
DEBUG=false
SECRET_KEY=<long-random-string>

# Use your public hostname or IP (include every UI origin users will open).
CORS_ORIGINS=["http://YOUR_HOST","http://YOUR_HOST:8080","http://YOUR_HOST:8081"]
```

If you terminate TLS later, switch these origins to `https://...`.

### 4.2 MySQL (external)

```env
# Inside a container, 127.0.0.1 is NOT the host.
# MySQL on this same Ubuntu box:
MYSQL_HOST=host.docker.internal
# MySQL on another machine:
# MYSQL_HOST=10.x.x.x

MYSQL_PORT=3306
MYSQL_USER=<app-user>
MYSQL_PASSWORD=<password>
MYSQL_DATABASE=reach_part_vision4dsv
```

Create the empty database on MySQL first, for example:

```sql
CREATE DATABASE reach_part_vision4dsv
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Tables are created/updated automatically when the **API** container starts. Catalog data (OE / vehicle / radiator specs) is maintained via the **Admin → Excel import** screens after login (not via DolphinScheduler USA tables anymore).

### 4.3 Redis & Celery

Leave the defaults unless you know you need otherwise:

```env
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
CELERY_ENABLED=true
CELERY_WORKER_CONCURRENCY=1
```

Compose starts Redis for you. Recognition uses queue `celery` (`worker`); WhatsApp uses queue `whatsapp` (`worker_whatsapp`).

### 4.4 Storage

```env
STORAGE_BACKEND=local
LOCAL_STORAGE_DIR=/data/uploads
```

Uploads live in the Docker volume `uploads`. Do not delete that volume on upgrade.

### 4.5 DeepSeek

```env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash-vision-exp
DEEPSEEK_CHAT_MODEL=deepseek-chat
```

Required for vision fallback and WhatsApp chat tools.

### 4.6 WhatsApp Cloud API (optional but typical for US)

```env
WHATSAPP_ENABLED=true
WHATSAPP_WEBHOOK_PATH_TOKEN=<path-secret>
WHATSAPP_VERIFY_TOKEN=<verify-token>
WHATSAPP_APP_SECRET=<app-secret>
WHATSAPP_ACCESS_TOKEN=<permanent-token>
WHATSAPP_PHONE_NUMBER_ID=<phone-number-id>
WHATSAPP_GRAPH_API_VERSION=v21.0
WHATSAPP_WORKER_CONCURRENCY=4
```

Point Meta’s webhook (or your gateway) at the API path  
`/sms/whatsapp/<WHATSAPP_WEBHOOK_PATH_TOKEN>`.  
If traffic enters via an external gateway on another host/port, forward to this stack’s API (`api:8000` inside Compose / Nginx as designed).

### 4.7 Image retrieval (SKU matching)

```env
RETRIEVAL_ENABLED=true
EMBEDDING_BACKEND=dinov2
EMBEDDING_MODEL_ID=facebook/dinov2-base
VECTOR_BACKEND=memory
SEARCH_INDEX_DIR=/data/indexes
PHOTO360_ROOT=          # optional: path to 360 gallery root category/SKU/*.jpg
HF_HOME=/data/models
```

**GPU build (default in `.env.example` for RTX / CUDA 12.8):**

```env
TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
SEARCH_SEGMENT_DEVICE=cuda
```

**CPU-only host:**

```env
TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
SEARCH_SEGMENT_DEVICE=cpu
```

Also remove `gpus: all` from the `worker` service in `docker-compose.yml` if the host has no NVIDIA runtime (otherwise `worker` will fail to start).

Use public PyPI indexes on a US server (already in `.env.example`):

```env
PIP_INDEX_URL=https://pypi.org/simple
```

### 4.8 Admin bootstrap user

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<strong-password>
ADMIN_DISPLAY_NAME=Administrator
```

### 4.9 Host ports

```env
H5_PORT=80
ADMIN_PORT=8080
WEB_PORT=8081
```

---

## 5. First start

```bash
cd reach_part_vision4dsv/deploy
docker compose up -d --build
```

Check:

```bash
docker compose ps
curl -sS http://127.0.0.1/health
curl -sS http://127.0.0.1/ready
```

| URL | Purpose |
|-----|---------|
| `http://YOUR_HOST/` | Mobile H5 |
| `http://YOUR_HOST:8081` | Desktop web |
| `http://YOUR_HOST:8080` | Admin |
| `http://YOUR_HOST/health` | Liveness |
| `http://YOUR_HOST/ready` | Readiness (Redis / Celery / retrieval) |

### First-time model download

On the first `worker` start, if the `models` volume is empty, the entry script downloads:

- `facebook/dinov2-base`
- `ZhengPeng7/BiRefNet`

The host must reach Hugging Face. Weights stay on the `models` volume and are reused after rebuilds.

### Load the vector index (required for SKU retrieval)

Indexes are **not** in Git. Copy a prepared `data/indexes/` tree into the worker volume, then restart the worker:

```bash
# From a machine that has the index files:
docker compose cp /path/to/indexes/. worker:/data/indexes/
docker compose restart worker
```

The volume should contain `latest_meta.json` and the matching `dinov2_*` directory (and optional white index if you use it).

---

## 6. After go-live checklist

1. Log in to **Admin** and import catalog Excel sheets: **OE**, **Vehicles**, **Radiator specs** (as needed).
2. Confirm `/ready` shows retrieval/worker healthy.
3. Test one photo recognition on H5/Web and one WhatsApp photo (if enabled).
4. Restrict firewall to only the ports you need; keep MySQL closed to the public internet.

---

## 7. Updating the deployment

On the server:

```bash
cd reach_part_vision4dsv
git pull
cd deploy
docker compose build
docker compose up -d
```

| Change | Action |
|--------|--------|
| Backend only | `docker compose build api && docker compose up -d api worker worker_whatsapp beat` |
| Frontend only | `docker compose build web && docker compose up -d web` |
| `.env` only | `docker compose up -d` (restart `worker` if retrieval/model vars changed) |
| New vector index | `docker compose cp ... worker:/data/indexes/` then `docker compose restart worker` |

Do **not** bind-mount application source into containers for production updates; rebuild images after `git pull`.

---

## 8. Common issues

| Symptom | What to check |
|---------|----------------|
| API cannot connect to MySQL | `MYSQL_HOST` (use `host.docker.internal` for host MySQL, not `127.0.0.1`); security group / `bind-address`; user grants from the Docker bridge network |
| `worker` exits immediately | GPU flagged but no NVIDIA runtime → CPU settings + remove `gpus: all` |
| Retrieval always empty | Index not copied into `/data/indexes`; restart worker after copy |
| Models re-download every time | `models` volume deleted or `HF_HOME` wrong |
| CORS errors in browser | `CORS_ORIGINS` must list the exact origins (scheme + host + port) |
| WhatsApp no reply | `worker_whatsapp` running; webhook URL/token; `DEEPSEEK_*` and `WHATSAPP_*` set |

Useful commands:

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f worker_whatsapp
docker compose ps
```

---

## 9. Security notes

- Keep `deploy/.env` private; never commit it.
- Use a strong `SECRET_KEY` and admin password.
- Prefer HTTPS (reverse proxy / load balancer) in production and update `CORS_ORIGINS` accordingly.
- Application DB user should be least-privilege for day-to-day traffic; catalog Excel import needs write access to the app catalog tables from the API process.
