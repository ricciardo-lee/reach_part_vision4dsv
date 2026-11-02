# Reach Part Vision（汽配零件视觉识别服务）

手机浏览器在同一页上传零件实拍图，并可选填写车型或 OE → 优先 360 图库 SKU 直匹配 → 未命中再 DeepSeek Vision 识别品类 → 用本地产品目录返回公司产品信息。结果页把用户照片和匹配产品的 360 图并排对照。

## 目录结构

```text
backend/           FastAPI + Tortoise + Celery + MinIO
frontend-h5/       手机端 H5（Vue3 + Vant）
frontend-web/      桌面端 Web（Vue3 + Element Plus）
frontend-admin/    管理后台（Vue3 + Element Plus）
scripts/           本地辅助脚本
```

## 技术栈

- 后端：FastAPI、Pydantic V2、Tortoise ORM、MySQL 8、Redis、Celery、MinIO、OpenAI SDK（DeepSeek 兼容）
- H5：Vue 3、Vite、Pinia、Vue Router、Axios、Vant（移动优先 + Emoji）
- 桌面 Web：Vue 3、Vite、Pinia、Vue Router、Axios、Element Plus
- 管理端：Vue 3、Element Plus

## 重要约束

1. **本地开发不用 Docker**。线上部署见 [deploy/README.md](deploy/README.md)；英文 Ubuntu 环境配置见 [deploy/README.en.md](deploy/README.en.md)。
2. MySQL 必须使用独立库 `reach_part_vision4dsv`，禁止连接 MDM 的 `ReachMDM_LMR`。
3. LLM / 数据库密码等全部放在 `backend/.env`，不要写入源码。默认用 **OpenAI**（`DEEPSEEK_*` 变量名兼容，指向 `https://api.openai.com/v1`）；也可改 `BASE_URL`/模型切回 DeepSeek.com（详见 `.env.example`）。

## 本地准备

### 1. 后端依赖

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：填写 MYSQL_*、REDIS_*、DEEPSEEK_API_KEY（本地不必配 MinIO）
```

### 2. 创建独立数据库

```bash
cd backend
source .venv/bin/activate
python -m app.scripts.init_db
```

### 3. 存储

本地默认把上传图写到 `backend/uploads/`，不连接 MinIO。线上把 `APP_ENV=production`（或 `STORAGE_BACKEND=minio`）后再初始化桶：

```bash
python -m app.scripts.init_minio
```

### 4. 一键启动（推荐）

自动检查/启动本地 Redis，并后台拉起 API、Celery worker/beat、手机 H5、桌面 Web 和管理后台。

```bash
./scripts/start_dev.sh
# 仅后端：
./scripts/start_dev.sh --api-only
# 停止：
./scripts/stop_dev.sh
```

日志目录：`backend/logs/`（`api.log` / `celery.log` / `beat.log` / `h5.log` / `web.log` / `admin.log`）

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

### 6. 启动桌面 Web

```bash
cd frontend-web
npm install
npm run dev
```

访问：<http://127.0.0.1:5175>

也可以执行 `./scripts/run_web.sh`。桌面 Web 与手机 H5 使用同一套识别用户账号，不使用管理后台账号。

### 7. 启动管理后台

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

## 本地产品与车型目录

产品、OE、车型与散热器技术参数由本应用自有表维护（管理后台 Excel 导入），**不再依赖海豚调度器同步的 `*_usa` 表**。`material_code` 即 SKU 唯一标识；展示名使用 material_code；品类来自 OE 表 `category`。

| 表 | 主键 / 唯一键 | 用途 |
|----|---------------|------|
| `vision_part_oe` | `(material_code, oe)` | 品类 + 物料 + OE（含 `oe_normalized`） |
| `vision_part_vehicle` | `(material_code, make_name, model_name, year)` | 物料适配车型（品牌/车型/年款） |
| `vision_radiator_spec` | `material_code` unique | 散热器技术参数 |
| `vision_catalog_import_logs` | 自增 id | Excel 导入审计 |

匹配规则：

1. 图库 SKU == `material_code`。没选车型和 OE 时，保持图库 SKU 或品类候选顺序。
2. OE 是强约束（按 `oe_normalized` 查询）。
3. 车型级联为 **品牌 → 车型 → 年款**（无车系）。按已选层级过滤并按适配数量重排。
4. 图库无可靠 SKU 时，按确认品类在 OE 表取 material_code（最多 20 条），再应用车型约束。
5. 产品卡片不显示价格与库存；可附带 `attributes.specs`（散热器技术参数非空字段）。

## 手机 H5

首页一步完成：上传 1–8 张零件照片，可选填品牌、车型、年款，或手工输入 / 铭牌识别 OE，然后点「开始识别」。没有单独的车型/OE 步骤，`/match` 会回到首页。

车型和 OE 两个区域各自有「清空」。清空车型不影响 OE；清空 OE 会清掉输入、铭牌图和识别结果。

识别完成后直接查看产品。SKU 直匹配和品类匹配都不再提供「改用原识别方式」。图库未命中时，识别流程仍会自动回退到品类识别。

## 桌面 Web

`frontend-web` 给普通识别用户使用，业务步骤与手机 H5 相同：登录、上传 1–8 张照片、可选车型或 OE、识别、确认品类、查看产品和反馈。线上由 Nginx 的 `8081` 端口提供，本地开发端口是 `5175`。

桌面页面按宽屏工作台操作：

- 上传页左侧是拖拽区和当前大图，右侧是车型与 OE。授权、进度和主操作在底部操作条。图片支持拖拽、粘贴和多选，单张不超过 10MB。
- 品牌、车系、车型和年款在宽屏同一行，使用与手机 H5 相同的分级目录，可搜索选择。
- 品类页左侧切换原图和去背景图，右侧确认 Top3 或手动品类。
- 产品页左侧是候选列表，右侧是当前产品详情和 360 对照。360 图可以用鼠标拖动、滚轮或方向键旋转。
- 顶栏可以退出登录。确认品类和查看产品只有在本次会话已经得到对应结果时才能进入。刷新后仍需重新开始，当前版本不保存历史记录。

车型、OE、优化授权和反馈规则与手机 H5 相同。

## 核心业务 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/public/auth/login` | 识别用户登录，返回 72 小时 access token |
| GET  | `/api/v1/public/auth/me` | 当前识别用户 |
| POST | `/api/v1/public/recognize` | 创建识别会话 |
| POST | `/api/v1/public/recognize/{id}/images` | 上传零件图（同一产品最多 8 张，`purpose=part`）或铭牌图 |
| POST | `/api/v1/public/recognize/{id}/start` | 启动识别（优先 360 图库 SKU 匹配，未命中再 DeepSeek） |
| POST | `/api/v1/public/recognize/{id}/confirm-category` | 确认品类 |
| POST | `/api/v1/public/recognize/{id}/vehicle` | 保存或清空车型 / OE，可在识别前调用 |
| POST | `/api/v1/public/recognize/{id}/consent` | 设置优化授权 |
| POST | `/api/v1/public/recognize/{id}/consent/revoke` | 撤回优化授权 |
| POST | `/api/v1/public/recognize/{id}/oe-ocr` | 铭牌 OE 识别 |
| POST | `/api/v1/public/recognize/{id}/oe-confirm` | 确认 OE |
| GET  | `/api/v1/public/recognize/{id}/products` | 用本地目录、图库候选和车型/OE 查询产品 |
| GET  | `/api/v1/public/gallery/{sku}/views` | 列出该 SKU 文件夹里的全部 360 图，按文件名排序 |
| GET  | `/api/v1/public/gallery/{sku}/files/{name}` | 读取单张 360 图，需识别用户登录 |
| POST | `/api/v1/admin/auth/login` | 管理端登录 |
| GET  | `/api/v1/admin/stats` | 含 Top-1 / Top-3 / 拒识率 |

## 360 图库 SKU 直匹配

识别启动后优先用 DINOv2 + Qdrant 对 1–8 张同产品多角度图做 SKU 检索：

1. **高置信直匹配**（score ≥ `SEARCH_HIGH_SCORE` 且 Top1–Top2 margin ≥ `SEARCH_MIN_MARGIN`）→ 跳过 DeepSeek，直接返回公司 SKU  
2. **未命中 / 低置信 / 检索不可用** → 自动回退 DeepSeek 品类识别；确认品类后按本地产品目录、车型和 OE 查询  
3. 产品页不再提供「不是这个，改用原方式查询」。图库未命中时由识别流程自动回退 DeepSeek。

### 上传图与 360 图对照

产品页左右并排：左边是用户照片，右边是匹配产品的 360 图。用户照片用箭头切换；360 图按住左右拖动旋转，点图片看大图。有多个候选时，点下方产品切换右侧 360 图。角度按文件名排成一圈，打开时停在检索命中的那一张。

360 原图目录优先用 `PHOTO360_ROOT`。没配时读取索引 `latest_meta.json` 或 `index_meta.json` 里的 `photo360_root`。结构是 `{品类文件夹}/{sku}/{r*.jpg}`。图库 SKU 就是产品文件夹名，对应目录 `material_code`。目录不存在或该 SKU 没有图片时，右侧显示「暂无 360 图」。

### 导入索引到 Qdrant

```bash
# 需本机已启动 Qdrant（默认 http://127.0.0.1:6333）
cd backend && source .venv/bin/activate
PYTHONPATH=. python ../scripts/import_qdrant_index.py \
  --index-dir ../data/indexes/dinov2_20260923T055903Z \
  --qdrant-url http://127.0.0.1:6333
```

索引产物放在项目 `data/indexes/`（已 gitignore）。Worker 默认 `CELERY_WORKER_CONCURRENCY=1`，避免重复加载 DINOv2。

关键环境变量见 `backend/.env.example`（`RETRIEVAL_ENABLED`、`QDRANT_*`、`SEARCH_*`、`PHOTO360_ROOT`）。

就绪探针 `GET /ready` 会额外返回 `retrieval` 状态；检索不可用时整站仍可用，仅降级到原 DeepSeek 流程。

## 图片保留策略

- 原图默认保留 **30 天**后由 Celery Beat 清理（物理删除）
- 用于模型优化必须用户显式勾选同意；撤回后不再进入评测导出
- 对象存储使用私有 Bucket + 签名 URL
- 识别启动按用户限流（默认每分钟 30 次，`RATE_LIMIT_PER_MINUTE`），依赖 Redis；Redis 不可用时限流 fail-open（仅告警）

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

## 三品类约束与目录维护

全链路（识别 / H5 / Web / WhatsApp）仅支持 **Compressor / Condenser / Radiator**（压缩机 / 冷凝器 / 散热器）。其它汽配品类会提示暂不支持；WhatsApp 使用固定英文回复 `WHATSAPP_UNSUPPORTED_CATEGORY_REPLY`。

对外产品接口与客服回复**不返回价格 / 库存 / 可供状态**；WhatsApp 只负责根据用户信息定位 SKU，被问价格或库存时引导联系销售。

车型检索可只凭 brand / model / year 从 `vision_part_vehicle` 出 SKU（不必先有 OE 行）。brand/model 支持大小写、空格、标点的宽松匹配；真正的别名（如「日产」→ Nissan）需要额外别名表，当前未做。

### 后台 Excel 目录（自有表）

| 菜单 | 表 | 能力 |
|------|-----|------|
| OE 零件号 | `vision_part_oe` | 列表 / 模板 / 导入 / 导出（列：category, material_code, OE） |
| 车型 | `vision_part_vehicle` | 同上（列：material_code, make_name, model_name, year） |
| 技术参数 | `vision_radiator_spec` | Radiator 全字段可用；Compressor/Condenser 仍占位（导入 501） |

权限：`catalog:read` / `catalog:write`。API 前缀：`/api/v1/admin/catalog/...`。

WhatsApp 工具 `search_products_by_specs` 在 `category=radiator` 时按 `vision_radiator_spec` 字段过滤。

## WhatsApp 智能客服（Meta Cloud API）

面向海外客户的文字 + 照片客服：用户发 WhatsApp 文本或零件照片 → Meta Cloud API webhook → DeepSeek Chat（function calling）查本地产品/OE/车型目录，或照片走完整识别流水线（DINOv2 SKU 直匹配 → DeepSeek Vision 回退）→ 英文回复。不主动发模板消息；只在 24 小时会话窗口内回复。仅支持压缩机 / 冷凝器 / 散热器；不报价。

### 欢迎卡片与快捷按钮

- 首次联系，或上一会话空闲超过 `WHATSAPP_CONVERSATION_IDLE_HOURS`（默认 24 小时）后新建会话时，自动发送英文欢迎卡片（interactive reply buttons）。
- 三个快捷按钮：`Send a photo` / `Find by OE` / `Search by vehicle`；点击后直接回英文引导文案，不走 LLM。
- 欢迎只发一次（`wa_conversations.welcome_sent_at`）；范围仅覆盖识图、OE、车型匹配产品，不含库存/订单。

### 结果页链接与共享账号（360°）

- 识图成功且有匹配产品 / SKU 时，英文回复末尾追加一条 H5 深链：`{WHATSAPP_H5_BASE_URL}/wa?sid={public_id}`（只需会话 id）。
- 点开后 H5 `/wa` 调用 `POST /api/v1/public/auth/wa-open`，自动以共享 AppUser（默认 `Lee`）登录，再跳到 `/wa/match`（仅匹配结果 + 360°）。
- WhatsApp 识图会话创建时归属到该共享账号；`WHATSAPP_H5_BASE_URL` 为空则不附带链接。
- **推荐本地调试**：`cd frontend-h5 && npm run build:h5`，由 FastAPI 在 `/h5` 提供静态页；`WHATSAPP_H5_BASE_URL` 设为与 webhook 同一 ngrok，例如 `https://<ngrok>/h5`。这样不必再开 Cloudflare 隧道（Vite 开发服经隧道拉模块容易被掐断）。

### Meta 后台配置

1. [Meta for Developers](https://developers.facebook.com/) 创建 App，添加 WhatsApp 产品。
2. WhatsApp → Configuration → Webhook：
   - Callback URL：`https://<公网域名>/sms/whatsapp/<WHATSAPP_WEBHOOK_PATH_TOKEN>`
   - Verify token：与 `WHATSAPP_VERIFY_TOKEN` 一致（默认 `reach-use`）
   - 订阅字段：`messages`
3. API Setup / System User：获取永久 `ACCESS_TOKEN`、`PHONE_NUMBER_ID`；App Settings → Basic 复制 `App Secret`。
4. 测试号需把收件人手机加入允许列表。

### 本地用 ngrok 调试

公网服务器暂时无法更新代码时，可用 ngrok 把本机 8000 暴露给 Meta：

```bash
# 终端 1：启动本服务
./scripts/start_dev.sh --api-only

# 终端 2：隧道
ngrok http 8000
```

Callback URL 示例：

```text
https://fragile-strung-gully.ngrok-free.dev/sms/whatsapp/3ffcb52b3d3140c6933dde80b43cafa8
```

Verify token：`reach-use`。调试面板：<http://127.0.0.1:4040>。免费 ngrok 域名重启后会变，需回 Meta 重新 Verify。

### 环境变量（`backend/.env`）

```env
WHATSAPP_ENABLED=true
WHATSAPP_WEBHOOK_PATH_TOKEN=3ffcb52b3d3140c6933dde80b43cafa8
WHATSAPP_VERIFY_TOKEN=reach-use
WHATSAPP_APP_SECRET=your-app-secret
WHATSAPP_ACCESS_TOKEN=your-access-token
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
WHATSAPP_GRAPH_API_VERSION=v21.0
WHATSAPP_IMAGE_DEBOUNCE_SECONDS=15
WHATSAPP_IMAGE_SESSION_TTL_MINUTES=10
WHATSAPP_RECOGNITION_TIMEOUT_SECONDS=90
WHATSAPP_H5_BASE_URL=https://your-h5.example.com
WHATSAPP_SHARED_APP_USER_USERNAME=Lee
WHATSAPP_SHARED_APP_USER_PASSWORD=123456
WHATSAPP_LINK_TOKEN_TTL_HOURS=72
DEEPSEEK_CHAT_MODEL=deepseek-chat
DEEPSEEK_CHAT_MAX_TOOL_ROUNDS=4
```

Webhook 路由挂在 API 根路径（不经 `/api/v1`）：`GET/POST /sms/whatsapp/{token}`。线上由 `pbx-reach.nsvoip.net:5001` 网关转发到本服务。

消息处理走独立 Celery 队列 `whatsapp`（`celery_whatsapp` worker），避免排在 DINOv2 识别 worker 后面。管理后台「WhatsApp 对话」可查看会话与工具调用；system prompt 在 Prompt 管理里 `purpose=whatsapp_chat`（默认全英文）。

### 照片识别

- 收到 image 消息后立即下载媒体（Meta 媒体 URL 约 5 分钟过期），压缩后写入与 H5 相同的 `UploadedImage` / `RecognitionSession`。
- 同一用户在 `WHATSAPP_IMAGE_DEBOUNCE_SECONDS`（默认 15 秒）内连续发的照片（最多 8 张）聚合为同一识别会话，只触发一次识别、只回复一次。
- 聚合结束后投递默认识别队列（`recognition.run_vision`）：DINOv2 + Qdrant SKU 直匹配 → 未命中再 DeepSeek Vision；随后本地目录出产品，DeepSeek Chat 生成英文回复；有产品时追加 H5 360° 结果页链接（见上节）。
- 识别 worker 不在线时返回英文提示，不在 WhatsApp worker 内联加载 DINOv2。轮询超时默认 90 秒。
- 上传图仍按 `IMAGE_RETENTION_DAYS`（默认 30 天）清理。管理后台气泡可跳到对应识别会话详情。

发给用户的全部文案为英文（prompt、工具 schema、兜底回复、品类名）。目录检索优先返回 `standard_label_en`。

## 后续可增强

- 人工接管与文档知识库（RAG）
- 感知哈希结果缓存进一步降本
- 生产反向代理与 HTTPS
- Flower / 任务死信队列可视化
