# GCAgents — 全自动 AI 游戏公司架构文档

## 概述

GCAgents 是一个多项目并行运作的 AI 游戏公司系统。它像一家真实的游戏公司一样运作：CEO 统一调度多个项目，每个项目独立推进（调研、设计、开发、测试），重要决策必须经过人类批准。12 个市场数据源提供情报支撑，Dashboard 实时展示项目看板、任务监控和决策卡片。

**核心理念**：
- 用 AI Agent 模拟游戏公司组织架构，CEO 作为调度大脑管理多个并行项目
- **重要决策必须人类批准**：新项目启动、发布上线、项目取消、预算超限、方向调整
- 12 个市场数据源（itch.io/Reddit/SteamSpy/TikTok/YouTube 等）提供跨源关联分析
- 每个项目有独立的生命周期和进度，互不阻塞

---

## 系统架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                         GCAgents System                              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                    CEO Scheduler (调度大脑)                   │     │
│  │  每个 tick: 处理指令 → 检查决策点 → 推进项目 → 执行任务      │     │
│  └────────┬──────────┬──────────┬──────────┬───────────────────┘     │
│           │          │          │          │                          │
│     ┌─────▼───┐ ┌────▼────┐ ┌──▼───┐ ┌───▼────┐                     │
│     │Project A│ │Project B│ │Proj C│ │ Market │                     │
│     │ 开发中  │ │ 设计中  │ │待批准│ │ 扫描器 │                     │
│     └────┬────┘ └────┬────┘ └──┬───┘ └───┬────┘                     │
│          │           │         │         │                           │
│  ┌───────▼───────────▼─────────▼─────────▼───────────────────┐      │
│  │                     Task Queue (任务队列)                   │      │
│  │  scan | design | art_gen | develop | qa | build | deploy  │      │
│  └────────────────────────────────────────────────────────────┘      │
│                                                                      │
│  ┌─────────────┐     ┌────────────────────────────────────────┐     │
│  │  Dashboard   │     │           AI Models                    │     │
│  │  项目看板     │     │  ┌──────────┐ ┌──────────┐           │     │
│  │  任务监控     │     │  │glm-4-flash│ │deepseek- │           │     │
│  │  决策卡片     │     │  │(分析/设计)│ │coder     │           │     │
│  │  市场趋势     │     │  └──────────┘ │(代码生成)│           │     │
│  │  高管对话     │     │               └──────────┘           │     │
│  └─────────────┘     └────────────────────────────────────────┘     │
│                                                                      │
│  ┌─────────────┐     ┌────────────────────────────────────────┐     │
│  │  SQLite DB   │     │  12 Market Sources                     │     │
│  │  持久化      │     │  itch · reddit · steam · youtube · ... │     │
│  └─────────────┘     └────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 编排引擎 | **CEO Scheduler** (Python async tick loop) | 多项目并行调度、决策门控、任务队列管理 |
| AI 分析 | **glm-4-flash** (智谱免费) | 市场分析、游戏设计、评估决策 |
| AI 代码 | **deepseek-coder** | 生成 Phaser 4 + TypeScript 游戏源码 |
| 美术生成 | **ComfyUI + SD 1.5** (本地 GPU) | AI 生成游戏美术资产（背景/角色/UI 图标） |
| 游戏运行 | **Phaser 4 + TypeScript + Vite** | 生成 Web 小游戏（加载并显示 ComfyUI 美术资产） |
| 监控面板 | **FastAPI + 原生 HTML/CSS/JS** | 项目看板、任务监控、决策卡片、高管对话、市场趋势 |
| 市场情报 | **12 个数据源** (itch/Reddit/SteamSpy/TikTok/YouTube/...) | 跨源关联分析、趋势追踪、竞品密度 |
| 持久化 | **SQLite + SQLAlchemy (async)** | 项目、决策、任务、财务、聊天、事件 |
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

## 核心工作流 — 多项目调度器

系统有两种运行模式：**经典线性管道**（LangGraph）和**多项目调度器**（推荐）。

### 模式 1: 多项目调度器（推荐）

CEO 作为调度大脑，每个 tick 处理所有项目的一步操作：

```
每个 tick (默认 300s):
┌─────────────────────────────────────────────────┐
│ 1. 处理人类指令 (从 chat 读取)                    │
│ 2. 检查决策点 — 跳过等待人类的项目                │
│ 3. 定期市场扫描 (每 10 ticks)                     │
│ 4. 推进各项目:                                    │
│    backlog → [人类批准] → scanning → designing    │
│    → developing → testing → building              │
│    → [人类批准] → publishing → live               │
│ 5. 从任务队列取一个任务执行                        │
│ 6. 根据执行结果更新项目状态                        │
│ 7. 生成主动汇报到 chat                            │
└─────────────────────────────────────────────────┘
```

**5 类决策门控（必须人类批准）**：

| 决策类型 | 触发条件 | 示例 |
|---------|---------|------|
| 新项目启动 | 市场扫描发现机会 | "发现3个机会，推荐A，启动？" |
| 项目发布 | QA 通过 | "项目A测试通过，发布到itch.io？" |
| 项目取消 | QA 连续失败 3 次 | "项目C连续失败，取消？" |
| 预算超限 | 开发前预算检查 | "项目B预算达80%，继续？" |
| 方向调整 | 市场变化 | "建议调整B方向？" |

### 模式 2: 经典线性管道（兼容）

保留原有 13 节点 LangGraph 管道，单项目线性执行。

### 项目状态定义 (`shared/models.py`)

```python
class ProjectPhase(str, Enum):
    BACKLOG = "backlog"        # 待启动
    SCANNING = "scanning"      # 市场调研中
    DESIGNING = "designing"    # 设计中
    DEVELOPING = "developing"  # 开发中
    TESTING = "testing"        # 测试中
    BUILDING = "building"      # 构建中
    PUBLISHING = "publishing"  # 发布中
    LIVE = "live"              # 已上线
    PAUSED = "paused"          # 已暂停
    CANCELLED = "cancelled"    # 已取消
```

### 执行入口 (`orchestrator/main.py`)

```bash
# 多项目调度器（推荐）
python3 -m orchestrator.main run-scheduler              # 启动调度器，默认 300s/tick
python3 -m orchestrator.main run-scheduler --interval 60 # 1 分钟一个 tick

# 经典模式（兼容）
python3 -m orchestrator.main run              # 完整运行一个周期
python3 -m orchestrator.main run-forever       # 24/7 模式，循环运行
python3 -m orchestrator.main scan             # 仅执行市场扫描
```

---

## Agent 节点详解

### 1. 市场扫描器 (`agents/research/scanner.py`)

从 **12 个数据源**采集游戏市场信号：

```
数据源:
├── itch.io RSS        — 最新/热门/免费游戏 RSS
├── itch.io API        — 按标签搜索游戏详情
├── Reddit             — r/webgames, r/incremental_games, r/idle_games 等社区
├── StatKraken         — CrazyGames/Poki/Newgrounds 排行榜
├── Google Play        — 移动端分类排行榜
├── App Store          — iOS 免费游戏榜
├── SteamSpy           — Steam 独立游戏数据（免费 API，按标签查询）
├── X/Twitter          — 游戏话题趋势
├── YouTube Gaming     — 游戏视频趋势 RSS
├── Product Hunt       — 游戏类新品
├── TikTok             — 游戏标签热门
└── PlugPlay           — Web 游戏平台
```

**增强分析能力**：
- **跨源关联**：同一 genre 在多个数据源同时出现时提升可信度
- **竞品密度**：统计每个 genre 的已有游戏数量
- **趋势方向**：判断 rising/stable/declining
- **机会评分**：`score = trend_strength × (1 - competition) × market_size`

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
| `projects` | 多项目编排（项目看板） | id, name, genre, phase, progress, awaiting_decision |
| `decisions` | 决策门控（人类审批） | id, project_id, decision_type, question, status, human_response |
| `tasks` | 任务队列（异步执行） | id, project_id, task_type, status, progress, error |
| `agent_logs` | 每个 Agent 节点的执行日志 | node_name, status, duration_ms, error |
| `game_projects` | 游戏项目记录 | name, genre, status, gdd, itch_url, current_version |
| `market_signals` | 原始市场信号（12 源） | source, genre, title, score, captured_at |
| `market_reports` | AI 市场分析报告 | signals_count, opportunities_json, raw_analysis |
| `company_memory` | 公司长期记忆 | category, title, content, importance |
| `game_feedback` | 用户反馈（itch.io 评论抓取）| project_id, category, content, processed |
| `game_versions` | 版本快照 | project_id, version, gdd_snapshot, changelog |
| `game_metrics` | 游戏遥测数据 | project_id, event_type, score, play_time |
| `api_usage_logs` | LLM 调用追踪 | model, agent_name, total_tokens, estimated_cost_usd |
| `finance_budgets` | 预算配置 | category, budget_type, budget_limit_usd, spent_usd |
| `chat_messages` | 高管聊天记录 | role, content, agent_name, metadata_json |
| `event_logs` | 公司事件日志 | event_type, severity, title, source_agent |

### 写入时机

| 事件 | 写入内容 |
|---|---|
| 项目阶段变更 | `projects` 更新 phase/progress |
| 决策创建/解决 | `decisions` 记录人类决策 |
| 任务执行 | `tasks` 记录状态/进度/结果 |
| 每个节点执行完成 | `agent_logs` 写入耗时 + 状态 |
| 每次LLM调用 | `api_usage_logs` 写入 token 用量 + 成本 |
| 市场扫描完成 | `market_signals` + `market_reports` |
| 管道阶段变更 | `orchestrator_state` + `game_projects` |
| 部署完成 | `game_versions`（版本号 + GDD 快照） |
| 反馈收集 | `game_feedback`（itch.io 评论 + AI 分类） |
| 游戏运行 | `game_metrics`（分析事件埋点上报） |
| 财务操作 | `finance_budgets` + `event_logs` |
| 高管聊天/决策 | `chat_messages`（含决策卡片） |
| 所有重要事件 | `event_logs` |

---

## Dashboard 监控

Dashboard 运行在独立进程（FastAPI + 静态 HTML/CSS/JS），与管道解耦。

### API 端点

| 路径 | 方法 | 用途 |
|---|---|---|
| **项目管理** | | |
| `/api/orchestrator/projects` | GET | 多项目列表（看板数据） |
| `/api/orchestrator/projects/{id}` | GET | 单项目详情 |
| `/api/projects/{id}/pause` | POST | 暂停项目 |
| `/api/projects/{id}/resume` | POST | 恢复项目 |
| `/api/projects/{id}/cancel` | POST | 取消项目 |
| **决策门控** | | |
| `/api/decisions` | GET | 待处理决策列表 |
| `/api/decisions/{id}/respond` | POST | 回复决策（approve/reject/discuss） |
| **任务监控** | | |
| `/api/orchestrator/tasks` | GET | 任务列表（支持按项目过滤） |
| **经典管道** | | |
| `/api/pipeline/run` | POST | 触发单次管道运行 |
| `/api/pipeline/run-forever` | POST | 启动 24/7 模式 |
| `/api/pipeline/stop` | POST | 停止运行中的管道 |
| `/api/pipeline/status` | GET | 管道进程状态 |
| `/api/pipeline/history` | GET | 管道历史快照 |
| **数据查询** | | |
| `/api/status` | GET | 当前系统状态 |
| `/api/agents` | GET | 各 Agent 执行统计 |
| `/api/market/report` | GET | 最新市场分析报告 |
| `/api/market/latest` | GET | 最新市场信号 |
| `/api/projects` | GET | 游戏项目列表 |
| `/api/memory` | GET | 公司记忆 |
| `/api/gdd/{id}` | GET | 项目 GDD 详情 |
| `/api/events` | GET | 事件日志查询 |
| `/api/feedback/{id}` | GET | 项目反馈列表 |
| `/api/projects/live` | GET | 已上线项目列表 |
| `/api/analytics/event` | POST | 游戏遥测事件 |
| **对话与财务** | | |
| `/api/chat/send` | POST | 发送高管聊天消息 |
| `/api/chat/history` | GET | 聊天历史记录 |
| `/api/finance/budget` | POST | 设置预算 |
| `/api/finance/summary` | GET | 财务摘要 |

### 前端功能

- **Project Board** — 看板式项目面板（Backlog → Design → Dev → Test → Build → Live），每项目独立进度
- **Task Monitor** — 任务监控列表，实时显示状态/进度/耗时
- **Executive Chat** — 与 CEO/CFO/COO 高管对话，含决策卡片（批准/拒绝/讨论按钮）
- **Market Trends** — 市场趋势面板，来源健康度、趋势方向、跨源确认
- **Company Event Log** — 终端风格实时滚动日志
- **Agent Monitor** — 各 Agent 执行状态
- **Active Games** — 构建的游戏列表，支持 iframe 预览
- **Company Memory** — 长期记忆
- **24/7 Mode Toggle** — 一键启停 24/7 运行模式
- **Run Pipeline Button** — 一键启动管道

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
├── orchestrator/           # 核心编排
│   ├── scheduler.py        #   CEO 多项目调度器（tick-based）
│   ├── task_queue.py       #   任务队列（SQLite-backed）
│   ├── decision_gate.py    #   决策门控（5 类人类审批）
│   ├── graph/pipeline.py   #   经典线性管道（LangGraph，兼容）
│   ├── nodes/ceo.py        #   CEO 评估（经典模式）
│   ├── nodes/cfo.py        #   CFO 预算预检
│   ├── nodes/coo.py        #   COO 健康检查
│   ├── event_bus.py        #   统一事件发射
│   ├── state.py            #   全局状态定义
│   ├── persistence.py      #   SQLite 持久化（含 projects/decisions/tasks 表）
│   └── main.py             #   CLI 入口（run/run-forever/run-scheduler/scan）
├── agents/                 # AI Agent 实现
│   ├── research/           #   市场研究（12 个数据源）
│   │   ├── scanner.py      #     多源扫描
│   │   ├── analyzer.py     #     增强分析（跨源关联/竞品密度/趋势方向）
│   │   └── sources/        #     12 个数据源适配器
│   │       └── fetchers.py #       itch/reddit/steam/youtube/tiktok/...
│   ├── dev/                #   游戏开发
│   │   ├── designer/       #     GDD 生成
│   │   ├── artist/         #     美术生成 (ComfyUI SD 1.5)
│   │   ├── programmer/     #     代码生成 (DeepSeek)
│   │   ├── qa/             #     质量测试
│   │   └── builder/        #     Vite 构建
│   └── ops/                #   运维部署
│       ├── deployer/       #     itch.io 发布
│       └── analytics/      #     数据分析 + 反馈收集
├── dashboard/web/          # 监控面板
│   ├── api_server.py       #   FastAPI 后端（35 个 API 端点）
│   ├── index.html          #   前端（项目看板/任务监控/决策卡片/市场趋势）
│   ├── app.js              #   前端逻辑
│   └── style.css           #   样式
├── shared/                 # 共享模块
│   ├── config.py           #   配置加载 (pydantic-settings)
│   ├── models.py           #   数据模型（ProjectState/DecisionPoint/TaskRecord + 原有模型）
│   └── llm_client.py       #   统一 LLM 客户端（token 追踪 + 成本记录 + 重试退避）
├── config/                 # 配置文件
│   ├── agents.yaml         #   Agent 与模型映射
│   └── sources.yaml        #   12 个市场数据源配置
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
| 迭代 | Dashboard 监控面板、CEO 决策、QA 循环、Build 阶段 |
| 迭代 | ComfyUI 美术管线、反馈闭环、版本管理、分析埋点 |
| 迭代 | 统一 LLM 客户端、CFO/COO Agent、高管聊天面板、财务 API |
| 迭代 | 24/7 运行模式、Dashboard 启停按钮 |
| **当前** | **多项目编排重构**：CEO 调度器、决策门控（5 类）、任务队列、12 市场数据源、项目看板、任务监控、决策卡片、市场趋势面板 |

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
# 多项目调度器（推荐）
python3 -m orchestrator.main run-scheduler
python3 -m orchestrator.main run-scheduler --interval 60

# 经典模式
python3 -m orchestrator.main run
python3 -m orchestrator.main run-forever

# 仅市场扫描
python3 -m orchestrator.main scan

# 启动监控面板
python3 -m dashboard.web.api_server
# 访问 http://localhost:8080
```
