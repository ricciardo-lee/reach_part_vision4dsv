# 线上 Docker 部署

在已安装 Docker 和 Git 的服务器上运行。MySQL 使用公司现有库，不放进容器。Python 和 npm 依赖只在构建镜像时安装，不要进入容器执行 `pip install` 或 `npm install`。

## 首次启动

```bash
git clone <gitlab-repo-url> reach_part_vision4dsv
cd reach_part_vision4dsv/deploy
cp .env.example .env
# 编辑 .env：SECRET_KEY、MYSQL_*、DEEPSEEK_API_KEY、ADMIN_PASSWORD、CORS_ORIGINS
docker compose up -d --build
```

- H5：`http://服务器:80`
- 桌面 Web：`http://服务器:8081`
- 管理端：`http://服务器:8080`
- 健康检查：`http://服务器/health`
- 就绪检查：`http://服务器/ready`（应能看到 Celery worker）

容器里的 `127.0.0.1` 不是宿主机。MySQL 在本机时，`.env` 里写 `host.docker.internal`。在别的机器上时，写那台机器的局域网地址。

第一次启动 worker 时，若模型卷是空的，会用镜像里的 `huggingface_hub` 下载 `facebook/dinov2-base` 和 `ZhengPeng7/BiRefNet`。服务器需要能访问 Hugging Face。下载完成后权重留在 `models` 卷，之后重建容器不会再下。

向量索引不在 Git 里。首次把本机 `data/indexes/` 拷进卷后再重启 worker：

```bash
docker compose cp ../data/indexes/. worker:/data/indexes/
docker compose restart worker
```

`data/indexes/` 里需要有 `latest_meta.json` 和对应的 `dinov2_*` 目录。

## 更新代码

和其他项目一样，在宿主机拉 GitLab，然后重建镜像。不要把源码目录挂进容器。

```bash
cd reach_part_vision4dsv
git pull
cd deploy
docker compose build
docker compose up -d
```

只改了后端时：

```bash
docker compose build api
docker compose up -d api worker beat
```

`api`、`worker`、`beat` 共用一个后端镜像。只改了前端时：

```bash
docker compose build web
docker compose up -d web
```

`deploy/.env` 不在 Git 里，`git pull` 不会覆盖它。

## 各部分怎么更新

- **依赖：**改 `backend/requirements.txt` 或前端 `package.json` 后，走上面的 `git pull` 和 `docker compose build`。不要进容器补装。
- **环境变量：**改 `deploy/.env` 后执行 `docker compose up -d`。改了检索或模型相关变量时再执行 `docker compose restart worker`。
- **向量索引：**worker 只在进程启动时加载索引。把新的 `dinov2_*` 目录和 `latest_meta.json` 拷进卷后，只重启 worker：

  ```bash
  docker compose cp /path/to/new-index/. worker:/data/indexes/
  docker compose restart worker
  ```

  不要把索引打进镜像，也不要重启 API。
- **模型缓存：**权重在 `models` 卷。重建镜像或容器都会继续用这块卷。更换 `EMBEDDING_MODEL_ID` 或 `SEARCH_MATTING_MODEL_ID` 后重启 worker，启动脚本发现卷里没有对应 `config.json` 时会下载。
- **上传图片：**在 `uploads` 卷。发版和重建容器都不要删除这个卷。过期图片仍由 beat 触发、worker 执行清理。
- **MySQL：**表结构在 API 启动时补齐。发版后 `docker compose up -d api` 即可。不要把数据库放进 Compose。产品、OE 和车型三张表也由这次启动建出空表；随后用海豚调度器的写入账号导入数据。应用账号只保留这三张表的 `SELECT` 权限。`price` 保持源数据单位，不要在导入时换算。

## 显卡

`worker` 已设置 `gpus: all`，API、beat 和网页不使用显卡。RTX 5060 Ti 使用 CUDA 12.8：`TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128`，`SEARCH_SEGMENT_DEVICE=cuda`。改这两项后重建后端镜像并重启 `api`、`worker`、`beat`。没有 NVIDIA runtime 的机器要把 `worker` 的 `gpus: all` 去掉，并把 `SEARCH_SEGMENT_DEVICE` 改回 `cpu`。
