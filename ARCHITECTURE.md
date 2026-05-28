# GCAgents — 全自动 AI 游戏公司架构文档

## 概述

GCAgents 是一个完全自主运行的 AI 游戏公司系统。它像一家真实的游戏公司一样运作：研究市场趋势 → 评估机会 → 设计方案 → 开发代码 → 质量测试 → 构建发布 → 部署上线。整个过程**零人工干预**，所有决策和产出均由 AI Agent 驱动。

**核心理念**：用 AI Agent 模拟游戏公司组织架构，每一个员工角色对应一个 Agent 节点，通过 LangGraph 状态机编排协作流程。

---

## 系统架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                         GCAgents System                              │
│                                                                      │
│  ┌─────────────┐     ┌─────────────────────────────────────────┐    │
│  │   CLI / API  │────▶│         LangGraph State Machine          │    │
│  │  (入口)      │     │  ┌──────┐  ┌────────┐  ┌───────────┐    │    │
│  └─────────────┘     │  │ Scan │─▶│Evaluate│─▶│  Design   │    │    │
│                      │  └──────┘  └────────┘  └─────┬─────┘    │    │
│  ┌─────────────┐     │         ┌────────┐          │          │    │
│  │  Dashboard   │────▶│  ◀─────│   QA   │◀─────┐   │          │    │
│  │  (FastAPI +  │     │  │     └────────┘      │   ▼          │    │
│  │   HTML/CSS)  │     │  │     ┌──────────┐    │ ┌────────┐   │    │
│  └─────────────┘     │  │     │  Build   │    │ │  Art   │   │    │
│                      │  │     └────┬─────┘    │ └────┬───┘   │    │
│  ┌─────────────┐     │  │          ▼          │     │       │    │
│  │   SQLite DB  │◀────│  │     ┌──────────┐    │     │       │    │
│  │  (持久化)    │     │  │     │  Deploy  │    │     │       │    │
│  └─────────────┘     │  │     └──────────┘    │     │       │    │
│                      │  └──────────────────────┼─────┘       │    │
│                      │                         ▼             │    │
│                      │                    ┌──────────┐       │    │
│                      │                    │ Develop  │◀──────┘    │
│                      │                    └──────────┘           │
│                      └─────────────────────────────────────────┘    │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │                      AI Models                              │     │
│  │  ┌───────────┐  ┌───────────┐  ┌───────────────────────┐   │     │
│  │  │ glm-4-flash│  │deepseek-  │  │  Phaser 4 + Vite     │   │     │
│  │  │(免费·分析) │  │coder      │  │  (游戏运行时)        │   │     │
│  │  └───────────┘  │(代码生成)  │  └───────────────────────┘   │     │
│  │                 └───────────┘                                │     │
│  └────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 编排引擎 | **LangGraph** (Python) | 状态机构建、节点路由、条件跳转 |
| AI 分析 | **glm-4-flash** (智谱免费) | 市场分析、游戏设计、评估决策 |
| AI 代码 | **deepseek-coder** | 生成 Phaser 4 + TypeScript 游戏源码 |
| 游戏运行 | **Phaser 4 + TypeScript + Vite** | 生成 Web 小游戏 |
| 监控面板 | **FastAPI + 原生 HTML/CSS/JS** | 实时查看公司运营状态 |
| 持久化 | **SQLite + SQLAlchemy (async)** | Agent 日志、市场信号、项目数据 |
| 部署 | **Butler CLI** | 推送到 itch.io |

---

## AI 模型策略

出于**成本优化**考虑，系统对不同任务使用不同的 AI 模型：

```
                ┌──────────────────┐
                │   市场扫描       │ ← glm-4-flash (免费)
                ├──────────────────┤
                │   CEO 评估       │ ← glm-4-flash (免费)
                ├──────────────────┤
                │   GDD 设计       │ ← glm-4-flash (免费)
                ├──────────────────┤
                │   代码生成       │ ← deepseek-coder (付费)
                ├──────────────────┤
                │   QA 分析        │ ← glm-4-flash (免费)
                └──────────────────┘
```

**关键决策**：分析/设计类任务使用免费模型（文字理解即可），只有代码生成使用付费模型。在 `config/agents.yaml` 中按 role 配置模型映射。

---

## 核心工作流 — LangGraph 状态机

系统以 `CompanyState` 作为全局状态，通过 LangGraph 的 `StateGraph` 编排节点。

### 状态定义 (`orchestrator/state.py`)

```python
class CompanyState(BaseModel):
    phase: PipelinePhase           # 当前阶段
    market_insights: list[dict]    # 市场分析结果
    current_proposal: GameProposal # CEO 选中的项目提案
    gdd: dict | None               # 游戏设计文档
    game_code_path: str | None     # 生成的游戏代码路径
    build_path: str | None         # 构建输出路径
    itch_url: str | None           # 部署 URL
    qa_results: dict | None        # QA 测试结果
    errors: list[str]              # 错误列表
    retry_count: int               # 重试计数
```

### 工作流图 (`orchestrator/graph/pipeline.py`)

```
扫描 ──▶ 评估 ──▶ 设计 ──▶ 美术 ──▶ 开发 ──▶ QA ──▶ 构建 ──▶ 部署 ──▶ 完成
                                  ▲         │
                                  │         │ (失败且<3次)
                                  └─────────┘
```

**关键路由逻辑**：

- **评估后**：如果分数 ≥ 0.6 且 genre 未重复 → 进入设计；否则重新扫描或等待
- **QA 后**：如果通过 → 构建；如果失败且重试 < 3 次 → 回开发修复；否则终止
- **Agent 日志包装器**：`_logged_node()` 自动记录每个节点的起止时间、耗时、状态到数据库

### 执行入口 (`orchestrator/main.py`)

```bash
python3 -m orchestrator.main run    # 完整运行一个周期
python3 -m orchestrator.main scan   # 仅执行市场扫描
```

---

## Agent 节点详解

### 1. 市场扫描器 (`agents/research/scanner.py`)

从多个数据源采集游戏市场信号：

```
数据源:
├── itch.io RSS feeds    — 最新热门游戏趋势
├── Reddit (gamedev, webgames, casual) — 社区讨论热度
├── StatKraken API       — 平台排行榜数据 (当前不可用)
├── Google Play          — 移动端趋势 (依赖 google_play_scraper)
└── App Store            — iOS 趋势
```

**数据流**：原始信号 → `analyze_signals()` 调用 glm-4-flash 分析 → 输出 `market_insights`（含评分、genre、差异化建议）

### 2. CEO (`orchestrator/nodes/ceo.py`)

模拟 CEO 决策角色：

- 读取 `market_insights`，按 `market_opportunity_score` 排序
- 通过 `_get_completed_genres()` 查询数据库已做过的 genre，避免重复
- 评分 > 0.6 则生成 `GameProposal` 并进入设计阶段
- 评分不足则继续扫描或进入休眠

### 3. 游戏设计师 (`agents/dev/designer/`)

接收 GDD 生成任务，调用 glm-4-flash 生成结构化的游戏设计文档：

- 游戏标题、类型、核心玩法
- 场景列表（Boot → Menu → Game → GameOver）
- 游戏机制和控制系统
- 参考游戏和差异化定位

### 4. 美术师 (`agents/dev/artist/`)

**设计意图**：连接 ComfyUI（Stable Diffusion）生成像素艺术资产。

**现实情况**：本地 ComfyUI 未部署，自动降级为 Phaser 内置形状渲染（矩形、圆形、多边形），不需要外部资源文件。

### 5. 程序员 (`agents/dev/programmer/`)

调用 **deepseek-coder** 生成完整的 Phaser 4 + TypeScript 游戏代码：

```
generate_game_code(gdd, project_dir, config, build_error="")
```

- 接收 GDD，用 Jinja2 模板 + AI 生成完整游戏源码
- 强制约束：`import * as Phaser from 'phaser'`（Phaser 4 ESM 无默认导出）
- **构建重试机制**：如果 `build_error` 参数非空，自动将错误信息追加到 AI prompt 中，让 AI 修复后重新生成
- 生成后自动执行 `npm install && npm run build`
- 使用 `project-dir-timestamp` 模式避免目录冲突

### 6. QA 测试员 (`agents/dev/qa/`)

- 检查构建产物是否存在
- 如需构建则执行构建并捕获 stderr
- 失败时返回 `retry_count+1` 和错误详情
- 构建错误会通过 LangGraph 状态传递回 Developer，实现**错误反馈闭环**

### 7. 构建打包 (`agents/dev/builder/`)

- 执行 `vite build` 生成 `dist/` 目录
- 输出 HTML5 游戏包（单页应用）

### 8. 部署 (`agents/ops/deployer/itch_deployer.py`)

通过 Butler CLI 将游戏推送到 **itch.io**：

- 使用 `BUTLER_API_KEY` 环境变量认证（无需交互式登录）
- 推送到 `{username}/{project_name}:html` 频道
- 注意：游戏页面需预先在 itch.io 手动创建

---

## 数据持久化

系统使用 **SQLite** 数据库存储所有运营数据（路径：`data/gcagents.db`）。

### 表结构

| 表 | 用途 | 关键字段 |
|---|---|---|
| `agent_logs` | 每个 Agent 节点的执行日志 | node_name, status, duration_ms, error |
| `orchestrator_state` | 管道状态快照 | phase, errors, updated_at |
| `game_projects` | 游戏项目记录 | name, genre, status, gdd, itch_url |
| `market_signals` | 原始市场信号 | source, genre, title, score, captured_at |
| `market_reports` | AI 市场分析报告 | signals_count, opportunities_json, raw_analysis |
| `company_memory` | 公司长期记忆 | category, title, content, importance |

### 写入时机

| 事件 | 写入内容 |
|---|---|
| 每个节点执行完成 | `agent_logs` 写入耗时 + 状态 |
| 市场扫描完成 | `market_signals` + `market_reports` |
| 管道阶段变更 | `orchestrator_state` + `game_projects` |
| CEO 决策 | `game_projects`（更新状态） |

---

## Dashboard 监控

Dashboard 运行在独立进程（FastAPI + 静态 HTML/CSS/JS），与管道解耦。

### API 端点

| 路径 | 方法 | 用途 |
|---|---|---|
| `/api/status` | GET | 当前状态、阶段、活跃项目 |
| `/api/agents` | GET | 各 Agent 执行统计 |
| `/api/pipeline/run` | POST | 触发管道运行 |
| `/api/pipeline/status` | GET | 管道进程状态 |
| `/api/market/report` | GET | 最新市场分析报告 |
| `/api/market/latest` | GET | 最新市场信号 |
| `/api/projects` | GET | 游戏项目列表 |
| `/api/pipeline/history` | GET | 管道历史快照 |
| `/api/memory` | GET | 公司记忆 |
| `/api/gdd/{id}` | GET | 项目 GDD 详情 |
| `/games-preview/{name}/dist/` | GET | 游戏预览静态文件 |

### 前端功能

- **Agent Monitor** — 8 个 Agent 的执行状态和统计数据
- **Pipeline Timeline** — 可视化管道进度
- **Market Report** — AI 分析结果与原始信号
- **Active Games** — 构建的游戏列表，支持 iframe 预览
- **Company Memory** — 长期记忆
- **Run Pipeline** 一键按钮 — 后台启动管道，自动轮询进度

---

## 关键技术决策

### 为什么用 LangGraph 而不是 CrewAI？

- LangGraph 提供**条件路由**（evaluate → re-scan / design）、**状态持久化**、**循环控制**（QA → redevelop 循环）
- CrewAI 更适合平行协作场景，本系统本质是一个**线性流水线 + 条件回退**，LangGraph 的 StateGraph 模型更匹配

### 为什么用 SQLite 而不是 PostgreSQL？

- **零外部依赖**：无需 Docker、无需数据库服务
- 同一 SQLAlchemy API，升级到 PG 只需改连接字符串
- 单文件存储，备份和迁移简单

### 为什么前端用原生 HTML/CSS/JS？

- 零构建步骤，改完即生效
- 无需 Node.js 运行时依赖
- FastAPI 可直接挂载静态文件

### 为什么游戏用 Phaser 4？

- **Web 原生**：无插件、无下载，浏览器直接运行
- **TypeScript 支持**：AI 生成代码类型安全
- **内置形状渲染**：无美术资产也能制作可玩游戏
- **Vite 构建**：现代打包工具，输出为单 HTML5 文件

---

## 项目结构

```
gcagents/
├── orchestrator/           # 核心编排 (LangGraph)
│   ├── graph/pipeline.py   #   状态机构建 + 节点注册
│   ├── nodes/ceo.py        #   CEO 评估 + 路由决策
│   ├── state.py            #   全局状态定义
│   ├── persistence.py      #   SQLite 持久化
│   └── main.py             #   CLI 入口
├── agents/                 # AI Agent 实现
│   ├── research/           #   市场研究
│   │   ├── scanner.py      #     多源扫描
│   │   ├── analyzer.py     #     AI 分析
│   │   ├── sources/        #     各数据源适配器
│   ├── dev/                #   游戏开发
│   │   ├── designer/       #     GDD 生成
│   │   ├── artist/         #     美术生成 (ComfyUI)
│   │   ├── programmer/     #     代码生成 (DeepSeek)
│   │   ├── qa/             #     质量测试
│   │   └── builder/        #     Vite 构建
│   └── ops/                #   运维部署
│       └── deployer/       #     itch.io 发布
├── dashboard/web/          # 监控面板
│   ├── api_server.py       #   FastAPI 后端
│   ├── index.html          #   前端 HTML
│   ├── app.js              #   前端逻辑
│   └── style.css           #   样式
├── shared/                 # 共享模块
│   ├── config.py           #   配置加载 (pydantic-settings)
│   └── models.py           #   数据模型
├── config/                 # 配置文件
│   ├── agents.yaml         #   Agent 与模型映射
│   └── sources.yaml        #   市场数据源配置
├── data/                   # 运行数据 (gitignored)
│   ├── gcagents.db         #   SQLite 数据库
│   └── games/              #   生成游戏项目
└── .env                    # API 密钥 (gitignored)
```

---

## 开发日志与演进

| 日期 | 变更 |
|---|---|
| 初始 | 基础框架搭建：LangGraph 状态机、市场扫描、代码生成 |
| 迭代 | 添加 CEO 决策、QA 循环、Build 阶段 |
| 迭代 | Dashboard 监控面板 v1（5 个 Section） |
| 迭代 | 字段名规范化（score→market_opportunity_score） |
| 迭代 | DeepSeek max_tokens 提升至 16384，解决 JSON 截断 |
| 迭代 | 构建重试闭环：QA 捕获 stderr→Developer 带错误重生成 |
| 最近 | Dashboard 一键运行按钮 + 游戏 iframe 预览 |
| 最近 | 修复 Butler 部署（移除交互式 login，直接用 API key） |
| 最近 | 管道全流程验证通过 |

---

## 部署要求

### 环境变量 (`.env`)

```
DEEPSEEK_API_KEY=sk-...        # deepseek-coder 代码生成
ZHIPU_API_KEY=...              # glm-4-flash 分析/设计
BUTLER_API_KEY=...             # itch.io Butler 部署
BUTLER_USERNAME=kingsman666    # itch.io 用户名
```

### 系统依赖

- Python 3.11+
- Node.js 18+ (游戏构建)
- Butler CLI v15+ (itch.io 部署，可选)
- ComfyUI + Stable Diffusion (美术生成，可选)

### 启动

```bash
# 完整运行一次
python3 -m orchestrator.main run

# 仅市场扫描
python3 -m orchestrator.main scan

# 启动监控面板
python3 -m dashboard.web.api_server
# 访问 http://localhost:8080
```
