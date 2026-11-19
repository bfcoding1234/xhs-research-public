# xhs-research 文档中心

## 1. 文档用途

本文是项目文档的统一入口，负责说明阅读顺序、维护角色和权威来源。它不复制其他文档正文。

项目文档按传统软件开发流程组织：

```text
市场与需求
  → 产品规则与页面方案
  → 技术架构与详细设计
  → 前后端实现
  → 测试、验收与运行
  → 全景可视化与历史沉淀
```

## 2. 核心文档

| 阶段 | 第一责任角色 | 文档 | 回答的问题 |
| --- | --- | --- | --- |
| 协作入口 | 技术负责人 | [AGENTS.md](../AGENTS.md) | 每次开发都必须遵守哪些边界、如何验证和交付 |
| 产品定义 | 产品经理 / 业务分析师 | [PRODUCT_RULES.md](./PRODUCT_RULES.md) | 对象是什么、业务规则和默认行为是什么 |
| 页面设计 | 产品经理 / 交互设计师 | [页面细节](./details/pages.md) | 每个页面长什么样、包含哪些区块、字段、状态和操作 |
| 页面规范 | UI/UX / 前端负责人 | [页面规范索引](./page-specs/README.md) | 同一类页面应按什么结构和交互形成 |
| 总体设计 | 架构师 / 技术负责人 | [ARCHITECTURE.md](./ARCHITECTURE.md) | 为什么这样选型、系统如何分层和协作 |
| 详细设计 | 前后端 / 数据 / 集成工程师 | [细节文档索引](./details/README.md) | 页面、接口、服务、数据和外部依赖的具体契约是什么 |
| 实现导航 | 前后端研发 | [CODEMAP.md](./CODEMAP.md) | 明确要改什么后，应从哪些文件、接口和测试进入 |
| 工程治理 | 技术负责人 / 质量负责人 | [ENGINEERING_GUARDRAILS.md](./ENGINEERING_GUARDRAILS.md) | 实现时有哪些高风险约束和质量门禁 |
| 测试验收 | 测试 / 研发 / 产品 | [TESTING.md](./TESTING.md) | 如何组织测试层级、自动化用例、UAT 和交付门禁 |
| 方案评审 | 产品、架构、研发、测试 | [方案索引](./plans/README.md) | 尚未成为当前事实的变更准备怎样实施和验收 |
| 历史追溯 | 项目经理 / 技术负责人 | [历史资料索引](./history/README.md) | 旧规则、交付快照和派生产物应如何查阅 |

运行配置和数据语义分别由 [configuration.md](./details/configuration.md) 与 [data-model.md](./details/data-model.md) 维护；旧兼容入口已进入 [待删除清单](./待删除/README.md)。子工程启动和构建命令见 [workbench README](../scripts/workbench/README.md)。

## 3. 权威来源矩阵

每项事实只维护一个权威位置，其他文档只链接或解释其使用场景。

| 事实类型 | 权威位置 | 变化时同步检查 |
| --- | --- | --- |
| 已确认产品语义、术语和默认行为 | `PRODUCT_RULES.md` | 页面细节、测试、方案状态 |
| 页面空间结构和关键交互 | `details/pages.md` | 页面源码、页面规范、产品规则 |
| 通用页面形成规则 | `page-specs/` | 共享组件、工程约束、页面验收 |
| 系统边界、模块关系、任务和数据关系 | `ARCHITECTURE.md` | CODEMAP、数据模型、可视化架构地图 |
| API、服务和依赖能力说明 | `details/` | 前后端契约、相邻测试、配置参考；CLI 版本化实测证据也归入此处 |
| 数据表真实定义 | `schema.sql` 与 `Database.initialize()` | `details/data-model.md`、API 类型、迁移测试 |
| 代码位置和测试入口 | `CODEMAP.md` | 路由、文件职责和测试归属 |
| 实现约束与质量门禁 | `ENGINEERING_GUARDRAILS.md` | lint、测试、构建和运行验收 |
| 当前测试策略、测试位置与验收职责 | `TESTING.md` + 测试代码 | CODEMAP、已确认方案和产品验收标准 |
| 待实施或已废弃设计 | `plans/` | 确认后回写当前事实文档 |
| 实际运行行为 | 当前代码、数据库约束和测试 | 与文档冲突时先核实现状，再修正文档 |

## 4. 按任务阅读

| 任务 | 最小阅读路径 |
| --- | --- |
| 修改页面布局或交互 | 产品规则相关小节 → 对应页面细节 → 对应页面规范 → CODEMAP |
| 新增或修改 API | 产品方案/规则 → API 细节 → ARCHITECTURE 相关边界 → CODEMAP |
| 修改服务、任务或并发 | ARCHITECTURE → 服务细节 → ENGINEERING_GUARDRAILS → CODEMAP |
| 修改表或数据关系 | ARCHITECTURE → `details/data-model.md` → Schema / 迁移 → CODEMAP |
| 调整外部 CLI、OCR 或 Codex | 依赖能力细节（CLI 变更时同时读实测报告）→ `details/configuration.md` → ARCHITECTURE → CODEMAP |
| 了解历史原因 | 先读当前权威文档，再按关键词查历史资料索引 |

## 5. 文档状态

- **当前规范**：描述已确认、需要持续维护的当前事实。
- **待确认方案**：说明计划中的变化；未确认前不得据此改变应用行为。
- **已完成方案**：保留决策和验收记录；当前行为仍以规范、代码和测试为准。
- **已废弃 / 历史快照**：仅用于追溯，不作为开发输入。
- **派生产物**：由当前事实生成的可视化或交付版本，不得成为第二事实源。

## 6. 维护与验证

文档、路由、文件职责或测试归属变化后运行：

```bash
python3 scripts/validate_architecture_docs.py
```

新增文档时必须在本入口或对应专题索引中登记。接口、页面、服务和数据发生跨层变化时，同时检查“用户操作 → 页面 → API / 本地行为 → 服务 → 数据 → 测试”是否闭环。
