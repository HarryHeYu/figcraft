# v0.1.0 Release Gate 检查清单

对应 PROJECT-PLAN 草案 §八 的 8 项验收。自动化项由
`tests/test_release_gate.py` 持续验证；本文件记录证据位置。

| # | 验收项 | 状态 | 证据 |
|---|---|---|---|
| 1 | Figure IR 正确验证合法与非法输入 | ✅ | `test_release_gate.py::test_gate_1_*`；完整矩阵 `tests/test_schema.py` |
| 2 | 同一 IR 导出 SVG/PDF/PPTX | ✅ | `test_gate_2_*`（三个示例逐一构建） |
| 3 | SVG/PDF 非栅格化；PPTX 框/文本/箭头可编辑 | ✅ | `test_gate_3_*`（无 `<image>`/`/Subtype /Image`/media；有可编辑文本与原生 connector） |
| 4 | 三示例无严重溢出与误连接 | ✅ | `test_gate_4_*`（FC001–FC008：0 错误 0 警告） |
| 5 | 单节点改色后其余节点属性不变 | ✅ | `test_gate_5_*`（逐字段比对，只有目标节点变化） |
| 6 | 错误 Patch 不修改原文件和 revision | ✅ | `test_gate_6_*`；事务语义 `tests/test_patch.py` |
| 7 | Agent 无人工修改 JSON 完成创建/修改/导出 | ✅ | `tests/test_mcp_e2e.py`（纯 MCP 协议三轮修改）；记录 `docs/m3-e2e-log.md` |
| 8 | Windows/macOS/Linux CI 通过 | ✅ | GitHub Actions run（6 job 矩阵：3.12/3.14 × 三平台），见 README 徽章链接 |

## 发布物核对

- [x] 可安装的 Python 包（src-layout + hatchling，`uv sync` 即用）
- [x] CLI：`init / validate / patch / layout / render / lint / inspect / build`
- [x] Figure IR 规范（`docs/figure-ir.md`）
- [x] SVG / PDF / PPTX 渲染器（确定性输出）
- [x] MCP Server（`docs/mcp.md`，7 工具）
- [x] Agent Skill（`skills/papercanvas/SKILL.md`）
- [x] 三个科研图示例（`examples/`，三格式产物齐备）
- [x] 自动化测试（`uv run pytest`，225 项）
- [x] README 与文档
- [ ] PyPI 发布（`papercanvas`，执行 `uv build && uv publish` 时进行）

## 已知限制（v0.1 明示）

- PDF 的 CJK/emoji 在无 CJK 字形的字体下渲染为 .notdef（SVG/PPTX 由查看器
  回退，不受影响）；CJK 回退排在后续版本。
- PPTX→IR 不做反向同步（PPTX 是产物，可自由编辑，但不回流 IR）。
- 正交路由无避障（lint FC006 事后提示穿越）。
- 组标签不自动换行（短标签场景；支持显式 `\n`）。
