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

1. **本地开发不用 Docker**。线上部署见 [deploy/README.md](deploy/README.md)。
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

产品、OE 号和车型不再调用 mdm-query。数据放在本服务自己的 MySQL 库中，由海豚调度器写入；识图服务只读取这三张表，不提供目录维护接口。

应用账号对以下表只授予 `SELECT`。海豚使用单独的写入账号，可以用 `TRUNCATE` 后全量导入，或按唯一键做 `INSERT ... ON DUPLICATE KEY UPDATE`。`price` 按源数据原值保存和返回，服务不做分/元换算。

API 首次启动会建出空表。海豚不要再用全 `LONGTEXT`、无主键的旧 DDL 覆盖它们。

| 表 | 主键 / 唯一键 | 用途 |
|----|---------------|------|
| `product_basic_info_usa` | `material_code`，`short_num` 有索引 | 物料名称与价格。图库 SKU 对应 `short_num` |
| `vehicle_basic_info_usa` | `reach_car_id` | 品牌、车系、车型、年款级联 |
| `product_oe_vehicle_usa` | 自增 `id`，唯一键 `(material_code, ref_num, reach_car_id)` | OE 与车型适配关系 |

字段使用可索引的 `VARCHAR`：物料号 64、OE 号 128、车型 ID 64，品牌/车系/车型 128，标准名称 1024。三张表都没有业务外键和时间戳，避免全量换表时互相阻塞。

匹配规则：

1. 图库 SKU 对应 `product_basic_info_usa.short_num`。没选车型和 OE 时，保持图库 SKU 或品类候选的原顺序，并用产品表补名称和价格。OE、车型适配仍按 `material_code` 关联。
2. OE 是强约束。优先返回它和图片候选的交集；没有交集时返回该 OE 直接关联的产品。
3. 车型按已选层级过滤并按适配车型数量重排。和图片候选没有交集时返回空结果。
4. 两者都选时，先按 OE 限定，再用车型过滤。
5. 图库没有可靠 SKU 时，用品类名匹配 `standard_label_cn/en`（最多 20 条），再应用车型约束。
6. 产品卡片不显示库存。零件号只显示一个：用零件号搜索时显示所搜的 `ref_num`；否则显示适配到的第一个 `ref_num`。选了车型时只取适配该车型的零件号。

## 手机 H5

首页一步完成：上传 1–8 张零件照片，可选填品牌、车系、车型、年款，或手工输入 / 铭牌识别 OE，然后点「开始识别」。没有单独的车型/OE 步骤，`/match` 会回到首页。

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

360 原图目录优先用 `PHOTO360_ROOT`。没配时读取索引 `latest_meta.json` 或 `index_meta.json` 里的 `photo360_root`。结构是 `{品类文件夹}/{sku}/{r*.jpg}`。图库 SKU 就是产品文件夹名，对应 `short_num`。目录不存在或该 SKU 没有图片时，右侧显示「暂无 360 图」。

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

## 后续可增强

- 感知哈希结果缓存进一步降本
- 生产反向代理与 HTTPS
- Flower / 任务死信队列可视化
