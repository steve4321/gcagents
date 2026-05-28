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
│  │  (入口)      │     │                                          │    │
│  └─────────────┘     │  ┌──────┐  ┌────────┐  ┌───────────┐    │    │
│                      │  │ Scan │─▶│Evaluate│─▶│  Design   │    │    │
│  ┌─────────────┐     │  └──────┘  └────────┘  └─────┬─────┘    │    │
│  │  Dashboard   │────▶│         ┌────────┐          │          │    │
│  │  (FastAPI +  │     │  ◀─────│   QA   │◀─────┐   │          │    │
│  │   HTML/CSS + │     │  │     └────────┘      │   ▼          │    │
│  │   WebSocket) │     │  │     ┌──────────┐    │ ┌────────┐   │    │
│  └─────────────┘     │  │     │  Build   │    │ │  Art   │   │    │
│                      │  │     └────┬─────┘    │ └────┬───┘   │    │
│  ┌─────────────┐     │  │          ▼          │     │       │    │
│  │   SQLite DB  │◀────│  │     ┌──────────┐    │     ▼       │    │
│  │  (持久化)    │     │  │     │  Deploy  │    │ ┌────────┐   │    │
│  └─────────────┘     │  │     └──────────┘    │ │ CFO    │   │    │
│                      │  └──────────────────────┼ │ Check  │   │    │
│  ┌─────────────┐     │                         ▼ └───┬────┘   │    │
│  │ Executive    │     │                    ┌──────────┐ │       │    │
│  │ Chat (WS)   │────▶│                    │ Develop  │◀┘       │    │
│  │ CEO/CFO/COO │     │                    └──────────┘         │    │
│  └─────────────┘     └─────────────────────────────────────────┘    │
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
| 美术生成 | **ComfyUI + SD 1.5** (本地 GPU) | AI 生成游戏美术资产（背景/角色/UI 图标） |
| 游戏运行 | **Phaser 4 + TypeScript + Vite** | 生成 Web 小游戏（加载并显示 ComfyUI 美术资产） |
| 监控面板 | **FastAPI + 原生 HTML/CSS/JS + WebSocket** | 实时查看公司运营状态 + 高管聊天 + 事件流 |
| 持久化 | **SQLite + SQLAlchemy (async)** | Agent 日志、市场信号、项目数据、财务、聊天、事件 |
| 部署 | **Butler CLI** | 推送到 itch.io |

---

## AI 模型与工具策略

系统使用三类 AI 能力，各司其职：

| 工具 | 用途 | 成本 |
|---|---|---|
| **glm-4-flash** | 市场分析、游戏设计、评估决策、指令分类 | 免费 |
| **deepseek-coder** | 生成 Phaser 4 + TypeScript 游戏源码 | ~$0.0015/1K tokens |
| **ComfyUI + SD 1.5** | 生成游戏美术资产（背景/角色/UI 图标），运行在本地 GPU | 免费（本地推理） |

**关键决策**：
- **ComfyUI** 是美术资产生成工具，不是游戏引擎。它输出 PNG 图片。
- **Phaser** 是游戏运行时引擎，负责加载 ComfyUI 生成的图片并运行游戏逻辑。
- 分析/设计类任务使用免费模型，只有代码生成使用付费模型。
- 所有 LLM 调用通过统一客户端 `shared/llm_client.py` 管理，自动追踪 token 和成本。

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
COO检查 ──▶ 收集反馈 ──▶ 扫描 ──▶ 评估 ──┬─▶ 设计 ──▶ 美术 ──▶ CFO检查 ──▶ 开发 ──▶ QA ──▶ 构建 ──▶ 部署 ──▶ 存版本 ──▶ 完成
                                          │                                    ▲         │
                                          │                                    │         │ (失败且<3次)
                                          ├─▶ 更新 ◀───────────────────────────┘         │
                                          │       │                                      │
                                          │       └─▶ CFO检查 ──▶ 开发（跳过设计/美术）──┘
                                          │
                                          └─▶ 重新扫描 / 休眠
```

**关键路由逻辑**：

- **收集反馈**：每个周期开始时，先从 itch.io 游戏页面抓取用户评论，AI 分类为 bug/feature/praise/question
- **评估后**：如果存在 ≥2 条未处理的 bug/feature 反馈 → MODE_UPDATE 进入更新流程；否则按评分决定设计/重新扫描/休眠
- **更新流程**：跳过设计和美术阶段，直接进入开发修复
- **QA 后**：如果通过 → 构建；如果失败且重试 < 3 次 → 回开发修复；否则终止
- **存版本**：部署后自动在 `game_versions` 表记录 GDD 快照和版本号
- **Agent 日志包装器**：`_logged_node()` 自动记录每个节点的起止时间、耗时、状态到数据库
- **COO 健康检查**：管道入口处检查错误数量，≥3 个错误时暂停管道
- **CFO 预算检查**：在开发（最贵步骤）前检查月度和项目预算，超预算则终止管道

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
- **反馈驱动更新**：通过 `_find_project_to_update()` 检查已上线项目的未处理反馈
  - 如果 ≥2 条 bug/feature 反馈 → 路由到 MODE_UPDATE（跳过设计/美术，直接修复）
  - 否则按评分决定是否启动新项目
- 评分 > 0.6 则生成 `GameProposal` 并进入设计阶段
- 评分不足则继续扫描或进入休眠
- **用户指令处理**：通过 `_process_ceo_instructions()` 从聊天界面接收用户指令
  - genre 指令（"下一个做解谜类"）→ 写入 company_memory，优先匹配该 genre
  - 停止指令 → 立即进入 IDLE 状态
  - 问题/反馈 → 记录为系统事件
  - 使用 glm-4-flash 进行意图分类（direction/question/feedback/stop）

### 2a. CFO (`orchestrator/nodes/cfo.py`)

模拟 CFO 财务管控角色：

- **预算预检** (`cfo_budget_check`)：在开发步骤前检查月度和项目预算
  - 开发步骤估算成本 ~$0.10（~50K tokens deepseek-coder）
  - 超预算则终止管道并记录财务事件
  - 无预算配置时默认放行（不设限）
- **财务报告** (`cfo_financial_report`)：生成 30 天财务摘要
  - 汇总 token 用量、按模型/Agent 分组成本
  - 使用 glm-4-flash 生成 AI 财务洞察

### 2b. COO (`orchestrator/nodes/coo.py`)

模拟 COO 运营监控角色：

- **管道健康检查** (`coo_health_check`)：管道入口处检查状态
  - ≥3 个累积错误 → 暂停管道
  - ≥3 次重试 → 记录告警
- **指令处理** (`coo_process_instructions`)：从聊天界面接收运营指令
  - "暂停"/"停止" → 切换到 IDLE
  - "状态"/"报告" → 记录运营事件

### 3. 游戏设计师 (`agents/dev/designer/`)

接收 GDD 生成任务，调用 glm-4-flash 生成结构化的游戏设计文档：

- 游戏标题、类型、核心玩法
- 场景列表（Boot → Menu → Game → GameOver）
- 游戏机制和控制系统
- 参考游戏和差异化定位

### 4. 美术师 (`agents/dev/artist/`)

通过 **ComfyUI + Stable Diffusion 1.5** 生成游戏美术资产。**ComfyUI 不是游戏引擎**，它是美术资产生成工具——生成的 PNG 图片由 Phaser 游戏引擎加载使用。

**ComfyUI 的角色**：接到 GDD 中的美术需求 → 调用本地 ComfyUI API → SD 1.5 生成 PNG → 放入游戏 `public/assets/` → Phaser 通过 `this.load.image()` / `this.add.image()` 加载显示。

**核心组件**：
- `comfyui_client.py` — ComfyUI HTTP API 客户端（queue → poll → download）
- `sprite_generator.py` — 角色精灵、背景、UI 图标生成器
- `workflows.py` — SD 1.5 工作流定义（含 VAE 连接，兼容 ComfyUI v1.44+）

**资产类型**：
| 类型 | 分辨率 | 用途 |
|---|---|---|
| 背景图 | 800×600 | 菜单、游戏、结算场景背景 |
| 角色精灵 | 64×64 | 玩家、NPC 角色 |
| UI 图标 | 32×32 | 道具、能力、金币等 |

**性能**：RTX 3060 首次生成 ~391s（模型加载），后续 ~10s/张。

**集成方式**：生成的 PNG 放入游戏 `public/assets/`，Phaser 的 BootScene 通过 `this.load.image()` 加载，场景用 `this.add.image()` 替代 `this.add.rectangle()` 矩形占位符。

**ComfyUI 与 Phaser 的关系**：
```
ComfyUI (生成美术)                    Phaser (游戏运行时)
┌─────────────────┐                 ┌──────────────────────┐
│ GDD 美术需求     │                 │ BootScene            │
│      ↓          │                 │   this.load.image()  │
│ SD 1.5 推理     │  →  PNG 文件 →  │ GameScene            │
│ (RTX 3060 GPU)  │     写入磁盘    │   this.add.image()   │
│      ↓          │                 │ 玩家控制/碰撞/动画    │
│ PNG 输出        │                 └──────────────────────┘
└─────────────────┘
```
ComfyUI 负责"画画"，Phaser 负责"运行游戏"，两者是上下游协作关系。

### 5. 程序员 (`agents/dev/programmer/`)

调用 **deepseek-coder** 生成完整的 **Phaser 4**（预览版）+ TypeScript 游戏代码。Phaser 是游戏运行时引擎，负责场景管理、玩家输入、碰撞检测、动画——ComfyUI 生成的美术资产在 Phaser 中加载和显示。

```
generate_game_code(gdd, project_dir, config, build_error="")
```

- 接收 GDD，用 Jinja2 模板 + AI 生成完整游戏源码
- 强制约束：`import * as Phaser from 'phaser'`（Phaser 4 ESM 无默认导出）
- 游戏代码引用 ComfyUI 生成的美术资产路径（`assets/bg_menu.png`、`assets/player.png` 等），运行时通过 Phaser 加载
- **构建重试机制**：如果 `build_error` 参数非空，自动将错误信息追加到 AI prompt 中，让 AI 修复后重新生成
- **分析埋点**：在生成的游戏代码中注入 `navigator.sendBeacon` 调用，上报 `game_start`/`game_over` 事件（含分数、游戏时长）
- **磁盘管理**：构建完成后自动删除 `node_modules/`，npm 缓存保证后续安装速度
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
| `game_projects` | 游戏项目记录 | name, genre, status, gdd, itch_url, current_version, feedback_count |
| `market_signals` | 原始市场信号 | source, genre, title, score, captured_at |
| `market_reports` | AI 市场分析报告 | signals_count, opportunities_json, raw_analysis |
| `company_memory` | 公司长期记忆 | category, title, content, importance |
| `game_feedback` | 用户反馈（itch.io 评论抓取）| project_id, category, content, processed, post_id |
| `game_versions` | 版本快照 | project_id, version, gdd_snapshot, changelog |
| `game_metrics` | 游戏遥测数据 | project_id, event_type, score, play_time |
| `api_usage_logs` | LLM 调用追踪 | model, agent_name, total_tokens, estimated_cost_usd |
| `finance_budgets` | 预算配置 | category, budget_type, budget_limit_usd, spent_usd |
| `chat_messages` | 高管聊天记录 | role, content, agent_name, metadata_json |
| `event_logs` | 公司事件日志 | event_type, severity, title, source_agent |

### 写入时机

| 事件 | 写入内容 |
|---|---|
| 每个节点执行完成 | `agent_logs` 写入耗时 + 状态 |
| 每次LLM调用 | `api_usage_logs` 写入 token 用量 + 成本 |
| 市场扫描完成 | `market_signals` + `market_reports` |
| 管道阶段变更 | `orchestrator_state` + `game_projects` |
| CEO 决策 | `game_projects`（更新状态） |
| 部署完成 | `game_versions`（版本号 + GDD 快照） |
| 反馈收集 | `game_feedback`（itch.io 评论 + AI 分类） |
| 游戏运行 | `game_metrics`（分析事件埋点上报） |
| 财务操作 | `finance_budgets`（预算设置/更新）、`event_logs`（财务事件） |
| 高管聊天 | `chat_messages`（用户消息 + Agent 回复） |
| 所有重要事件 | `event_logs`（公司级别事件，WebSocket 实时推送） |

---

## Dashboard 监控

Dashboard 运行在独立进程（FastAPI + 静态 HTML/CSS/JS + WebSocket），与管道解耦。

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
| `/api/analytics/event` | POST | 游戏遥测事件（game_start/game_over） |
| `/api/feedback/{id}` | GET | 项目反馈列表 + 分类统计 |
| `/api/projects/live` | GET | 已上线项目列表 |
| `/ws/events` | WebSocket | 实时事件流推送 |
| `/api/events` | GET | 事件日志查询（支持 type 筛选） |
| `/api/chat/send` | POST | 发送高管聊天消息（CEO/CFO/COO） |
| `/api/chat/history` | GET | 聊天历史记录 |
| `/api/finance/budget` | POST | 设置预算（月度/项目） |
| `/api/finance/summary` | GET | 财务摘要（用量+预算） |
| `/games-preview/{name}/dist/` | GET | 游戏预览静态文件 |

### 前端功能

- **Executive Chat** — 与 CEO/CFO/COO 高管对话，发送指令和查询
- **Company Event Log** — 终端风格实时滚动日志，WebSocket 推送公司所有事件
- **Agent Monitor** — 8 个 Agent 的执行状态和统计数据
- **Pipeline Timeline** — 可视化管道进度
- **Market Report** — AI 分析结果与原始信号
- **Active Games** — 构建的游戏列表，支持 iframe 预览
- **Company Memory** — 长期记忆
- **Run Pipeline** 一键按钮 — 后台启动管道，自动轮询进度

### 事件总线 (`orchestrator/event_bus.py`)

所有 Agent 通过 `emit()` 函数发射事件，自动双写到 DB 和 WebSocket：
- 写入 `event_logs` 表持久化
- 通过 Dashboard WebSocket `/ws/events` 实时推送到前端
- Dashboard 未运行时静默忽略（不影响管道）

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
- **纯单机**：游戏代码无服务器依赖，无网络请求，离线可玩
- **TypeScript 支持**：AI 生成代码类型安全
- **ComfyUI 美术集成**：通过 SD 1.5 生成真实游戏资产替代矩形占位符
- **Vite 构建**：现代打包工具，输出为单 HTML5 文件

---

## 项目结构

```
gcagents/
├── orchestrator/           # 核心编排 (LangGraph)
│   ├── graph/pipeline.py   #   状态机构建 + 反馈循环 + CFO/COO 集成
│   ├── nodes/ceo.py        #   CEO 评估 + 反馈驱动 + 用户指令处理
│   ├── nodes/cfo.py        #   CFO 预算预检 + 财务报告
│   ├── nodes/coo.py        #   COO 管道健康检查 + 运营指令处理
│   ├── event_bus.py        #   统一事件发射（DB + WebSocket 双写）
│   ├── state.py            #   全局状态定义（含 UPDATING 阶段）
│   ├── persistence.py      #   SQLite 持久化（含财务/聊天/事件表）
│   └── main.py             #   CLI 入口
├── agents/                 # AI Agent 实现
│   ├── research/           #   市场研究
│   │   ├── scanner.py      #     多源扫描
│   │   ├── analyzer.py     #     AI 分析
│   │   └── sources/        #     各数据源适配器
│   ├── dev/                #   游戏开发
│   │   ├── designer/       #     GDD 生成
│   │   ├── artist/         #     美术生成 (ComfyUI SD 1.5)
│   │   │   ├── comfyui_client.py  # ComfyUI HTTP 客户端
│   │   │   ├── sprite_generator.py # 精灵/背景/图标生成
│   │   │   └── workflows.py       # SD 1.5 工作流定义
│   │   ├── programmer/     #     代码生成 (DeepSeek + 分析埋点)
│   │   ├── qa/             #     质量测试
│   │   └── builder/        #     Vite 构建
│   └── ops/                #   运维部署
│       ├── deployer/       #     itch.io 发布
│       └── analytics/      #     数据分析
│           └── feedback_collector.py  # itch.io 评论抓取 + AI 分类
├── dashboard/web/          # 监控面板
│   ├── api_server.py       #   FastAPI 后端（含 WebSocket + 聊天 + 事件 + 财务 API）
│   ├── index.html          #   前端 HTML（含聊天面板 + 事件日志）
│   ├── app.js              #   前端逻辑（含 WebSocket 实时事件流）
│   └── style.css           #   样式
├── shared/                 # 共享模块
│   ├── config.py           #   配置加载 (pydantic-settings)
│   ├── models.py           #   数据模型（含 FinanceBudget, ChatMessage, EventLog）
│   └── llm_client.py       #   统一 LLM 客户端（token 追踪 + 成本记录 + 重试退避）
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
| 最近 | ComfyUI 美术管线：SD 1.5 生成背景/角色/UI 图标，接入游戏代码 |
| 最近 | 反馈闭环：itch.io 评论抓取 → AI 分类 → CEO 路由 MODE_UPDATE |
| 最近 | 分析埋点：游戏运行时上报 game_start/game_over 事件 |
| 最近 | 版本管理：部署后自动存 GDD 快照 + 版本号 |
| 最近 | 已发布游戏集成 ComfyUI 真实美术资源（pixel-parkour-prodigy v1.3.0）|
| 最近 | 统一 LLM 客户端：token 追踪 + 成本记录 + 指数退避重试 |
| 最近 | CFO Agent：月度/项目预算管控 + 开发前预算预检 |
| 最近 | COO Agent：管道健康检查 + 运营指令处理 |
| 最近 | CEO 升级：聊天指令处理（genre 指令/停止/反馈）|
| 最近 | Dashboard 高管聊天面板（CEO/CFO/COO）|
| 最近 | 公司事件日志：终端风格实时滚动 + WebSocket 推送 |
| 最近 | 财务 API：预算设置 + 用量摘要 + 成本追踪 |

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
- ComfyUI + Stable Diffusion 1.5 (美术生成，需 GPU)

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
