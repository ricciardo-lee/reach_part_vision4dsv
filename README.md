# Reach Part Vision（汽配零件视觉识别服务）

手机浏览器上传零件实拍图 → DeepSeek Vision 识别品类 → 选择车型 / 输入 OE → 返回公司产品信息。

## 目录结构

```text
backend/           FastAPI + Tortoise + Celery + MinIO
frontend-h5/       手机端 H5（Vue3 + Vant）
frontend-admin/    管理后台（Vue3 + Element Plus）
scripts/           本地辅助脚本
```

## 技术栈

- 后端：FastAPI、Pydantic V2、Tortoise ORM、MySQL 8、Redis、Celery、MinIO、OpenAI SDK（DeepSeek 兼容）
- H5：Vue 3、Vite、Pinia、Vue Router、Axios、Vant（移动优先 + Emoji）
- 管理端：Vue 3、Element Plus

## 重要约束

1. **不要使用 Docker**（当前阶段）。
2. MySQL 必须使用独立库 `reach_part_vision4dsv`，禁止连接 MDM 的 `ReachMDM_LMR`。
3. DeepSeek API Key、数据库密码等全部放在 `backend/.env`，不要写入源码。

## 本地准备

### 1. 后端依赖

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：填写 MYSQL_*、REDIS_*、MINIO_*、DEEPSEEK_API_KEY
```

### 2. 创建独立数据库

```bash
cd backend
source .venv/bin/activate
python -m app.scripts.init_db
```

### 3. 初始化 MinIO Bucket

```bash
python -m app.scripts.init_minio
```

### 4. 一键启动（推荐）

自动检查/启动本地 Redis，并后台拉起 API + Celery worker + H5：

```bash
./scripts/start_dev.sh
# 仅后端：
./scripts/start_dev.sh --api-only
# 含管理后台：
./scripts/start_dev.sh --with-admin
# 停止：
./scripts/stop_dev.sh
```

日志目录：`backend/logs/`（`api.log` / `celery.log` / `h5.log`）

也可分开启动：

```bash
./scripts/run_api.sh
./scripts/run_worker.sh
```

健康检查：<http://127.0.0.1:8000/health>  
就绪检查（Redis / Celery）：<http://127.0.0.1:8000/ready>

`start_dev.sh` 会同时启动 **Celery worker + beat**（每日 03:00 清理过期原图）。

### 5. 启动手机 H5

```bash
cd frontend-h5
npm install
npm run dev
```

访问：<http://127.0.0.1:5173>

### 6. 启动管理后台

```bash
cd frontend-admin
npm install
npm run dev
```

访问：<http://127.0.0.1:5174>  
默认账号：`admin` / `Admin@123456`（可在 `.env` 修改）

## DeepSeek Vision

参考脚本：`/Users/litongxue/vehiclePartAI/scripts/deepseek_vision_demo.py`

环境变量：

```env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash-vision-exp
```

请勿在日志中打印完整 API Key。

## MDM 产品接口

默认 `MDM_USE_MOCK=true`。对接真实 Reach MDM 时：

```env
MDM_USE_MOCK=false
MDM_QUERY_BASE_URL=http://<mdm-query-service-host>
MDM_CLIENT_ID=<issued-client-id>
MDM_CLIENT_SECRET=<issued-client-secret>
MDM_QUERY_TIMEOUT_SECONDS=30
MDM_QUERY_MAX_RETRIES=2
MDM_TOKEN_REFRESH_SKEW_SECONDS=30
MDM_VEHICLE_TYPE=passenger
MDM_COUNTRY=            # 可选车型国家筛选
```

适配器通过 `POST /oauth/token` 获取并缓存短期 Bearer Token，随后调用：

- `GET /api/public/v1/vehicles/options`（车型级联）
- `POST /api/public/v1/products/resolve-by-oe`（OE 优先）
- `POST /api/public/v1/cn-vehicle/products/search`（品类 fallback）

第三方应用需具备 `vehicle:read`、`product:read`、`cn_vehicle:read` Scope。客户端会在
Token 临期时主动刷新，并在业务请求收到 401 时强制刷新一次。

## 核心业务 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/public/sessions/device` | 创建设备匿名会话 |
| POST | `/api/v1/public/recognize` | 创建识别会话 |
| POST | `/api/v1/public/recognize/{id}/images` | 上传零件图（可按角度 purpose）或铭牌图 |
| POST | `/api/v1/public/recognize/{id}/start` | 启动视觉识别 |
| POST | `/api/v1/public/recognize/{id}/confirm-category` | 确认品类 |
| POST | `/api/v1/public/recognize/{id}/consent` | 设置优化授权 |
| POST | `/api/v1/public/recognize/{id}/consent/revoke` | 撤回优化授权 |
| POST | `/api/v1/public/recognize/{id}/oe-ocr` | 铭牌 OE 识别 |
| POST | `/api/v1/public/recognize/{id}/oe-confirm` | 确认 OE |
| GET  | `/api/v1/public/recognize/{id}/products` | 查询产品 |
| POST | `/api/v1/admin/auth/login` | 管理端登录 |
| GET  | `/api/v1/admin/stats` | 含 Top-1 / Top-3 / 拒识率 |

## 图片保留策略

- 原图默认保留 **30 天**后由 Celery Beat 清理（物理删除）
- 用于模型优化必须用户显式勾选同意；撤回后不再进入评测导出
- 对象存储使用私有 Bucket + 签名 URL
- 设备级限流依赖 Redis；Redis 不可用时限流 fail-open（仅告警）

## 评测错误样本导出

```bash
cd backend && source .venv/bin/activate
PYTHONPATH=. python ../scripts/export_eval_errors.py -o logs/eval_errors.csv
# 默认仅导出 optimization_consent=true 的会话
```

## 日志

启动后日志会输出到：

- 控制台（uvicorn 终端）
- `backend/logs/app.log`（滚动文件，单文件最大 10MB）

`DEBUG=true` 时为 DEBUG 级别，否则为 INFO。关键链路包含：请求中间件、设备会话、上传、识别、DeepSeek 调用、产品检索与异常。

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## 后续可增强

- 感知哈希结果缓存进一步降本
- 生产反向代理与 HTTPS
- Flower / 任务死信队列可视化
