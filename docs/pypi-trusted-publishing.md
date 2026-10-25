# PyPI Trusted Publishing 方案（v0.1.0 正式发布）

目标：零明文凭据、零长期 API Token。PyPI 的 Trusted Publishing 基于
GitHub Actions 的 OIDC 短期令牌，由 PyPI 端配置信任关系后自动放行。

## 一次性配置（仓库所有者操作，约 5 分钟）

1. 在 pypi.org 注册/登录账号 `HarryHeYu`（开启 2FA——Trusted Publishing 要求）。
2. 项目 `papercanvas` 首次发布需要"占位"：首次仍需一个临时
   API Token 完成第一次上传（PyPI 限制：项目不存在前无法预配置 Trusted
   Publisher）。发布完成一次后立即在 PyPI 账号设置里**撤销该 Token**。
   —— 或者使用 "Pending Publisher" 预注册：在 PyPI 的 Publishing 页面
   预填 GitHub 信息（见下），首次上传即可全程无 Token。
3. PyPI → Account Settings → **Trusted Publishing** → Add：
   - PyPI project name: `papercanvas`
   - Owner: `HarryHeYu`
   - Repository: `figcraft`
   - Workflow name: `release.yml`
   - Environment: `pypi`
4. GitHub 仓库 → Settings → Environments → 创建 `pypi` 环境
   （建议开启 "Required reviewers" 指向自己，作为发布双确认）。

## 已就位的工作流

`.github/workflows/release.yml`（已提交）：推送到 `v*` tag 触发 →
`uv build` → `twine check` → `pypa/gh-action-pypi-publish`（OIDC，
`environment: pypi`，`permissions: id-token: write`）。无任何 secret。

## 发布执行步骤（经确认后）

```bash
git tag -a v0.1.0 -m "PaperCanvas v0.1.0"
git push origin v0.1.0
# Actions 自动构建 + 校验 + 上传；在 Environment 的 Required reviewers
# 中点击批准后，包进入 PyPI
```

## 验证

- PyPI 页面 https://pypi.org/project/papercanvas/0.1.0/ 出现后，全新环境
  `pip install papercanvas` 并复跑 RC 冒烟（`docs/rc/stdio_smoke.py`）。
- 上传证据：Actions run 日志中的 OIDC claim 与 PyPI 的 publisher 记录。

## 安全说明

- 仓库中没有任何 secret；`id-token: write` 是唯一权限，作用域仅本次运行。
- Token 泄漏风险面：不存在（无长期凭据）。
- 若日后改用 API Token 方案（不推荐）：需以 secret 注入并定期轮换。
