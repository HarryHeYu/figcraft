# AGENTS.md — PaperCanvas 工程规则（对所有 Agent 生效）

PaperCanvas 是 Agent-Native Scientific Figure Studio：Figure IR（JSON）是唯一事实来源，
SVG/PDF/PPTX 全是构建产物。修改本项目时必须遵守以下硬性约束，违反任何一条都算实现错误。

## 六条工程约束（批准版 PROJECT-PLAN.md §2，执行时硬性遵守）

1. **命名统一**：项目名 `papercanvas`（PyPI 包名/CLI/MCP 前缀 `papercanvas_*`）。
   GitHub 仓库为 `HarryHeYu/figcraft`（用户 2026-10-24 拍板创建）：仓库名与包名不一致是
   已记录的决策——PyPI 端保留干净的 `papercanvas`，仓库沿用本地目录名。本地目录 `figcraft`
   与仓库同名，代码/文档中不得出现 FigCraft 作为**包名或 CLI 名**。
2. **TextLayout 统一文本层**：字体度量在 `text/text_metrics.py`（Pillow），
   换行/行高/位置/溢出预计算在 TextLayout。三个渲染器只消费统一文本布局，
   **禁止在任何渲染器里独立决定换行**。
3. **读写纪律**：Layout、Patch 是修改 IR 的操作 ⇒ 必须走
   `FigureDocument.save_figure()`（文件锁 + expected_revision + 原子提交）。
   Render、Lint、Inspect 严格只读，绝不写 IR 文件。
4. **路由点制**：`layout/routing.py` 输出正交路径点序列；SVG 消费为 polyline；
   PPTX（M2）不得假设一个 ELBOW connector 能还原任意路径，用多段原生线段实现。
5. **Validation 与 Lint 分离**：无效引用、重复 ID、非法尺寸/颜色、自环等是硬错误
   （`core/validate.py`），禁止提交或渲染；Lint（M2）只管图形质量
   （FC001–FC008：溢出、重叠、字号、箭头穿框等）。
6. **新增测试（约束 6 五类）**：
   a. render 不修改源文件（前后字节比对）；
   b. layout 成功提交后 revision+1；
   c. TextLayout 跨后端一致（SVG 文本行数 == TextLayout 行数）；
   d. 正交路径点序列确定性（同输入同点列）；
   e. Patch 失败后原文件字节不变。

## 架构速览

```
Agent (CLI / MCP / Skill)
        │ 语义化 Patch（验证 → 事务提交 → revision+1）
        ▼
    Figure IR（唯一源，JSON on disk）
        │ Layout（linear / layered + 正交路由，可变操作）
        ▼
  统一几何 + TextLayout（Pillow 度量，唯一换行处）
   ┌────┼────────┐
  SVG(lxml)  PDF(reportlab, M2)  PPTX(python-pptx 原生形状, M2)
```

- 布局只在显式调用时改写坐标；渲染器只消费坐标，绝不自行布局。
- 单位换算只在 `core/geometry.py` 一处（mm ↔ pt ↔ px/EMU）；禁止各渲染器自行换算。
- 几何坐标毫米、字号 pt；IR 中节点宽高字段名是 `w`/`h`。
- MCP Server、CLI、Python API 调用相同的 `core` 服务层，不各写一套逻辑。

## 常用命令

```bash
uv sync                 # 安装/同步依赖（uv.lock 已锁定）
uv run pytest -v        # 全部测试
uv run ruff check .     # lint
uv run ruff format .    # 格式化（改动后建议跑）
uv run papercanvas --help
```

## 其他纪律

- 确定性是产品承诺：同 IR + 同字体 + 同版本 ⇒ 字节级相同输出。
  任何代码路径不得引入时间戳、随机数、集合迭代顺序、locale 依赖。
- 所有 IR 对象有稳定唯一 ID；样式修改不得改变 ID。
- Patch 9 操作：add_node / remove_node / update_node / set_style / add_edge /
  remove_edge / add_group / update_label / move_node；批量事务；失败零写入。
- 新增功能必须带测试；不要留空实现、伪测试或静默跳过的错误。
- v0.1 不做：网页画布、AI 图像模型、位图→SVG 逆向、任意 SVG/PPTX 无损双向导入、
  TikZ 编译器、PPTX→IR 反向同步（README 明示）。
