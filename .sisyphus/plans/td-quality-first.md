# Tower Defense Quality-First Production Plan

**Status:** Approved (2025-06-17)
**Goal:** 以塔防为单一 genre 打磨，建立质量门控体系，实现稳定量产后再横向扩展
**Output shape:** 10 波、3 塔 3 敌、数据驱动、可部署到 itch.io 的 TD web 游戏

---

## 1. 为什么选塔防

TD 是唯一一个在**中等复杂度下覆盖全部质量门控维度**的 genre：

| 质量维度 | TD 测试方式 | 优势 |
|---|---|---|
| 点击命中率 | 网格放塔，精确坐标验证 | 坐标 bug 一眼可见 |
| 游戏循环闭合 | 波次 → 基地血量 → 胜/负 | 输赢条件明确 |
| 机制完整性 | 7 个核心机制（放置/寻路/射击/波次/经济/升级/基地） | 比 puzzle (3-4) 多 |
| 资产存在性 | 多塔型 + 多敌型 + 路径 + UI | 资产引用密集 |
| `__TEST__` 契约 | 波次/金币/敌人/塔状态全可测 | 测试接口自然 |
| 质量可见性 | 敌人走不走、塔射不射、金币涨不涨肉眼秒判 | **最优** |

**核心策略**：先用手工打造的「黄金模板」校准质量门控，再用 LLM 基于模板生成变体，迭代到稳定。

---

## 2. 四阶段路线图

```
TD-0  黄金模板（1.5-2 周）—— 工程师手写，是质量基准线
  ↓
TD-1  质量门控（2 周，与 TD-0 后半段并行）—— quality_gate.py
  ↓
TD-2  LLM 生成迭代（2-3 周）—— 调优 prompt，目标 80% 通过门控
  ↓
TD-3  量产验证（1-2 周）—— 3-5 个/周，成本 ≤$5，通过率 ≥70%

总计 7-9 周（1 人全职）
```

**关键转折点**：TD-0 + TD-1 完成（~3.5 周）后，系统从「能产出」变成「能判断好坏」。

---

## 3. Phase TD-0：黄金模板

### 3.0 设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 固定路径 vs 动态寻路 | **固定路径（waypoint 数组）** | 简化 LLM 生成；绝大多数流行 TD 用固定路径 |
| Phaser 图形 vs ComfyUI 美术 | **Phaser 图形占位** | 可靠性优先（D4）；模板零外部依赖 |
| 飞行敌人 | **不加**（首版） | 增加复杂度但不增加门控覆盖；阶段 2 再加 |
| 塔升级 | **2 级**（基础 + 1 次升级） | 验证升级机制存在，但不膨胀复杂度 |
| 对象池 | **ProjectilePool** | 子弹高频创建销毁，必须池化 |
| 坐标系统 | **`__GAME_CONFIG__` 唯一来源** | 修复 H3 坐标偏移 bug |

### 3.1 游戏设计

**画布**：800 × 600

**网格**：40px 格子 → 20 × 15 格

**路径**：S 型曲线，约 15 个 waypoint

**初始资源**：100 金币

**基地**：20 HP

**3 种塔**：

| 塔 | 成本 | 伤害 | 射程 | 攻速 | 特效 |
|---|---|---|---|---|---|
| Arrow Tower（箭塔） | 50 | 10 | 120px | 500ms | 单体 |
| Cannon Tower（炮塔） | 100 | 30 | 100px | 1500ms | AOE（半径 40px） |
| Frost Tower（冰塔） | 75 | 5 | 110px | 800ms | 减速 50%（持续 1s） |

**升级**：每塔 1 次升级，费用 = 基础成本 × 0.75，效果：伤害 +50%，射程 +20%

**3 种敌人**：

| 敌人 | 血量 | 速度 | 金币奖励 | 基地伤害 |
|---|---|---|---|---|
| Runner（跑者） | 30 | 80px/s | 5 | 1 |
| Tank（坦克） | 100 | 40px/s | 15 | 3 |
| Brute（壮汉） | 60 | 60px/s | 10 | 2 |

**10 波次**：

| 波 | 敌人组成 | 间隔 |
|---|---|---|
| 1 | 5 × Runner | 800ms |
| 2 | 8 × Runner | 700ms |
| 3 | 5 × Runner + 2 × Brute | 700ms |
| 4 | 10 × Runner | 600ms |
| 5 | 3 × Tank | 1200ms |
| 6 | 8 × Runner + 3 × Brute | 600ms |
| 7 | 4 × Tank + 5 × Runner | 800ms |
| 8 | 10 × Brute | 500ms |
| 9 | 5 × Tank + 5 × Brute + 5 × Runner | 500ms |
| 10 | 8 × Tank | 1000ms |

**胜负条件**：
- 胜利：消灭第 10 波全部敌人，基地 HP > 0
- 失败：基地 HP ≤ 0

### 3.2 文件结构

```
game-templates/tower-defense/
├── package.json                         # 复用 puzzle-match 的 Phaser 4 + Vite 配置
├── tsconfig.json                        # 复用
├── vite.config.ts                       # 复用
├── index.html                           # TD 专用 body（canvas + UI 叠加层）
├── public/
│   └── assets/                          # 空目录占位（Phaser 图形运行时生成，无静态资源）
└── src/
    ├── main.ts                          # 场景注册 + __TEST__ 契约挂载
    └── game/
        ├── config.ts                    # ★ __GAME_CONFIG__ — 坐标/网格/画布唯一来源
        ├── data/
        │   ├── waves.json               # 10 波配置
        │   ├── enemies.json             # 3 种敌人属性
        │   ├── towers.json              # 3 种塔属性 + 升级数据
        │   └── path.json                # waypoint 坐标数组
        ├── entities/
        │   ├── Tower.ts                 # 放置/瞄准/射击/升级/范围圈渲染
        │   ├── Enemy.ts                 # 寻路/血量条/减速状态/死亡
        │   ├── Projectile.ts            # 弹道/命中/AOE
        │   └── Base.ts                  # 基地血量/受击
        ├── systems/
        │   ├── WaveManager.ts           # 波次生成/间隔/进度/全部清除检测
        │   ├── PathFinder.ts            # waypoint 跟随（沿路径插值移动）
        │   ├── TowerFactory.ts          # 塔创建/类型/放置验证（格子占用检查）
        │   ├── ProjectilePool.ts        # 子弹对象池（预分配/复用）
        │   └── EconomyManager.ts        # 金币/消费/击杀奖励/升级消费
        └── scenes/
            ├── BootScene.ts             # Phaser 图形纹理预生成（无外部加载）
            ├── MenuScene.ts             # 标题 + Start 按钮
            ├── GameScene.ts             # ★ 主玩法 — 网格/路径/放塔/战斗/经济/HUD
            └── GameOverScene.ts         # 胜负显示 + 重玩
```

**预估 LOC**：1200-1500

### 3.3 `__GAME_CONFIG__`（config.ts）

```typescript
export const __GAME_CONFIG__ = {
  canvas: { width: 800, height: 600 },
  grid: { cellSize: 40, cols: 20, rows: 15, offsetX: 0, offsetY: 0 },
  path: { color: 0x8b7355, width: 38 },       // 路径渲染颜色/宽度
  buildable: { color: 0x2d5a1e, alpha: 0.3 },  // 可建造区域
  economy: { startGold: 100 },
  base: { maxHp: 20 },
  waves: { count: 10 },
  hud: {
    goldX: 16, goldY: 16,
    hpX: 16, hpY: 48,
    waveX: 700, waveY: 16,
    towerMenuY: 540,  // 底部塔选择栏
  },
} as const;
```

**强制约束**（写入 PROGRAMMER_SYSTEM_PROMPT）：
- 所有交互坐标必须通过 `__GAME_CONFIG__` 计算
- 禁止硬编码像素值
- 网格坐标 ↔ 屏幕坐标转换函数在 config.ts 中定义

### 3.4 `__TEST__` 契约（main.ts）

```typescript
declare global {
  interface Window { __TEST__: GameTestContract; }
}

interface GameTestContract {
  ready: boolean;

  state(): {
    gold: number;
    baseHealth: number;
    maxBaseHealth: number;
    currentWave: number;      // 0 = 未开始, 1-10 = 进行中
    totalWaves: number;
    enemiesAlive: number;
    towersPlaced: number;
    isWaveInProgress: boolean;
    isGameOver: boolean;
    isVictory: boolean;
  };

  // 质量门控命令
  placeTower(gridCol: number, gridRow: number, towerType: string): boolean;
  upgradeTower(gridCol: number, gridRow: number): boolean;
  startNextWave(): boolean;
  getTowerCount(): number;
  getEnemyPositions(): Array<{ x: number; y: number; hp: number; maxHp: number }>;
  fastForward(ms: number): void;  // 加速游戏时间（测试用）
}
```

### 3.5 关键实现要点

**TowerFactory — 放置验证**：
- 检查格子是否在 buildable 区域（非路径上）
- 检查格子是否已被占用
- 检查金币是否足够
- 放置成功 → 扣金币 → 创建 Tower 实体 → 注册到网格占用表

**PathFinder — waypoint 跟随**：
- 读取 `path.json` 的 waypoint 数组
- Enemy 沿 waypoint 线性插值移动
- 到达终点 → 对 Base 造成伤害 → 移除 Enemy
- 减速效果：速度 × 0.5，持续时间内生效

**WaveManager — 波次控制**：
- `startNextWave()` → 按 waves.json 生成敌人
- 全部敌人生成后，等待 `enemiesAlive === 0` → 波次完成
- 第 10 波完成 → 触发胜利

**GameScene — HUD 渲染**：
- 左上：金币数（带图标）
- 左上下方：基地血量条
- 右上：波次进度（3/10）
- 底部：塔选择栏（3 个按钮 + 价格 + 图标）
- 选中塔后：鼠标跟随半透明预览圆圈（显示射程）

**BootScene — 图形纹理生成**（零外部资源）：
```typescript
// 用 Phaser Graphics 生成纹理，避免依赖外部 PNG
// 箭塔：绿色三角形
// 炮塔：红色方形
// 冰塔：蓝色六边形
// 跑者：黄色小圆
// 坦克：紫色大圆
// 壮汉：橙色方圆
```

### 3.6 TD-0 验收标准

| 检查项 | 标准 |
|---|---|
| `npm run build` | 零错误零警告 |
| `npm run dev` → 浏览器 | 游戏可玩 |
| 手动试玩 | 能放塔、敌人沿路径走、塔射击、金币涨、波次推进、10 波后胜利或中途失败 |
| `__TEST__` 接口 | 浏览器控制台 `__TEST__.state()` 返回完整状态对象 |
| 放塔测试 | `__TEST__.placeTower(5, 5, 'arrow')` → `towersPlaced` +1 |
| 波次测试 | `__TEST__.startNextWave()` → `enemiesAlive > 0` → 等待 → `enemiesAlive === 0` → `currentWave` +1 |
| 胜利测试 | 放足够塔 + 打完 10 波 → `isVictory === true` |
| 失败测试 | 不放塔 → `baseHealth` 减少到 0 → `isGameOver === true` |
| TypeScript | 零 `any` 类型 |
| 文件数 | ≤ 16 个 .ts 文件 |

---

## 4. Phase TD-1：质量门控引擎

### 4.1 新建 `shared/quality_gate.py`

```python
@dataclass
class GateResult:
    name: str
    severity: Literal["hard_veto", "soft_warn"]
    passed: bool
    evidence: str        # 具体失败原因（给 LLM 反馈用）

@dataclass
class GateReport:
    results: list[GateResult]
    overall_passed: bool  # 全部 hard_veto 通过 + 无 hard_veto 失败
    hard_failures: list[GateResult]
    soft_warnings: list[GateResult]

async def run_quality_gate(
    game_dir: Path,
    gdd: dict,
    mode: str = "standard"  # "strict" | "standard" | "quick"
) -> GateReport:
    ...
```

### 4.2 六项检查实现

| # | 检查 | 严重级别 | 实现方式 |
|---|---|---|---|
| 1 | **机制完整性** | hard_veto | 解析 GDD `min_mechanics`，grep 生成代码验证每个机制有对应 class/function |
| 2 | **资产存在性** | hard_veto | 正则提取所有 `this.load.image()` / `load.audio()` 路径，验证文件存在 |
| 3 | **游戏循环闭合** | hard_veto | Playwright：放塔 → 开始波次 → 等待 → 断言 `isGameOver` 或 `isVictory` 在 120s 内变为 true |
| 4 | **`__TEST__` 契约** | hard_veto | Playwright eval `__TEST__`，验证 `ready === true` + `state()` 返回 10 个字段 + `placeTower()` 返回 boolean |
| 5 | **点击命中率** | hard_veto | Playwright：在网格不同位置点击放塔，验证 `towersPlaced` 递增，成功率 ≥ 90% |
| 6 | **复杂度评分** | soft_warn | 复用 `shared/complexity.py`，阈值 0.55（从 0.45 提高） |

### 4.3 校准流程

1. **黄金模板必须 100% 通过**：如果手工写的 TD 模板通不过某个检查 → 检查逻辑有 bug，修复检查
2. **旧游戏至少 60% 被否决**：拿 data/games/ 下 3 个旧游戏跑门控，预期大部分被否决（证明门控有效）
3. **接入 scheduler**：QA 阶段后调用 `run_quality_gate()`，hard_veto 失败 → Layer 2 恢复

### 4.4 TD-1 验收标准

| 检查项 | 标准 |
|---|---|
| 黄金模板通过率 | 100%（6/6 检查全通过） |
| 旧游戏否决率 | ≥ 60%（证明门控不是橡皮图章） |
| 门控执行时间 | < 30 秒/游戏（Playwright 模拟 + 静态分析） |
| 接入 scheduler | QA 阶段自动触发，hard_veto 失败触发 Layer 2 |

---

## 5. Phase TD-2：LLM 生成迭代

### 5.1 生成策略

基于黄金模板的「scaffold + 变体」策略（复用 VN 计划 D5）：

1. **Round 1（数据层）**：LLM 生成新的 `waves.json` + `enemies.json` + `towers.json` + `path.json`，主题化命名（如太空主题：Laser Tower / Plasma Tower / Shield Tower）
2. **Round 2（逻辑层）**：LLM 基于黄金模板的 GameScene 做主题化修改（纹理颜色、特效、HUD 文案），不改核心逻辑结构

**LLM 不能修改**：`config.ts`（坐标系统）、`main.ts`（`__TEST__` 契约）、所有 `systems/` 文件、`entities/` 的接口

### 5.2 迭代循环

```
生成 5 个不同主题 TD（太空/中世纪/植物/像素/蒸汽朋克）
  ↓
运行质量门控
  ↓
分析失败模式（哪个检查最容易挂？）
  ↓
修复 prompt / 模板 / 检查逻辑
  ↓
重新生成 → 重测
  ↓
重复直到 ≥ 80% 通过
```

### 5.3 TD-2 验收标准

| 检查项 | 标准 |
|---|---|
| 生成成功率 | ≥ 80%（5 个主题中 ≥ 4 个通过全部 hard_veto） |
| 单游戏生成时间 | ≤ 15 分钟 |
| 单游戏成本 | ≤ $3 |
| 失败模式可追溯 | 每个失败案例有具体原因 + 修复方案 |

---

## 6. Phase TD-3：量产验证

### 6.1 批次生产

连续 2 周内生成 10+ 个 TD 游戏，测量：

| 指标 | 目标 |
|---|---|
| 通过率 | ≥ 70% |
| 单游戏成本 | ≤ $5 |
| 端到端时间 | ≤ 90 分钟（扫描→设计→开发→QA→构建→部署） |
| itch.io 上线率 | 100%（通过的自动部署） |

### 6.2 运维接入

- 反馈收集器接入 scheduler tick（每 30 ticks）
- 已上线 TD 游戏收到 ≥ 2 条 bug/feature 反馈 → 触发 MODE_UPDATE
- 记忆系统：每个完成的 TD 项目自动提取教训，注入后续生成 prompt

### 6.3 TD-3 验收标准

| 检查项 | 标准 |
|---|---|
| 产能 | ≥ 3 个/周 |
| 质量 | ≥ 70% 通过 6 项门控 |
| 成本 | ≤ $5/个 |
| 反馈闭环 | 至少 1 个已上线游戏触发自动更新 |
| 记忆利用 | ≥ 3 个 `lesson:programmer` 条目被注入 prompt |

---

## 7. 横向扩展（TD-3 后）

TD 阶段产出的通用基础设施，迁移到其他 genre 时复用：

| 产出 | 复用方式 |
|---|---|
| `quality_gate.py` | 换 GDD schema 和 `__TEST__` 字段即可 |
| `__GAME_CONFIG__` 约定 | 所有 genre 统一坐标系统 |
| `__TEST__` 契约模式 | 每个 genre 定义自己的 state + commands |
| 生成 prompt 优化经验 | scaffold + variant 策略通用 |
| 门控校准方法论 | 黄金模板校准法 |

预估每个新 genre 适配：1-2 周。

---

## 8. 与现有计划的关系

| 现有计划 | 本方案关系 |
|---|---|
| `demo-to-product` H1-H10 | H3（坐标）→ config.ts；H6（机制截断）→ 门控检查 1；H8（预算）已完成；其余分配到 TD-2/TD-3 |
| `demo-to-product` 12 项验收 | 精简为 6 项 TD 专用检查，TD-3 后扩展到通用 12 项 |
| `vn-pipeline` | 暂停 — VN 专属代码开发推迟到 TD 量产验证后 |
| `multi-project-orchestrator` | 已完成，本方案在其基础上运行 |

---

## 9. 风险与缓解

| 风险 | 严重度 | 缓解 |
|---|---|---|
| 黄金模板过于复杂，LLM 无法有效生成变体 | 高 | 数据驱动设计——LLM 只改 JSON 数据，不改逻辑代码 |
| 质量门控误判（好的游戏被拒/差的游戏通过） | 高 | 黄金模板校准法——已知好的必须 100% 通过 |
| LLM 在 Round 2 破坏模板结构 | 中 | 明确 "MUST NOT modify" 清单 + 生成后 diff 检查 |
| 生成成本超 $5 | 中 | Round 1+2 共 2 次 LLM 调用，预算 ~$0.60；ComfyUI 可选 |
| itch.io TD 游戏太多，曝光不足 | 低 | 主题差异化（太空/植物/蒸汽朋克）+ 标题优化 |

---

## 10. 里程碑总览

| 周次 | 里程碑 |
|---|---|
| W1-2 | TD-0 黄金模板可玩，`__TEST__` 完整 |
| W2-3.5 | TD-1 质量门控引擎上线，黄金模板 100% 通过 |
| W3.5-6 | TD-2 生成迭代，≥ 80% 通过门控 |
| W6-8 | TD-3 量产验证，≥ 70% 通过率，3-5 个/周 |
| **W8** | **塔防稳定量产达成** |
