# v0.1.0 (Alpha) 发布冻结报告

**冻结基线：commit `99e4444`（main HEAD at freeze）**
**发布物：`dist/papercanvas-0.1.0-py3-none-any.whl` + `dist/papercanvas-0.1.0.tar.gz`**
**CI：run [40182600314](https://github.com/HarryHeYu/figcraft/actions/runs/40182600314) — 8/8 job success**
（test: ubuntu/windows/macos × 3.12/3.14；smoke: ubuntu + windows，含 wheel 安装、
CLI 流程与真实 MCP stdio smoke）

## 冻结范围确认

自 RC1（`8941ac1`）以来的功能收敛提交（此后不再修改 v0.1.0 功能代码）：

| 提交 | 内容 |
|---|---|
| `ccd813b` | CJK 字形覆盖感知的字体解析（fontTools cmap；全图选字；PDF TTC 嵌入；CFF 明确报错） |
| `f68972b` | 避障正交路由（确定性通道绕行；三渲染器 + FC006 共用；无穿越时输出逐点不变） |
| `5d9b640` | README 重构、社区文件（CONTRIBUTING/SECURITY/COC/模板）、architecture/versioning 文档 |
| `100e341` | CI wheel-install smoke job + 服务层路径策略回归测试 |
| `8941ac1` | RC1 准备（构建验证、入口点、smoke 脚本、Trusted Publishing） |
| `71bffc9` | 字体替代语义修复（Ubuntu CI 发现；内嵌名验证）+ fixture 平台化 |
| `5a15b65`/`99e4444` | CI smoke 矩阵扩展至 Windows + 路径解析修复 |
| `a6abf0a` | 字形覆盖显式警告、最大覆盖选字、Quickstart 逐字验证、Alpha 定位、v0.2 roadmap |

## 验证结果（全部为实际运行输出）

| 项 | 结果 |
|---|---|
| 本地测试 | **278 passed, 1 skipped**（skip = 本机无 symlink 特权，CI Windows runner 上真实执行） |
| 远端 CI | **8/8 job success**（逐 job conclusion 读取，非退出码推断） |
| Wheel 安装 | 全新 venv 安装成功；`papercanvas --version` → 0.1.0；含中文标签的图 build → SVG/PDF/PPTX；FC007 明确报告 Arial→SimHei 替代；lint 0 错误 |
| sdist 安装 | 全新 venv 源码构建安装成功；`papercanvas-mcp` 真实 stdio smoke PASS（7 工具发现、create/render、路径逃逸拒绝） |
| twine check | wheel + sdist 双 PASSED |
| 示例产物 | 三示例（basic_pipeline / video_unlearning / multi_branch）SVG/PDF/PPTX 共 9 文件随库分发，lint 全 0 错误 |
| 快速上手 | README Quickstart 在 Windows Git Bash 下逐字复制运行通过（发现并修复 `<(...)` 不可移植问题） |

## 已知限制（冻结清单，详见 README / RELEASE_NOTES / release-checklist）

1. PDF 的 CJK 依赖本机 TrueType CJK 字体；CFF-only（Noto CJK）环境给出
   明确报错；emoji 在 PDF 中为 .notdef——**渲染时始终有显式警告，不静默**。
2. PPTX→IR 无反向同步。
3. 路由避障为确定性候选通道；堵死场景保留穿越并经 FC006 报告。
4. 组标签不自动换行（支持显式 `\n`）。
5. `unit` 仅 mm；`schema_version` 仅 0.1。

## 发布执行（等待授权）

PyPI 上传、`v0.1.0` tag 与 GitHub Release 均未执行。经确认后将按
`docs/pypi-trusted-publishing.md` 执行：配置 Trusted Publisher → 打 tag →
Actions 自动 build/check/publish（OIDC，零凭据）→ PyPI 页面 + 全新环境
安装复验。
