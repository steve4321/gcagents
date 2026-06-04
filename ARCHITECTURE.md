# GCAgents — 全自动 AI 游戏公司架构文档

## 概述

GCAgents 是一个多项目并行运作的 AI 游戏公司系统。它像一家真实的游戏公司一样运作：CEO 统一调度多个项目，每个项目独立推进（调研、设计、开发、测试），重要决策必须经过人类批准。12 个市场数据源提供情报支撑，Dashboard 实时展示项目看板、任务监控和决策卡片。

**核心理念**：
- 用 AI Agent 模拟游戏公司组织架构，CEO 作为调度大脑管理多个并行项目
- **CEO-only 交互模式**：用户只与 CEO 对话，CFO/COO 作为内部节点自动运行，不提供独立交互入口
- **重要决策必须人类批准**：新项目启动、发布上线、项目取消、预算超限、方向调整
- 12 个市场数据源（itch.io/Reddit/SteamSpy/TikTok/YouTube 等）提供跨源关联分析
- 每个项目有独立的生命周期和进度，互不阻塞
- **事件溯源（Event Sourcing）**：所有系统状态变化均记录为不可变事件，支持回放和审计
- **看板调度（Kanban Board）**：替代传统 FIFO 队列，支持任务状态跟踪、优先级管理和原子认领
- **DAG Planner**：基于有向无环图的执行规划，支持波次并行执行和结构化恢复
- **验证框架（Verification Framework）**：所有 Agent 输出必须经过独立验证，支持 strict/soft/advisory 三种模式
- **文档查看器**：所有 Agent 工作文档（proposal、GDD、market scan、art report、music report、QA report、build report）可通过 Dashboard 文档弹窗查看

---

## 系统架构总览

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              GCAgents System                                      │
│                                                                                   │
│  ┌──────────────────────────────────────────────────────────────────────────┐    │
│  │                    CEO Scheduler (调度大脑)                                │    │
│  │  每个 tick: 处理指令 → 检查决策点 → 推进项目 → 执行任务 → 生成汇报          │    │
│  └────────────┬───────────┬────────────┬────────────┬─────────────────────────┘    │
│               │           │            │            │                                │
│         ┌─────▼───┐ ┌────▼────┐ ┌─────▼────┐ ┌─────▼──────┐                     │
│         │Project A│ │Project B│ │  Proj C  │ │   Market   │                     │
│         │ 开发中   │ │ 设计中   │ │  已上线   │ │   扫描器   │                     │
│         └─────┬────┘ └────┬────┘ └──────┬───┘ └──────┬────┘                     │
│               │           │            │            │                            │
│  ┌────────────▼───────────▼────────────▼────────────▼─────────────────────┐      │
│  │                    Kanban Board + Task Queue                           │      │
│  │  triaged → claimed → running → review → completed/failed/blocked      │      │
│  └────────────────────────────────────────────────────────────────────────┘      │
│                                                                                   │
│  ┌────────────────┐  ┌─────────────────────────────────────────────────────┐     │
│  │   Event Store   │  │              AI Models (Model Router)               │     │
│  │   事件溯源      │  │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │     │
│  │   不可变事件   │  │  │MiniMax-M3│ │MiniMax-M2│ │glm-4-flash│            │     │
│  └────────────────┘  │  │(strong)  │ │(code)    │ │ (cheap)  │            │     │
│                     │  │  deepseek │ │ ComfyUI  │ │  Suno    │            │     │
│  ┌────────────────┐  │  └──────────┘ └──────────┘ └──────────┘            │     │
│  │   DAG Planner  │  │  6 层模型路由: strong/fast/cheap/code/art/audio  │     │
│  │  波次并行执行   │  └─────────────────────────────────────────────────────┘     │
│  └────────────────┘                                                            │
│  ┌────────────────┐  ┌─────────────────────────────────────────────────────┐     │
│  │ Verification   │  │  Context Manager — 4 层渐进压缩                     │     │
│  │ Framework      │  │  raw → summarized → compressed → minimal            │     │
│  │ strict/soft/   │  └─────────────────────────────────────────────────────┘     │
│  │ advisory       │                                                            │
│  └────────────────┘  ┌─────────────────────────────────────────────────────┐     │
│                      │              12 Market Sources                       │     │
│  ┌────────────────┐  │  itch · reddit · steam · youtube · tiktok · ...   │     │
│  │  Sandbox        │  └─────────────────────────────────────────────────────┘     │
│  │  进程隔离执行   │                                                            │
│  └────────────────┘  ┌─────────────────────────────────────────────────────┐     │
│                      │              Dashboard (FastAPI)                       │     │
│  ┌────────────────┐  │  项目看板 / 任务监控 / 决策卡片 / 文档查看器 / 市场趋势 │     │
│  │  Code Graph    │  └─────────────────────────────────────────────────────┘     │
│  │  PageRank 排名  │                                                            │
│  └────────────────┘  ┌─────────────────────────────────────────────────────┐     │
│                      │              SQLite DB (18 张表)                       │     │
│  ┌────────────────┐  │  projects, decisions, tasks, kanban_tasks, event_logs...│     │
│  │  Agent Msg      │  └─────────────────────────────────────────────────────┘     │
│  │  SQLite 邮箱    │                                                            │
│  └────────────────┘                                                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 编排引擎 | **CEO Scheduler** (Python async tick loop) | 多项目并行调度、决策门控、任务队列管理 |
| 执行规划 | **DAG Planner** + **Kanban Board** | 波次并行执行、任务状态管理、原子认领 |
| 事件溯源 | **Event Store** (SQLite-backed) | 不可变事件流、项目时间线回放 |
| 验证框架 | **Verification Framework** | Agent 输出独立验证，strict/soft/advisory 三模式 |
| AI 分析 | **glm-4-flash** (智谱免费) | 市场分析、游戏设计、评估决策 |
| AI 代码 | **MiniMax-M2.1** / **deepseek-v4-flash** | 生成 Phaser 4 + TypeScript 游戏源码 |
| AI 强模型 | **MiniMax-M3** | 复杂推理、架构设计、CEO 决策 |
| 美术生成 | **ComfyUI + SD XL** (本地 GPU) | AI 生成游戏美术资产（背景/角色/UI 图标） |
| 音乐生成 | **Suno API** / Web Audio 程序化 | 游戏背景音乐和音效 |
| 游戏运行 | **Phaser 4 + TypeScript + Vite** | 生成 Web 小游戏（加载并显示 ComfyUI 美术资产） |
| 监控面板 | **FastAPI + 原生 HTML/CSS/JS** | 项目看板、任务监控、决策卡片、CEO 汇报、文档查看器、市场趋势 |
| 市场情报 | **12 个数据源** (itch/Reddit/SteamSpy/TikTok/YouTube/...) | 跨源关联分析、趋势追踪、竞品密度 |
| 持久化 | **SQLite + SQLAlchemy (async)** | 项目、决策、任务、财务、聊天、事件、kanban_tasks、domain_events |
| 沙箱隔离 | **SubprocessSandbox** | 受限执行 npm build 等高危操作 |
| 代码分析 | **Code Graph** (PageRank 排名) | TypeScript/JavaScript 依赖图分析 |
| 部署 | **Butler CLI** | 推送到 itch.io |

---

## AI 模型与工具策略

系统使用多层级 AI 能力，通过 **Model Router** 实现成本感知的智能路由：

### 6 层模型路由体系

| 层级 | 模型 | 用途 | 成本 |
|---|---|---|---|
| **strong** | MiniMax-M3 (fallback: deepseek-v4-flash) | 复杂推理、架构设计、CEO 决策、规划 | 中高 |
| **fast** | MiniMax-M3 (fallback: glm-4-flash) | 分析、分类、摘要、评估 | 中 |
| **cheap** | glm-4-flash | 翻译、格式化、简单验证、意图分类 | 低 |
| **code** | MiniMax-M2.1 (fallback: deepseek-v4-flash) | 代码生成、代码编辑、代码审查 | 中 |
| **art** | stable-diffusion-xl (ComfyUI) | 美术资产生成 | 免费（本地） |
| **audio** | suno | 音乐生成 | 中 |

### 模型配置（config/agents.yaml）

```yaml
model_tiers:
  strong:
    primary: "MiniMax-M3"
    fallback: "deepseek-v4-flash"
    roles: [planning, ceo, architecture, game_design]
  fast:
    primary: "MiniMax-M3"
    fallback: "glm-4-flash"
    roles: [analysis, classification, summarization, evaluation]
  cheap:
    primary: "glm-4-flash"
    fallback: null
    roles: [translation, formatting, commit_message, simple_validation, intent_classification]
  code:
    primary: "MiniMax-M2.1"
    fallback: "deepseek-v4-flash"
    roles: [code_gen, code_edit, code_review]
  art:
    primary: "stable-diffusion-xl"
    fallback: null
    roles: [art_gen]
  audio:
    primary: "suno"
    fallback: null
    roles: [music_gen]
```

### 任务类别到模型层级映射

| 任务类别 | 默认层级 | 说明 |
|---|---|---|
| ARCHITECTURE | strong | 复杂架构设计 |
| CODE_GENERATION | code | 代码生成 |
| GAME_DESIGN | strong | 游戏设计 |
| MARKET_ANALYSIS | fast | 市场分析 |
| CLASSIFICATION | fast | 快速分类 |
| SUMMARIZATION | fast | 摘要生成 |
| TRANSLATION | cheap | 翻译 |
| PLANNING | strong | 规划任务 |
| ART_GENERATION | art | 美术生成 |
| MUSIC_GENERATION | audio | 音乐生成 |
| CODE_EDIT | code | 代码编辑 |
| CODE_REVIEW | code | 代码审查 |

**关键决策**：
- **ComfyUI** 是美术资产生成工具，不是游戏引擎。它输出 PNG 图片。
- **Phaser** 是游戏运行时引擎，负责加载 ComfyUI 生成的图片并运行游戏逻辑。
- 分析/设计类任务使用免费或低成本模型，只有代码生成使用付费模型。
- 所有 LLM 调用通过统一客户端 `shared/llm_client.py` 管理，自动追踪 token 和成本。
- Model Router 支持复杂度驱动的层级升降：复杂任务自动升级到 strong 模型，简单任务降级到 cheap。

---

## 核心工作流 — 多项目调度器

系统有两种运行模式：**经典线性管道**（LangGraph）和**多项目调度器**（推荐）。

### 模式 1: 多项目调度器（推荐）

CEO 作为调度大脑，每个 tick 处理所有项目的一步操作：

```
每个 tick (默认 60s):
┌──────────────────────────────────────────────────────────────────┐
│ 0. 检查调度器暂停状态（文件标志 .scheduler_paused）                 │
│ 1. 处理人类指令 (从 chat 读取)                                     │
│ 2. 检查决策点 — 跳过等待人类的项目                                 │
│ 3. 定期市场扫描 (每 5 ticks)                                       │
│ 4. CEO 评估新项目 (每 3 ticks)                                     │
│ 5. 定期获取 itch.io 统计数据 (每 30 ticks)                         │
│ 6. 推进各项目:                                                    │
│    backlog → [人类批准] → scanning → designing                     │
│    → developing (art → music → code) → testing                    │
│    → building → localize → [人类批准] → publishing                 │
│    → live (consolidate 记忆)                                      │
│ 7. 从任务队列取任务执行（含 3 层错误恢复）                         │
│ 8. 根据执行结果更新项目状态 + 存储记忆                              │
│ 9. 生成主动汇报到 chat（CEO 汇报，每 5 ticks）                     │
└──────────────────────────────────────────────────────────────────┘
```

**5 类决策门控（必须人类批准）**：

| 决策类型 | 触发条件 | 示例 |
|---------|---------|------|
| 新项目启动 | CEO 创建项目于 BACKLOG，`awaiting_decision="new_project"` | "发现3个机会，推荐A，启动？" |
| 项目发布 | QA 通过 | "项目A测试通过，发布到itch.io？" |
| 项目取消 | QA 连续失败 3 次 | "项目C连续失败，取消？" |
| 预算超限 | 开发前预算检查 | "项目B预算达80%，继续？" |
| 方向调整 | 市场变化 | "建议调整B方向？" |

**看板任务状态机**：

```
triaged → claimed → running → review → completed
                      ↓          ↓
                    failed     blocked (依赖未满足)
                      ↓
                    retry (最多 3 次)
```

| 状态 | 说明 |
|---|---|
| **triaged** | 已分析，等待认领 |
| **claimed** | 已被 Agent 原子认领（CAS） |
| **running** | 正在执行 |
| **review** | 完成，等待验证 |
| **completed** | 已完成并验证通过 |
| **failed** | 执行失败 |
| **blocked** | 等待依赖任务完成 |
| **cancelled** | 手动取消 |

**优先级体系**：

| 优先级 | 说明 |
|---|---|
| critical | 最高优先级，优先调度 |
| high | 高优先级 |
| normal | 默认优先级 |
| low | 低优先级，可延迟 |

**看板特性**：
- **原子 CAS 认领**：防止多个 Agent 同时认领同一任务
- **依赖跟踪**：任务可声明对其他任务的依赖，被依赖者未完成时无法执行
- **自动分解**：复杂任务可自动分解为多个子任务，父任务被阻塞直到所有子任务完成
- **优先级排序**：按 critical → high → normal → low 排序，同优先级按创建时间 FIFO

### DAG Planner（执行规划器）

基于有向无环图的执行规划，支持波次并行执行：

```
执行计划结构:
plan_id, version, project_id, goal
nodes: [PlanNode, ...]  (不可变，版本化)
waves: [[node_a, node_b], [node_c], [node_d, node_e]]  (同波次并行)

PlanNode:
  node_id, task_type, agent_role, dependencies, params
  status: pending → ready → running → done/failed/skipped
  retry_count, max_retries
```

**RecoveryLevel（恢复层级）**：

| 层级 | 策略 | 触发条件 |
|---|---|---|
| RETRY | 重试（最多 2 次） | 超时、限流、临时失败 |
| STRATEGY_CHANGE | 切换策略（如 develop → develop_simple） | 逻辑错误、验证失败 |
| REPLAN | 完整重规划 | 结构性失败、依赖缺失 |

**计划模板**：

| 模板 | 用途 | DAG 结构 |
|---|---|---|
| `plan_full_game` | 完整游戏开发 | scan → design → [art \|\| music] → develop → qa → build → deploy |
| `plan_prototype` | 快速原型（跳过美术音乐） | design → develop_simple → qa → build |
| `plan_market_scan` | 周期性市场扫描 | scan |
| `plan_update` | 已有游戏更新 | develop → qa → build → deploy |

### Topology Selector（拓扑选择器）

分析 DAG 结构，智能选择编排模式：

| 拓扑类型 | 特征 | 适用场景 |
|---|---|---|
| PARALLEL | 宽而浅，低耦合 | art + music 并行生成 |
| SEQUENTIAL | 链式，高耦合 | 严格顺序依赖的流水线 |
| HIERARCHICAL | 深而窄，lead 委托 | 多级分解任务 |
| HYBRID | 菱形/fan-out+fan-in | 复杂依赖模式 |

**推荐并行度**：基于 DAG 最大宽度 × 并行潜力，估算最优并发任务数。

**速度提升估算**：sequential_time / parallel_time，估算相比串行的加速倍数。

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

### 原型快速模式 (`orchestrator/prototype_mode.py`)

5 分钟内生成可玩原型，跳过美术和详细设计：

```
概念提示 → LLM 最小规格 → Phaser 模板代码 → 构建预览
```

- 使用彩色矩形/emoji 替代美术资产
- Dashboard 一键按钮 "⚡ Prototype"
- 预览后人工决定是否提升为正式项目

### 3 层嵌套错误恢复

| 层级 | 策略 | 行为 |
|------|------|------|
| **Layer 1** | `retry_with_feedback` | 同任务重试最多 2 次，错误信息反馈给 Agent |
| **Layer 2** | `strategy_change` | 切换策略（如 develop → develop_simple），最多 1 次 |
| **Layer 3** | `direction_change` | 创建决策点，暂停项目，等待人类决策；超过 2 次自动取消 |

**Layer 2 Fallback 映射**：

| Task Type | Layer 2 Fallback | 行为 |
|---|---|---|
| `develop` | `develop_simple` | 使用简化策略重新生成代码 |
| `qa` | 无 | 直接 escalate 到 Layer 3 |
| `build` | 无 | 直接 escalate 到 Layer 3 |
| `design_game` | 无 | 直接 escalate 到 Layer 3 |
| `art_gen` | 无 | 直接 escalate 到 Layer 3 |
| `generate_music` | 无 | 直接 escalate 到 Layer 3 |
| `market_scan` | 无 | 直接 escalate 到 Layer 3 |

### 调度器暂停/恢复

支持通过文件标志暂停和恢复整个调度器：

- **暂停机制**：通过 API 创建 `data/.scheduler_paused` 文件标志，调度器在每个 tick 开始时检查该文件
- **恢复机制**：删除暂停文件，调度器恢复正常 tick 循环
- **Dashboard 控制**：提供 "⏸ 下班" / "▶ 上班" 按钮切换暂停状态
- **API 端点**：`POST /api/pipeline/run-scheduler`、`POST /api/pipeline/stop`、`GET /api/pipeline/status`

### 执行入口 (`orchestrator/main.py`)

```bash
# 多项目调度器（推荐）
python3 -m orchestrator.main run-scheduler              # 启动调度器，默认 60s/tick
python3 -m orchestrator.main run-scheduler --interval 60 # 1 分钟一个 tick

# 原型快速模式
python3 -m orchestrator.main run-prototype "space shooter with powerups"

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

### 2a. CFO (`orchestrator/nodes/cfo.py`) — 内部节点，无独立交互入口

模拟 CFO 财务管控角色（作为内部节点自动运行，用户通过 CEO 获取财务信息）：

- **预算预检** (`cfo_budget_check`)：在开发步骤前检查月度和项目预算
  - 开发步骤估算成本 ~$0.10（~50K tokens deepseek-coder）
  - 超预算则终止管道并记录财务事件
  - 无预算配置时默认放行（不设限）
- **财务报告** (`cfo_financial_report`)：生成 30 天财务摘要
  - 汇总 token 用量、按模型/Agent 分组成本
  - 使用 glm-4-flash 生成 AI 财务洞察

### 2b. COO (`orchestrator/nodes/coo.py`) — 内部节点，无独立交互入口

模拟 COO 运营监控角色（作为内部节点自动运行，用户通过 CEO 获取运营信息）：

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

**机制规划层** (`mechanic_planner.py`)：
- GDD 生成后自动分解为有序机制列表
- 每个机制包含：name、description、inputs/outputs、constraints、dependencies、complexity
- 程序员按机制逐一生成代码（核心系统→游戏玩法→打磨）
- 无机制规划时退化为整体生成（向后兼容）

### 4. 美术师 (`agents/dev/artist/`)

通过 **ComfyUI + Stable Diffusion XL** 生成游戏美术资产。**ComfyUI 不是游戏引擎**，它是美术资产生成工具——生成的 PNG 图片由 Phaser 游戏引擎加载使用。

**ComfyUI 的角色**：接到 GDD 中的美术需求 → 调用本地 ComfyUI API → SD XL 生成 PNG → 放入游戏 `public/assets/` → Phaser 通过 `this.load.image()` / `this.add.image()` 加载显示。

**核心组件**：
- `comfyui_client.py` — ComfyUI HTTP API 客户端（queue → poll → download）
- `sprite_generator.py` — 角色精灵、背景、UI 图标生成器
- `workflows.py` — SD XL 工作流定义（含 VAE 连接，兼容 ComfyUI v1.44+）

**资产类型**：
| 类型 | 分辨率 | 用途 |
|---|---|---|
| 背景图 | 800×600 | 菜单、游戏、结算场景背景 |
| 角色精灵 | 64×64 | 玩家、NPC 角色 |
| UI 图标 | 32×32 | 道具、能力、金币等 |

**性能**：RTX 3060 首次生成 ~391s（模型加载），后续 ~10s/张。

**美术风格一致性** (`art_style.py`)：
- 5 种预设风格：pixel_16、pixel_8、cartoon、flat_design、handdrawn
- 每种风格定义 prompt_suffix、negative_prompt、sprite_size、palette
- 根据 genre 自动选择风格（platformer→pixel_16, puzzle→flat_design, idle→cartoon）
- ArtStyleConfig 持久化在项目 GDD 中，确保所有资产生成使用相同风格

**集成方式**：生成的 PNG 放入游戏 `public/assets/`，Phaser 的 BootScene 通过 `this.load.image()` 加载，场景用 `this.add.image()` 替代 `this.add.rectangle()` 矩形占位符。

**ComfyUI 与 Phaser 的关系**：
```
ComfyUI (生成美术)                    Phaser (游戏运行时)
┌─────────────────┐                 ┌──────────────────────┐
│ GDD 美术需求     │                 │ BootScene            │
│      ↓          │                 │   this.load.image()  │
│ SD XL 推理      │  →  PNG 文件 →  │ GameScene            │
│ (本地 GPU)      │     写入磁盘    │   this.add.image()   │
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
- **机制驱动生成**：如果 GDD 包含 mechanics 列表，按依赖顺序逐机制生成代码；否则整体生成
- 强制约束：`import * as Phaser from 'phaser'`（Phaser 4 ESM 无默认导出）
- 游戏代码引用 ComfyUI 生成的美术资产路径（`assets/bg_menu.png`、`assets/player.png` 等），运行时通过 Phaser 加载
- **构建重试机制**：如果 `build_error` 参数非空，自动将错误信息追加到 AI prompt 中，让 AI 修复后重新生成
- **分析埋点**：在生成的游戏代码中注入 `navigator.sendBeacon` 调用，上报 `game_start`/`game_over` 事件（含分数、游戏时长）
- **磁盘管理**：构建完成后自动删除 `node_modules/`，npm 缓存保证后续安装速度
- 生成后自动执行 `npm install && npm run build`
- 使用 `project-dir-timestamp` 模式避免目录冲突
- **Sandbox 隔离**：通过 `ProjectSandbox` 执行 npm 操作，限制内存和超时

### 6. QA 测试员 (`agents/dev/qa/`)

- 检查构建产物是否存在
- 如需构建则执行构建并捕获 stderr
- 失败时返回 `retry_count+1` 和错误详情
- 构建错误会通过 LangGraph 状态传递回 Developer，实现**错误反馈闭环**

**自动化 Playtest** (`auto_playtest.py` + `playtest_checks.py`)：
- 使用 Playwright headless Chromium 执行 8 项自动化验证：
  - 页面加载（无 JS 错误）、Canvas 存在、Canvas 渲染（非零尺寸）
  - 非白屏、交互元素存在、开始按钮可点击
  - 分数系统响应（点击后文本变化）、控制台错误检查
- 容忍度：允许 1 项检查失败
- 返回 playtest score（0-1）和详细检查结果
- 构建成功后自动运行，QA 通过需要 build_ok + playtest_passed

### 7. 构建打包 (`agents/dev/builder/`)

- 执行 `vite build` 生成 `dist/` 目录
- 输出 HTML5 游戏包（单页应用）
- 通过 `ProjectSandbox` 隔离执行，限制超时和资源

### 8. 部署 (`agents/ops/deployer/itch_deployer.py`)

通过 Butler CLI 将游戏推送到 **itch.io**：

- 使用 `BUTLER_API_KEY` 环境变量认证（无需交互式登录）
- 推送到 `{username}/{project_name}:html` 频道
- 注意：游戏页面需预先在 itch.io 手动创建

### 9. 音乐生成 (`agents/dev/music/`)

为游戏生成背景音乐和音效，支持多种后端：

| 后端 | 条件 | 输出 |
|------|------|------|
| **Suno API** | `suno_api_key` 已配置 | AI 生成的 MP3 音乐 |
| **Web Audio 程序化** (默认) | 无需外部 API | 基于振荡器的循环旋律 |

- 程序化 BGM 根据 genre 配置不同参数（tempo/scale/octave）：arcade=140bpm、puzzle=90bpm、rpg=80bpm
- 5 种 SFX：jump、collect、hit、gameover、click（振荡器合成）
- 输出 `bgm.js` + `sfx.js` 到 `assets/audio/`
- 在 DEVELOPING 阶段（art → music → develop）自动执行

### 10. 自动本地化 (`agents/dev/localize/`)

将游戏 UI 文字翻译为多语言，仅面向海外市场（无中文）：

- **字符串提取** (`string_extractor.py`)：从 HTML 文本节点和 JS 字符串中提取可翻译字符串
- **LLM 翻译** (`translator.py`)：使用 glm-4-flash/deepseek 翻译到 15 种语言
- **注入本地化**：生成 `assets/loc/loc.js`，自动注入 `<script>` 标签到 index.html
- 默认翻译前 5 大市场：日语、韩语、西班牙语、葡萄牙语、德语
- 支持语言：ja, ko, es, pt, de, fr, ru, ar, hi, th, vi, id, tr, it, pl
- 在 BUILDING 阶段后自动执行（build → localize → publishing）

---

## 共享模块详解

### Event Sourcing（`shared/events.py` + `orchestrator/event_store.py`）

**不可变事件作为单一真相来源**。

```python
class ActionType(str, Enum):
    # Scheduler lifecycle
    SCHEDULER_TICK_START = "scheduler.tick_start"
    SCHEDULER_TICK_END = "scheduler.tick_end"
    # Task lifecycle
    TASK_ENQUEUED = "task.enqueued"
    TASK_DEQUEUED = "task.dequeued"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRIED = "task.retried"
    # Decision gate
    DECISION_CREATED = "decision.created"
    DECISION_RESOLVED = "decision.resolved"
    # Project lifecycle
    PROJECT_CREATED = "project.created"
    PROJECT_PHASE_CHANGED = "project.phase_changed"
    PROJECT_CANCELLED = "project.cancelled"
    PROJECT_PUBLISHED = "project.published"
    # Agent actions
    AGENT_CALLED = "agent.called"
    AGENT_TOOL_USED = "agent.tool_used"
    # Verification
    VERIFICATION_PLAN_CREATED = "verification.plan_created"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"

@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: ActionType
    timestamp: str  # ISO 8601
    tick_id: int
    project_id: str | None
    agent_name: str | None
    payload: dict[str, Any]
    parent_event_id: str | None  # 因果链
    metadata: dict[str, Any]
```

**SqliteEventStore**（`orchestrator/event_store.py`）：
- **append-only**：只插入不更新，保证事件不可变
- **replay**：支持项目时间线回放，从指定 tick 重放所有事件
- **project timeline**：获取项目所有事件，按时间排序
- **batch append**：支持批量插入提高性能
- 表结构：`event_id, event_type, timestamp, tick_id, project_id, agent_name, payload, parent_event_id, metadata`

**事件发射时机**：
- tick 开始/结束
- 任务入队/出队/完成/失败
- 项目阶段变更
- 决策创建/解决
- 验证计划创建/通过/失败

---

### Kanban Board（`orchestrator/kanban.py`）

**SQLite 背书的看板系统，原子 CAS 认领防止双重领取**。

```python
class KanbanStatus(str, Enum):
    TRIAGED = "triaged"    # 已分析，等待认领
    CLAIMED = "claimed"    # 已被 Agent 认领
    RUNNING = "running"    # 正在执行
    REVIEW = "review"      # 完成，等待验证
    COMPLETED = "completed" # 完成且验证通过
    FAILED = "failed"      # 失败
    BLOCKED = "blocked"    # 依赖未满足
    CANCELLED = "cancelled"# 手动取消

class KanbanPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

@dataclass
class KanbanTask:
    id: str
    project_id: str
    task_type: str
    status: KanbanStatus = KanbanStatus.TRIAGED
    priority: KanbanPriority = KanbanPriority.NORMAL
    params: dict
    result: dict | None = None
    error: str | None = None
    claimed_by: str | None = None
    depends_on: list[str]  # 依赖的任务 ID 列表
    parent_task_id: str | None  # 分解出来的子任务的父任务
    plan_id: str | None  # 所属的执行计划 ID
    retry_count: int = 0
    max_retries: int = 3
```

**核心操作**：
- `add_task`：添加新任务到看板，发射 `TASK_ENQUEUED` 事件
- `claim_task`：原子 CAS 认领（UPDATE WHERE status='triaged'），防止双重领取
- `complete_task`：标记任务完成，发射 `TASK_COMPLETED` 事件
- `fail_task`：标记任务失败，发射 `TASK_FAILED` 事件
- `block_task` / `unblock_task`：阻塞/解除阻塞任务
- `retry_task`：重试失败任务（递增 retry_count，上限 max_retries）
- `auto_decompose`：将复杂任务自动分解为多个子任务，父任务被阻塞

**查询操作**：
- `get_available_tasks`：获取可认领任务（排除依赖未满足的）
- `get_running_tasks`：获取正在运行的任务
- `get_tasks_by_project`：获取项目所有任务
- `count_by_status`：按状态统计任务数量
- `get_board_summary`：获取看板各列计数

---

### DAG Planner（`orchestrator/planner.py`）

**版本化不可变执行计划，基于波次的并行执行**。

```python
class PlanNodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"   # 依赖全部完成
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

class RecoveryLevel(str, Enum):
    RETRY = "retry"           # Level 1: 临时错误，重试
    STRATEGY_CHANGE = "strategy"  # Level 2: 改变策略
    REPLAN = "replan"         # Level 3: 完整重规划

@dataclass
class PlanNode:
    node_id: str
    task_type: str    # e.g., "market_scan", "design_game", "develop"
    agent_role: str    # e.g., "scanner", "designer", "programmer"
    dependencies: list[str]  # 依赖的 node_id 列表
    params: dict
    status: PlanNodeStatus = PlanNodeStatus.PENDING
    result: dict | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2

@dataclass
class ExecutionPlan:
    plan_id: str
    version: int  # 每次结构变更递增
    project_id: str
    goal: str     # 计划的高层描述
    nodes: list[PlanNode]
    created_at: str
    parent_plan_id: str | None  # 跟踪重规划血缘
```

**关键方法**：
- `get_waves()`：通过拓扑排序计算执行波次，同波次内节点可并行执行
- `get_ready_nodes()`：获取依赖全部满足且处于 pending 状态的节点
- `is_complete()`：所有节点均处于 done 或 skipped 状态
- `progress()`：返回完成百分比
- `determine_recovery()`：根据错误特征决定恢复层级（RETRY / STRATEGY_CHANGE / REPLAN）
- `replan()`：从失败节点创建新版本计划，保留已完成节点，替换失败部分

**计划模板**：
- `plan_full_game(project_id, name, genre)`：完整游戏开发（scan → design → [art||music] → develop → qa → build → deploy）
- `plan_prototype(project_id, name, genre)`：快速原型（design → develop_simple → qa → build）
- `plan_market_scan()`：周期性市场扫描
- `plan_update(project_id, name, feedback_count)`：更新已有游戏

---

### Topology Selector（`orchestrator/topology.py`）

**分析 DAG 结构，智能选择最优编排模式**。

```python
class TopologyType(str, Enum):
    PARALLEL = "parallel"    # 宽而浅，低耦合
    SEQUENTIAL = "sequential" # 链式，高耦合
    HIERARCHICAL = "hierarchical"  # 深而窄，lead 委托
    HYBRID = "hybrid"        # 菱形/fan-out+fan-in

@dataclass(frozen=True)
class DAGMetrics:
    node_count: int
    edge_count: int
    max_depth: int
    avg_fan_out: float
    coupling_score: float   # edges / (nodes * (nodes-1)), 0-1
    parallelism_potential: float  # 1 - (longest_path / total_nodes), 0-1
```

**选择规则**：
- **SEQUENTIAL**：线性链（max fan-out == 1，路径跨度覆盖所有节点）
- **PARALLEL**：宽而浅（max fan-out > 2，深度 <= 2）
- **HIERARCHICAL**：深而窄（深度 > 3，max fan-out <= 2）
- **HYBRID**：其他所有情况（菱形、fan-out+fan-in）

**关键方法**：
- `analyze(plan_or_dag)` → `DAGMetrics`：计算 DAG 结构指标
- `select_topology(plan_or_dag)` → `TopologyType`：选择最优拓扑
- `recommend_parallelism(plan_or_dag)` → `int`：推荐最大并发数
- `estimate_speedup(plan_or_dag, max_workers)` → `float`：估算相对串行的加速倍数

---

### Model Router（`shared/model_router.py`）

**多层级模型路由器，基于任务复杂度和成本选择最优模型**。

```python
class ModelTier(str, Enum):
    STRONG = "strong"       # 最佳推理质量
    FAST = "fast"          # 好质量，快速响应
    CHEAP = "cheap"        # 可接受质量，最低成本
    SPECIALIZED_CODE = "code"   # 代码优化模型
    SPECIALIZED_ART = "art"      # 美术生成（ComfyUI）
    SPECIALIZED_AUDIO = "audio" # 音频生成（Suno）

class TaskCategory(str, Enum):
    ARCHITECTURE = "architecture"
    CODE_GENERATION = "code_generation"
    GAME_DESIGN = "game_design"
    MARKET_ANALYSIS = "market_analysis"
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    PLANNING = "planning"
    EVALUATION = "evaluation"
    FORMATTING = "formatting"
    COMMIT_MESSAGE = "commit_message"
    LOG_ANALYSIS = "log_analysis"
    SIMPLE_VALIDATION = "simple_validation"
    INTENT_CLASSIFICATION = "intent_classification"
    CODE_EDIT = "code_edit"
    CODE_REVIEW = "code_review"
    ART_GENERATION = "art_generation"
    MUSIC_GENERATION = "music_generation"

@dataclass
class RoutingDecision:
    model: str
    tier: ModelTier
    category: TaskCategory
    reason: str
    estimated_cost: str  # "low" | "medium" | "high"
    fallback: str | None = None
```

**关键方法**：
- `route(category, complexity, agent_role, prefer_cheaper)` → `RoutingDecision`：根据任务类别和复杂度选择模型
- `route_task_type(task_type, complexity)` → `RoutingDecision`：根据调度器任务类型自动映射到 TaskCategory
- `get_model_for_agent(agent_role)` → `str`：获取 Agent 角色对应的主要模型
- `get_all_tiers()` → `dict`：获取所有配置层级的摘要

**复杂度驱动升降**：
- complexity >= 0.7 且当前层级为 FAST/CHEAP → 自动升级到 STRONG
- complexity < 0.3 且 prefer_cheaper=True 且当前层级为 STRONG → 降级到 FAST

---

### Context Manager（`shared/context_manager.py`）

**4 层渐进压缩，防止 LLM 对话上下文溢出**。

```python
class CompactionLevel(str, Enum):
    NONE = "none"
    SNIP = "snip"        # Layer 1: 清除旧工具结果
    SEGMENT = "segment"  # Layer 2: 总结对话片段
    FULL = "full"        # Layer 3: 完整压缩

@dataclass
class ContextBudget:
    max_tokens: int = 128_000
    soft_threshold: float = 0.70   # 触发后台压缩
    hard_threshold: float = 0.85    # 触发立即压缩
    critical_threshold: float = 0.95  # 触发紧急压缩
    reserved_tokens: int = 4_000    # 为系统 prompt 和响应保留

@dataclass
class ConversationSummary:
    segment_start: int
    segment_end: int
    decisions_made: list[str]
    key_findings: list[str]
    tasks_completed: list[str]
    pending_items: list[str]
    errors_encountered: list[str]
    token_count_approx: int
    summary_text: str
```

**4 层渐进压缩**：

| 层级 | 触发条件 | 策略 | 效果 |
|---|---|---|---|
| Layer 0 | 工具调用前 | Tool Result Budget | 预估 token 成本，检查是否可执行 |
| Layer 1 | 使用率 >= 70% | Snip Compression | 清除旧工具结果，保留最近 3 条 |
| Layer 2 | 使用率 >= 85% | Segment Compression | 总结对话片段，替换为摘要消息 |
| Layer 3 | 使用率 >= 95% | Full Compaction | 完整对话压缩，保留系统 prompt + 摘要 + 最近 2 条 |

**token 估算**：中文约 1.5 字符/token，英文约 4 字符/token。

---

### Verification Framework（`shared/verification.py`）

**验证优先协议：每个 Agent 输出必须经过独立验证**。

```python
class VerificationMode(str, Enum):
    QUICK = "quick"       # 基本检查（文件存在，无语法错误）
    STANDARD = "standard" # 标准检查 + 结构验证
    STRICT = "strict"    # 完整检查 + 回归测试 + 边界情况

class ArtifactType(str, Enum):
    CODE = "code"
    ART = "art"
    GDD = "gdd"
    BUILD = "build"
    MARKET_REPORT = "market_report"
    MUSIC = "music"
    LOCALIZATION = "localization"
    GAME_PACKAGE = "game_package"

@dataclass
class VerificationCheck:
    name: str
    description: str
    check_type: str  # "file_exists" | "command" | "custom" | "schema"
    command: str | None = None
    expected_path: str | None = None
    required: bool = True

@dataclass
class VerificationPlan:
    agent_name: str
    artifact_type: ArtifactType
    artifact_path: str | None
    checks: list[VerificationCheck]
    success_criteria: list[str]
    edge_cases: list[str]
    mode: VerificationMode = VerificationMode.STANDARD

@dataclass
class VerificationResult:
    plan: VerificationPlan
    passed: bool
    check_results: list[CheckResult]
    summary: str
    total_duration_ms: int
```

**内置计划生成器**：
- `plan_for_code(agent_name, code_path, mode)` → `VerificationPlan`：代码验证计划
- `plan_for_build(agent_name, build_path)` → `VerificationPlan`：构建验证计划
- `plan_for_art(agent_name, art_path)` → `VerificationPlan`：美术资源验证计划
- `plan_for_gdd(agent_name)` → `VerificationPlan`：GDD 结构验证计划

**Verifier 执行器**：
- 独立上下文执行，防止自我验证偏差
- 异步执行所有检查
- 必需检查失败则整体失败
- 返回详细失败证据供 Agent 反馈

---

### Sandbox（`shared/sandbox.py`）

**进程级沙箱，隔离高危操作**。

```python
@dataclass
class SandboxConfig:
    working_dir: str = "."
    timeout_secs: int = 120
    max_output_bytes: int = 1_000_000  # 1 MB
    env_vars: dict[str, str] = field(default_factory=dict)

@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
```

**SubprocessSandbox**：
- 通过 `asyncio.create_subprocess_exec` 执行命令
- 超时自动 kill（`asyncio.wait_for` + `proc.kill()`）
- 输出截断到 `max_output_bytes`
- 捕获 returncode / stdout / stderr

**ProjectSandbox**（高级 API）：
- `npm_install(project_path)`：在项目目录执行 npm install
- `npm_build(project_path)`：执行 npm run build
- `type_check(project_path)`：执行 tsc --noEmit
- `list_artifacts(project_path)`：列出构建产物

---

### Code Graph（`shared/code_graph.py`）

**TypeScript/JavaScript 项目依赖图 + PageRank 重要性排名**。

```python
@dataclass
class CodeNode:
    file_path: str
    name: str
    node_type: str  # class | function | interface | import | export
    line_number: int
    references: list[str]

@dataclass
class FileSummary:
    path: str
    exports: list[str]
    imports: list[str]
    classes: list[str]
    functions: list[str]
    size_bytes: int
    line_count: int
```

**关键方法**：
- `build_graph(project_path)`：解析所有 .ts/.js/.tsx/.jsx 文件，构建依赖图
- `get_relevant_context(target_file, token_budget)`：在 token 预算内返回目标文件的相关上下文（按 PageRank + 临近度排序）
- `get_project_map()`：紧凑的字符串项目概览
- `get_dependents(file_path)`：依赖该文件的文件列表（被谁导入）
- `get_dependencies(file_path)`：该文件依赖的文件列表（导入谁）

**PageRank 算法**：考虑节点重要性和文件间临近度（0.4 * PageRank + 0.6 * 临近度）。

---

### Agent Messaging（`shared/agent_messaging.py`）

**SQLite 背书的 Agent 间直接消息传递邮箱**。

```python
MessagePriority = Literal["low", "normal", "high", "critical"]
MessageType = Literal[
    "gdd_update", "bug_report", "feedback_insight",
    "task_request", "task_complete", "status_update",
    "question", "directive",
]

@dataclass
class Message:
    id: str
    from_agent: str
    to_agent: str
    message_type: str
    payload: dict | str
    priority: MessagePriority = "normal"
    read: bool = False
    timestamp: str
```

**AgentMailbox 操作**：
- `send(from_agent, to_agent, msg_type, payload, priority)` → `str`：发送消息（异步，插入 WAL 模式 SQLite）
- `receive(agent_name, msg_type, timeout)` → `Message | None`：接收下一条未读消息（按优先级排序）
- `broadcast(from_agent, msg_type, payload, agents)` → `list[str]`：广播消息到所有已知 Agent
- `get_pending_count(agent_name)` → `int`：获取未读消息数
- `get_all_messages(agent_name, limit)` → `list[Message]`：获取所有消息（最新优先）

**优先级排序**：`critical > high > normal > low`，同优先级按创建时间 ASC。

---

### Skills System（`skills/`）

**可插拔的 Agent 能力系统，条件激活**。

```python
@dataclass
class SkillContext:
    task_type: str
    project_id: str | None = None
    agent_role: str = ""
    artifact_path: str | None = None
    params: dict = field(default_factory=dict)
    project_state: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

@dataclass
class SkillResult:
    skill_name: str
    success: bool
    output: dict = field(default_factory=dict)
    message: str = ""
    artifacts: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=dict)

class Skill(ABC):
    skill_name: str = ""
    skill_description: str = ""
    skill_version: str = "1.0.0"
    skill_dependencies: list[str] = []
    skill_conflicts: list[str] = []

    @abstractmethod
    def should_activate(self, context: SkillContext) -> bool: ...

    @abstractmethod
    async def execute(self, context: SkillContext) -> SkillResult: ...

class SkillRegistry:
    _skills: dict[str, type[Skill]]
    @classmethod
    def register(cls, skill_cls: type[Skill]) -> type[Skill]: ...
    @classmethod
    def get_skill(cls, name: str) -> type[Skill] | None: ...
    @classmethod
    def get_applicable_skills(cls, context: SkillContext) -> list[Skill]: ...
    @classmethod
    def get_all_skills(cls) -> dict[str, str]: ...
```

**内置 Skill**：

| Skill | 说明 | 激活条件 |
|---|---|---|
| **CodeReviewSkill** | 生成后代码质量审查 | task_type in (develop, develop_simple) 且有 artifact_path |

**CodeReviewSkill 审查标准**：
1. TypeScript 类型安全（无 any 类型，正确的接口）
2. 错误处理（无空 catch 块）
3. 游戏架构（正确的场景管理，资源加载）
4. 性能（无不必要的重渲染，正确的清理）

---

### Tool Registry（`shared/tools.py`）

**集中式工具管理，自注册机制**。

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    category: str  # file_ops | code_gen | art | deploy | analysis | memory | verification
    handler: Callable[..., Coroutine[Any, Any, dict]]
    input_schema: dict[str, Any] = field(default_factory=dict)
    permission_level: int = 1  # 1=read, 2=write, 3=execute, 4=admin
    is_concurrency_safe: bool = True
    cost_estimate: str = "low"  # low | medium | high
    agent_roles: list[str] = field(default_factory=list)

class ToolRegistry:
    _tools: dict[str, ToolSpec]

    @classmethod
    def register(cls, name, category, description, ...) -> Callable: ...

    @classmethod
    def get_tool(cls, name: str) -> ToolSpec | None: ...
    @classmethod
    def get_all_tools(cls) -> dict[str, ToolSpec]: ...
    @classmethod
    def get_tools_by_category(cls, category: str) -> list[ToolSpec]: ...
    @classmethod
    def get_tools_for_agent(cls, agent_role: str, declared_tools) -> list[ToolSpec]: ...
    @classmethod
    def get_concurrent_safe_tools(cls, tool_names: list[str]) -> list[ToolSpec]: ...
    @classmethod
    def tool_exists(cls, name: str) -> bool: ...
    @classmethod
    def count(cls) -> int: ...
    @classmethod
    def list_tool_names(cls) -> list[str]: ...
```

**工具分类**：
- `file_ops`：文件操作（读、写、搜索）
- `code_gen`：代码生成
- `art`：美术生成
- `deploy`：部署
- `analysis`：分析
- `memory`：记忆系统
- `verification`：验证

---

## Dashboard 监控

Dashboard 运行在独立进程（FastAPI + 静态 HTML/CSS/JS），与管道解耦。

### 完整 API 端点列表（38 个）

| 路径 | 方法 | 用途 | 鉴权 |
|---|---|---|---|
| **状态与信息** | | | |
| `GET /api/status` | GET | 系统状态 | 否 |
| `GET /api/agents` | GET | Agent 日志和统计 | 否 |
| `GET /api/market/report` | GET | 最新市场分析报告 | 否 |
| `GET /api/market/latest` | GET | 最新市场信号 | 否 |
| `GET /api/projects` | GET | 所有项目列表 | 否 |
| `GET /api/pipeline/history` | GET | 编排器历史 | 否 |
| `GET /api/memory` | GET | 公司记忆 | 否 |
| `GET /api/gdd/{project_id}` | GET | 项目 GDD | 否 |
| **项目控制** | | | |
| `POST /api/pipeline/run-scheduler` | POST | 启动调度器 | **是** |
| `POST /api/pipeline/stop` | POST | 停止调度器 | **是** |
| `GET /api/pipeline/status` | GET | 调度器状态 | 否 |
| `POST /api/projects/{id}/pause` | POST | 暂停项目 | **是** |
| `POST /api/projects/{id}/resume` | POST | 恢复项目 | **是** |
| `POST /api/projects/{id}/cancel` | POST | 取消项目 | **是** |
| `POST /api/projects/{id}/advance` | POST | 推进项目阶段 | 否 |
| `GET /api/projects/live` | GET | 已上线项目列表 | 否 |
| `GET /api/projects/{id}/documents` | GET | 项目所有文档 | 否 |
| **分析** | | | |
| `POST /api/analytics/event` | POST | 游戏遥测事件 | 否 |
| `GET /api/analytics/summary` | GET | 分析摘要 | 否 |
| `GET /api/itch/stats` | GET | itch.io 统计数据 | 否 |
| `POST /api/itch/refresh` | POST | 刷新 itch 统计 | 否 |
| **反馈** | | | |
| `GET /api/feedback/{project_id}` | GET | 项目反馈列表 | 否 |
| **WebSocket** | | | |
| `WS /ws/events` | WS | 实时事件流 | **条件** |
| **聊天** | | | |
| `POST /api/chat/send` | POST | 发送消息给 CEO | **是** |
| `GET /api/chat/history` | GET | 聊天历史 | 否 |
| **事件** | | | |
| `GET /api/events` | GET | 最近事件 | 否 |
| **财务** | | | |
| `POST /api/finance/budget` | POST | 设置预算 | **是** |
| `GET /api/finance/summary` | GET | 财务摘要 | 否 |
| **策略** | | | |
| `GET /api/policy` | GET | 获取公司策略 | 否 |
| `POST /api/policy` | POST | 设置公司策略 | **是** |
| **决策** | | | |
| `GET /api/decisions` | GET | 待处理决策列表 | 否 |
| `GET /api/decisions/history` | GET | 决策历史 | 否 |
| `POST /api/decisions/{id}/respond` | POST | 回复决策 | **是** |
| **编排器** | | | |
| `GET /api/orchestrator/projects` | GET | 所有项目（编排器） | 否 |
| `GET /api/orchestrator/projects/{id}` | GET | 单项目详情 | 否 |
| `GET /api/orchestrator/tasks` | GET | 任务列表 | 否 |
| **记忆** | | | |
| `GET /api/memory/{project_id}/recent` | GET | 项目近期记忆 | 否 |
| `GET /api/memory/search` | GET | 搜索长期记忆 | 否 |
| `GET /api/memory/lessons` | GET | 所有经验教训 | 否 |
| **游戏预览** | | | |
| `GET /games-preview/{path}` | GET | 静态游戏文件服务 | 否 |

### 前端功能

- **Project Board** — 看板式项目面板（Backlog → Design → Dev → Test → Build → Live），每项目独立进度，内联 approve/reject 和文档查看按钮
- **Task Monitor** — 任务监控列表，实时显示状态/进度/耗时
- **Executive Chat** — 仅与 CEO 对话（CFO/COO 为内部节点），含决策卡片（批准/拒绝/讨论按钮）
- **Document Viewer** — 文档查看弹窗，查看所有 Agent 工作文档（proposal、GDD、market scan、art report、music report、QA report、build report）
- **Market Trends** — 市场趋势面板，来源健康度、趋势方向、跨源确认
- **Company Event Log** — 终端风格实时滚动日志
- **Agent Monitor** — 各 Agent 执行状态
- **Active Games** — 构建的游戏列表，支持 iframe 预览
- **Company Memory** — 长期记忆
- **Scheduler Control** — 调度器暂停/恢复按钮（"⏸ 下班" / "▶ 上班"）
- **24/7 Mode Toggle** — 一键启停 24/7 运行模式
- **CEO Reports** — CEO 主动汇报取代原 Scheduler Reports，展示项目进展和决策建议
- **⚡ Prototype Button** — 快速原型模式（输入概念 → 5 分钟生成可玩 demo）
- **Run Pipeline Button** — 一键启动管道

---

## 数据持久化

系统使用 **SQLite** 数据库存储所有运营数据（路径：`data/gcagents.db`）。

### 表结构（19 张表）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `projects` | 多项目编排（项目看板） | id, name, genre, phase, progress, awaiting_decision |
| `decisions` | 决策门控（人类审批） | id, project_id, decision_type, question, status, human_response |
| `tasks` | 任务队列（异步执行） | id, project_id, task_type, status, progress, result, error |
| `kanban_tasks` | 看板任务（Kanban Board） | id, project_id, task_type, status, priority, params, claimed_by, depends_on |
| `orchestrator_state` | 经典管道状态追踪 | phase, current_project_id, errors, updated_at |
| `company_policy` | 公司策略配置 | budget_limit_usd, preferred_genres, auto_publish, max_active_projects |
| `agent_logs` | 每个 Agent 节点的执行日志 | node_name, status, duration_ms, error |
| `market_reports` | AI 市场分析报告 | signals_count, opportunities_json, raw_analysis |
| `market_signals` | 原始市场信号（12 源） | source, genre, title, score, captured_at |
| `game_projects` | 游戏项目记录 | name, genre, status, gdd, itch_url, current_version |
| `game_feedback` | 用户反馈（itch.io 评论抓取）| project_id, category, content, processed |
| `game_versions` | 版本快照 | project_id, version, gdd_snapshot, changelog |
| `game_metrics` | 游戏遥测数据 | project_id, metric_name, metric_value |
| `api_usage_logs` | LLM 调用追踪 | model, agent_name, total_tokens, estimated_cost_usd |
| `finance_budgets` | 预算配置 | category, budget_type, budget_limit_usd, spent_usd |
| `chat_messages` | 高管聊天记录 | role, content, agent_name, metadata_json |
| `event_logs` | 公司事件日志 | event_type, severity, title, source_agent |
| `company_memory` | 公司长期记忆 | category, title, content, importance |
| `domain_events` | 事件溯源（Event Store） | event_id, event_type, timestamp, tick_id, project_id, payload |
| `agent_mailbox` | Agent 间消息传递 | id, from_agent, to_agent, message_type, payload, priority, read |
| `itch_stats` | itch.io 统计数据 | game_name, downloads_count, plays_count, last_updated |

### 写入时机

| 事件 | 写入内容 |
|---|---|
| 项目阶段变更 | `projects` 更新 phase/progress |
| 决策创建/解决 | `decisions` 记录人类决策 |
| 任务执行 | `tasks` 记录状态/进度/结果 |
| 看板任务操作 | `kanban_tasks`（claim/complete/fail/block） |
| 每个节点执行完成 | `agent_logs` 写入耗时 + 状态 |
| 每次LLM调用 | `api_usage_logs` 写入 token 用量 + 成本 |
| 市场扫描完成 | `market_signals` + `market_reports` |
| 管道阶段变更 | `orchestrator_state` + `game_projects` |
| 部署完成 | `game_versions`（版本号 + GDD 快照） |
| 反馈收集 | `game_feedback`（itch.io 评论 + AI 分类） |
| 游戏运行 | `game_metrics`（分析事件埋点上报） |
| 财务操作 | `finance_budgets` + `event_logs` |
| 高管聊天/决策 | `chat_messages`（含决策卡片） |
| 记忆存储 | `memories`（短期事件 + 长期教训） |
| 项目完成 | `memories` consolidate（短期→长期提取） |
| 所有重要事件 | `event_logs` + `domain_events`（双重写入） |
| Agent 间消息 | `agent_mailbox` |

---

## Dashboard 安全模型

Dashboard 提供双模式安全策略：

| 模式 | 触发条件 | 监听地址 | 控制面鉴权 |
|------|---------|---------|-----------|
| **本地开发（默认）** | 未设置 `DASHBOARD_API_KEY` | `127.0.0.1` | 无（仅本机访问） |
| **生产/远程** | 设置 `DASHBOARD_API_KEY` | `0.0.0.0` | 控制面端点需 `X-API-Key` header |

**输入验证**：
- `interval` 参数：`Query(ge=1, le=3600)` — 防止 DoS
- `budget_limit_usd`：必须为非负数（`>= 0`）
- `q` 查询参数：必填，防止空查询

**CEO 动作白名单**：
- `create_project`：创建新项目
- `cancel_project`：取消项目
- `publish_project`：发布项目
- `update_project`：更新项目
- `pause_project`：暂停项目

**控制面端点**（需鉴权）：`POST /api/pipeline/{run-scheduler,stop}`、`POST /api/projects/{id}/{pause,resume,cancel}`、`POST /api/decisions/{id}/respond`、`POST /api/chat/send`、`POST /api/finance/budget`、`POST /api/policy`、`WS /ws/events`（支持 `?api_key=` 查询参数回退）。

**公开端点**：所有 `GET` 请求 + `POST /api/analytics/event`（浏览器游戏埋点，无需鉴权）。

CORS 默认仅允许 `http://localhost:8080`；可通过 `DASHBOARD_CORS_ORIGINS` 环境变量（逗号分隔）扩展。

鉴权失败返回 `401 {"detail": "Invalid or missing X-API-Key"}`。

---

## 测试与质量

### 测试套件

使用 `pytest` + `pytest-asyncio`，测试位于 `tests/` 目录：

| 文件 | 覆盖模块 | 关键测试 |
|------|---------|---------|
| `test_persistence.py` | `orchestrator/persistence.py` | 表创建、ORM 操作 |
| `test_scheduler.py` | `orchestrator/scheduler.py` | tick 执行、任务调度、错误恢复 |
| `test_decision_gate.py` | `orchestrator/decision_gate.py` | 决策创建/解决流程 |
| `test_llm_client.py` | `shared/llm_client.py` | 成本估算、429 重试 |
| `test_models.py` | `shared/models.py` | Pydantic 模型验证 |
| `test_memory.py` | `shared/memory.py` | 分层记忆存储/检索 |
| `test_config.py` | `shared/config.py` | 配置加载 |
| `test_exceptions.py` | `shared/exceptions.py` | 异常层级 |
| `test_complexity.py` | `shared/complexity.py` | 游戏复杂度评分 |
| `test_scanner.py` | `agents/research/scanner.py` | 市场扫描 |
| `test_nodes.py` | `orchestrator/nodes/` | CEO/CFO/COO 节点 |
| `test_api_server.py` | `dashboard/web/api_server.py` | API 端点测试 |
| `test_code_generator.py` | `agents/dev/programmer/code_generator.py` | 代码生成 |
| `conftest.py` | — | pytest fixtures、临时 SQLite |
| `__init__.py` | — | 测试包初始化 |

**总计**：15 个测试文件，覆盖 orchestrator、shared、agents、dashboard 所有核心模块。

DB 测试使用 `tmp_path` 临时 SQLite，monkeypatch `_get_engine()`，不污染 `data/gcagents.db`。所有异步测试使用 `@pytest.mark.asyncio`。

### 持续集成

`.github/workflows/ci.yml` 在 push/PR 到 `master`/`main` 时运行：

- `ruff check .`（lint）
- `ruff format --check .`（格式检查）
- `mypy orchestrator shared agents dashboard`（类型检查，aspirational strict，使用 `continue-on-error`）
- `pytest tests/ -v`（测试，覆盖率门槛 60%）

Python 3.11/3.12 matrix，job timeout 10 分钟，pip 缓存。

### 错误恢复策略

#### Layer 2 Fallback 映射

只有 `develop → develop_simple` 有真实的 Layer 2 策略变更。其他所有 task type 在 Layer 1 重试耗尽后直接跳到 Layer 3（人类决策），避免无效的 identity re-queue。

| Task Type | Layer 2 Fallback | 行为 |
|---|---|---|
| `develop` | `develop_simple` | 使用简化策略重新生成代码 |
| `qa` | 无 | 直接 escalate 到 Layer 3 |
| `build` | 无 | 直接 escalate 到 Layer 3 |
| `design_game` | 无 | 直接 escalate 到 Layer 3 |
| `art_gen` | 无 | 直接 escalate 到 Layer 3 |
| `generate_music` | 无 | 直接 escalate 到 Layer 3 |
| `market_scan` | 无 | 直接 escalate 到 Layer 3 |

---

## 项目结构

```
gcagents/
├── orchestrator/           # 核心编排
│   ├── main.py             #   CLI 入口（run/run-forever/run-scheduler/run-prototype/scan）
│   ├── scheduler.py        #   CEO 多项目调度器（tick-based + 3 层错误恢复）
│   ├── task_queue.py       #   SQLite-backed FIFO 任务队列
│   ├── kanban.py           #   Kanban Board（原子 CAS 认领，状态机管理）
│   ├── planner.py          #   DAG Planner（波次并行执行，版本化计划）
│   ├── topology.py         #   Topology Selector（DAG 分析，编排模式选择）
│   ├── event_store.py      #   SQLite Event Store（append-only，事件溯源）
│   ├── decision_gate.py    #   决策门控（5 类人类审批）
│   ├── event_bus.py        #   统一事件发射（log_event + emit）
│   ├── state.py            #   全局状态定义（CompanyState, PipelinePhase）
│   ├── persistence.py      #   SQLite 持久化（19 张表）
│   ├── prototype_mode.py   #   原型快速模式（5 分钟 demo）
│   └── graph/
│       └── pipeline.py     #   经典线性管道（LangGraph，兼容）
│   └── nodes/
│       ├── ceo.py          #   CEO 评估（经典模式 + 调度器反馈驱动更新）
│       ├── cfo.py          #   CFO 预算预检 + 财务报告
│       └── coo.py          #   COO 健康检查 + 运营指令
├── agents/                 # AI Agent 实现
│   ├── research/           #   市场研究（12 个数据源）
│   │   ├── scanner.py      #     多源扫描
│   │   ├── analyzer.py    #     增强分析（跨源关联/竞品密度/趋势方向）
│   │   └── sources/
│   │       └── fetchers.py #     itch/reddit/steam/youtube/tiktok/...
│   └── dev/
│       ├── designer/       #     GDD 生成 + 机制规划
│       │   ├── agent.py    #       design_game Agent
│       │   ├── gdd_generator.py  # GDD 生成器
│       │   └── mechanic_planner.py  # 机制分解（GDD → 有序机制列表）
│       ├── artist/         #     美术生成 (ComfyUI SD XL)
│       │   ├── art_agent.py    # art_gen Agent
│       │   ├── art_node.py     # generate_art 入口
│       │   ├── art_style.py    # 美术风格一致性（5 种预设）
│       │   ├── comfyui_client.py  # ComfyUI HTTP 客户端
│       │   ├── sprite_generator.py  # 角色/背景/UI 生成器
│       │   └── workflows.py    # SD XL 工作流定义
│       ├── programmer/     #     代码生成 (deepseek/MiniMax-M2.1)
│       │   ├── agent.py    #     develop_game Agent
│       │   └── code_generator.py  # Phaser 4 + TypeScript 代码生成
│       ├── qa/             #     质量测试
│       │   ├── qa_agent.py #       run_qa Agent
│       │   ├── auto_playtest.py  # Playwright 自动化 playtest
│       │   └── playtest_checks.py  # 8 项验证检查
│       ├── music/          #     音乐生成（Web Audio 程序化 + Suno API）
│       │   └── music_generator.py
│       ├── localize/       #     自动本地化（15 种语言）
│       │   ├── string_extractor.py  # 字符串提取 + 注入
│       │   └── translator.py       # LLM 翻译
│       └── builder/        #     Vite 构建
│           └── build_agent.py
├── ops/
│   ├── deployer/
│   │   ├── itch_deployer.py  # Butler CLI itch.io 部署
│   │   └── itch_stats.py     # itch.io 统计抓取
│   └── analytics/
│       └── feedback_collector.py  # itch.io 评论抓取
├── dashboard/web/
│   ├── api_server.py      #   FastAPI 后端（38 个 API 端点 + WebSocket）
│   ├── index.html         #   前端（项目看板/任务监控/决策卡片/文档查看器/市场趋势）
│   ├── app.js             #   前端逻辑（CEO 聊天、决策卡片、看板）
│   └── style.css          #   样式
├── shared/                 # 共享模块
│   ├── config.py           #   配置加载 (pydantic-settings)
│   ├── models.py           #   数据模型（ProjectState/DecisionPoint/TaskRecord + 原有模型）
│   ├── memory.py           #   分层记忆系统（短期事件 + 长期教训 + 项目上下文）
│   ├── llm_client.py       #   统一 LLM 客户端（token 追踪 + 成本记录 + 重试退避）
│   ├── exceptions.py       #   领域异常层级（SchedulerError/TaskExecutionError/...）
│   ├── constants.py        #   集中常量（超时/阈值/截断长度）
│   ├── complexity.py      #   游戏复杂度评分（GDD + 代码）
│   ├── events.py          #   Event Sourcing 核心（ActionType/Event）
│   ├── model_router.py    #   6 层模型路由器
│   ├── context_manager.py #   4 层渐进压缩上下文管理
│   ├── verification.py    #   Verification Framework（strict/soft/advisory）
│   ├── sandbox.py         #   SubprocessSandbox + ProjectSandbox
│   ├── code_graph.py      #   TypeScript/JavaScript 依赖图 + PageRank
│   ├── agent_messaging.py #   SQLite Agent 邮箱
│   └── tools.py           #   ToolRegistry + @register 装饰器
├── skills/                 # Skills 系统
│   ├── base.py            #   Skill ABC + SkillRegistry 自注册
│   └── code_review.py     #   CodeReviewSkill（生成后代码质量审查）
├── tools/                  # 工具实现
│   ├── file_ops.py        #   文件操作工具
│   ├── code_gen.py        #   代码生成工具
│   ├── art.py             #   美术生成工具
│   └── deploy.py          #   部署工具
├── config/
│   ├── agents.yaml        #   Agent 与模型映射（6 层 tier 配置）
│   └── sources.yaml       #   12 个市场数据源配置
├── scripts/
│   ├── e2e_test.py        #   端到端测试
│   └── setup_local.py     #   本地环境配置
├── tests/                 # 测试套件（15 个文件）
│   ├── conftest.py        #   pytest fixtures
│   ├── test_scheduler.py  #   调度器测试
│   ├── test_persistence.py # 持久化测试
│   ├── test_decision_gate.py # 决策门控测试
│   ├── test_llm_client.py #   LLM 客户端测试
│   ├── test_models.py     #   数据模型测试
│   ├── test_memory.py     #   记忆系统测试
│   ├── test_config.py     #   配置加载测试
│   ├── test_exceptions.py #   异常测试
│   ├── test_complexity.py #   复杂度评分测试
│   ├── test_scanner.py    #   市场扫描测试
│   ├── test_nodes.py      #   Agent 节点测试
│   ├── test_api_server.py #   API 服务器测试
│   └── test_code_generator.py # 代码生成测试
├── data/                  # 运行数据 (gitignored)
│   ├── gcagents.db        #   SQLite 数据库
│   └── games/             #   生成游戏项目
└── .env                   # API 密钥 (gitignored)
```

---

## 关键技术决策

### 为什么用 Event Sourcing？

- **不可变性**：append-only 事件保证数据完整性，支持审计和回放
- **因果追踪**：parent_event_id 建立因果链，定位问题根因
- **时间旅行**：任意时间点的项目状态可通过重放事件重建
- **解耦**：事件驱动的架构使各模块低耦合，通过事件总线通信

### 为什么用 Kanban Board 替代 FIFO？

- **状态可见性**：任务所处阶段一目了然（triaged/claimed/running/review/completed）
- **优先级管理**：critical/high/normal/low 四级优先级，而非单纯时间顺序
- **防止双重领取**：原子 CAS 认领保证同一任务同一时间只被一个 Agent 处理
- **依赖跟踪**：任务可声明对其他任务的依赖，被依赖者未完成时无法执行
- **自动分解**：复杂任务可分解为多个子任务，父任务自动阻塞

### 为什么用 DAG Planner？

- **并行感知**：波次内任务可并行执行，最大化资源利用率
- **依赖可视化**：DAG 结构清晰展示任务间的数据流和控制流
- **结构化恢复**：失败节点可基于 DAG 结构决定是重试、换策略还是重规划
- **拓扑优化**：TopologySelector 可根据 DAG 特征选择最优编排模式
- **版本化**：每次结构变更创建新版本计划，支持回溯和比较

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
- **ComfyUI 美术集成**：通过 SD XL 生成真实游戏资产替代矩形占位符
- **Vite 构建**：现代打包工具，输出为单 HTML5 文件

---

## 开发日志与演进

| 版本 | 日期 | 变更 |
|---|---|---|
| 初始 | — | 基础框架搭建：LangGraph 状态机、市场扫描、代码生成 |
| 迭代 | — | Dashboard 监控面板、CEO 决策、QA 循环、Build 阶段 |
| 迭代 | — | ComfyUI 美术管线、反馈闭环、版本管理、分析埋点 |
| 迭代 | — | 统一 LLM 客户端、CFO/COO Agent、高管聊天面板、财务 API |
| 迭代 | — | 24/7 运行模式、Dashboard 启停按钮 |
| **当前** | — | **多项目编排重构**：CEO 调度器、决策门控（5 类）、任务队列、12 市场数据源、项目看板、任务监控、决策卡片、市场趋势面板 |
| **v2** | — | **8 项增强**：自动化 Playtest（Playwright 8 项检查）、机制规划层（GDD→有序机制→逐机制代码生成）、3 层嵌套错误恢复、美术风格一致性（5 种预设）、原型快速模式（5 分钟 demo）、分层记忆系统（短期+长期）、音乐生成（Web Audio+Suno）、自动本地化（15 种语言） |
| **v3** | — | **代码质量与安全强化**：修复 `orchestrator_state` 表缺失 bug（管线状态追踪静默失败）；添加 Dashboard `X-API-Key` 鉴权（localhost-only 回退模式 + CORS 收紧）；新增 pytest 测试套件（14 个测试 + 3 个回归测试）；新增 GitHub Actions CI（ruff + mypy + pytest）；新增 README.md 用户入口；ARCHITECTURE.md 更新 |
| **v4** | — | **Dashboard UX 重构**：CEO-only 交互模式（CFO/COO 转为内部节点，移除独立交互 tab）；文档查看器（所有 Agent 工作文档可通过弹窗查看）；项目看板内联审批按钮（approve/reject/document 直接在项目卡片上操作）；调度器暂停/恢复功能（文件标志 + Dashboard "⏸ 下班" 按钮）；CEO 汇报取代 Scheduler Reports；新增 API：`/api/scheduler/{pause,resume,paused}`、`/api/projects/{id}/documents` |
| **v5** | 2026-06-04 | **代码质量审查与新系统添加**：<br>• 安全修复：路径遍历漏洞修复（`data/gcagents.db` 使用 Path 安全拼接）<br>• bare-except 清理：所有裸 except 块替换为具体异常类型<br>• 输入验证：`interval` 参数 `Query(ge=1, le=3600)`，预算非负检查<br>• **8 个共享模块**：Event Sourcing (events.py)、Model Router (model_router.py)、Context Manager (context_manager.py)、Verification Framework (verification.py)、Sandbox (sandbox.py)、Code Graph (code_graph.py)、Agent Messaging (agent_messaging.py)、Tool Registry (tools.py)<br>• **4 个编排器模块**：Kanban Board (kanban.py)、DAG Planner (planner.py)、Topology Selector (topology.py)、Event Store (event_store.py)<br>• **Skills/Tools 框架**：Skill ABC + 自注册装饰器、CodeReviewSkill、ToolRegistry + @register<br>• **6 层模型路由**：strong/fast/cheap/code/art/audio，配置于 agents.yaml<br>• **38 个 API 端点**：完整列表覆盖项目管理、任务调度、分析、聊天、财务、决策、记忆、游戏预览等 |

---

## 部署要求

### 环境变量 (`.env`)

```
DEEPSEEK_API_KEY=sk-...        # deepseek-v4-flash 代码生成
MINIMAX_API_KEY=...            # MiniMax-M3 分析 + MiniMax-M2.1 代码
ZHIPU_API_KEY=...              # glm-4-flash 便宜任务
BUTLER_API_KEY=...             # itch.io Butler 部署
BUTLER_USERNAME=...            # itch.io 用户名
SUNO_API_KEY=...               # 音乐生成（可选）
DASHBOARD_API_KEY=...          # Dashboard 生产鉴权（可选）
DASHBOARD_CORS_ORIGINS=...     # CORS 允许的域名（逗号分隔，可选）
```

### 系统依赖

- Python 3.11+
- Node.js 18+ (游戏构建)
- Butler CLI v15+ (itch.io 部署，可选)
- ComfyUI + Stable Diffusion XL (美术生成，需 GPU，可选)
- Suno API (音乐生成，可选)

### 启动

```bash
# 多项目调度器（推荐）
python3 -m orchestrator.main run-scheduler
python3 -m orchestrator.main run-scheduler --interval 60

# 原型快速模式
python3 -m orchestrator.main run-prototype "space shooter with powerups"

# 经典模式
python3 -m orchestrator.main run
python3 -m orchestrator.main run-forever

# 仅市场扫描
python3 -m orchestrator.main scan

# 启动监控面板
python3 -m dashboard.web.api_server
# 访问 http://localhost:8080
```

---

*最后更新：v5 (2026-06-04)*