# 视觉小说生产管线流程图

## 两条入口

### 入口 1：单游戏生产（`scripts/run_anti_capitalist_vn.py`）

```
python3 scripts/run_anti_capitalist_vn.py --step all
```

**流程**：
```
GAME_PROPOSAL (硬编码在脚本中)
        ↓
[Step 1: step_design] ──→ data/games/capital-revolt/gdd.json
        ↓                      (agents/dev/designer/gdd_generator.py)
[Step 2: step_art] ────→ data/games/capital-revolt/public/assets/
        ↓                      (ComfyUI via SpriteGenerator)
[Step 3: step_music] ──→ public/assets/audio/
        ↓                      (WebAudio 程序化 BGM)
[Step 4: step_code] ───→ data/games/unknown/  (注意：路径是 "unknown" 不是 "capital-revolt")
        ↓                      (agents/dev/programmer/code_generator.py)
[Step 5: step_qa] ──────→ Playwright 运行时检查
[Step 6: step_build] ───→ data/games/unknown/dist/
```

**问题**：
- 美术只生成空占位文件（已修复，调用了 ComfyUI）
- 代码生成到 `unknown/` 目录，与美术/配乐目录不一致
- 步骤串行，总耗时 ~15 分钟
- 单次产出 28K 字符，1.7K 代码行

---

### 入口 2：章节化生产（`scripts/chapter_pipeline/run_chapter_production.py`）

```
python3 -m scripts.chapter_pipeline.run_chapter_production \
    --gdd data/games/capital-revolt/gdd.json \
    --output data/games/capital-revolt-chapters \
    --chapters 5
```

**流程**：
```
gdd.json (单游戏 GDD)
        ↓
[1] world_bible.py ───→ world_bible.json
        │                (角色、地点、属性、风格、剧情大纲 — 全游戏共享)
        ↓
[2] chapter_splitter.py ──→ chapter_1_gdd.json ... chapter_5_gdd.json
        │                     (每章独立 GDD，引用世界书，包含本章节点/对话/写作指令)
        ↓
[3] 串行循环：每章执行
    ├── [3a] _run_chapter_art  ──→ chapter_N/public/assets/{backgrounds,characters}
    │       (ComfyUI 生成 3 背景 + 4 角色立绘, ~3 分钟)
    ├── [3b] _run_chapter_code ──→ chapter_N/src/game/{systems,scenes,data}
    │       (LLM 8 轮生成: engine + common + 4 routes + endings + scenes, ~7 分钟)
    │       (chapter_codegen.py 容错版: 单轮失败不中断整个章节)
    └── [3c] validate against bible
        ↓
[4] chapter_merger.py ──→ final/data/{branching,dialogue,endings,world_bible,cross_chapter}.json
        │                   (合并所有章节，命名空间化 node id，跨章节存档)
        ↓
[5] final 目录：
    ├── data/         (合并后的数据)
    ├── public/assets/(所有章节的美术资源)
    ├── chapter_select.html  (章节选择页面)
    └── ...  (但还缺统一的 game 代码入口)
```

**关键模块**：

| 文件 | 职责 | 输入 | 输出 |
|---|---|---|---|
| `world_bible.py` | 提取/校验世界一致性 | gdd.json | world_bible.json |
| `chapter_splitter.py` | GDD 拆分（Freytag 戏剧弧） | gdd + bible | N 个 chapter_N_gdd.json |
| `chapter_codegen.py` | 容错版章节代码生成 | chapter GDD | chapter_N/src/ |
| `chapter_merger.py` | 章节合并 + 跨章节存档 | N 个章节数据 | final/ |
| `run_chapter_production.py` | 主编排 | GDD 路径 | 完整章节游戏 |

**已验证**：Chapter 1 跑通（8 轮 0 失败）

---

## 美术资源文档来源（你要问的核心问题）

**当前流程中谁决定要画什么图？**

```
┌─────────────────────────────────────────────────────┐
│ 美术资源"需求清单"来源链                              │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. World Bible (world_bible.py)                    │
│     └─ 角色视觉描述 (characters[].visual)            │
│     └─ 全局风格指南 (art_style.character/background)  │
│     └─ 否定提示词 (art_style.negative_prompt)       │
│                                                     │
│  2. Chapter GDD (chapter_splitter.py)               │
│     └─ 继承自原始 GDD:                               │
│        ├─ scenes[] ──→ 背景图清单                   │
│        └─ character_roster[] ──→ 角色立绘清单        │
│     └─ chapter_specific: scenes 用 ch{N}_ 前缀命名  │
│                                                     │
│  3. ComfyUI 实际生成 (sprite_generator.py)          │
│     └─ 接收 scene_name + scene_description           │
│     └─ 用 art_style 构造 prompt                      │
│     └─ 输出: assets/{backgrounds,characters}/*.png  │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**问题清单**：

| 问题 | 影响 | 当前处理 |
|---|---|---|
| 5 章节共用原始 GDD 的 7 个 scenes | 每章背景几乎一样 | 章节用 `ch{N}_` 前缀区分文件名 |
| character_roster 5 角色，5 章节 | 每章画同一批角色立绘 | OK (角色是连贯的，这是设计意图) |
| 没有章节特定的场景描述 | 背景图无章节特异性 | splitter 没生成 chapter_scenes |
| 角色 visual 描述空 (GDD 字段没填) | ComfyUI 只能用默认 prompt | 兜底用 character 名称 |

**应当改进**：

1. **chapter_splitter 应该为每章生成专属 scenes**
   - 第1章: "公司总部办公室、财务部深夜走廊、地铁末班车"
   - 第5章: "奥姆尼公司CEO办公室、证券交易所、革命广场"
2. **World Bible 的 character.visual 应来自原始 GDD 的描述字段**
3. **美术和代码可以并行跑**（你已经问到）

---

## 并行化机会

**当前**：每章内部 art → code 串行（等 3 分钟 art 才开始 code）

**可以并行**：
- 第 N 章 art 和 第 N-1 章 code 可以同时跑
- 不同章节的 art 完全独立（不同 output 目录）
- 不同章节的 code 完全独立（不同 project_dir）

**最优并行架构**：
```
Chapter 1: [art 3min | code 7min]
Chapter 2:   [art 3min | code 7min]   ← Chapter 2 art 跟 Chapter 1 code 并行
Chapter 3:     [art 3min | code 7min] ← Chapter 3 art 跟 Chapter 2 code 并行
Chapter 4:       [art 3min | code 7min]
Chapter 5:         [art 3min | code 7min]
                                            ↓
                                       [merge 1min]
```

总耗时：~22 分钟（vs 当前串行 ~50 分钟）

---

## 现状一句话总结

- **单游戏入口**（`run_anti_capitalist_vn.py`）：工作但规模小（28K 字符）
- **章节入口**（`chapter_pipeline/`）：架构搭好，Chapter 1 验证通过，但还有几处待补：
  1. 美术资源文档：当前继承自原始 GDD，没有章节特异性场景
  2. 并行化：现在是串行，应该让 art/code 跨章节并行
  3. 最终统一游戏代码：merger 输出数据但没生成统一 game 代码（ChapterMenuScene 已写好但没注入）
  4. final 目录目前缺 index.html 入口（需要从某章代码复制 + 注入 ChapterMenuScene）

---

## 待你决策

1. **美术文档改进**：
   - A. splitter 自动为每章生成 3-5 个章节特定场景描述
   - B. 保持现状，靠 GDD 原始 scenes
   - C. 让 LLM 在 chapter_splitter 里生成章节特定场景（多一次 LLM 调用）

2. **并行执行**：
   - A. 改写 run_chapter_production.py，用 asyncio.gather 让 art/code 跨章节并行
   - B. 保持串行，先把单章节跑通
   - C. 用独立进程跑 art，独立进程跑 code（更彻底并行但复杂）

3. **统一游戏入口**：
   - A. 用 Chapter 1 代码 + 替换数据 + 注入 ChapterMenuScene
   - B. LLM 单独生成一个 unified-game 的代码（多一次 LLM 调用）
   - C. 用现有的 merger 输出数据，让玩家分别打开每章 dist/
