# Figure IR v0.1 规范

Figure IR 是 PaperCanvas 的唯一事实来源（JSON on disk）；SVG/PDF/PPTX 全是构建产物。
本文是 v0.1 的字段级参考。严格校验由 Pydantic 完成（未知字段、非有限数字一律拒绝）。

## 顶层对象

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | `"0.1"` | 唯一支持版本 |
| `id` | string | 图形 id；`[A-Za-z0-9_-]+` |
| `revision` | int ≥ 1 | 乐观并发版本号；patch/layout 成功提交后 +1 |
| `canvas` | Canvas | 画布 |
| `theme` | Theme | 全局视觉规范 |
| `nodes` | Node[] | 方框 |
| `edges` | Edge[] | 带端口的有向连接 |
| `groups` | Group[] | 逻辑分组（虚线背景框） |

## Canvas

`width`/`height`（mm，>0）、`unit`（仅 `"mm"`）、`margin`（mm，≥0）。
布局成功后画布按 `内容 + margin` 重算。

## Node

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 全局唯一（与边/组共用命名空间） |
| `type` | `rect` \| `rounded_rect` | 圆角半径 = min(3, w/4, h/4) mm |
| `label` | string | 可空；换行由 TextLayout 决定 |
| `x`/`y`/`w`/`h` | mm 或 null | 渲染坐标；null 表示待布局（渲染前必须先 layout） |
| `style` | Style | 见下 |

## Edge

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 全局唯一 |
| `source`/`target` | node id | 自环是硬错误 |
| `source_port`/`target_port` | `left\|right\|top\|bottom` | 端口在节点边框中点上，箭头止于边界 |
| `style` | EdgeStyle | `stroke`、`stroke_width`、`arrow: none\|end\|start\|both` |

## Group

`id`、`children`（非空 node id 列表，每节点至多属一组）、`label`、`style`。
默认样式：`#999999` 虚线框。组框 = 子节点包围盒 + 3mm padding；
组标签画在框上边线上方、不换行。

## Style（节点/组）

`fill`、`stroke`、`stroke_width`（mm）、`stroke_dash: solid|dashed|dotted`。
颜色为 `#rgb`/`#rrggbb` 或 `theme.palette` 的键。

## Theme

`font_family`（默认 Arial）、`font_size_pt`（默认 8，>0）、
`palette`（键 → hex）、`background`（hex）。

字体在渲染机器上解析；找不到时使用替代字体并在 lint FC007 中报告
（`FontMetrics.resolved_family` 记录实际使用的族名）。

## 硬校验（core/validate.py，违反即禁止写入/渲染）

- `schema_version` 受支持
- nodes/edges/groups 的 id 全局唯一
- 边的 source/target 必须存在；自环拒绝
- 节点 w/h > 0（存在时）；画布尺寸 > 0；margin ≥ 0
- 颜色可解析（hex 或调色板键）；stroke_width > 0
- 组 children 非空、存在、无重复、每节点至多一组

## 质量检查（lint，独立于硬校验，不阻塞写入/渲染）

FC001 越界(error) / FC002 结构(error) / FC003 文字溢出(error) /
FC004 节点重叠(warning) / FC005 字号阈值(warning，可配) /
FC006 箭头穿节点(warning) / FC007 字体替代(warning) /
FC008 未声明栅格图像(warning)。

## 确定性与序列化

同一 IR + 同一字体 + 同一版本 ⇒ 字节级相同的输出。
磁盘序列化固定为 `indent=2, ensure_ascii=false` + 尾换行；字段顺序即模型声明顺序。
