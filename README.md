# gdou_aichat_rag

## 目录

- [项目简介](#项目简介)
- [当前能力](#当前能力)
- [技术栈](#技术栈)
- [项目目录结构](#项目目录结构)
- [核心架构](#核心架构)
- [配置说明](#配置说明)
- [本地开发运行](#本地开发运行)
- [Docker 部署](#docker-部署)
- [Ubuntu 22.04 + 1Panel 部署](#ubuntu-2204--1panel-部署)
- [后台控制台使用说明](#后台控制台使用说明)
- [网页对话测试](#网页对话测试)
- [外部接口说明](#外部接口说明)
- [RAG 数据库目录说明](#rag-数据库目录说明)
- [维护注意事项](#维护注意事项)

## 项目简介

`gdou_aichat_rag` 是一个基于 Django 的 RAG 问答系统。系统支持通过后台 Web 控制台管理多个独立 RAG 数据库，并对外保持单一聊天接口。

当前版本的核心目标：

```text
后台管理多个 RAG 数据库
        ↓
后台选择当前启用数据库
        ↓
外部始终调用同一个 /myapp/chat 接口
        ↓
系统使用当前启用数据库完成 RAG 问答
```

保留原有网页对话测试页面：

```text
/myapp/chat_view
```

该页面用于测试后台当前启用的 RAG 数据库。

## 当前能力

- 后台 Web 控制台：`/myapp/console/`
- 多个独立 RAG 数据库管理
- 新增 RAG 数据库
- 向已有 RAG 数据库上传 PDF/TXT 数据
- 删除非当前 RAG 数据库
- 设置当前外部接口使用的 RAG 数据库
- 设置大语言模型 API 地址和 API Key
- 设置 DashScope API Key
- 保留单一外部问答接口：`POST /myapp/chat`
- 保留网页对话测试页面：`GET /myapp/chat_view`
- 上传文档统一通过后台控制台完成，不再公开未鉴权上传接口

当前不包含：

- 面向终端用户的业务用户体系
- 多后台账号管理
- Web 中修改后台账号密码
- 流式输出
- 文档级删除
- 前端工程化构建
- 多模型供应商动态切换

## 技术栈

- Python 3.11
- Django 4.1.13
- LangChain 0.3.x
- Chroma / langchain-chroma
- DashScope Embedding：`text-embedding-v4`
- DashScope Rerank：`qwen3-rerank`
- DeepSeek Chat：`deepseek-chat`
- MinerU：PDF 解析
- jieba + rank_bm25：中文 BM25 检索
- SQLite：Django 后台配置与元数据存储

## 项目目录结构

```text
app/
├── manage.py
├── api_r.py                         # 统一 JSON 响应封装
├── Dockerfile
├── requirements.txt
├── server/
│   ├── settings.py                   # Django 配置、后台账号、多库根目录
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── myapp/
│   ├── apps.py
│   ├── config.py                     # RAG 参数、上传限制、Prompt、固定模型常量
│   ├── document_parser.py            # PDF/TXT 内容解析
│   ├── storage.py                    # 上传校验与保存
│   ├── models.py                     # RAG 数据库、运行配置、文档记录模型
│   ├── rag.py                        # SchoolRAG 与 RAGManager
│   ├── views.py                      # 前台接口与后台控制台视图
│   ├── urls.py                       # 前台与后台路由
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py
│   └── templates/
│       ├── chat.html                 # 网页对话测试
│       ├── upload.html               # 历史上传模板，当前未公开路由，上传以后台控制台为准
│       ├── console_login.html        # 后台登录页
│       └── console_dashboard.html    # 后台控制台
├── chroma_db/                        # 兼容原始版本的默认 Chroma 目录
├── bm25/                             # 兼容原始版本的默认 BM25 目录
├── uploads/                          # 兼容原始版本的默认上传目录
├── mineru_output/                    # 兼容原始版本的默认 MinerU 输出目录
└── rag_databases/                    # 新增 RAG 数据库默认根目录
    └── <slug>/
        ├── chroma_db/
        ├── bm25/
        ├── uploads/
        └── mineru_output/
```

## 核心架构

### 文档入库链路

```text
后台选择目标 RAG 数据库
        ↓
上传 PDF/TXT
        ↓
保存到该数据库 uploads/
        ↓
PDF 使用 MinerU 转 Markdown；TXT 直接读取
        ↓
MarkdownHeaderTextSplitter 按标题切分
        ↓
写入该数据库 Chroma
        ↓
写入该数据库 bm25/docs.json
        ↓
重建该数据库 Retriever
```

### 问答链路

```text
外部调用 /myapp/chat
        ↓
RAGManager 读取当前启用数据库
        ↓
加载或复用对应 SchoolRAG 实例
        ↓
Chroma similarity k=10
        +
BM25 k=10
        ↓
EnsembleRetriever weights=[0.5, 0.5]
        ↓
DashScope Rerank qwen3-rerank top_n=3
        ↓
Prompt 拼接上下文
        ↓
DeepSeek deepseek-chat 生成回答
```

## 配置说明

主要配置位于：

```text
app/server/settings.py
```

### 后台账号密码

后台账号密码不在 Web 中修改，需要通过配置文件或环境变量设置：

```python
RAG_ADMIN_USERNAME = os.environ.get('RAG_ADMIN_USERNAME', 'admin')
RAG_ADMIN_PASSWORD = os.environ.get('RAG_ADMIN_PASSWORD', '')
```

生产部署时必须设置 `RAG_ADMIN_PASSWORD`，否则后台无法正常登录。

### 多数据库根目录

```python
RAG_DATABASE_ROOT = os.path.join(BASE_DIR, 'rag_databases')
```

新增 RAG 数据库时会在该目录下生成独立目录。

### 默认兼容目录

首次迁移会创建一个默认 RAG 数据库，指向原始版本目录：

```python
RAG_PERSIST_DIRECTORY = os.path.join(BASE_DIR, 'chroma_db')
UPLOAD_DIRECTORY = os.path.join(BASE_DIR, 'uploads')
MINERU_OUTPUT_DIRECTORY = os.path.join(BASE_DIR, 'mineru_output')
BM25_PERSIST_DIRECTORY = os.path.join(BASE_DIR, 'bm25')
```

### 模型 API 配置

后台控制台中可配置：

- 大语言模型 API 地址
- 大语言模型 API Key
- DashScope API Key

固定不可在后台修改：

- Embedding 模型：`text-embedding-v4`
- Rerank 模型：`qwen3-rerank`
- 默认 LLM 类：`ChatDeepSeek`
- 默认 LLM 模型：`deepseek-chat`

## 本地开发运行

进入应用目录：

```bash
cd app
```

安装依赖：

```bash
pip install -r requirements.txt
```

初始化 Django 数据库：

```bash
python manage.py migrate
```

启动开发服务器：

```bash
python manage.py runserver 0.0.0.0:8000
```

访问：

- 后台控制台：`http://localhost:8000/myapp/console/`
- 网页对话测试：`http://localhost:8000/myapp/chat_view`

如果后台密码使用环境变量：

```bash
export RAG_ADMIN_USERNAME=admin
export RAG_ADMIN_PASSWORD='your-password'
python manage.py runserver 0.0.0.0:8000
```

## Docker 部署

Dockerfile 位于：

```text
app/Dockerfile
```

构建镜像：

```bash
cd app
docker build -t gdou-aichat-rag .
```

运行容器：

```bash
cd app
mkdir -p data chroma_db bm25 uploads mineru_output rag_databases

docker run -d \
  --name gdou-aichat-rag \
  -p 8000:8000 \
  -e RAG_ADMIN_USERNAME=admin \
  -e RAG_ADMIN_PASSWORD='your-password' \
  -e SQLITE_NAME=/app/data/db.sqlite3 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/chroma_db:/app/chroma_db \
  -v $(pwd)/bm25:/app/bm25 \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/mineru_output:/app/mineru_output \
  -v $(pwd)/rag_databases:/app/rag_databases \
  gdou-aichat-rag
```

如果希望把 SQLite 文件放在持久化目录中，可以通过环境变量指定：

```bash
-e SQLITE_NAME=/app/data/db.sqlite3
```

不要在宿主机不存在 `db.sqlite3` 文件时直接把文件挂载到 `/app/db.sqlite3`，否则 Docker 可能创建同名目录导致 SQLite 打开失败。

首次运行前需要执行迁移。可以进入容器执行：

```bash
docker exec -it gdou-aichat-rag python manage.py migrate
```

也可以在部署命令中覆盖启动命令，让容器启动前自动迁移。下面示例保留同样的持久化挂载：

```bash
docker run -d \
  --name gdou-aichat-rag \
  -p 8000:8000 \
  -e RAG_ADMIN_USERNAME=admin \
  -e RAG_ADMIN_PASSWORD='your-password' \
  -e SQLITE_NAME=/app/data/db.sqlite3 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/chroma_db:/app/chroma_db \
  -v $(pwd)/bm25:/app/bm25 \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/mineru_output:/app/mineru_output \
  -v $(pwd)/rag_databases:/app/rag_databases \
  gdou-aichat-rag \
  sh -c "python manage.py migrate && gunicorn --bind 0.0.0.0:8000 --timeout 300 server.wsgi:application"
```

生产部署建议挂载持久化目录，至少包括：

- `/app/data/db.sqlite3`，需设置 `SQLITE_NAME=/app/data/db.sqlite3`
- `/app/chroma_db`
- `/app/bm25`
- `/app/uploads`
- `/app/mineru_output`
- `/app/rag_databases`

## Ubuntu 22.04 + 1Panel 部署

以下步骤面向 Ubuntu 22.04 服务器，并使用 1Panel 面板部署。

### 1. 准备服务器

建议配置：

- Ubuntu 22.04 LTS
- 2 核 CPU 以上
- 4GB 内存以上，PDF 解析较多时建议 8GB+
- 磁盘空间根据上传文档和向量库规模预留

更新系统：

```bash
sudo apt update
sudo apt upgrade -y
```

### 2. 安装 1Panel

在服务器执行 1Panel 官方安装脚本。请以 1Panel 官方文档为准，通常类似：

```bash
curl -sSL https://resource.fit2cloud.com/1panel/package/v2/quick_start.sh -o quick_start.sh
sudo bash quick_start.sh
```

安装完成后登录 1Panel 面板。

### 3. 在 1Panel 安装运行环境

在 1Panel 中确认安装：

- Docker
- Docker Compose
- OpenResty / Nginx，若需要域名反向代理

### 4. 上传项目代码

推荐目录：

```text
/opt/gdou_aichat_rag
```

可以通过以下方式之一上传：

- 1Panel 文件管理上传压缩包后解压；
- 使用 Git 拉取；
- 使用 SFTP 上传。

项目结构应类似：

```text
/opt/gdou_aichat_rag/
├── README.md
└── app/
    ├── Dockerfile
    ├── manage.py
    └── ...
```

### 5. 准备持久化目录

在服务器上创建目录：

```bash
cd /opt/gdou_aichat_rag/app
mkdir -p data chroma_db bm25 uploads mineru_output rag_databases
```

如果已有原始版本数据，将原来的 `chroma_db`、`bm25`、`uploads`、`mineru_output` 放到 `app/` 下对应目录。

### 6. 使用 1Panel 创建容器应用

在 1Panel 中选择：

```text
容器 -> 编排/Compose -> 创建编排
```

可使用如下 `docker-compose.yml`：

```yaml
version: "3.8"

services:
  gdou-aichat-rag:
    build:
      context: /opt/gdou_aichat_rag/app
      dockerfile: Dockerfile
    container_name: gdou-aichat-rag
    restart: always
    ports:
      - "8000:8000"
    environment:
      RAG_ADMIN_USERNAME: "admin"
      RAG_ADMIN_PASSWORD: "请修改为强密码"
      SQLITE_NAME: "/app/data/db.sqlite3"
    volumes:
      - /opt/gdou_aichat_rag/app/data:/app/data
      - /opt/gdou_aichat_rag/app/chroma_db:/app/chroma_db
      - /opt/gdou_aichat_rag/app/bm25:/app/bm25
      - /opt/gdou_aichat_rag/app/uploads:/app/uploads
      - /opt/gdou_aichat_rag/app/mineru_output:/app/mineru_output
      - /opt/gdou_aichat_rag/app/rag_databases:/app/rag_databases
    command: >
      sh -c "python manage.py migrate && gunicorn --bind 0.0.0.0:8000 --timeout 300 server.wsgi:application"
```

保存并启动编排。

> 注意：`RAG_ADMIN_PASSWORD` 必须修改为强密码。

### 7. 配置反向代理，绑定域名

如果需要通过域名访问，可在 1Panel 网站/OpenResty 中创建反向代理：

- 域名：例如 `rag.example.com`
- 代理地址：`http://127.0.0.1:8000`

常见 Nginx 配置示例：

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
}
```

PDF 解析和入库可能耗时较长，建议代理超时时间不低于 300 秒。

### 8. 访问后台

访问：

```text
http://服务器IP:8000/myapp/console/
```

或域名：

```text
https://rag.example.com/myapp/console/
```

使用 `RAG_ADMIN_USERNAME` 和 `RAG_ADMIN_PASSWORD` 登录。

### 9. 首次后台配置

登录后台后：

1. 在“模型API配置”中填写大语言模型 API 地址。
   - DeepSeek 默认：`https://api.deepseek.com`
2. 填写大语言模型 API Key。
3. 填写 DashScope API Key。
4. 保存配置。
5. 如已有默认知识库，可直接打开 `/myapp/chat_view` 测试。
6. 如需新知识库，先创建数据库，再上传文档，最后设为当前数据库。

## 后台控制台使用说明

后台地址：

```text
/myapp/console/
```

### 登录

账号密码来自配置：

```text
RAG_ADMIN_USERNAME
RAG_ADMIN_PASSWORD
```

### 新增 RAG 数据库

在“新增RAG数据库”区域填写：

- 数据库名称
- 数据库标识 slug
- 描述

slug 只能包含：

```text
字母、数字、下划线、短横线
```

创建后会生成独立目录。

### 上传数据到数据库

上传入口只在后台控制台中提供，旧的 `/myapp/upload` 与 `/myapp/upload_view` 不再作为公开路由使用。

在“RAG数据库列表”中，每个数据库都有上传入口。

支持：

- `.pdf`
- `.txt`

限制：

- 最大 10MB

上传成功后，系统会将数据写入该数据库对应的 Chroma 和 BM25。

### 设置当前数据库

点击“设为当前”，即可让外部接口 `/myapp/chat` 和测试页面 `/myapp/chat_view` 使用该数据库。

### 删除数据库

可以删除非当前数据库。

当前限制：

- 不能删除当前正在使用的数据库；
- 不能删除最后一个数据库；
- 不能删除默认兼容数据库 `default`。

### 设置 API

后台可设置：

- 大语言模型 API 地址
- 大语言模型 API Key
- DashScope API Key

Key 输入框留空表示保持原值不变。

## 网页对话测试

访问：

```text
/myapp/chat_view
```

该页面仍然调用：

```text
POST /myapp/chat
```

测试对象是后台当前启用的 RAG 数据库。

## 外部接口说明

### 聊天接口

```http
POST /myapp/chat
Content-Type: application/json
```

请求体：

```json
{
  "question": "中华白海豚是什么？"
}
```

成功响应：

```json
{
  "code": 0,
  "msg": "对话成功",
  "data": "..."
}
```

外部调用方不需要传数据库 ID。系统会自动使用后台当前启用的 RAG 数据库。

## RAG 数据库目录说明

默认兼容库继续使用原始目录：

```text
app/chroma_db
app/bm25
app/uploads
app/mineru_output
```

后台新增数据库使用：

```text
app/rag_databases/<slug>/chroma_db
app/rag_databases/<slug>/bm25
app/rag_databases/<slug>/uploads
app/rag_databases/<slug>/mineru_output
```

其中：

- `chroma_db`：Chroma 向量库
- `bm25/docs.json`：BM25 文档索引
- `uploads`：上传原始文件
- `mineru_output`：PDF 解析生成的 Markdown 和资源

## 维护注意事项

- `db.sqlite3` 保存后台配置、当前数据库、API key 和文档记录，生产环境应限制文件权限并做好备份。
- DashScope API Key 同时用于 Embedding 和 Rerank。
- Embedding 模型固定为 `text-embedding-v4`，不要直接修改，否则可能影响已有 Chroma 数据兼容性。
- 删除数据库会删除其物理目录；当前数据库、最后一个数据库和默认兼容数据库不允许删除。
- PDF 解析和入库可能耗时较长，反向代理和 Gunicorn timeout 建议不少于 300 秒。
- 当前后台为轻量 session 登录，不提供 Web 修改后台密码功能。
- 若 DeepSeek 或 DashScope API Key 未配置，聊天或入库链路会因外部服务不可用而失败。
- 不要将包含 API key 的 `db.sqlite3` 提交到代码仓库。
