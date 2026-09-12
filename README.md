# 南京租房数据监控平台

基于贝壳平台的南京租房数据自动采集、分析与可视化系统。定时爬取全城在租房源，入库聚合后生成可视化报告页面，并推送行情日报到企业微信。

## 功能概览

- **数据采集**：自动遍历南京 11 个行政区、逐商圈抓取贝壳在租房源（支持人工登录 + 验证码自动识别）
- **数据存储**：全量覆盖写入 MySQL，每次抓取自动落行政区/商圈价格快照
- **可视化报告**：自包含 HTML 报告页（ECharts 图表、城区 Tab 切换、商圈/户型/租赁方式多维筛选、租金分布矩阵、价格趋势走势）
- **行情推送**：企业微信群机器人推送各行政区租金环比日报
- **自动化编排**：一键执行「登录 → 爬取 → 入库 → 生成页面 → 推送 Git → 排程日报」

## 技术栈

| 层级 | 技术 |
|------|------|
| 爬虫 | DrissionPage（浏览器自动化）+ requests（打码接口） |
| 数据库 | MySQL 8 + SQLAlchemy 2.0（async）+ aiomysql |
| Web 服务 | FastAPI + Uvicorn + Jinja2 |
| 前端 | 原生 HTML/CSS/JS + ECharts 5.5 |
| 包管理 | uv + Python 3.13 |

## 项目结构

```
houseprice/
├── src/houseprice/
│   ├── main.py                    # FastAPI 应用入口
│   ├── db_config.py               # 数据库连接与建表
│   ├── getdata/                   # 数据采集层
│   │   ├── spiders/
│   │   │   ├── base.py            # 爬虫公共基类（浏览器、分页、登录墙、去重）
│   │   │   ├── beike.py           # 贝壳租房爬虫
│   │   │   └── wuba.py            # 58同城爬虫（适配中）
│   │   ├── save.py                 # JSON → MySQL 全量覆盖入库 + 快照
│   │   └── output/                # 爬取的 JSON（gitignore）
│   ├── model/                     # ORM 模型
│   │   ├── house.py               # house_listings 房源表
│   │   ├── district_snapshot.py   # district_snapshots 行政区快照
│   │   └── business_district_snapshot.py  # 商圈快照
│   ├── schemas/report.py          # Pydantic 报告数据模型
│   ├── services/
│   │   ├── report_service.py      # 报告聚合统计 + 价格趋势对比
│   │   └── wecom_notify.py        # 企业微信日报推送
│   ├── interfaces/report.py       # FastAPI 路由
│   ├── scripts/
│   │   ├── run_pipeline.py        # 全流程编排脚本
│   │   └── build_static.py        # 生成静态 HTML 报告
│   └── templates/
│       └── report.html            # Jinja2 报告模板
├── docs/index.html                # 生成的静态报告页（GitHub Pages）
├── .env.example                    # 环境变量示例
├── run_pipeline.bat                # Windows 任务计划程序入口
├── wecom_notify.bat                # 日报推送入口
├── pyproject.toml
└── README.md
```

## 快速开始

### 环境要求

- **Python 3.13+**
- **MySQL 8+**（需提前建好数据库）
- **uv**（Python 包管理器，[安装指南](https://docs.astral.sh/uv/getting-started/installation/)）
- **Edge 或 Chrome 浏览器**（爬虫依赖，默认使用 Edge）

### 第一步：克隆并安装依赖

```bash
git clone <仓库地址>
cd houseprice
uv sync
```

### 第二步：配置环境变量

复制示例配置并填写：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# MySQL 连接
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=houseprice

# 企业微信群机器人 webhook（不需要推送可留空）
WECOM_WEBHOOK_URL=

# 贝壳登录页 URL（通常不需要改）
BEIKE_LOGIN_URL=https://clogin.ke.com/login?service=...
```

### 第三步：创建数据库

在 MySQL 中创建数据库（表会自动创建）：

```sql
CREATE DATABASE houseprice CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 第四步：运行

**方式一：完整全流程（爬取 → 入库 → 生成页面 → 推送）**

```bash
uv run python -m houseprice.scripts.run_pipeline --pages 3
```

运行后会弹出浏览器，手动完成贝壳登录，之后自动执行全流程。

**方式二：仅生成报告页（用现有数据库数据）**

```bash
uv run python -m houseprice.scripts.build_static
```

生成的 `docs/index.html` 可直接浏览器打开，或部署到 GitHub Pages。

**方式三：启动 Web 服务（在线报告）**

```bash
uv run uvicorn houseprice.main:app --reload
```

访问 `http://localhost:8000` 查看在线报告。

## 各模块用法

### 爬虫（单独运行）

```bash
# 全城抓取（默认3页/商圈）
uv run python -m houseprice.getdata.spiders.beike --pages 5

# 指定行政区抓取
uv run python -m houseprice.getdata.spiders.beike --district gulou --pages 5

# 指定行政区 + 自动解析商圈逐个抓取
uv run python -m houseprice.getdata.spiders.beike --district gulou --auto-business --pages 3

# 遍历全部行政区 + 自动解析商圈
uv run python -m houseprice.getdata.spiders.beike --all-districts --auto-business --pages 3

# 指定商圈抓取
uv run python -m houseprice.getdata.spiders.beike --business ninghailu huaqiaolu
```

### 入库（单独运行）

```bash
# 处理 output 目录下全部 JSON
uv run python -m houseprice.getdata.save

# 处理指定文件
uv run python -m houseprice.getdata.save --input path/to/file.json
```

### 生成静态报告页

```bash
uv run python -m houseprice.scripts.build_static
```

输出到 `docs/index.html`，自包含（内嵌数据 JSON），可直接部署。

### 企业微信日报推送

```bash
uv run python -m houseprice.services.wecom_notify
```

需要至少两批快照数据（即至少运行过两次入库），否则会跳过推送。

## 自动化部署

### Git 与 GitHub 配置（必须）

`run_pipeline` 会自动 `git commit & push` 更新报告页，需要先完成以下配置：

**1. 在 GitHub 创建仓库并关联远程**

```bash
# 如果是 clone 别人的仓库，改成自己的远程地址
git remote set-url origin git@github.com:你的用户名/houseprice.git

# 如果是新项目，新建仓库后：
git remote add origin git@github.com:你的用户名/houseprice.git
```

**2. 配置 SSH 密钥认证**

```bash
# 生成密钥（已有可跳过）
ssh-keygen -t ed25519 -C "你的邮箱"

# 查看公钥，复制到 GitHub → Settings → SSH and GPG keys → New SSH key
cat ~/.ssh/id_ed25519.pub

# 验证连通
ssh -T git@github.com
```

> 也可用 HTTPS + Personal Access Token，首次 push 时会提示输入。

**3. 启用 GitHub Pages**

1. 在 GitHub 仓库 Settings → Pages
2. Source 选 `main` 分支 `/docs` 目录
3. 保存后等待几分钟，报告页即上线

**4. 在 `.env` 中填写 Pages 地址**

```env
GITHUB_PAGES_URL=https://你的用户名.github.io/houseprice/
```

此地址会嵌入企业微信日报的详情页链接。不填则日报不含链接。

### Windows 任务计划程序

通过 `run_pipeline.bat` 实现无人值守定时执行：

1. 打开「任务计划程序」
2. 创建基本任务 → 触发器选「按计划」（如每月1次）
3. 操作选「启动程序」→ 选择 `run_pipeline.bat`
4. 完成后，任务会自动执行全流程

`run_pipeline.bat` 执行的流程：
1. 弹出浏览器等待人工登录（超时 10 分钟，超时则中止）
2. 遍历南京全部行政区，逐商圈抓取
3. 全量覆盖写入 MySQL + 落区域快照
4. 渲染 `docs/index.html`
5. git commit & push（触发 GitHub Pages 更新）
6. 注册一次性任务，在次日 09:00 推送企业微信日报

> 首次使用前确认 `run_pipeline.bat` 中的 `cd /d` 路径与实际项目路径一致。

## 数据库表结构

### house_listings（房源表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT PK | 自增主键 |
| district | VARCHAR(50) | 行政区 |
| business_district | VARCHAR(50) | 商圈 |
| community_name | VARCHAR(100) | 小区名称 |
| layout | VARCHAR(50) | 户型（如 2室1厅1卫） |
| area | FLOAT | 面积（㎡） |
| monthly_rent | FLOAT | 月租金（元） |
| decoration | VARCHAR(20) | 装修 |
| source_platform | VARCHAR(50) | 来源平台 |
| source_url | VARCHAR(255) UNIQUE | 房源链接（去重依据） |
| first_crawled_at | DATETIME | 首次抓取时间 |
| updated_at | DATETIME | 更新时间 |

### district_snapshots（行政区快照）

每次入库后按行政区聚合写入一行（含"全部"代表全城），用于环比对比。

### business_district_snapshots（商圈快照）

与行政区快照同期写入，按商圈聚合，用于商圈级价格趋势对比。

## 报告页面功能

- **KPI 概览**：房源数量、平均/中位月租金、平均面积（随城区与筛选条件实时联动）
- **城区 Tab 切换**：12 个城区一键切换，筛选器自动填充
- **租金分布矩阵**：8 档租金区间卡片矩阵，高亮峰值档位
- **房源明细表**：支持商圈/户型/租赁方式三维筛选，表头排序，15 条/页分页
- **价格趋势图表**：ECharts 折线图（全城平均租金走势）+ 柱状图（城区涨跌排行）
- **环比对比表**：行政区/商圈两级行情对比（上期 vs 当期）
- **商圈筛选器**：按城区筛选商圈趋势

## 注意事项

- 首次运行需手动登录贝壳，登录态保存在 `.browser_profile/`，之后无需重复登录
- 登录超时会直接中止流程，防止空数据覆盖清空数据库
- 爬虫浏览器默认使用 Edge，如需改用 Chrome，修改 `base.py` 中的 `BROWSER_PATH`
- 验证码自动识别依赖第三方打码服务，未配置时验证码页面会跳过
- 库中只保留最近一次抓取的「当前在租」房源（全量覆盖策略）
- 区域快照每天仅记录一次，多次入库不会重复落快照
