# M3 真实 Agent 端到端验收记录（2026-10-24）

验收人：Claude（ZCode，真实 Coding Agent 会话内执行）。
输入方法描述（用户视角）：

> 画一个视频 Unlearning 框架图：视觉编码器提取特征，经跨模态连接器送入 LLM，
> LLM 分出 Forget 和 Retain 两个遗忘头，两路输出经门控合成最终输出。

全部操作通过真实 CLI（`uv run papercanvas …`）完成，无任何手工 JSON 编辑。
工作目录 `/tmp/pc-e2e/`，最终产物已入库 `examples/video_unlearning.*`，
逐轮 patch 文件在 `docs/e2e/ops*.json`。

## 时间线

| 步骤 | 命令（节选） | 结果 |
|---|---|---|
| 创建 | `papercanvas init video_unlearning.json --id video_unlearning` | rev 1 |
| 结构填充 | `papercanvas patch --ops ops1.json`（6 节点 + 6 边一批） | rev 2，列出 12 条 applied |
| 自动布局 | `papercanvas layout --preset layered` | rev 3，画布 178.6×34 mm |
| **修改轮 1** | ops2.json：`set_style forget_head`（橙）、`set_style retain_head`（淡蓝）、`add_group forget_retain` | rev 4 |
| **修改轮 2** | ops3.json：`update_label connector`→"Cross-Modal Connector"、`update_node llm w=34` | rev 5 |
| **修改轮 3** | ops4.json：`remove_edge e_forget_out` + `add_edge`（top→bottom 重走线）、`set_style gated_output stroke_width 0.8` | rev 6 |
| Lint 反馈修复 | lint 报 **FC003**（轮 2 改名导致标签溢出）→ ops5.json：`update_node connector w=26` | rev 7，lint clean |
| 导出 | `papercanvas render --format all`（执行两次验证确定性） | svg/pdf/pptx 全部生成 |
| 不变性验证 | 逐对象 dict 比对（脚本内联于会话） | 全部 PASS（见下） |
| 确定性 | 两份导出 SHA-256 对比 | svg/pdf/pptx 全 PASS |
| 视觉检查 | 浏览器截图 + 数值定位核验 | PASS（详见下） |

## 未指定对象不变性（验收硬条件）

以 rev 3 布局结果为基线快照（`docs/e2e/snap_base.json`），对每轮 patch 后的
IR 做逐对象字典比对：

- 轮 1 后：未触及节点（visual_encoder/connector/llm/gated_output）与全部 6 条边逐字节不变 → **PASS**
- 轮 2 后：connector 与 llm 之外的对象不变 → **PASS**
- 轮 3 后：`e_forget_out` 与 `gated_output`（本轮请求目标）之外，
  visual_encoder/forget_head 之外的节点全部不变；`gated_output` 坐标未变
  （仅按请求改描边）；`llm` 仅 w 字段变化 → **PASS**
- 最终核验：`visual_encoder == base: True`、`gated_output 坐标未变: True`、
  `llm 仅 w 变化: True`、未触及边全部不变 → **PASS**

注：轮 2 的首次比对脚本误用轮 2 目标集去比对轮 3 之后的文件（gated_output
已按轮 3 请求变化），属验收脚本时序错误而非数据问题，已用合并目标集复验。

## Lint 驱动的真实修复

轮 2 的改名让 `connector` 节点标签在原自动尺寸盒内溢出（FC003：
y+3.16 mm）。按 Skill 工作流以最小 patch 修复（`update_node connector w=26`）
而非重画——lint → 定向修复 → clean 闭环在真实使用中得到验证。

## 视觉质量检查

- 浏览器整图截图：流向清晰（左→右），Forget Head 橙色 / Retain Head 淡蓝、
  虚线分组框与加粗输出描边符合三轮修改预期，箭头起止于节点边界。
- 首次截图发现组标签 "Unlearning" 基线压到 Forget Head 顶边（组内标签条
  与子节点间距不足）→ 三渲染器统一修复：组标签改画在虚线框上边线上方、
  不换行（`wrap_text(…, inf)`，仍由 TextLayout 模块裁决）、贴画布顶时向下
  钳制（回归测试 `test_group_label_stays_inside_canvas_when_group_hugs_the_top`）。
- 修复后数值核验：标签基线 y=3.06 mm（画布内、子节点顶 4 mm 之上），
  组框 y=1.0 mm → **PASS**。
- （visual-judge 子代理供应商不可用，按交付规程降级为本人判定 + 数值核验。）

## 确定性

两份独立导出 SHA-256：svg `17eb…`、pdf `b2c4…`、pptx 一致 → **三格式全 PASS**。

## 结论

**验收通过。** 一个真实 Coding Agent 仅凭 CLI/补丁接口完成了创建、三轮
局部修改、lint 修复与三格式导出；未指定对象全程不变；产物为
`examples/video_unlearning.{json,svg,pdf,pptx}`。
