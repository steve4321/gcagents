# GCAgents

**GCAgents —— 自主运营的 AI 游戏公司。**

它调研市场、设计游戏、生成代码与美术、本地化、部署上线，全程由 AI Agent 协作完成，重要决策保留人类审批入口。

---

## 第 0 章 序章：这份文档讲什么

| 章节 | 受众 | 你能拿到什么 |
|---|---|---|
| [第 1 章 总览](#第-1-章-总览) | 所有人 | 5 分钟看懂系统 |
| [第 2 章 快速开始](#第-2-章-快速开始) | 开发者 | 装、跑、配置、常见命令 |
| [第 3 章 系统能力](#第-3-章-系统能力) | 产品 / 运营 | 28 项功能矩阵 |
| [第 4 章 技术栈](#第-4-章-技术栈) | 架构师 | 各层技术选型与理由 |
| [第 5 章 项目结构](#第-5-章-项目结构) | 贡献者 | 目录树、模块职责 |
| [第 6 章 测试与持续集成](#第-6-章-测试与持续集成) | 贡献者 | 33 个测试文件、CI 流程 |
| [附录 A 术语表](#附录-a-术语表) | 所有人 | 统一术语解释 |
| 配套：[`ARCHITECTURE.md`](ARCHITECTURE.md) | 深度阅读者 | 完整的架构、数据模型、API、Agent 详解 |

> 配套阅读：架构细节、数据库表结构、API 完整列表、Dashboard 13 个分区详解见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

---

## 第 1 章 总览

GCAgents 用 AI Agent 模拟一家真实游戏公司的组织架构，**CEO（首席执行官）作为调度大脑**统一管理多个并行项目，每个项目独立推进（调研 → 设计 → 开发 → 测试 → 构建 → 发布），重要节点保留人类审批门控。

### 1.1 系统架构图

```
                            GCAgents 系统
═══════════════════════════════════════════════════════════════════════

  CEO 调度器（tick 节拍、多项目并行）
  ┌─────────────────────────────────────────────────────────────────┐
  │  每个 tick（默认 60 秒）                                          │
  │  检查门控 → 认领任务（CAS，原子比较交换）→ 执行 DAG（有向无环图） │
  │  → 验证输出 → 写入记忆 → 推送事件                                 │
  └────┬─────────────┬─────────────┬─────────────┬───────────────────┘
       │             │             │             │
   ┌───▼────┐   ┌────▼────┐  ┌─────▼───┐  ┌──────▼──────┐
   │ 项目 A │   │ 项目 B  │  │ 项目 C  │  │  市场扫描器 │
   │(开发中)│   │(设计中) │  │ (待批准)│  │  (12 数据源)│
   └────────┘   └─────────┘  └─────────┘  └─────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │  任务看板（CAS 原子认领，已取代 FIFO 先进先出队列）                │
  │  状态: triaged（已分诊）→ claimed（已认领）→ running（执行中）      │
  │        → review（待验证）→ completed（已完成）                     │
  └──────┬───────────────┬────────────────┬──────────────────────────┘
         │               │                │
    ┌────▼────┐    ┌─────▼────┐    ┌──────▼──────┐
    │  DAG    │    │  验证框架  │    │  事件存储    │
    │ 规划器  │    │(严格/标准/ │    │（仅追加，   │
    │(波次)   │    │ 提示性)   │    │ 可回放）    │
    └─────────┘    └───────────┘    └─────────────┘

  ┌──────────────┐     ┌────────────────────────────────────────┐
  │  Dashboard   │     │  模型路由器（成本感知选型）               │
  │  FastAPI     │     │  MiniMax-M3（强）/ MiniMax-M2.1（代码）│
  │  :8080       │     │  deepseek-v4-flash（回退）/ glm-4-flash│
  └──────────────┘     │  stable-diffusion-xl（美术）/ suno（音频）│
                       └────────────────────────────────────────┘
  ┌──────────────┐     ┌────────────────────────────────────────┐
  │   SQLite     │     │  技能系统                               │
  │  (异步)       │     │  可插拔、按条件激活的 Agent 能力         │
  │  24 张表     │     │                                        │
  └──────────────┘     └────────────────────────────────────────┘
═══════════════════════════════════════════════════════════════════════
```

### 1.2 关键设计原则

- **CEO 单一交互**：用户只与 CEO 对话；CFO（首席财务官）、COO（首席运营官）作为内部节点自动运行，不提供独立交互入口
- **5 类决策门控必须人类批准**：新项目启动、发布上线、项目取消、预算超限、方向调整
- **任务看板取代 FIFO 队列**：原子 CAS 认领、依赖跟踪、状态机管理
- **事件溯源**：所有状态变化以不可变事件形式追加，支持回放与审计
- **DAG 波次并行**：基于有向无环图的执行规划，最大化并行度
- **6 层模型路由**：根据任务复杂度与成本约束选择最优模型

---

## 第 2 章 快速开始

### 2.1 环境要求

- Python 3.11+
- Node.js 18+（游戏构建时使用）
- Butler CLI v15+（itch.io 部署时使用，可选）
- ComfyUI + Stable Diffusion XL（美术生成时使用，需 GPU，可选）
- Suno API（音乐生成时使用，可选）

### 2.2 安装

```bash
# 克隆并安装
git clone https://github.com/steve4321/gcagents.git
cd gcagents
pip install -e ".[dev]"

# 配置 API 密钥
cp .env.example .env  # 然后编辑 .env 填入你的密钥
```

### 2.3 启动

```bash
# 终端 1：启动多项目调度器（推荐）
python -m orchestrator.main run-scheduler

# 终端 2：启动 Dashboard
python -m dashboard.web.api_server

# 浏览器打开 http://localhost:8080
```

### 2.4 常用命令

| 命令 | 用途 |
|---|---|
| `python -m orchestrator.main run-scheduler` | 启动多项目调度器（推荐） |
| `python -m orchestrator.main run-scheduler --interval 60` | 自定义 tick 间隔（秒） |
| `python -m orchestrator.main run` | 跑一遍完整周期（扫描 → 设计 → 开发 → 部署） |
| `python -m orchestrator.main run-forever` | 24/7 持续运行 |
| `python -m orchestrator.main run-prototype "puzzle game"` | 5 分钟快速原型 |
| `python -m orchestrator.main scan` | 仅执行市场扫描 |
| `python -m dashboard.web.api_server` | 启动 Dashboard（默认 :8080） |

### 2.5 配置

**`.env` 文件**填入 API 密钥：

```
DEEPSEEK_API_KEY=sk-...        # deepseek-v4-flash 回退代码生成
MINIMAX_API_KEY=...            # MiniMax-M3 分析 + MiniMax-M2.1 代码
ZHIPU_API_KEY=...              # glm-4-flash 便宜任务
BUTLER_API_KEY=...             # itch.io Butler 部署
BUTLER_USERNAME=...            # itch.io 用户名
SUNO_API_KEY=...               # Suno 音乐生成（可选）
DASHBOARD_API_KEY=...          # Dashboard 生产鉴权（可选）
DASHBOARD_CORS_ORIGINS=...     # 跨域白名单（可选）
```

**`config/agents.yaml`** —— Agent 与模型映射、6 层路由配置（详见 ARCHITECTURE.md 第 4 章）。

**`config/sources.yaml`** —— 12 个市场数据源配置（详见 ARCHITECTURE.md 第 3 章）。

---

## 第 3 章 系统能力

共 28 项能力，按"调度-设计-开发-运营-监控"五条业务线分组：

### 3.1 调度与编排（6 项）

- **多项目调度器** —— CEO 同时管理多个游戏，每条独立生命周期
- **5 类人类审批门控** —— 新项目 / 发布 / 取消 / 预算超限 / 方向调整
- **任务看板取代 FIFO** —— CAS 原子认领，状态机管理
- **DAG 波次并行规划** —— 依赖跟踪、并行执行、结构化恢复
- **事件溯源** —— 不可变事件流，支持项目时间线回放
- **调度器暂停/恢复** —— 文件标志 + Dashboard 一键按钮

### 3.2 设计与规划（4 项）

- **12 个市场数据源** —— itch.io / Reddit / SteamSpy / TikTok / YouTube / Google Play / App Store / X / Product Hunt 等跨源关联
- **机制规划层** —— GDD（游戏设计文档）分解为有序机制，逐机制代码生成
- **1200 行 Phaser 知识库** —— 11 种游戏类型的架构指南
- **5 分钟原型模式** —— 彩色矩形 + emoji 占位美术快速验证概念

### 3.3 开发与生成（8 项）

- **3 层嵌套错误恢复** —— 重试 → 换策略 → 人工决策
- **验证框架** —— 严格 / 标准 / 提示性三模式
- **AI 美术管线** —— ComfyUI + SD XL，5 种风格预设（16 位像素、8 位像素、卡通、扁平、手绘）
- **角色视觉一致性** —— 跨场景角色统一
- **广告 SDK 注入** —— CrazyGames / Poki 平台自动注入
- **多平台部署** —— itch.io（Butler）、CrazyGames（API）、Poki（API）适配器模式
- **程序化音乐** —— Web Audio API BGM + Suno API 音乐生成
- **自动本地化** —— 15 种语言翻译（含字符名）

### 3.4 视觉小说（VN）专属（3 项）

- **混合 VN 管线** —— 公共路线 + N 角色路线，统计分支
- **VN GDD 校验** —— 10 个必填字段（剧情前提、角色名册、统计系统、分支树、结局、CG 里程碑、场景流、对话风格、美术方向、音乐方向）
- **路线独立 QA 与构建** —— 每条路线独立验证后合并发布

### 3.5 监控与运营（7 项）

- **Dashboard 13 分区** —— 公司策略、游戏分析、游戏性能、财务、决策历史、高管聊天、项目看板、任务监控、市场报告、已上线游戏、Agent 监控、事件日志、公司记忆
- **复杂度评分** —— GDD + 代码双维度，0.45 最低阈值才进入 QA
- **自动化 Playwright 试玩** —— 8 项无头浏览器验证
- **用户反馈闭环** —— itch.io 评论抓取 → AI 分类 → 反馈驱动更新
- **分层记忆系统** —— 短期事件 + 长期教训 + 项目上下文
- **代码依赖图** —— TypeScript / JavaScript PageRank（网页排名算法）分析
- **Prometheus 指标端点** —— `/metrics` 文本格式

---

## 第 4 章 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 编排引擎 | Python 3.11+ async | 多项目 tick 调度器 |
| 任务队列 | 任务看板（SQLite） | CAS 原子认领 |
| 执行规划 | DAG 规划器 | 波次并行执行 |
| 事件存储 | SQLite 仅追加 | 不可变事件流 |
| 分析 AI | MiniMax-M3 / glm-4-flash | 市场分析、游戏设计、评估 |
| 代码 AI | MiniMax-M2.1 / deepseek-v4-flash | Phaser 4 + TypeScript 代码生成 |
| 美术 AI | ComfyUI + SD XL | 游戏资产生成 |
| 音乐 AI | Suno / Web Audio | 背景音乐与音效 |
| 验证 | Playwright + 自定义 | 多模式输出验证 |
| 游戏引擎 | Phaser 4（预览版） + TypeScript + Vite | Web 小游戏运行时 |
| Dashboard | FastAPI + 原生 HTML/CSS/JS | 13 分区监控界面 |
| 数据库 | SQLite（异步 SQLAlchemy） | 24 张表（18 基础 + 6 VN） |
| 持续集成 | GitHub Actions | ruff + mypy + pytest |

### 4.1 6 层模型路由

| 层级 | 主模型 | 回退模型 | 用途 |
|---|---|---|---|
| **strong（强推理）** | MiniMax-M3 | deepseek-v4-flash | 复杂推理、架构设计、CEO 决策 |
| **fast（快速）** | MiniMax-M3 | glm-4-flash | 分析、分类、摘要、评估 |
| **cheap（廉价）** | glm-4-flash | —— | 翻译、格式化、提交信息、意图分类 |
| **code（代码）** | MiniMax-M2.1 | deepseek-v4-flash | 代码生成、编辑、审查 |
| **art（美术）** | stable-diffusion-xl | —— | 美术生成 |
| **audio（音频）** | suno | —— | 音乐生成 |

> 实际部署的模型名以 `config/agents.yaml` 为准；本章使用正式名称，README 历史版本中的 "DeepSeek Coder" 是早期产品名，已废弃。

---

## 第 5 章 项目结构

```
gcagents/
├── orchestrator/             # 核心编排
│   ├── main.py               #   CLI 入口（run / run-forever / run-scheduler / run-prototype / scan）
│   ├── scheduler.py          #   CEO 多项目 tick 调度器
│   ├── kanban.py             #   CAS 任务看板
│   ├── task_queue.py         #   SQLite FIFO 任务队列
│   ├── planner.py            #   DAG 波次规划器
│   ├── topology.py           #   拓扑选择器（DAG 分析）
│   ├── event_store.py        #   事件存储（仅追加）
│   ├── decision_gate.py      #   5 类人类审批门控
│   ├── event_bus.py          #   统一事件发射
│   ├── persistence.py        #   18 张基础表
│   ├── vn_persistence.py     #   6 张 VN 专属表
│   ├── vn_routes.py          #   VN 路线扩展
│   ├── state.py              #   全局状态定义
│   ├── prototype_mode.py     #   5 分钟快速原型
│   ├── graph/                #   经典 13 节点管道
│   └── nodes/                #   CEO / CFO / COO 节点
├── agents/                   # AI Agent
│   ├── research/             #   市场研究（12 源）
│   │   ├── scanner.py
│   │   ├── analyzer.py
│   │   └── sources/fetchers.py
│   └── dev/                  #   开发 Agent
│       ├── designer/         #     GDD 生成 + 机制规划
│       ├── artist/           #     ComfyUI + SD XL 美术（7 文件）
│       ├── programmer/       #     Phaser 4 + TypeScript 代码生成
│       ├── qa/               #     Playwright 自动化试玩
│       ├── music/            #     BGM + 音效生成（3 文件）
│       ├── localize/         #     15 语言翻译
│       └── builder/          #     Vite 构建
├── agents/ops/               # 运维 Agent
│   ├── deployer/             #   多平台部署（6 文件：base / registry / itch / crazygames / poki / itch_stats）
│   ├── analytics/            #   反馈收集
│   └── optimizer/            #   优化器（占位）
├── shared/                   # 共享模块
│   ├── llm_client.py         #   统一 LLM 客户端
│   ├── model_router.py       #   6 层模型路由
│   ├── memory.py             #   分层记忆
│   ├── verification.py       #   验证框架
│   ├── context_manager.py    #   4 层渐进压缩
│   ├── code_graph.py         #   依赖图 + PageRank
│   ├── agent_messaging.py    #   Agent 邮箱
│   ├── sandbox.py            #   沙箱执行
│   ├── complexity.py         #   复杂度评分
│   ├── vn_schema.py          #   VN GDD 校验
│   ├── ad_sdk.py             #   广告 SDK 注入
│   ├── fonts.py              #   CJK / RTL 字体回退
│   ├── npm_runner.py         #   异步 npm 操作
│   ├── persistence_metrics.py
│   └── tools/                #   工具目录（按职责平铺）
├── skills/                   # 技能系统（可插拔）
│   ├── base.py               #   Skill 基类
│   └── code_review.py        #   代码审查技能
├── tools/                    # 工具实现（4 文件，平铺）
│   ├── art.py
│   ├── code_gen.py
│   ├── deploy.py
│   └── file_ops.py
├── dashboard/web/            # Dashboard
│   ├── api_server.py         #   FastAPI 后端（44 端点 + WebSocket）
│   ├── index.html            #   13 分区界面
│   ├── app.js                #   前端逻辑
│   └── style.css
├── game-templates/           # 8 种游戏模板
│   ├── arcade/               #   街机（占位，文件待补）
│   ├── card-game/            #   卡牌
│   ├── idle-clicker/         #   放置点击
│   ├── platformer/           #   平台跳跃
│   ├── puzzle-match/         #   消消乐
│   ├── runner/               #   跑酷
│   ├── shooter/              #   射击
│   ├── tower-defense/        #   塔防
│   └── visual-novel/         #   视觉小说
├── config/
│   ├── agents.yaml           #   Agent ↔ 模型映射
│   ├── sources.yaml          #   12 市场源
│   ├── phaser_knowledge.yaml #   1200 行 Phaser 知识库
│   ├── platforms.yaml        #   多平台部署
│   └── prompts/              #   Prompt 模板
├── scripts/
│   ├── e2e_test.py
│   ├── setup_local.py
│   └── chapter_pipeline/     #   VN 章节化生产脚本
├── data/                     # 运行数据（git 忽略）
│   ├── gcagents.db
│   └── games/
└── tests/                    # 33 个测试文件
    ├── conftest.py
    ├── test_*.py             #   32 个单元 / 功能测试
    └── integration/
        └── test_scheduler_e2e.py
```

---

## 第 6 章 测试与持续集成

### 6.1 测试套件

| 类别 | 文件数 | 说明 |
|---|---|---|
| 单元 / 功能测试 | 32 | `tests/test_*.py` |
| 集成测试 | 1 | `tests/integration/test_scheduler_e2e.py` |
| **合计** | **33** | pytest + pytest-asyncio |

### 6.2 持续集成

`.github/workflows/ci.yml` 在 push / PR 到 `master` / `main` 时运行：

- `ruff check .`（代码风格）
- `ruff format --check .`（格式检查）
- `mypy orchestrator shared agents dashboard`（类型检查，渐进式严格）
- `pytest tests/ -v`（测试，覆盖率门槛 60%）

Python 3.11 / 3.12 双版本矩阵。

### 6.3 本地运行

```bash
pytest tests/        # 跑全部测试
ruff check .         # 代码风格
mypy .               # 类型检查
```

---

## 附录 A 术语表

> 全文统一使用以下术语，括号内为同义英文 / 旧称。

| 术语 | 解释 |
|---|---|
| **CEO 调度器** | tick 节拍驱动的多项目调度大脑，旧称 "CEO Scheduler" / "Multi-Project Scheduler" |
| **CFO 节点** | 首席财务官内部节点，负责预算预检与财务报告，无独立交互入口 |
| **COO 节点** | 首席运营官内部节点，负责健康检查与运营指令，无独立交互入口 |
| **项目阶段** | backlog（待启动）→ scanning（市场调研）→ designing（设计）→ developing（开发）→ testing（测试）→ building（构建）→ publishing（发布）→ live（已上线）/ paused（已暂停）/ cancelled（已取消） |
| **任务看板状态** | triaged（已分诊）→ claimed（已认领）→ running（执行中）→ review（待验证）→ completed（已完成）；失败可重试、被阻塞 |
| **CAS 认领** | Compare-And-Swap，原子比较交换，防止多个 Agent 同时认领同一任务 |
| **DAG 规划器** | 有向无环图波次并行执行规划器 |
| **GDD** | Game Design Document，游戏设计文档 |
| **VN** | Visual Novel，视觉小说 |
| **tick** | 调度器的一个时间节拍，默认 60 秒 |
| **MiniMax-M3** | 当前部署的强推理模型（README 旧称 "DeepSeek Coder" 仅为历史称呼） |
| **MiniMax-M2.1** | 当前部署的代码生成模型 |
| **deepseek-v4-flash** | 强推理与代码生成层的回退模型 |
| **glm-4-flash** | 智谱免费模型，用于翻译、格式化等廉价任务 |
| **stable-diffusion-xl** | 美术资产生成模型，SD XL 版本（README 历史版本中的 "SD 1.5" 表述已统一为 SD XL） |
| **suno** | 音乐生成 API |
| **Phaser 4** | Phaser 4 预览版游戏引擎，npm 包名仍为 `phaser` 的 v3.x 兼容 ESM 版本 |
| **ComfyUI** | 本地 GPU 运行的 Stable Diffusion 推理服务，输出 PNG 资产给 Phaser 加载 |
| **Butler** | itch.io 官方部署 CLI |
| **tick 节拍调度** | 调度器每隔固定时间（默认 60 秒）执行一轮检查、推进、验证、记录 |

---

## 许可证

[MIT](LICENSE)
