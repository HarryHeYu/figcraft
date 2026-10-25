# PaperCanvas v0.1.0 — Release Notes（发布候选 RC1）

**Agent-Native Scientific Figure Studio** — Figures as Code, Agents as Artists.

PaperCanvas 让 Coding Agent 像写代码一样绘制、修改、维护科研图：版本化
Figure IR（JSON）是唯一事实来源，Agent 只通过语义化 Patch 修改，
确定性渲染器输出真矢量、可编辑的 SVG / PDF / PPTX。

## 核心能力

- **Figure IR v0.1**：Pydantic 严格校验（未知字段/非有限数拒绝）、
  硬错误与质量 lint 分离、乐观并发 revision。
- **事务性 Patch 引擎**：9 个语义操作（add_node / remove_node / update_node /
  set_style / add_edge / remove_edge / add_group / update_label / move_node），
  批量事务、失败零写入、成功 revision+1。
- **确定性渲染**：同一 IR + 同一字体 ⇒ 字节级相同输出。
  - SVG（lxml）：可编辑 `<text>`、mm viewBox、按颜色生成箭头 marker
  - PDF（reportlab）：真矢量直出、TTF 子集嵌入、invariant 元数据
  - PPTX（python-pptx）：全原生形状、每段一个 connector、可编辑文本
- **TextLayout 统一文本层**：Pillow 度量，唯一换行处；三渲染器消费同一布局。
- **Lint FC001–FC008**：越界/结构/溢出（真字体度量）/重叠/字号/箭头穿框/
  字体替代/栅格图像；机器可读 JSON 输出。
- **CLI**：`init / validate / patch / layout / render / lint / inspect / build`。
- **MCP Server**（stdio）：7 个工具 `papercanvas_*`，路径白名单、结构化
  错误返回，与 CLI 共享同一服务层。
- **Agent Skill**：`skills/papercanvas/SKILL.md`（随包分发）。

## 安装（PyPI 发布后）

```bash
pip install papercanvas
papercanvas --help
papercanvas-mcp --root path/to/project
```

当前为发布候选阶段：从仓库安装 `uv sync && uv run papercanvas --help`。

## 质量

- 239 项自动化测试（Windows/macOS/Linux × Python 3.12/3.14 CI 矩阵）
- Release Gate 8 项验收自动化（`tests/test_release_gate.py`，
  证据表 `docs/release-checklist.md`）
- 真实 Coding Agent 端到端验收记录（`docs/m3-e2e-log.md`）
- 跨格式几何一致性 ~4×10⁻⁵ mm（验收线 0.2 mm）
- 三个科研图示例随库分发（`examples/`，含三格式产物）

## 已知限制（v0.1）

1. **PDF 的 CJK 字形依赖本机字体**：含中文标签的图会自动改用系统 CJK
   字体度量与嵌入（Windows：SimHei/微软雅黑/SimSun；macOS：Arial Unicode/
   STHeiti；Linux：WQY/Noto），FC007 会报告替代。仅有 CFF 格式 CJK 字体
   （如部分 Noto CJK）的机器上 PDF 导出会给出明确报错（请改用 SVG/PPTX）；
   emoji 在 PDF 中仍为 .notdef 方框。
2. **PPTX→IR 不做反向同步**：PPTX 是产物，可在 PowerPoint 中自由编辑，
   但修改不会回流 IR。
3. **正交路由无避障**：连线可能穿过无关节点，lint FC006 事后提示。
4. **组标签不自动换行**：支持显式 `\n`；超长组标签横向溢出由后续版本处理。
5. **unit 仅支持 mm**；`schema_version` 仅 `"0.1"`。

## 升级与兼容

首个公开版本，无兼容性负担。`schema_version` 机制已就位，后续格式变更
将带迁移路径。
