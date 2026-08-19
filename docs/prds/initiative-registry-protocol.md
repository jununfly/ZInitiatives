# Initiative Registry Protocol

## 1. 目的

Initiative Registry Protocol 定义一个由 GitHub repository 承载、可跨设备和跨 Agent 共享的 Initiative 导航数据协议。协议的核心关系固定为 `Initiative → Spec → Plan`，生成完整 Registry 的输入是分片 manifest，生成物供 Agent 和 Human 查询。

本协议不定义具体 Agent Skill；`zj-initiative-registry` 的用户体验和执行流程由 [ZAgentic Spec](https://github.com/jununfly/ZAgentic/blob/main/docs/prds/zj-initiative-registry-skill.md) 定义。

## 2. 仓库布局

```text
registry/
├── initiatives/<initiative-id>.json
├── specs/<initiative-id>/<spec-id>.json
└── plans/<initiative-id>/<plan-id>.json
generated/
├── global-initiative-registry.json
├── global-initiative-registry.md
└── global-initiative-registry.mmd
schemas/
scripts/
```

Registry 仓库本身不保存 Initiative 仓库的 PRD 或 Plan 内容；manifest 只保存远程仓库标识和仓库内相对路径。

## 3. 节点模型

### Initiative

Initiative manifest 至少包含：`id`、`label`、`kind`、`lifecycle`、`repository`、`defaultBranch` 和 `owner`。`kind` 使用 `product`、`shared-capability`、`experimental` 或 `external`；`lifecycle` 使用 `active`、`dormant` 或 `archived`。

### Spec

Spec manifest 至少包含：`id`、`initiativeId`、`label`、`kind` 和 `path`。`path` 必须位于对应 Initiative 仓库的 `docs/prds/` 下。

### Plan

Plan manifest 至少包含：`id`、`initiativeId`、`specId`、`label`、`path` 和 `engine`。`path` 必须位于对应 Initiative 仓库的 `docs/plans/` 下，`engine` 的第一版值为 `zj-roadmap-driven`。

所有 ID 在 Registry 内全局唯一，使用稳定的 kebab-case。ID 只有在实体身份改变时才允许改变；改名和移动文件只更新 label 或 path。

## 4. 路径和生成规则

协议中不允许保存本地绝对路径。所有远程引用由 `repository` 和 repository-relative `path` 组成。生成器必须按稳定排序读取 manifest，并从同一输入生成 JSON、Markdown 和 Mermaid，不依赖当前设备路径、文件遍历顺序或时间戳。

生成的 `global-initiative-registry.json` 至少包含 `$schema`、`generatedFrom.repository`、`generatedFrom.commit` 和三层节点。生成器不得把 Plan 的执行 status、focus、decision 或 notes 复制到全局 Registry。

## 5. 完整性规则

Validator 必须拒绝：重复 ID、未知 node type、Spec 没有合法 Initiative、Plan 没有合法 Spec、越出 `docs/prds/` 或 `docs/plans/` 的路径、损坏的 JSON Plan、生成物与 manifest 不一致和缺失的注册引用。

Validator 应警告：Initiative 没有 Spec、Spec 没有 Plan、仓库存在未登记 PRD/Plan、默认分支变化和已归档 Initiative 仍有新增 Plan。未登记文件默认 warning，已登记但失效的引用是 error。

## 6. 版本和演化

协议使用显式 schema version，例如 `zj-global-initiative-registry/v1`。改变节点必填字段、层级语义、路径安全规则或生成物解释时递增主版本；增加可选字段或新的非破坏性输出时递增次版本。旧生成物保留 `generatedFrom.commit`，不与新协议版本混合比较。

协议变更必须同时更新 schema、validator、示例 manifest、生成物和本文件，并通过一个最小真实 Registry fixture 验证。

## 7. Git 协作和审计

Registry 的共享事实源是 GitHub 默认分支的已合并 manifest 和生成物。Agent 默认通过 scoped branch 和 pull request 修改；pull request 必须运行 schema、路径、生成物和 drift checks。禁止隐式覆盖远端更新，禁止 force-push。

每次生成物必须能够通过 `generatedFrom.commit` 回溯到 Registry 输入。Registry 不记录 GitHub token、SSH key、设备绝对路径或运行时秘密。

## 8. 与 Initiative 仓库的关系

Registry 只索引，不拥有 Initiative 的 Spec 和 Plan 内容。Initiative 仓库是 PRD 和 roadmap-plan-file 的事实源；Registry 是这些事实的跨仓导航投影。移动或删除被索引文件时，修改 Initiative 仓库和 Registry manifest 必须在同一个协作变更中完成。
