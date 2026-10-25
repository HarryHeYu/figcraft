# MCP Server

PaperCanvas 通过 stdio MCP server 暴露 7 个工具，与 CLI 共享同一 `service.py`
服务层（无重复业务逻辑）。基于 MCP Python SDK 2.3 的 v2 `MCPServer` API。

## 启动

```bash
uv run papercanvas-mcp --root path/to/project
# 安装后：papercanvas-mcp --root path/to/project
```

`--root`（默认当前目录）是唯一允许的文件访问范围。

## 安全策略

- **路径白名单**：所有工具的 path 参数（绝对或相对）必须解析到 root 内，
  否则返回 `{"ok": false, "error": "...escapes the project root..."}`。
- **输出限制**：渲染产物固定写在 IR 文件旁边（root 内），不接受任意外部
  输出路径；渲染永远不会覆盖 IR 文件本身。
- **结构化错误**：域错误（文件不存在、revision 冲突、非法操作、路径逃逸）
  以 `{"ok": false, "error": "..."}` 返回，不抛协议异常——Agent 可以读取
  消息后自纠。
- **只读工具**（get/lint/inspect）绝不写盘；lint 使用 lenient 加载以诊断
  硬校验会拒绝的图。

## 工具

| 工具 | 参数 | 返回（摘要） |
|---|---|---|
| `papercanvas_create` | path, figure_id, width?=182, height?=58, margin?=4 | `{ok, path, figure_id, revision}` |
| `papercanvas_get` | path | 完整 IR + `hard_errors` 列表 |
| `papercanvas_patch` | path, operations[], expected_revision? | `{ok, revision, applied[]}`；事务性，失败零写入 |
| `papercanvas_layout` | path, preset?=linear-h | `{ok, revision, canvas, nodes_placed}` |
| `papercanvas_render` | path, formats?=["svg"] | `{ok, files:[{path, format, bytes}]}` |
| `papercanvas_lint` | path, min_font_size_pt?=6 | FC001–FC008 findings + summary |
| `papercanvas_inspect` | path, object_id? | 对象清单或单对象详情（几何/样式/关联） |

## 推荐的 Agent 工作流

1. `papercanvas_create` 建图；
2. `papercanvas_patch` 一批加入节点与边（`expected_revision` 防并发覆盖）；
3. `papercanvas_layout` 排布（layered / linear-h / linear-v）；
4. `papercanvas_lint` 检查；对 `severity: "error"` 的 finding 用定向 patch 修复；
5. `papercanvas_render`（formats `["svg","pdf","pptx"]`）交付。

细节见 `skills/papercanvas/SKILL.md`；真实运行记录见
`docs/m3-e2e-log.md` 与 `tests/test_mcp_e2e.py`（协议级端到端）。
