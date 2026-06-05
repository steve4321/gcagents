# GCAgents 架构文档

> 本文档是 [`README.md`](README.md) 的深度补充。读者画像：架构师、贡献者、运维。请先读 README 第 1 章建立整体认知，再按需查本文件。
>
> 全文统一术语参见 [附录 A 术语表](#附录-a-术语表)。

---

## 目录

- [第 0 章 概述](#第-0-章-概述)
- [第 1 章 系统架构总览](#第-1-章-系统架构总览)
- [第 2 章 AI 模型与工具策略](#第-2-章-ai-模型与工具策略)
- [第 3 章 核心工作流 —— 多项目调度器](#第-3-章-核心工作流--多项目调度器)
- [第 4 章 Agent 节点详解](#第-4-章-agent-节点详解)
- [第 5 章 共享模块详解](#第-5-章-共享模块详解)
- [第 6 章 Visual Novel 专属管线](#第-6-章-visual-novel-专属管线)
- [第 7 章 数据持久化（24 张表）](#第-7-章-数据持久化24-张表)
- [第 8 章 Dashboard 详解（13 分区 + 44 端点）](#第-8-章-dashboard-详解13-分区--44-端点)
- [第 9 章 Dashboard 安全模型](#第-9-章-dashboard-安全模型)
- [第 10 章 测试与持续集成](#第-10-章-测试与持续集成)
- [第 11 章 部署与运维](#第-11-章-部署与运维)
- [第 12 章 关键技术决策（Why）](#第-12-章-关键技术决策why)
- [第 13 章 开发日志](#第-13-章-开发日志)
- [附录 A 术语表](#附录-a-术语表)
- [附录 B 端点速查](#附录-b-端点速查)

---

## 第 0 章 概述

GCAgents 是一个**多项目并行运作的 AI 游戏公司**系统。它像一家真实的游戏公司一样运转：CEO 统一调度多个项目，每个项目独立推进（调研、设计、开发、测试、构建、发布），重要决策必须经过人类批准。12 个市场数据源提供情报支撑，Dashboard 实时展示项目看板、任务监控、决策卡片与公司记忆。

**核心理念**：

- **AI Agent 模拟组织架构**：CEO 作为调度大脑管理多个并行项目
- **CEO 单一交互模式**：用户只与 CEO 对话；CFO / COO 作为内部节点自动运行，不提供独立交互入口
- **5 类人类审批门控**：新项目启动、发布上线、项目取消、预算超限、方向调整
- **12 个市场数据源跨源关联分析**
- **每项目独立生命周期、互不阻塞**
- **事件溯源**：所有状态变化记录为不可变事件，支持回放与审计
- **任务看板调度**：原子 CAS 认领，依赖跟踪，状态机管理
- **DAG 波次并行执行**：结构化恢复（重试 → 换策略 → 重规划）
- **验证框架**：每个 Agent 输出独立验证，支持严格 / 标准 / 提示性三模式
- **文档查看器**：所有 Agent 工作产物（提案 / GDD / 市场报告 / 美术 / 音乐 / QA / 构建）通过 Dashboard 弹窗查看

---

## 第 1 章 系统架构总览

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          GCAgents 系统                                    │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │               CEO 调度器（tick 节拍、多项目并行）                      │ │
│  │   每个 tick：处理指令 → 检查决策点 → 推进项目 → 执行任务 → 汇报       │ │
│  └────┬──────────┬──────────┬──────────┬───────────────────────────────┘ │
│       │          │          │          │                                │
│  ┌────▼────┐ ┌───▼────┐ ┌───▼────┐ ┌──▼─────────┐                      │
│  │ 项目 A  │ │ 项目 B │ │ 项目 C │ │ 市场扫描器 │                       │
│  │ 开发中  │ │ 设计中 │ │ 待批准 │ │ (12 数据源)│                       │
│  └────┬────┘ └───┬────┘ └───┬────┘ └──┬─────────┘                      │
│       │          │          │         │                                 │
│  ┌────▼──────────▼──────────▼─────────▼──────────────────────────────┐ │
│  │              任务看板 + 任务队列                                     │ │
│  │  triaged → claimed → running → review → completed / failed / blocked│ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  ┌─────────────────┐  ┌──────────────────────────────────────────────┐ │
│  │   事件存储       │  │              模型路由器                       │ │
│  │   事件溯源       │  │  6 层：strong / fast / cheap / code / art / audio│
│  │   不可变事件     │  │  实配：MiniMax-M3 / MiniMax-M2.1 /            │ │
│  └─────────────────┘  │  deepseek-v4-flash / glm-4-flash / SD XL / suno│ │
│                       └──────────────────────────────────────────────┘ │
│  ┌─────────────────┐  ┌──────────────────────────────────────────────┐ │
│  │   DAG 规划器    │  │   上下文管理器（4 层渐进压缩）                  │ │
│  │   波次并行      │  │   raw → summarized → compressed → minimal    │ │
│  └─────────────────┘  └──────────────────────────────────────────────┘ │
│  ┌─────────────────┐  ┌──────────────────────────────────────────────┐ │
│  │   验证框架      │  │   12 个市场数据源                              │ │
│  │   严格/标准/    │  │   itch · reddit · steam · youtube · tiktok · …│ │
│  │   提示性        │  └──────────────────────────────────────────────┘ │
│  └─────────────────┘                                                     │
│  ┌─────────────────┐  ┌──────────────────────────────────────────────┐ │
│  │   沙箱          │  │   Dashboard（FastAPI :8080，13 分区）          │ │
│  │   进程隔离       │  │   项目看板 / 任务监控 / 决策卡片 / 文档查看器 │ │
│  └─────────────────┘  └──────────────────────────────────────────────┘ │
│  ┌─────────────────┐  ┌──────────────────────────────────────────────┐ │
│  │   技能系统      │  │   SQLite 数据库（24 张表）                    │ │
│  │   可插拔激活    │  │   projects / decisions / tasks / kanban_tasks │ │
│  └─────────────────┘  │   event_logs / company_memory / domain_events │ │
│                       │   + 6 张 VN 专属表                            │ │
│  ┌─────────────────┐  └──────────────────────────────────────────────┘ │
│  │   Agent 邮箱   │                                                     │
│  │   SQLite 异步  │                                                     │
│  └─────────────────┘                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### 1.1 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 编排引擎 | CEO 调度器（Python 3.11+ async tick 循环） | 多项目并行调度、决策门控、任务队列管理 |
| 执行规划 | DAG 规划器 + 任务看板 | 波次并行执行、任务状态管理、原子认领 |
| 事件溯源 | 事件存储（SQLite） | 不可变事件流、项目时间线回放 |
| 验证框架 | 验证框架 | Agent 输出独立验证（严格 / 标准 / 提示性） |
| 分析 AI | glm-4-flash（智谱免费） | 市场分析、游戏设计、评估决策 |
| 代码 AI | MiniMax-M2.1 / deepseek-v4-flash | Phaser 4 + TypeScript 游戏源码 |
| 强推理 AI | MiniMax-M3 | 复杂推理、架构设计、CEO 决策 |
| 美术生成 | ComfyUI + Stable Diffusion XL（本地 GPU） | 游戏美术资产（背景 / 角色 / UI 图标） |
| 音乐生成 | Suno API / Web Audio 程序化 | 游戏背景音乐与音效 |
| 游戏运行 | Phaser 4（预览版） + TypeScript + Vite | 生成 Web 小游戏（加载并显示 ComfyUI 美术资产） |
| 监控面板 | FastAPI + 原生 HTML/CSS/JS | 13 分区 Dashboard |
| 市场情报 | 12 个数据源 | 跨源关联分析、趋势追踪、竞品密度 |
| 持久化 | SQLite + SQLAlchemy（异步） | 24 张表（18 基础 + 6 VN） |
| 沙箱隔离 | SubprocessSandbox | 受限执行 npm build 等高危操作 |
| 代码分析 | 代码依赖图（PageRank） | TypeScript / JavaScript 依赖图分析 |
| 部署 | Butler CLI | 推送到 itch.io |
| 持续集成 | GitHub Actions | ruff + mypy + pytest |

---

## 第 2 章 AI 模型与工具策略

### 2.1 6 层模型路由

| 层级 | 主模型 | 回退模型 | 用途 |
|---|---|---|---|
| **strong（强推理）** | MiniMax-M3 | deepseek-v4-flash | 复杂推理、架构设计、CEO 决策、规划 |
| **fast（快速）** | MiniMax-M3 | glm-4-flash | 分析、分类、摘要、评估 |
| **cheap（廉价）** | glm-4-flash | —— | 翻译、格式化、提交信息、简单验证、意图分类 |
| **code（代码）** | MiniMax-M2.1 | deepseek-v4-flash | 代码生成、代码编辑、代码审查 |
| **art（美术）** | stable-diffusion-xl | —— | 美术资产生成 |
| **audio（音频）** | suno | —— | 音乐生成 |

> **统一命名说明**：本文档与 `config/agents.yaml` 一致使用正式模型名（MiniMax-M3、MiniMax-M2.1、deepseek-v4-flash、glm-4-flash、stable-diffusion-xl、suno）。README 历史版本中的 "DeepSeek Coder" 为早期产品名，现已废弃。

### 2.2 模型配置（`config/agents.yaml`）

```yaml
models:
  deepseek:
    provider: openai_compatible
    base_url: "https://api.deepseek.com"
    model: "deepseek-v4-flash"
    api_key_env: "DEEPSEEK_API_KEY"

  minimax:
    provider: openai_compatible
    base_url: "https://api.minimaxi.com/v1"
    model: "MiniMax-M3"
    api_key_env: "MINIMAX_API_KEY"
    roles: [ceo, researcher, programmer, qa, analytics]

  minimax_code:
    provider: openai_compatible
    base_url: "https://api.minimaxi.com/v1"
    model: "MiniMax-M2.1"
    api_key_env: "MINIMAX_API_KEY"
    roles: [lead_programmer]

  glm:
    provider: zhipuai
    model: "glm-4-flash"
    api_key_env: "ZHIPU_API_KEY"
    roles: [designer, writer]

  art:
    provider: comfyui
    base_url: "http://localhost:8188"
    model: "stable-diffusion-xl"

  audio:
    provider: suno
    api_key_env: "SUNO_API_KEY"

model_tiers:
  strong: { primary: "MiniMax-M3",       fallback: "deepseek-v4-flash" }
  fast:   { primary: "MiniMax-M3",       fallback: "glm-4-flash" }
  cheap:  { primary: "glm-4-flash",      fallback: null }
  code:   { primary: "MiniMax-M2.1",     fallback: "deepseek-v4-flash" }
  art:    { primary: "stable-diffusion-xl", fallback: null }
  audio:  { primary: "suno",             fallback: null }
```

### 2.3 任务类别到模型层级映射

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

### 2.4 关键决策

- **ComfyUI 是美术资产生成工具，不是游戏引擎**。它输出 PNG 图片，由 Phaser 加载使用。
- **Phaser 是游戏运行时引擎**，负责场景管理、玩家输入、碰撞检测、动画。
- 分析 / 设计类任务使用免费或低成本模型，只有代码生成使用付费模型。
- 所有 LLM 调用通过统一客户端 `shared/llm_client.py` 管理，自动追踪 token 与成本。
- 模型路由器支持复杂度驱动的层级升降：复杂任务自动升级到 strong 模型，简单任务降级到 cheap。

---

## 第 3 章 核心工作流 —— 多项目调度器

系统有两种运行模式：**多项目调度器**（推荐）与 **经典 13 节点管道**（兼容）。

### 3.1 模式 1：多项目调度器（推荐）

CEO 作为调度大脑，每个 tick（默认 60 秒）处理所有项目的一步操作：

```
每个 tick（默认 60s）：
┌──────────────────────────────────────────────────────────────────┐
│ 0. 检查调度器暂停状态（文件标志 .scheduler_paused）                │
│ 1. 处理人类指令（从聊天界面读取）                                   │
│ 2. 检查决策点 —— 跳过等待人类的项目                                │
│ 3. 定期市场扫描（每 5 ticks）                                     │
│ 4. CEO 评估新项目（每 3 ticks）                                   │
│ 5. 定期获取 itch.io 统计数据（每 30 ticks）                        │
│ 6. 推进各项目：                                                  │
│    backlog → [人类批准] → scanning → designing                     │
│    → developing（art / music 与 code 并行）→ testing               │
│    → building → localize → [人类批准] → publishing                 │
│    → live（consolidate 记忆）                                     │
│ 7. 从任务队列取任务执行（含 3 层错误恢复）                          │
│ 8. 根据执行结果更新项目状态 + 存储记忆                              │
│ 9. 生成主动汇报到聊天（CEO 汇报，每 5 ticks）                       │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 5 类决策门控（必须人类批准）

| 决策类型 | 触发条件 | 示例 |
|---|---|---|
| **新项目启动** | CEO 创建项目于 backlog，`awaiting_decision="new_project"` | "发现 3 个机会，推荐 A，启动？" |
| **项目发布** | QA 通过 | "项目 A 测试通过，发布到 itch.io？" |
| **项目取消** | QA 连续失败 3 次 | "项目 C 连续失败，取消？" |
| **预算超限** | 开发前预算检查 | "项目 B 预算达 80%，继续？" |
| **方向调整** | 市场变化 | "建议调整 B 方向？" |

### 3.3 任务看板状态机

```
triaged → claimed → running → review → completed
            ↓           ↓
          failed    blocked（依赖未满足）
            ↓
         retry（最多 3 次）
```

> **状态名统一**：本文档统一使用代码中的正式状态名（`triaged` / `claimed` / `running` / `review` / `completed` / `failed` / `blocked` / `cancelled`）。README 历史版本中的"pending / verify / done"为旧表述。

| 状态 | 说明 |
|---|---|
| **triaged（已分诊）** | 已分析，等待认领 |
| **claimed（已认领）** | 已被 Agent 原子认领（CAS） |
| **running（执行中）** | 正在执行 |
| **review（待验证）** | 完成，等待验证 |
| **completed（已完成）** | 已完成并验证通过 |
| **failed（失败）** | 执行失败 |
| **blocked（被阻塞）** | 等待依赖任务完成 |
| **cancelled（已取消）** | 手动取消 |

### 3.4 优先级体系

| 优先级 | 说明 |
|---|---|
| **critical（紧急）** | 最高优先级，优先调度 |
| **high（高）** | 高优先级 |
| **normal（普通）** | 默认优先级 |
| **low（低）** | 低优先级，可延迟 |

### 3.5 任务看板特性

- **原子 CAS 认领**：防止多个 Agent 同时认领同一任务
- **依赖跟踪**：任务可声明对其他任务的依赖，被依赖者未完成时无法执行
- **自动分解**：复杂任务可自动分解为多个子任务，父任务被阻塞直到所有子任务完成
- **优先级排序**：critical → high → normal → low，同优先级按创建时间 FIFO

### 3.6 DAG 规划器（执行规划器）

基于有向无环图的执行规划，支持波次并行执行：

```
执行计划结构：
plan_id, version, project_id, goal
nodes: [PlanNode, ...]   （不可变，版本化）
waves: [[node_a, node_b], [node_c], [node_d, node_e]]   （同波次并行）

PlanNode：
  node_id, task_type, agent_role, dependencies, params
  status: pending → ready → running → done / failed / skipped
  retry_count, max_retries
```

#### 恢复层级（RecoveryLevel）

| 层级 | 策略 | 触发条件 |
|---|---|---|
| **RETRY** | 重试（最多 2 次） | 超时、限流、临时失败 |
| **STRATEGY_CHANGE** | 切换策略（如 develop → develop_simple） | 逻辑错误、验证失败 |
| **REPLAN** | 完整重规划 | 结构性失败、依赖缺失 |

#### 计划模板

| 模板 | 用途 | DAG 结构 |
|---|---|---|
| `plan_full_game` | 完整游戏开发 | scan → design → [art \|\| music] → develop → qa → build → deploy |
| `plan_prototype` | 快速原型（跳过美术音乐） | design → develop_simple → qa → build |
| `plan_market_scan` | 周期性市场扫描 | scan |
| `plan_update` | 已有游戏更新 | develop → qa → build → deploy |

### 3.7 拓扑选择器（TopologySelector）

分析 DAG 结构，智能选择编排模式：

| 拓扑类型 | 特征 | 适用场景 |
|---|---|---|
| **PARALLEL** | 宽而浅，低耦合 | art + music 并行生成 |
| **SEQUENTIAL** | 链式，高耦合 | 严格顺序依赖的流水线 |
| **HIERARCHICAL** | 深而窄，lead 委托 | 多级分解任务 |
| **HYBRID** | 菱形 / fan-out+fan-in | 复杂依赖模式 |

### 3.8 3 层嵌套错误恢复

| 层级 | 策略 | 行为 |
|---|---|---|
| **Layer 1** | `retry_with_feedback` | 同任务重试最多 2 次，错误信息反馈给 Agent |
| **Layer 2** | `strategy_change` | 切换策略（如 develop → develop_simple），最多 1 次 |
| **Layer 3** | `direction_change` | 创建决策点，暂停项目，等待人类决策；超过 2 次自动取消 |

**Layer 2 回退映射**：只有 `develop → develop_simple` 有真实的 Layer 2 策略变更。其他所有 task type 在 Layer 1 重试耗尽后直接跳到 Layer 3（人类决策），避免无效的重新入队。

| Task Type | Layer 2 回退 | 行为 |
|---|---|---|
| `develop` | `develop_simple` | 使用简化策略重新生成代码 |
| `qa` | 无 | 直接升级到 Layer 3 |
| `build` | 无 | 直接升级到 Layer 3 |
| `design_game` | 无 | 直接升级到 Layer 3 |
| `art_gen` | 无 | 直接升级到 Layer 3 |
| `generate_music` | 无 | 直接升级到 Layer 3 |
| `market_scan` | 无 | 直接升级到 Layer 3 |

### 3.9 调度器暂停 / 恢复

- **暂停机制**：通过 API 创建 `data/.scheduler_paused` 文件标志，调度器在每个 tick 开始时检查该文件
- **恢复机制**：删除暂停文件，调度器恢复正常 tick 循环
- **Dashboard 控制**：header 按钮"💼 开始上班 / 下班"切换暂停状态
- **API 端点**：`POST /api/pipeline/run-scheduler`、`POST /api/pipeline/stop`、`GET /api/pipeline/status`

### 3.10 项目阶段定义

定义于 `shared/models.py` 中的 `ProjectPhase` 枚举。完整的合法转换链为：

```
backlog → scanning → designing → developing → testing → building → publishing → live
                                                                            ↓
                                                                       paused / cancelled
```

| 阶段 | 含义 |
|---|---|
| **backlog（待启动）** | 项目刚加入待办，等候人类批准 |
| **scanning（市场调研中）** | 等待市场信号采集完成 |
| **designing（设计中）** | GDD 生成与机制规划 |
| **developing（开发中）** | 美术、音乐、代码并行生成 |
| **testing（测试中）** | QA 自动化试玩 |
| **building（构建中）** | Vite 打包 |
| **publishing（发布中）** | 推送到 itch.io / CrazyGames / Poki |
| **live（已上线）** | 进入维护期，接收反馈与统计 |
| **paused（已暂停）** | 人类主动暂停 |
| **cancelled（已取消）** | 人类或系统自动取消 |

### 3.11 原型快速模式

5 分钟内生成可玩原型，跳过美术和详细设计：

```
概念提示 → LLM 最小规格 → Phaser 模板代码 → 构建预览
```

- 使用彩色矩形 / emoji 替代美术资产
- 当前在 dashboard 暂未提供"⚡ Prototype"独立按钮（v4 release note 中提及但未落地），可通过 CLI 触发：`python -m orchestrator.main run-prototype "puzzle game"`

### 3.12 执行入口（`orchestrator/main.py`）

```bash
# 多项目调度器（推荐）
python -m orchestrator.main run-scheduler                # 默认 60s/tick
python -m orchestrator.main run-scheduler --interval 60  # 自定义 tick 间隔

# 原型快速模式
python -m orchestrator.main run-prototype "space shooter with powerups"

# 经典模式（兼容）
python -m orchestrator.main run              # 完整运行一个周期
python -m orchestrator.main run-forever       # 24/7 持续循环
python -m orchestrator.main scan             # 仅执行市场扫描
```

### 3.13 模式 2：经典 13 节点管道（兼容）

保留原有 13 节点 LangGraph 管道，单项目线性执行。代码入口在 `orchestrator/graph/pipeline.py`，不再主动演进，仅作向后兼容。

---

## 第 4 章 Agent 节点详解

### 4.1 CEO（`orchestrator/nodes/ceo.py`）

模拟 CEO 决策角色：

- 读取 `market_insights`，按 `market_opportunity_score` 排序
- 通过 `_get_completed_genres()` 查询数据库已做过的 genre，避免重复
- **反馈驱动更新**：通过 `_find_project_to_update()` 检查已上线项目的未处理反馈
  - 如果 ≥2 条 bug / feature 反馈 → 路由到 MODE_UPDATE（跳过设计 / 美术，直接修复）
  - 否则按评分决定是否启动新项目
- 评分 > 0.6 则生成 `GameProposal` 并进入设计阶段；评分不足则继续扫描或休眠
- **用户指令处理**：通过 `_process_ceo_instructions()` 从聊天界面接收用户指令
  - genre 指令（"下一个做解谜类"）→ 写入 company_memory，优先匹配该 genre
  - 停止指令 → 立即进入 IDLE 状态
  - 问题 / 反馈 → 记录为系统事件
  - 使用 glm-4-flash 进行意图分类（direction / question / feedback / stop）

### 4.2 CFO（`orchestrator/nodes/cfo.py`）—— 内部节点

模拟 CFO 财务管控角色（作为内部节点自动运行，用户通过 CEO 获取财务信息）：

- **预算预检**（`cfo_budget_check`）：在开发步骤前检查月度和项目预算
  - 开发步骤估算成本 ~$0.10（~50K tokens deepseek-coder）
  - 超预算则终止管道并记录财务事件
  - 无预算配置时默认放行（不设限）
- **财务报告**（`cfo_financial_report`）：生成 30 天财务摘要
  - 汇总 token 用量、按模型 / Agent 分组成本
  - 使用 glm-4-flash 生成 AI 财务洞察

### 4.3 COO（`orchestrator/nodes/coo.py`）—— 内部节点

模拟 COO 运营监控角色（作为内部节点自动运行）：

- **管道健康检查**（`coo_health_check`）：管道入口处检查状态
  - ≥3 个累积错误 → 暂停管道
  - ≥3 次重试 → 记录告警
- **指令处理**（`coo_process_instructions`）：从聊天界面接收运营指令
  - "暂停" / "停止" → 切换到 IDLE
  - "状态" / "报告" → 记录运营事件

### 4.4 游戏设计师（`agents/dev/designer/`）

接收 GDD 生成任务，调用 glm-4-flash 生成结构化的游戏设计文档：

- 游戏标题、类型、核心玩法
- 场景列表（Boot → Menu → Game → GameOver）
- 游戏机制和控制系统
- 参考游戏和差异化定位

**机制规划层**（`mechanic_planner.py`）：

- GDD 生成后自动分解为有序机制列表
- 每个机制包含：name、description、inputs / outputs、constraints、dependencies、complexity
- 程序员按机制逐一生成代码（核心系统 → 游戏玩法 → 打磨）
- 无机制规划时退化为整体生成（向后兼容）

**Phaser 知识库**（`config/phaser_knowledge.yaml`）：

- 1200+ 行综合 Phaser 4 知识库，被 Designer 和 Programmer Agent 加载
- 11 种 genre 架构映射：platformer、puzzle-match、tower-defense、idle-clicker、shooter、rpg、card-game、racing、runner、arena、strategy、arcade
- 每 genre：推荐物理 / 模式、核心系统、数据文件、典型场景、最小机制、代码组织
- 常见陷阱（Phaser 3 API in v4、import 错误、scene key 不匹配）
- 商业模式（广告集成点、留存机制、进度系统）

### 4.5 美术师（`agents/dev/artist/`）

通过 **ComfyUI + Stable Diffusion XL** 生成游戏美术资产。

> **重要**：ComfyUI 不是游戏引擎，它是美术资产生成工具——生成的 PNG 图片由 Phaser 游戏引擎加载使用。

**ComfyUI 的角色**：接到 GDD 中的美术需求 → 调用本地 ComfyUI API → SD XL 生成 PNG → 放入游戏 `public/assets/` → Phaser 通过 `this.load.image()` / `this.add.image()` 加载显示。

**核心组件（7 文件）**：

| 文件 | 职责 |
|---|---|
| `comfyui_client.py` | ComfyUI HTTP API 客户端（queue → poll → download） |
| `sprite_generator.py` | 角色精灵、背景、UI 图标生成器 |
| `character_consistency.py` | 角色视觉一致性 |
| `workflows.py` | SD XL 工作流定义（含 VAE 连接，兼容 ComfyUI v1.44+） |
| `art_agent.py` | art_gen Agent 入口 |
| `art_node.py` | generate_art 管道节点 |
| `art_style.py` | 5 种风格预设 |

**资产类型**：

| 类型 | 分辨率 | 用途 |
|---|---|---|
| 背景图 | 800×600 | 菜单、游戏、结算场景背景 |
| 角色精灵 | 64×64 | 玩家、NPC 角色 |
| UI 图标 | 32×32 | 道具、能力、金币等 |

**性能**：RTX 3060 首次生成约 391 秒（模型加载），后续约 10 秒 / 张。

**美术风格一致性**（`art_style.py`）：

- 5 种预设风格：`pixel_16`、`pixel_8`、`cartoon`、`flat_design`、`handdrawn`
- 每种风格定义 `prompt_suffix`、`negative_prompt`、`sprite_size`、`palette`
- 根据 genre 自动选择风格（platformer→pixel_16，puzzle→flat_design，idle→cartoon）
- `ArtStyleConfig` 持久化在项目 GDD 中，确保所有资产生成使用相同风格

**集成方式**：生成的 PNG 放入游戏 `public/assets/`，Phaser 的 BootScene 通过 `this.load.image()` 加载，场景用 `this.add.image()` 替代 `this.add.rectangle()` 矩形占位符。

### 4.6 程序员（`agents/dev/programmer/`）

调用 **MiniMax-M2.1**（回退 deepseek-v4-flash）生成完整的 **Phaser 4**（预览版）+ TypeScript 游戏代码。

```
generate_game_code(gdd, project_dir, config, build_error="")
```

- 接收 GDD，用 Jinja2 模板 + AI 生成完整游戏源码
- **机制驱动生成**：如果 GDD 包含 mechanics 列表，按依赖顺序逐机制生成代码；否则整体生成
- 强制约束：`import * as Phaser from 'phaser'`（Phaser 4 ESM 无默认导出）
- 游戏代码引用 ComfyUI 生成的美术资产路径（`assets/bg_menu.png`、`assets/player.png` 等），运行时通过 Phaser 加载
- **构建重试机制**：如果 `build_error` 参数非空，自动将错误信息追加到 AI prompt 中，让 AI 修复后重新生成
- **分析埋点**：在生成的游戏代码中注入 `navigator.sendBeacon` 调用，上报 `game_start` / `game_over` 事件（含分数、游戏时长）
- **磁盘管理**：构建完成后自动删除 `node_modules/`，npm 缓存保证后续安装速度
- 生成后自动执行 `npm install && npm run build`
- 使用 `project-dir-timestamp` 模式避免目录冲突
- **沙箱隔离**：通过 `ProjectSandbox` 执行 npm 操作，限制内存和超时

### 4.7 QA 测试员（`agents/dev/qa/`）

- 检查构建产物是否存在
- 如需构建则执行构建并捕获 stderr
- 失败时返回 `retry_count+1` 和错误详情
- 构建错误会通过状态传递回 Developer，实现**错误反馈闭环**

**自动化 Playwright 试玩**（`auto_playtest.py` + `playtest_checks.py`）：

- 使用 Playwright headless Chromium 执行 8 项自动化验证：
  - 页面加载（无 JS 错误）、Canvas 存在、Canvas 渲染（非零尺寸）
  - 非白屏、交互元素存在、开始按钮可点击
  - 分数系统响应（点击后文本变化）、控制台错误检查
- 容忍度：允许 1 项检查失败
- 返回试玩评分（0-1）和详细检查结果
- 构建成功后自动运行，QA 通过需要 build_ok + playtest_passed

**复杂度评分**（`shared/complexity.py`）：

- **GDD 评分**（`score_gdd`）：评估机制数量、场景数量、实体数量、进度 / 平衡 / 胜利条件深度、核心循环步骤、商业信号（5 维度：model、ads、IAP、retention、engagement）
- **代码评分**（`score_code`）：评估文件数量、代码行数、特性信号（physics / collision / tween / timer / update_loop / score / level）、输入类型、场景数量
- VN 代码额外加分（检测 VN 数据文件）
- 最低通过分数：0.45（低于此阈值的游戏被拒绝进入 QA）

### 4.8 构建打包（`agents/dev/builder/`）

- 执行 `vite build` 生成 `dist/` 目录
- 输出 HTML5 游戏包（单页应用）
- 通过 `ProjectSandbox` 隔离执行，限制超时和资源

### 4.9 部署（`agents/ops/deployer/`）

通过 Butler CLI 将游戏推送到 **itch.io**：

- 使用 `BUTLER_API_KEY` 环境变量认证（无需交互式登录）
- 推送到 `{username}/{project_name}:html` 频道
- 注意：游戏页面需预先在 itch.io 手动创建

**多平台部署（6 个 deployer 文件）**：

| 文件 | 平台 | 部署方式 | SDK | 广告类型 |
|---|---|---|---|---|
| `base.py` | —— | 适配器基类 | —— | —— |
| `registry.py` | —— | 平台注册表 | —— | —— |
| `itch_deployer.py` | itch.io | Butler CLI | 无 | 无 |
| `crazygames_deployer.py` | CrazyGames | API 上传 | CrazySDK v1 | midgame / rewarded / banner |
| `poki_deployer.py` | Poki | API 上传 | PokiSDK v4 | commercialBreak / rewardedBreak |
| `itch_stats.py` | itch.io | 统计拉取 | —— | —— |

> Newgrounds 在 README 早期版本中被列为"手动上传"平台，但**当前代码中尚未实现 `newgrounds_deployer.py`**，仅在 ARCHITECTURE 历史草稿中提及。读者若有需求可作为后续工作。

- 配置：`config/platforms.yaml`
- 平台注册表：`agents/ops/deployer/registry.py`
- 广告 SDK 注入：`shared/ad_sdk.py`（自动注入 SDK 脚本和安全 no-op stubs）
- 平台 SDK 片段：`shared/constants.py`（`PLATFORM_SDK_SNIPPETS`，`PLATFORM_AD_PATTERNS`）

### 4.10 音乐生成（`agents/dev/music/`）

为游戏生成背景音乐和音效，支持多种后端（3 文件）：

| 后端 | 条件 | 输出 |
|---|---|---|
| **Suno API** | `suno_api_key` 已配置 | AI 生成的 MP3 音乐 |
| **Web Audio 程序化**（默认） | 无需外部 API | 基于振荡器的循环旋律 |

- 程序化 BGM 根据 genre 配置不同参数（tempo / scale / octave）：arcade=140bpm、puzzle=90bpm、rpg=80bpm
- 5 种 SFX：jump、collect、hit、gameover、click（振荡器合成）
- 输出 `bgm.js` + `sfx.js` 到 `assets/audio/`
- `mood_bgm.py` 情绪 BGM 生成
- `sfx_generator.py` 音效生成器
- 在 DEVELOPING 阶段（art → music → develop）自动执行

### 4.11 自动本地化（`agents/dev/localize/`）

将游戏 UI 文字翻译为多语言，仅面向海外市场（无中文）：

- **字符串提取**（`string_extractor.py`）：从 HTML 文本节点和 JS 字符串中提取可翻译字符串
- **LLM 翻译**（`translator.py`）：使用 glm-4-flash / deepseek 翻译到 15 种语言
- **注入本地化**：生成 `assets/loc/loc.js`，自动注入 `<script>` 标签到 index.html
- 默认翻译前 5 大市场：日语、韩语、西班牙语、葡萄牙语、德语
- 支持语言：ja、ko、es、pt、de、fr、ru、ar、hi、th、vi、id、tr、it、pl
- `character_names.py` 角色名翻译
- `ts_extractor.py` TypeScript 字符串提取
- 在 BUILDING 阶段后自动执行（build → localize → publishing）

### 4.12 反馈收集（`agents/ops/analytics/`）

- `feedback_collector.py` 抓取 itch.io 评论
- `feedback_analytics.py` 使用 glm-4-flash 对评论分类（bug / feature / praise / other）
- 未处理反馈 ≥2 条 bug / feature → CEO 进入 MODE_UPDATE，跳过设计与美术，直接修复

---

## 第 5 章 共享模块详解

### 5.1 事件溯源（`shared/events.py` + `orchestrator/event_store.py`）

**不可变事件作为单一真相来源**。

```python
class ActionType(str, Enum):
    # Scheduler 生命周期
    SCHEDULER_TICK_START = "scheduler.tick_start"
    SCHEDULER_TICK_END = "scheduler.tick_end"
    # 任务生命周期
    TASK_ENQUEUED = "task.enqueued"
    TASK_DEQUEUED = "task.dequeued"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRIED = "task.retried"
    # 决策门控
    DECISION_CREATED = "decision.created"
    DECISION_RESOLVED = "decision.resolved"
    # 项目生命周期
    PROJECT_CREATED = "project.created"
    PROJECT_PHASE_CHANGED = "project.phase_changed"
    PROJECT_CANCELLED = "project.cancelled"
    PROJECT_PUBLISHED = "project.published"
    # Agent 动作
    AGENT_CALLED = "agent.called"
    AGENT_TOOL_USED = "agent.tool_used"
    # 验证
    VERIFICATION_PLAN_CREATED = "verification.plan_created"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"

@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: ActionType
    timestamp: str          # ISO 8601
    tick_id: int
    project_id: str | None
    agent_name: str | None
    payload: dict[str, Any]
    parent_event_id: str | None    # 因果链
    metadata: dict[str, Any]
```

**`SqliteEventStore`**：

- **仅追加**：只插入不更新，保证事件不可变
- **replay**：支持项目时间线回放，从指定 tick 重放所有事件
- **project timeline**：获取项目所有事件，按时间排序
- **batch append**：支持批量插入提高性能
- 表结构：`event_id, event_type, timestamp, tick_id, project_id, agent_name, payload, parent_event_id, metadata`

**事件发射时机**：tick 开始 / 结束、任务入队 / 出队 / 完成 / 失败、项目阶段变更、决策创建 / 解决、验证计划创建 / 通过 / 失败。

### 5.2 任务看板（`orchestrator/kanban.py`）

SQLite 背书的看板系统，原子 CAS 认领防止双重领取。

```python
class KanbanStatus(str, Enum):
    TRIAGED = "triaged"        # 已分诊
    CLAIMED = "claimed"        # 已认领
    RUNNING = "running"        # 执行中
    REVIEW = "review"          # 待验证
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"          # 失败
    BLOCKED = "blocked"        # 依赖未满足
    CANCELLED = "cancelled"    # 已取消

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
    depends_on: list[str]
    parent_task_id: str | None
    plan_id: str | None
    retry_count: int = 0
    max_retries: int = 3
```

**核心操作**：

- `add_task`：添加新任务到看板，发射 `TASK_ENQUEUED` 事件
- `claim_task`：原子 CAS 认领（UPDATE WHERE status='triaged'），防止双重领取
- `complete_task`：标记任务完成，发射 `TASK_COMPLETED` 事件
- `fail_task`：标记任务失败，发射 `TASK_FAILED` 事件
- `block_task` / `unblock_task`：阻塞 / 解除阻塞
- `retry_task`：重试失败任务（递增 `retry_count`，上限 `max_retries`）
- `auto_decompose`：将复杂任务自动分解为多个子任务，父任务被阻塞

**查询操作**：

- `get_available_tasks`：获取可认领任务（排除依赖未满足的）
- `get_running_tasks`：获取正在运行的任务
- `get_tasks_by_project`：获取项目所有任务
- `count_by_status`：按状态统计任务数量
- `get_board_summary`：获取看板各列计数

### 5.3 DAG 规划器（`orchestrator/planner.py`）

**版本化不可变执行计划，基于波次的并行执行**。

```python
class PlanNodeStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"        # 依赖全部完成
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

class RecoveryLevel(str, Enum):
    RETRY = "retry"                  # Level 1：临时错误
    STRATEGY_CHANGE = "strategy"     # Level 2：改变策略
    REPLAN = "replan"                # Level 3：完整重规划

@dataclass
class PlanNode:
    node_id: str
    task_type: str     # e.g., "market_scan", "design_game", "develop"
    agent_role: str    # e.g., "scanner", "designer", "programmer"
    dependencies: list[str]
    params: dict
    status: PlanNodeStatus = PlanNodeStatus.PENDING
    result: dict | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2

@dataclass
class ExecutionPlan:
    plan_id: str
    version: int       # 每次结构变更递增
    project_id: str
    goal: str
    nodes: list[PlanNode]
    created_at: str
    parent_plan_id: str | None    # 跟踪重规划血缘
```

**关键方法**：

- `get_waves()`：通过拓扑排序计算执行波次，同波次内节点可并行执行
- `get_ready_nodes()`：获取依赖全部满足且处于 pending 状态的节点
- `is_complete()`：所有节点均处于 done 或 skipped 状态
- `progress()`：返回完成百分比
- `determine_recovery()`：根据错误特征决定恢复层级（RETRY / STRATEGY_CHANGE / REPLAN）
- `replan()`：从失败节点创建新版本计划，保留已完成节点，替换失败部分

**计划模板**：

- `plan_full_game(project_id, name, genre)`：完整游戏开发
- `plan_prototype(project_id, name, genre)`：快速原型
- `plan_market_scan()`：周期性市场扫描
- `plan_update(project_id, name, feedback_count)`：更新已有游戏

### 5.4 拓扑选择器（`orchestrator/topology.py`）

**分析 DAG 结构，智能选择最优编排模式**。

```python
class TopologyType(str, Enum):
    PARALLEL = "parallel"           # 宽而浅，低耦合
    SEQUENTIAL = "sequential"      # 链式，高耦合
    HIERARCHICAL = "hierarchical"  # 深而窄，lead 委托
    HYBRID = "hybrid"              # 菱形 / fan-out+fan-in

@dataclass(frozen=True)
class DAGMetrics:
    node_count: int
    edge_count: int
    max_depth: int
    avg_fan_out: float
    coupling_score: float          # edges / (nodes * (nodes-1)), 0-1
    parallelism_potential: float   # 1 - (longest_path / total_nodes), 0-1
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

### 5.5 模型路由器（`shared/model_router.py`）

**多层级模型路由器，基于任务复杂度和成本选择最优模型**。

```python
class ModelTier(str, Enum):
    STRONG = "strong"
    FAST = "fast"
    CHEAP = "cheap"
    SPECIALIZED_CODE = "code"
    SPECIALIZED_ART = "art"
    SPECIALIZED_AUDIO = "audio"

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
    estimated_cost: str      # "low" | "medium" | "high"
    fallback: str | None = None
```

**关键方法**：

- `route(category, complexity, agent_role, prefer_cheaper)` → `RoutingDecision`
- `route_task_type(task_type, complexity)` → `RoutingDecision`
- `get_model_for_agent(agent_role)` → `str`
- `get_all_tiers()` → `dict`

**复杂度驱动升降**：

- `complexity >= 0.7` 且当前层级为 FAST / CHEAP → 自动升级到 STRONG
- `complexity < 0.3` 且 `prefer_cheaper=True` 且当前层级为 STRONG → 降级到 FAST

### 5.6 上下文管理器（`shared/context_manager.py`）

**4 层渐进压缩，防止 LLM 对话上下文溢出**。

```python
class CompactionLevel(str, Enum):
    NONE = "none"
    SNIP = "snip"        # Layer 1：清除旧工具结果
    SEGMENT = "segment"  # Layer 2：总结对话片段
    FULL = "full"        # Layer 3：完整压缩

@dataclass
class ContextBudget:
    max_tokens: int = 128_000
    soft_threshold: float = 0.70
    hard_threshold: float = 0.85
    critical_threshold: float = 0.95
    reserved_tokens: int = 4_000
```

**4 层渐进压缩**：

| 层级 | 触发条件 | 策略 | 效果 |
|---|---|---|---|
| Layer 0 | 工具调用前 | Tool Result Budget | 预估 token 成本，检查是否可执行 |
| Layer 1 | 使用率 ≥ 70% | Snip 压缩 | 清除旧工具结果，保留最近 3 条 |
| Layer 2 | 使用率 ≥ 85% | Segment 压缩 | 总结对话片段，替换为摘要消息 |
| Layer 3 | 使用率 ≥ 95% | 完整压缩 | 保留系统 prompt + 摘要 + 最近 2 条 |

**token 估算**：中文约 1.5 字符 / token，英文约 4 字符 / token。

### 5.7 验证框架（`shared/verification.py`）

**验证优先协议：每个 Agent 输出必须经过独立验证**。

```python
class VerificationMode(str, Enum):
    QUICK = "quick"        # 基本检查（文件存在，无语法错误）
    STANDARD = "standard"  # 标准检查 + 结构验证
    STRICT = "strict"      # 完整检查 + 回归测试 + 边界情况

class ArtifactType(str, Enum):
    CODE = "code"
    ART = "art"
    GDD = "gdd"
    BUILD = "build"
    MARKET_REPORT = "market_report"
    MUSIC = "music"
    LOCALIZATION = "localization"
    GAME_PACKAGE = "game_package"
```

**内置计划生成器**：

- `plan_for_code(agent_name, code_path, mode)` → `VerificationPlan`
- `plan_for_build(agent_name, build_path)` → `VerificationPlan`
- `plan_for_art(agent_name, art_path)` → `VerificationPlan`
- `plan_for_gdd(agent_name)` → `VerificationPlan`

**验证器执行器**：

- 独立上下文执行，防止自我验证偏差
- 异步执行所有检查
- 必需检查失败则整体失败
- 返回详细失败证据供 Agent 反馈

### 5.8 沙箱（`shared/sandbox.py`）

**进程级沙箱，隔离高危操作**。

```python
@dataclass
class SandboxConfig:
    working_dir: str = "."
    timeout_secs: int = 120
    max_output_bytes: int = 1_000_000
    env_vars: dict[str, str] = field(default_factory=dict)

@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
```

**`SubprocessSandbox`**：

- 通过 `asyncio.create_subprocess_exec` 执行命令
- 超时自动 kill（`asyncio.wait_for` + `proc.kill()`）
- 输出截断到 `max_output_bytes`
- 捕获 returncode / stdout / stderr

**`ProjectSandbox`**（高级 API）：

- `npm_install(project_path)`：在项目目录执行 `npm install`
- `npm_build(project_path)`：执行 `npm run build`
- `type_check(project_path)`：执行 `tsc --noEmit`
- `list_artifacts(project_path)`：列出构建产物

### 5.9 代码依赖图（`shared/code_graph.py`）

**TypeScript / JavaScript 项目依赖图 + PageRank 重要性排名**。

```python
@dataclass
class CodeNode:
    file_path: str
    name: str
    node_type: str        # class | function | interface | import | export
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

- `build_graph(project_path)`：解析所有 .ts / .js / .tsx / .jsx 文件，构建依赖图
- `get_relevant_context(target_file, token_budget)`：在 token 预算内返回目标文件的相关上下文（按 PageRank + 临近度排序）
- `get_project_map()`：紧凑的字符串项目概览
- `get_dependents(file_path)`：依赖该文件的文件列表（被谁导入）
- `get_dependencies(file_path)`：该文件依赖的文件列表（导入谁）

**PageRank 算法**：考虑节点重要性和文件间临近度（0.4 × PageRank + 0.6 × 临近度）。

### 5.10 Agent 邮箱（`shared/agent_messaging.py`）

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

**`AgentMailbox` 操作**：

- `send(from_agent, to_agent, msg_type, payload, priority)` → `str`：发送消息（异步，WAL 模式）
- `receive(agent_name, msg_type, timeout)` → `Message | None`：接收下一条未读消息（按优先级排序）
- `broadcast(from_agent, msg_type, payload, agents)` → `list[str]`：广播
- `get_pending_count(agent_name)` → `int`：未读消息数
- `get_all_messages(agent_name, limit)` → `list[Message]`：所有消息（最新优先）

**优先级排序**：`critical > high > normal > low`，同优先级按创建时间 ASC。

### 5.11 技能系统（`skills/`）

**可插拔的 Agent 能力系统，按条件激活**。

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
    next_actions: list[dict] = field(default_factory=dict)

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
```

**内置技能**：

| 技能 | 说明 | 激活条件 |
|---|---|---|
| `CodeReviewSkill` | 生成后代码质量审查 | `task_type in (develop, develop_simple)` 且有 `artifact_path` |

**审查标准**：

1. TypeScript 类型安全（无 `any` 类型，正确的接口）
2. 错误处理（无空 `catch` 块）
3. 游戏架构（正确的场景管理，资源加载）
4. 性能（无不必要的重渲染，正确的清理）

### 5.12 工具注册表（`shared/tools.py`）

**集中式工具管理，自注册机制**。

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    category: str    # file_ops | code_gen | art | deploy | analysis | memory | verification
    handler: Callable[..., Coroutine[Any, Any, dict]]
    input_schema: dict[str, Any] = field(default_factory=dict)
    permission_level: int = 1   # 1=read, 2=write, 3=execute, 4=admin
    is_concurrency_safe: bool = True
    cost_estimate: str = "low"  # low | medium | high
    agent_roles: list[str] = field(default_factory=list)
```

**工具分类**：

- `file_ops`：文件操作（读 / 写 / 搜索）
- `code_gen`：代码生成
- `art`：美术生成
- `deploy`：部署
- `analysis`：分析
- `memory`：记忆系统
- `verification`：验证

---

## 第 6 章 Visual Novel 专属管线

### 6.1 概述

混合 VN（视觉小说）+ 统计分支游戏生产系统。将 1 个 GDD 分解为 common route（公共路线） + N character routes（角色路线），每条路线成为独立子项目。

### 6.2 核心组件

| 模块 | 文件 | 用途 |
|---|---|---|
| VN Schema | `shared/vn_schema.py` | GDD 校验（10 必填字段） |
| VN 持久化 | `orchestrator/vn_persistence.py` | 6 张 VN 专属表 |
| VN 路线扩展 | `orchestrator/vn_routes.py` | 项目分解 + 资产链接 |
| 章节化生产脚本 | `scripts/chapter_pipeline/` | 章节化生成、合并发布 |

### 6.3 VN GDD 必填字段

```
narrative_premise     剧情前提
character_roster      角色名册
stat_system           统计系统
branching_tree        分支树
ending_conditions     结局条件
cg_milestones         CG 里程碑
scene_flow            场景流
dialogue_style        对话风格
art_direction         美术方向
music_direction       音乐方向
```

### 6.4 生产流程

1. **GDD 校验** → `vn_schema.py` 验证 10 个必填字段
2. **项目分解** → common route（40% 预算） + N character routes（60% 拆分）
3. **资产架构** → symlink（符号链接） 共享资源，每条路线独立目录
4. **独立构建** → 每条路线独立 QA + build
5. **合并发布** → 路线整合为完整游戏

### 6.5 VN 复杂度评分

`complexity.py` 中 VN 代码评分额外加分（检测 VN 数据文件存在）。

---

## 第 7 章 数据持久化（24 张表）

系统使用 **SQLite** 数据库存储所有运营数据（路径：`data/gcagents.db`）。

### 7.1 表结构（24 张表：18 基础 + 6 VN 专属）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `projects` | 多项目编排 | id, name, genre, phase, progress, awaiting_decision |
| `decisions` | 决策门控（人类审批） | id, project_id, decision_type, question, status, human_response |
| `tasks` | 任务队列（异步执行） | id, project_id, task_type, status, progress, result, error |
| `kanban_tasks` | 任务看板 | id, project_id, task_type, status, priority, params, claimed_by, depends_on |
| `orchestrator_state` | 经典管道状态追踪 | phase, current_project_id, errors, updated_at |
| `company_policy` | 公司策略配置 | budget_limit_usd, preferred_genres, auto_publish, max_active_projects |
| `agent_logs` | Agent 节点的执行日志 | node_name, status, duration_ms, error |
| `market_reports` | AI 市场分析报告 | signals_count, opportunities_json, raw_analysis |
| `market_signals` | 原始市场信号 | source, genre, title, score, captured_at |
| `game_projects` | 游戏项目记录 | name, genre, status, gdd, itch_url, current_version |
| `game_feedback` | 用户反馈 | project_id, category, content, processed |
| `game_versions` | 版本快照 | project_id, version, gdd_snapshot, changelog |
| `game_metrics` | 游戏遥测数据 | project_id, metric_name, metric_value |
| `api_usage_logs` | LLM 调用追踪 | model, agent_name, total_tokens, estimated_cost_usd |
| `finance_budgets` | 预算配置 | category, budget_type, budget_limit_usd, spent_usd |
| `chat_messages` | 高管聊天记录 | role, content, agent_name, metadata_json |
| `event_logs` | 公司事件日志 | event_type, severity, title, source_agent |
| `company_memory` | 公司长期记忆 | category, title, content, importance |
| `domain_events` | 事件溯源 | event_id, event_type, timestamp, tick_id, project_id, payload |
| `agent_mailbox` | Agent 间消息传递 | id, from_agent, to_agent, message_type, payload, priority, read |
| `itch_stats` | itch.io 统计数据 | game_name, downloads_count, plays_count, last_updated |
| `vn_routes` | VN 路线定义 | project_id, route_name, route_type, budget_pct, status |
| `vn_characters` | VN 角色 | project_id, route_id, name, role, personality, stats |
| `vn_endings` | VN 结局 | project_id, route_id, ending_type, conditions, scene_id |
| `vn_cgs` | VN CG 里程碑 | project_id, route_id, milestone_name, prompt, status |
| `vn_stats` | VN 统计系统 | project_id, stat_name, display_name, range_min, range_max |
| `route_assets` | VN 路线资产映射 | project_id, route_id, asset_type, asset_path, shared |

### 7.2 写入时机

| 事件 | 写入内容 |
|---|---|
| 项目阶段变更 | `projects` 更新 phase / progress |
| 决策创建 / 解决 | `decisions` 记录人类决策 |
| 任务执行 | `tasks` 记录状态 / 进度 / 结果 |
| 任务看板操作 | `kanban_tasks`（claim / complete / fail / block） |
| 每个节点执行完成 | `agent_logs` 写入耗时 + 状态 |
| 每次 LLM 调用 | `api_usage_logs` 写入 token 用量 + 成本 |
| 市场扫描完成 | `market_signals` + `market_reports` |
| 管道阶段变更 | `orchestrator_state` + `game_projects` |
| 部署完成 | `game_versions`（版本号 + GDD 快照） |
| 反馈收集 | `game_feedback`（itch.io 评论 + AI 分类） |
| 游戏运行 | `game_metrics`（分析事件埋点上报） |
| 财务操作 | `finance_budgets` + `event_logs` |
| 高管聊天 / 决策 | `chat_messages`（含决策卡片） |
| 记忆存储 | `memories`（短期事件 + 长期教训） |
| 项目完成 | `memories` consolidate（短期→长期提取） |
| 所有重要事件 | `event_logs` + `domain_events`（双重写入） |
| Agent 间消息 | `agent_mailbox` |

---

## 第 8 章 Dashboard 详解（13 分区 + 44 端点）

### 8.1 总体布局

Dashboard 加载顺序从上到下、左到右：

```
┌─────────────────────────────────────────────────────────────────┐
│  [▶ GCAgents]   [IDLE]    Last update: 12:34:56  [💼上班] [⟳]  │  ← Header
├─────────────────────────────────────────────────────────────────┤
│  1. 公司策略 Company Policy（默认折叠）                            │
│  2. 游戏分析 Game Analytics                                      │
│  3. 游戏性能 Game Performance                                    │
│  4. 财务 Finance & Cost                                          │
│  5. 决策历史 Decision History                                     │
│  6. 高管聊天 Executive Chat                                      │
│  7. 项目看板 Project Board                                       │
│  8. 任务监控 Task Monitor                                        │
│  9. 市场报告 Market Report                                        │
│  10. 已上线游戏 Active Games                                     │
│  11. Agent 监控 Agent Monitor                                    │
│  12. 公司事件日志 Company Event Log                              │
│  13. 公司记忆 Company Memory                                     │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 13 分区详解

| # | 分区 | 数据来源 | 主要交互 |
|---|---|---|---|
| 1 | **公司策略** | `GET/POST /api/policy` | 编辑预算上限、偏好类型、自动发布开关、最大项目数、决策超时、Working Hours |
| 2 | **游戏分析** | `GET /api/analytics/summary`、`/api/analytics/top` | 全局游玩数、平均分、平均时长、Top 游戏列表 |
| 3 | **游戏性能** | `GET /api/itch/stats`、`/api/feedback/summary` | itch.io 下载数、表格化性能数据、反馈列表 |
| 4 | **财务** | `GET /api/finance/summary`、`POST /api/finance/budget` | 总花费 / API 调用数 / 按模型分组成本图 |
| 5 | **决策历史** | `GET /api/decisions`、`/api/decisions/history` | 5 类决策过滤（new_project / publish / cancel / budget_overrun / direction_change）、已批准 / 已拒绝过滤 |
| 6 | **高管聊天** | `GET/POST /api/chat/*` | 与 CEO 对话，CEO 通过 [ACTION] 隐藏块执行白名单动作（创建 / 取消 / 发布 / 更新 / 暂停项目） |
| 7 | **项目看板** | `GET /api/projects`、`/api/projects/{id}/documents` | 项目卡片，按阶段展示 QA badge、文档查看按钮 |
| 8 | **任务监控** | `GET /api/orchestrator/tasks` | 任务列表（pending / running / completed） |
| 9 | **市场报告** | `GET /api/market/report`、`/api/market/latest` | AI 分析、信号来源、跨源关联 |
| 10 | **已上线游戏** | `GET /api/projects/live`、`/api/itch/stats` | 已部署游戏列表，点击 iframe 预览 |
| 11 | **Agent 监控** | `GET /api/agents` | 各 Agent 节点状态、最近日志 |
| 12 | **公司事件日志** | `WS /ws/events`、`GET /api/events` | 终端风格实时滚动日志，5 秒轮询 |
| 13 | **公司记忆** | `GET /api/memory`、`/api/memory/lessons`、`/api/memory/search` | 短期事件 + 长期教训 + 项目上下文 |

### 8.3 文档查看器（嵌入弹窗）

在项目看板和已上线游戏分区中，点击项目卡片上的"文档"按钮会弹出 `docModal` 弹窗，显示以下 7 类文档（由 `GET /api/projects/{id}/documents` 返回）：

| 类型 | 标题 | 来源 |
|---|---|---|
| `proposal` | 项目提案 | `project.proposal` 字段 |
| `gdd` | 游戏设计文档 | `project.gdd` 字段 |
| `market_scan` | 市场调研报告 | 任务结果 `task_type='market_scan'` |
| `art_report` | 美术资源报告 | 任务结果 `task_type='art_gen'` |
| `music_report` | 音乐报告 | 任务结果 `task_type='generate_music'` |
| `qa_report` | QA 测试报告 | `project.qa_result` 字段 |
| `build_report` | 构建报告 | 任务结果 `task_type='build'` |

### 8.4 CEO 动作白名单

聊天分区中，CEO 回复中可包含 `[ACTION]...[/ACTION]` 隐藏 JSON 块。仅以下动作被允许执行：

| 动作 | 行为 |
|---|---|
| `create_project` | 创建新项目（写入 `projects` 表） |
| `cancel_project` | 取消项目（更新 phase 为 `cancelled`） |
| `publish_project` | 发布项目（更新 phase 为 `publishing`，并入队 `deploy` 任务） |
| `update_project` | 更新项目字段 |
| `pause_project` | 暂停项目（更新 phase 为 `paused`） |

未知动作会被静默忽略并记录警告日志。

### 8.5 完整 API 端点清单（44 个）

详细列表见 [附录 B 端点速查](#附录-b-端点速查)。

---

## 第 9 章 Dashboard 安全模型

Dashboard 提供双模式安全策略：

| 模式 | 触发条件 | 监听地址 | 控制面鉴权 |
|---|---|---|---|
| **本地开发（默认）** | 未设置 `DASHBOARD_API_KEY` | `127.0.0.1` | 无（仅本机访问） |
| **生产 / 远程** | 设置 `DASHBOARD_API_KEY` | `0.0.0.0` | 控制面端点需 `X-API-Key` 请求头 |

**输入验证**：

- `interval` 参数：`Query(ge=1, le=3600)` —— 防止 DoS（拒绝服务攻击）
- `budget_limit_usd`：必须为非负数（`>= 0`）
- `q` 查询参数：必填，防止空查询

**控制面端点**（需鉴权）：

- `POST /api/pipeline/{run-scheduler, stop}`
- `POST /api/projects/{id}/{pause, resume, cancel}`
- `POST /api/decisions/{id}/respond`
- `POST /api/chat/send`
- `POST /api/finance/budget`
- `POST /api/policy`
- `WS /ws/events`（支持 `?api_key=` 查询参数回退）

**公开端点**：所有 `GET` 请求 + `POST /api/analytics/event`（浏览器游戏埋点，无需鉴权）。

CORS（跨域资源共享）默认仅允许 `http://localhost:8080`；可通过 `DASHBOARD_CORS_ORIGINS` 环境变量（逗号分隔）扩展。

鉴权失败返回 `401 {"detail": "Invalid or missing X-API-Key"}`。

---

## 第 10 章 测试与持续集成

### 10.1 测试套件

| 类别 | 文件数 |
|---|---|
| `tests/test_*.py` 单元 / 功能测试 | 32 |
| `tests/integration/test_*.py` 集成测试 | 1 |
| **合计** | **33** |

> 历史 README 写作"36 个测试文件"系 v6 release note 残留口径；实际 `tests/` 目录中（含集成测试子目录）共 33 个 `test_*.py` 文件。

DB 测试使用 `tmp_path` 临时 SQLite，monkeypatch `_get_engine()`，不污染 `data/gcagents.db`。所有异步测试使用 `@pytest.mark.asyncio`。

### 10.2 持续集成

`.github/workflows/ci.yml` 在 push / PR 到 `master` / `main` 时运行：

- `ruff check .`（代码风格）
- `ruff format --check .`（格式检查）
- `mypy orchestrator shared agents dashboard`（类型检查，渐进式严格）
- `pytest tests/ -v`（测试，覆盖率门槛 60%）

Python 3.11 / 3.12 双版本矩阵，单个 job timeout 10 分钟，pip 缓存。

### 10.3 本地运行

```bash
pytest tests/        # 跑全部测试
ruff check .         # 代码风格
mypy .               # 类型检查
```

---

## 第 11 章 部署与运维

### 11.1 环境变量（`.env`）

```
DEEPSEEK_API_KEY=sk-...        # deepseek-v4-flash 回退代码生成
MINIMAX_API_KEY=...            # MiniMax-M3 分析 + MiniMax-M2.1 代码
ZHIPU_API_KEY=...              # glm-4-flash 便宜任务
BUTLER_API_KEY=...             # itch.io Butler 部署
BUTLER_USERNAME=...            # itch.io 用户名
SUNO_API_KEY=...               # Suno 音乐生成（可选）
DASHBOARD_API_KEY=...          # Dashboard 生产鉴权（可选）
DASHBOARD_CORS_ORIGINS=...     # CORS 跨域白名单（逗号分隔，可选）
```

### 11.2 系统依赖

- Python 3.11+
- Node.js 18+（游戏构建）
- Butler CLI v15+（itch.io 部署，可选）
- ComfyUI + Stable Diffusion XL（美术生成，需 GPU，可选）
- Suno API（音乐生成，可选）

### 11.3 启动

```bash
# 多项目调度器（推荐）
python -m orchestrator.main run-scheduler
python -m orchestrator.main run-scheduler --interval 60

# 原型快速模式
python -m orchestrator.main run-prototype "space shooter with powerups"

# 经典模式
python -m orchestrator.main run
python -m orchestrator.main run-forever

# 仅市场扫描
python -m orchestrator.main scan

# 启动 Dashboard
python -m dashboard.web.api_server
# 访问 http://localhost:8080
```

### 11.4 数据备份

- SQLite 文件备份：`data/gcagents.db` 单文件复制即可
- 已生成游戏项目：`data/games/`（部分由 `data/.gitignore` 忽略）
- 部署建议：定期 `cron` 备份 `data/` 目录到对象存储

---

## 第 12 章 关键技术决策（Why）

### 12.1 为什么用事件溯源？

- **不可变性**：仅追加事件保证数据完整性，支持审计与回放
- **因果追踪**：`parent_event_id` 建立因果链，定位问题根因
- **时间旅行**：任意时间点的项目状态可通过重放事件重建
- **解耦**：事件驱动的架构使各模块低耦合，通过事件总线通信

### 12.2 为什么用任务看板替代 FIFO？

- **状态可见性**：任务所处阶段一目了然（triaged / claimed / running / review / completed）
- **优先级管理**：critical / high / normal / low 四级优先级
- **防止双重领取**：原子 CAS 认领保证同一任务同一时间只被一个 Agent 处理
- **依赖跟踪**：任务可声明对其他任务的依赖，被依赖者未完成时无法执行
- **自动分解**：复杂任务可分解为多个子任务，父任务自动阻塞

### 12.3 为什么用 DAG 规划器？

- **并行感知**：波次内任务可并行执行，最大化资源利用率
- **依赖可视化**：DAG 结构清晰展示任务间的数据流和控制流
- **结构化恢复**：失败节点可基于 DAG 结构决定是重试、换策略还是重规划
- **拓扑优化**：拓扑选择器可根据 DAG 特征选择最优编排模式
- **版本化**：每次结构变更创建新版本计划，支持回溯和比较

### 12.4 为什么用 LangGraph 而不是 CrewAI？

- LangGraph 提供**条件路由**（evaluate → re-scan / design）、**状态持久化**、**循环控制**（QA → redevelop 循环）
- CrewAI 更适合平行协作场景，本系统本质是一个**线性流水线 + 条件回退**，LangGraph 的 StateGraph 模型更匹配

### 12.5 为什么用 SQLite 而不是 PostgreSQL？

- **零外部依赖**：无需 Docker、无需数据库服务
- 同一 SQLAlchemy API，升级到 PG 只需改连接字符串
- 单文件存储，备份和迁移简单

### 12.6 为什么前端用原生 HTML/CSS/JS？

- 零构建步骤，改完即生效
- 无需 Node.js 运行时依赖
- FastAPI 可直接挂载静态文件

### 12.7 为什么游戏用 Phaser 4？

- **Web 原生**：无插件、无下载，浏览器直接运行
- **纯单机**：游戏代码无服务器依赖，无网络请求，离线可玩
- **TypeScript 支持**：AI 生成代码类型安全
- **ComfyUI 美术集成**：通过 SD XL 生成真实游戏资产替代矩形占位符
- **Vite 构建**：现代打包工具，输出为单 HTML5 文件

> 当前部署的 npm 包名仍为 `phaser`（v3.x 兼容 ESM 版本），Phaser 4 处于预览阶段。代码层使用 Phaser 4 ESM 语法（`import * as Phaser from 'phaser'`）。

### 12.8 为什么美术用 ComfyUI？

- **本地 GPU 推理**：无需云服务，无 token 成本
- **可控风格**：通过 prompt 模板与风格预设实现一致性
- **批量生成**：HTTP API 支持并行排队多个任务
- **开源生态**：与 SD XL 工作流社区兼容，模型可替换

---

## 第 13 章 开发日志

| 版本 | 日期 | 变更 |
|---|---|---|
| 初始 | — | 基础框架搭建：LangGraph 状态机、市场扫描、代码生成 |
| 迭代 | — | Dashboard 监控面板、CEO 决策、QA 循环、Build 阶段 |
| 迭代 | — | ComfyUI 美术管线、反馈闭环、版本管理、分析埋点 |
| 迭代 | — | 统一 LLM 客户端、CFO / COO Agent、高管聊天面板、财务 API |
| 迭代 | — | 24/7 运行模式、Dashboard 启停按钮 |
| **v1** | — | **多项目编排重构**：CEO 调度器、决策门控（5 类）、任务队列、12 市场数据源、项目看板、任务监控、决策卡片 |
| **v2** | — | **8 项增强**：自动化试玩（Playwright 8 项检查）、机制规划层（GDD→有序机制→逐机制代码生成）、3 层嵌套错误恢复、美术风格一致性（5 种预设）、原型快速模式（5 分钟 demo）、分层记忆系统（短期+长期）、音乐生成（Web Audio + Suno）、自动本地化（15 种语言） |
| **v3** | — | **代码质量与安全强化**：修复 `orchestrator_state` 表缺失 bug；添加 Dashboard `X-API-Key` 鉴权；新增 pytest 测试套件；新增 GitHub Actions CI；新增 README.md 用户入口；ARCHITECTURE.md 更新 |
| **v4** | — | **Dashboard UX 重构**：CEO 单一交互模式（CFO / COO 转为内部节点，移除独立交互 tab）；文档查看器（弹窗查看所有 Agent 工作产物）；调度器暂停 / 恢复功能；CEO 汇报取代 Scheduler Reports；新增 API |
| **v5** | 2026-06-04 | **代码质量审查与新系统添加**：路径遍历漏洞修复；bare-except 清理；输入验证；8 个共享模块；4 个编排器模块；技能 / 工具框架；6 层模型路由；38 个 API 端点 |
| **v6** | 2026-06-04 | **Visual Novel 管线**：6 张 VN 专属表、多平台部署（itch.io + CrazyGames + Poki）、Phaser 4 知识库、复杂度评分、广告 SDK 注入、Prompt 模板目录 |
| **v7** | 2026-06-05 | **章节化 VN 生产脚本 + 文档统一**：scripts/chapter_pipeline/ 提供按章节生成 VN 内容的工程化能力；统一 README 与 ARCHITECTURE 的术语、模型名、API 数（44）、测试文件数（33）、游戏模板数（8）等不一致项；Dashboard 13 分区全部纳入文档 |

---

## 附录 A 术语表

> 全文统一使用以下术语。括号内为同义英文 / 旧称。

### A.1 角色与组织

| 术语 | 解释 |
|---|---|
| **CEO 调度器**（CEO Scheduler / Multi-Project Scheduler） | tick 节拍驱动的多项目调度大脑，是用户唯一可交互的角色 |
| **CFO 节点**（Chief Financial Officer） | 首席财务官内部节点，负责预算预检与财务报告，无独立交互入口 |
| **COO 节点**（Chief Operating Officer） | 首席运营官内部节点，负责健康检查与运营指令，无独立交互入口 |
| **Agent** | AI 代理，模拟公司某类岗位（Designer / Artist / Programmer / QA / ...） |

### A.2 项目阶段

| 阶段 | 含义 |
|---|---|
| **backlog（待启动）** | 项目已加入待办，等候人类批准 |
| **scanning（市场调研中）** | 等待市场信号采集完成 |
| **designing（设计中）** | GDD 生成与机制规划 |
| **developing（开发中）** | 美术、音乐、代码并行生成 |
| **testing（测试中）** | QA 自动化试玩 |
| **building（构建中）** | Vite 打包 |
| **publishing（发布中）** | 推送到 itch.io / CrazyGames / Poki |
| **live（已上线）** | 进入维护期，接收反馈与统计 |
| **paused（已暂停）** | 人类主动暂停 |
| **cancelled（已取消）** | 人类或系统自动取消 |

### A.3 任务看板状态

| 状态 | 含义 |
|---|---|
| **triaged（已分诊）** | 已分析，等待认领 |
| **claimed（已认领）** | 已被 Agent 原子认领 |
| **running（执行中）** | 正在执行 |
| **review（待验证）** | 完成，等待验证 |
| **completed（已完成）** | 已完成并验证通过 |
| **failed（失败）** | 执行失败 |
| **blocked（被阻塞）** | 等待依赖任务完成 |
| **cancelled（已取消）** | 手动取消 |

> 历史 README 写作"pending / verify / done"，已统一为 `triaged` / `review` / `completed`。

### A.4 调度与执行

| 术语 | 解释 |
|---|---|
| **tick** | 调度器的一个时间节拍，默认 60 秒 |
| **DAG**（Directed Acyclic Graph） | 有向无环图，波次并行执行规划器 |
| **CAS**（Compare-And-Swap） | 原子比较交换，防止多个 Agent 同时认领同一任务 |
| **GDD**（Game Design Document） | 游戏设计文档 |
| **Phaser 4**（preview） | Phaser 4 预览版游戏引擎，npm 包名仍为 `phaser` 的 v3.x 兼容 ESM 版本 |
| **ComfyUI** | 本地 GPU 运行的 Stable Diffusion 推理服务，输出 PNG 资产给 Phaser 加载 |
| **Butler** | itch.io 官方部署 CLI |
| **PageRank** | 网页排名算法，用于代码依赖图的重要性评分 |

### A.5 模型与 AI

| 术语 | 解释 |
|---|---|
| **MiniMax-M3** | 当前部署的强推理模型（README 旧称 "DeepSeek Coder" 已废弃） |
| **MiniMax-M2.1** | 当前部署的代码生成模型 |
| **deepseek-v4-flash** | 强推理与代码生成层的回退模型 |
| **glm-4-flash** | 智谱免费模型，用于翻译、格式化等廉价任务 |
| **stable-diffusion-xl** | 美术资产生成模型，SD XL 版本（README 历史版本中的"SD 1.5"表述已统一为 SD XL） |
| **suno** | 音乐生成 API |
| **6 层模型路由** | strong / fast / cheap / code / art / audio 6 个层级的成本感知选型 |
| **复杂度驱动升降** | `complexity >= 0.7` 自动升级到 strong；`< 0.3` 降级到 fast |

### A.6 决策门控

| 决策类型 | 触发条件 |
|---|---|
| **new_project（新项目启动）** | CEO 创建项目于 backlog |
| **publish（项目发布）** | QA 通过 |
| **cancel（项目取消）** | QA 连续失败 3 次 |
| **budget_overrun（预算超限）** | 开发前预算检查 |
| **direction_change（方向调整）** | 市场变化 |

### A.7 数据存储

| 术语 | 解释 |
|---|---|
| **事件溯源**（Event Sourcing） | 所有状态变化以不可变事件形式追加 |
| **WAL 模式**（Write-Ahead Logging） | SQLite 的预写日志模式，提升并发性能 |
| **24 张表** | 18 张基础表 + 6 张 VN 专属表 |
| **33 个测试文件** | 32 个单元 / 功能测试 + 1 个集成测试 |
| **44 个 API 端点** | 见 [附录 B 端点速查](#附录-b-端点速查) |

### A.8 框架特性

| 术语 | 解释 |
|---|---|
| **技能系统**（Skills） | 可插拔的 Agent 能力系统，按条件激活 |
| **工具注册表**（ToolRegistry） | 集中式工具管理，自注册机制 |
| **复杂度评分**（complexity） | GDD + 代码双维度评分，0.45 最低阈值 |
| **自动化试玩**（Playwright） | 8 项无头浏览器验证 |
| **原型模式**（prototype） | 5 分钟快速原型，矩形 + emoji 占位 |
| **分层记忆**（memory） | 短期事件 + 长期教训 + 项目上下文 |

---

## 附录 B 端点速查

| 路径 | 方法 | 用途 | 鉴权 |
|---|---|---|---|
| **状态与信息** | | | |
| `/api/status` | GET | 系统状态 | 否 |
| `/api/agents` | GET | Agent 日志与统计 | 否 |
| `/api/market/report` | GET | 最新市场分析报告 | 否 |
| `/api/market/latest` | GET | 最新市场信号 | 否 |
| `/api/projects` | GET | 所有项目列表 | 否 |
| `/api/pipeline/history` | GET | 编排器历史 | 否 |
| `/api/memory` | GET | 公司记忆 | 否 |
| `/api/gdd/{project_id}` | GET | 项目 GDD | 否 |
| **项目控制** | | | |
| `/api/pipeline/run-scheduler` | POST | 启动调度器 | 是 |
| `/api/pipeline/stop` | POST | 停止调度器 | 是 |
| `/api/pipeline/status` | GET | 调度器状态 | 否 |
| `/api/projects/{id}/pause` | POST | 暂停项目 | 是 |
| `/api/projects/{id}/resume` | POST | 恢复项目 | 是 |
| `/api/projects/{id}/cancel` | POST | 取消项目 | 是 |
| `/api/projects/{id}/advance` | POST | 推进项目阶段 | 否 |
| `/api/projects/live` | GET | 已上线项目列表 | 否 |
| `/api/projects/{id}/documents` | GET | 项目所有文档 | 否 |
| **分析** | | | |
| `/api/analytics/event` | POST | 游戏遥测事件 | 否 |
| `/api/analytics/summary` | GET | 分析摘要 | 否 |
| `/api/analytics/games` | GET | 游戏分析聚合 | 否 |
| `/api/analytics/games/{project_id}` | GET | 单游戏分析详情 | 否 |
| `/api/analytics/top` | GET | Top 游戏排行 | 否 |
| `/api/itch/stats` | GET | itch.io 统计数据 | 否 |
| `/api/itch/refresh` | POST | 刷新 itch 统计 | 否 |
| **反馈** | | | |
| `/api/feedback/summary` | GET | 反馈聚合 | 否 |
| `/api/feedback/{project_id}` | GET | 项目反馈列表 | 否 |
| **WebSocket** | | | |
| `/ws/events` | WS | 实时事件流 | 条件 |
| **聊天** | | | |
| `/api/chat/send` | POST | 发送消息给 CEO | 是 |
| `/api/chat/history` | GET | 聊天历史 | 否 |
| **事件** | | | |
| `/api/events` | GET | 最近事件 | 否 |
| **财务** | | | |
| `/api/finance/budget` | POST | 设置预算 | 是 |
| `/api/finance/summary` | GET | 财务摘要 | 否 |
| **策略** | | | |
| `/api/policy` | GET | 获取公司策略 | 否 |
| `/api/policy` | POST | 设置公司策略 | 是 |
| **决策** | | | |
| `/api/decisions` | GET | 待处理决策列表 | 否 |
| `/api/decisions/history` | GET | 决策历史 | 否 |
| `/api/decisions/{id}/respond` | POST | 回复决策 | 是 |
| **编排器** | | | |
| `/api/orchestrator/projects` | GET | 所有项目（编排器视图） | 否 |
| `/api/orchestrator/projects/{id}` | GET | 单项目详情 | 否 |
| `/api/orchestrator/tasks` | GET | 任务列表 | 否 |
| **记忆** | | | |
| `/api/memory/{project_id}/recent` | GET | 项目近期记忆 | 否 |
| `/api/memory/search` | GET | 搜索长期记忆 | 否 |
| `/api/memory/lessons` | GET | 所有经验教训 | 否 |
| **指标与静态** | | | |
| `/metrics` | GET | Prometheus 指标 | 否 |
| `/games-preview/{path}` | GET | 静态游戏文件服务 | 否 |

**统计**：GET × 27 + POST × 11 + WebSocket × 1 = 39 路由端点 + 2 静态 mount = **44 端点（实际注册到 `@app.*` 装饰器的为 44 个；其中 `/metrics` 是文本接口，`/games-preview` 是 StaticFiles mount）**。

---

*最后更新：v7（2026-06-05）—— 章节化文档统一、术语一致、模型名规范化、API/测试数对齐项目实际。*
