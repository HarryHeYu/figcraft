# FigCraft 项目计划（批准版 · v0.1.0 · 2026-10-24）

> Agent-Native Scientific Figure Studio —— 让 Coding Agent 像写代码一样绘制、修改、维护论文科研图，
> 输出真矢量、可编辑的 SVG / PDF / PPTX。
>
> 本文件是已批准的执行计划，与同目录的《FigCraft-开发规划草案-v0.1.txt》（原始草案）配合阅读。
> 本文件为准；草案中与本文件冲突之处以本文件为准。

## 0. 名称核实结果（2026-10-24 实查）

| 名称 | PyPI | GitHub | 结论 |
|---|---|---|---|
| FigCraft | ✅ 可用 (404) | ❌ `storytold/figcraft` 3320★，Rust 界面设计工具，当日仍在更新，领域过近 | 撞名风险高 |
| FigForge | ❌ 已占用 (200) | — | 排除 |
| VectorSmith | ❌ 已占用 (200) | — | 排除 |
| PaperCanvas | ✅ 可用 (404) | 仅同名小仓库（最高 8★，不同领域） | 当前最优 |

**待决**：最终名称二选一 —— (a) FigCraft：PyPI 可用，GitHub 放 `HarryHeYu/figcraft`（仓库在用户命名空间下技术上可用，但与 3.3k★ 设计工具重名，搜索会被淹没）；(b) PaperCanvas：两端都干净。
开工前（M0 第一步）定死并全局统一：仓库名、包名、CLI、MCP 前缀（`figcraft_*` / `papercanvas_*`）。

## 1. 定位与原则

- Figures as Code；Figure IR 是唯一事实来源；SVG/PDF/PPTX 全是构建产物。
- Agent 只通过语义化 Patch 修改，永不直接写 XML / PPTX 内部文件。
- 确定性渲染：同 IR + 同字体 + 同版本 ⇒ 字节级相同的输出。
- v0.1 不做：网页画布、AI 图像模型、位图→SVG 逆向、任意 SVG/PPTX 无损双向导入、TikZ 编译器。
- 技术栈：Python 3.11+ / uv / Pydantic v2 / Typer+Rich / lxml（SVG）/ reportlab（PDF，M2）/ python-pptx（M2）/ MCP SDK v2 `MCPServer`（M3，本机已装 2.2.0）。
- PDF 不用 CairoSVG（Windows 需 Cairo DLL，已核实本机未装）；文字度量用 Pillow，度量/换行只在 TextLayout 一处。

## 2. 六条工程约束（已批准，执行时硬性遵守）

1. **命名统一**：初始化前核实 GitHub/PyPI 占用，确认后统一仓库、包名、CLI、MCP 前缀。
2. **TextLayout 统一文本层**：在 text_metrics.py 之上预计算字体、换行、行高、位置、溢出状态；三个渲染器只消费统一文本布局，禁止独立决定换行。
3. **读写纪律**：Layout、Patch 是修改 IR 的操作 ⇒ 必须文件锁 + expected_revision + 原子提交；Render、Lint、Inspect 严格只读。
4. **路由点制**：routing.py 输出正交路径点序列；SVG 消费为 polyline；PPTX（M2）不得假设一个 ELBOW connector 能还原任意路径，用多段原生线段实现。
5. **Validation 与 Lint 分离**：无效引用、重复 ID、非法尺寸等是硬错误，禁止提交或渲染；Lint（M2）只管图形质量（溢出、重叠、字号、箭头穿框等 FC001–FC008）。
6. **新增测试**：render 不修改源文件；layout 提交 revision；TextLayout 跨后端一致；正交路径点一致；Patch 失败后原文件字节不变。

## 3. 架构

```
Agent (CLI / MCP / Skill)
        │ 语义化 Patch（验证 → 事务提交 → revision+1）
        ▼
    Figure IR（唯一源，JSON on disk）
        │ Layout（确定性：linear / layered + 正交路由，可变操作）
        ▼
  统一几何 + TextLayout（Pillow 度量，唯一换行处）
   ┌────┼────────┐
  SVG(lxml)  PDF(reportlab, M2)  PPTX(python-pptx 原生形状, M2)
```

- 布局只在显式调用时改写坐标；渲染器只消费坐标，绝不自行布局。
- 单位换算只在 geometry.py 一处（mm ↔ pt ↔ px/EMU）；禁止各渲染器自行换算。
- v0.1 不承诺 PPTX→IR 反向同步（README 明示）。

## 4. Figure IR v0.1

- `Figure(schema_version="0.1", id, revision, canvas, theme, nodes, edges, groups)`
- `Canvas(width, height, unit="mm", margin)`；`Node(id, type=rect|rounded_rect, x, y, w, h, label, style)`
- `Edge(id, source, target, source_port, target_port ∈ {left,right,top,bottom}, style)`；自环是硬错误
- `Group(id, children=[node ids], label, style)`；`Theme(font_family, font_size_pt, palette)`
- 硬校验（core/validate.py）：schema_version 支持项、跨 nodes/edges/groups 全局 ID 唯一、悬空边、自环、非法端口、尺寸 ≤0、颜色（既非 hex 又非调色板键）、group children 不存在。
- Patch 9 操作：add_node / remove_node / update_node / set_style / add_edge / remove_edge / add_group / update_label / move_node；批量事务；`expected_revision` 乐观并发；失败零写入；原子写 = 临时文件 + os.replace + sidecar 文件锁（O_EXCL，超时报错）。

## 5. 布局与渲染

- linear（水平/垂直，按 IR 数组顺序）、layered（简化 Sugiyama：DAG 分层 + 稳定排序，环依赖硬错）；布局后画布按内容 + margin 重算。
- routing.py：right→left 输出 [起点, 中间拐点, 终点] 的正交点列；端口在节点边界上，箭头止于边界。
- SVG：lxml 直出；`<text>` 可编辑、无 `<image>`、无时间戳；页面 bbox = mm 画布；箭头 marker。
- PPTX（M2）：原生 rounded_rect/connector/textbox；从 Office-PowerPoint-MCP-Server 的 utils/（add_textbox、connector_tools、整数枚举绕过 enum）移植。

## 6. 里程碑（每个以"测试绿 + 可演示产物"收口）

- **M0（半天–1 天）**：骨架 + CI（3.12/3.14 × ubuntu/windows/macos）+ ruff + AGENTS.md + Pydantic IR + validate/document(lock/atomic)/patch + CLI(init/validate)。
- **M1（1–2 天）**：TextLayout + linear/layered + routing + SVG 渲染器 + CLI(layout/render/patch)。**验收：三模块 Pipeline（Input Video → Video Encoder → Prediction）JSON → 一条命令出正确 SVG；`uv run pytest -v` 全绿；交付实际 SVG 文件与测试日志，不以"已实现"充当证据。**
- **M2（1–2 天）**：PDF（reportlab 直出、TTF 嵌入、bbox 紧贴）+ PPTX（原生形状、路径点多段线还原）+ Lint FC001–FC008 + 跨格式一致性（几何 ≤0.2mm）。
- **M3（1–2 天）**：CLI 完整化 + 7 个 MCP 工具（`*_create/get/patch/layout/render/lint/inspect`，同 core 服务层，stdio，路径白名单）+ Agent Skill（SKILL.md，只教流程）。
- **M4（1–2 天）**：三示例 + 真实 Agent 端到端（建→多轮修改→导出，未指定对象不动）+ 三平台 CI + README + v0.1.0 发布（Release Gate 8 条全过）。

## 7. 测试清单（约束 6 五类加粗）

- schema 硬错误矩阵（重复 ID / 悬空边 / 自环 / 非法端口 / 尺寸 ≤0 / 非法颜色）
- **Patch 失败后原文件字节不变**；expected_revision 冲突拒绝；成功 revision+1
- **Render 不修改源文件**（前后字节比对）；输出无 `<image>`、含 `<text>`；两次渲染字节相同
- **Layout 成功提交 revision+1**；两次布局输出字节相同（确定性）
- **TextLayout 两实例一致**；SVG 文本行数 == TextLayout 行数（跨后端一致的 M1 形态）
- **正交路径点序列确定性**（同输入同点列）
- CLI init/validate/layout/render 端到端（Typer runner）

## 8. 当前状态与下一步

- 状态（2026-10-24 更新）：
  - **已定名 PaperCanvas**（§0 待决项已决）：PyPI JSON API 复核 404 可用（HTML 端点被
    Fastly 人机验证墙干扰、状态码不可信，以 `/pypi/<name>/json` 为准）。包名/CLI/MCP 前缀
    统一 `papercanvas`。**GitHub 仓库：`HarryHeYu/figcraft`**（用户当日创建并拍板；仓库名
    沿用本地目录名，与 PyPI 包名不一致是已记录的决策——PyPI 端保持干净无撞名）。
    本地目录 `E:\code\figcraft` 即仓库工作副本。
  - **M0 完成**：git + uv 初始化（Python 3.13.3 本地 / CI 3.12+3.14）、Pydantic IR、
    validate/document(lock/atomic)/patch、CLI init/validate、ruff 全绿、CI workflow、AGENTS.md。
  - **M1 完成**：TextLayout（Pillow BASIC 引擎 + 64× 度量）、linear/layered + routing、
    SVG 渲染器、CLI layout/render/patch/build；**验收证据：`examples/basic_pipeline.json`
    → `uv run papercanvas build` 一条命令出 `examples/basic_pipeline.svg`（已浏览器截图
    验证），`uv run pytest -v` 125 全绿（日志 `docs/m1-test-log.txt`），含约束 6 五类测试**。
- 下一步：M2（PDF reportlab + PPTX python-pptx + Lint FC001–FC008 + 跨格式一致性 ≤0.2mm）
  → M3（CLI 完整化 + 7 个 MCP 工具 + Agent Skill）→ M4（三示例 + Agent 端到端 + 发布）。
  git 仓库已初始化（main 分支），代码尚未提交——等待用户指示后做首次 commit。
