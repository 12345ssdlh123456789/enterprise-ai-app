# Changesets

这个目录给 `release` job 用：合并到 `main` 后，`changesets/action` 会把这里待处理的 changeset
合成一个「版本 PR」（改版本号 + 生成 CHANGELOG），不会发布到 npm。

## 什么时候加

改动了 `apps/*` 或 `packages/*` 里的代码、并且希望下一个版本 PR 记上一笔时：

```bash
pnpm changeset            # 交互式选包 + 选 bump 类型 + 写一句说明
pnpm changeset status     # 看当前有哪些待发布的 changeset
```

生成的文件长这样（`@enterprise-ai/admin: patch`），提交到仓库即可：

```md
---
'@enterprise-ai/admin': patch
---

修了退出登录失败后界面仍显示已登录的问题。
```

## 注意

- `apps/*` 都是 `private: true`，`config.json` 里 `privatePackages.version = true`
  让它们参与版本号与 changelog，但 `tag = false` / 没有 `publish` 步骤，所以**不会发 npm**。
- 没有 changeset 时 `pnpm changeset status` 退出码是 1，CI 里已经用 `|| echo` 兜住，不算失败。
- 详细规则见 <https://github.com/changesets/changesets>。
