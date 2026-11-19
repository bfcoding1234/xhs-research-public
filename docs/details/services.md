# 服务与模块详细设计

## 1. 文档定位

本文对应传统开发中的模块详细设计（LLD）和服务设计说明书。稳定的系统边界与数据关系见 [ARCHITECTURE.md](../ARCHITECTURE.md)，函数和测试入口见 [CODEMAP.md](../CODEMAP.md)。

## 2. 运行时服务

| 服务 / 模块 | 主要职责 | 上游 | 下游与状态 | 不应承担 |
| --- | --- | --- | --- | --- |
| `scripts/xhs_research.py` | 识别 worktree，确定默认端口、数据目录并调用统一 HTTP 服务 | Codex / CLI | `cli.py` | 复制业务逻辑 |
| `cli.py` | 组装配置、Database、Provider、TaskRunner 和 HTTP 应用 | 薄入口 | 所有进程内服务 | 执行页面或领域规则 |
| `ResearchApplication` / `server.py` | HTTP 边界、应用编排、任务创建、调度、恢复、取消和安全停止 | Web / CLI API | Database、TaskRunner、执行器 | 在 Handler 中散落 SQL 和 Provider 细节 |
| `TaskRunner` / `runner.py` | 冻结输入，拆解业务能力，执行任务，写进度、事件和结果 | ResearchApplication | CapabilityRegistry、Database、OCR、Vision、Report | 处理前端展示状态 |
| `Database` / `db.py` | Schema、兼容迁移、事务、查询、关系和一致性 | Application / Runner | SQLite | 选择采集 Provider |
| `CapabilityRegistry` / `collector.py` | 业务原子能力、稳定指令 ID、默认和降级路由 | Runner | Provider 适配器 | 绑定页面或项目状态 |
| `socai.py` | Socai 参数、进程、认证错误和结果标准化 | CapabilityRegistry | Socai CLI、统一采集结果 | 决定任务阶段和项目关系 |
| `xiaohongshu_cli.py` | 登录校验、用户/帖子搜索、作者分页、详情和评论标准化 | CapabilityRegistry | xiaohongshu-cli、统一采集结果 | 保存 Cookie 或原始敏感响应 |
| `opencli.py` | 搜索、作者、详情和媒体下载的后备适配 | CapabilityRegistry | OpenCLI、统一采集结果 | 把退出码直接暴露为业务状态 |
| `keyword_generation.py` | 构造受限上下文并生成临时关键词候选 | keyword executor | CodexProcess、任务结果 | 未经用户确认写项目关键词 |
| `ocr.py` | RapidOCR 初始化与本地媒体 OCR | Runner | media_assets OCR 字段 | 采集新媒体或选择大模型 |
| `vision.py` / `vision_state.py` | 图片候选、批次、Codex 调用、缓存身份和派生状态 | Runner / 查询 | Codex、vision_analyses | 采集帖子或生成报告 |
| `attention.py` | 统一列表和报告使用的确定性关注分 | 列表查询、数据摘要 | 纯函数结果与稳定排序 | 维护页面私有计算口径 |
| `data_summary.py` | 在单一 SQLite 读快照中生成确定性描述统计 | API / Runner | reports / author_reports | 调用外部大模型 |
| `ai_reporting.py` | 冻结证据、分批、缓存、校验、修复和报告合成 | Report executor | Codex、report_chunks、reports | 修改作者或帖子主数据 |
| `report_presentation.py` | 校验结构化幻灯片并确定性渲染安全 HTML | Report executor | report_presentations | 运行任意模型生成的脚本 |
| `codex_process.py` | 统一启动、超时、取消和清理 Codex 子进程组 | Keyword / Vision / Report | Codex CLI、结果文件和诊断 | 决定具体业务 Prompt 或数据库提交 |
| `release.py` | 开发数据发布预览、确认、审计和事务提交 | API | 开发库与稳定库 | 隐式迁移活跃任务或删除稳定数据 |
| `config.py` / `lifecycle_lock.py` | 解析环境、端口、数据目录、二进制和生命周期锁 | 薄入口 / cli.py | 运行设置、唯一数据目录持有权 | 承担产品业务配置 |

## 3. 前端分层

| 层 | 位置 | 职责 |
| --- | --- | --- |
| 路由与全局布局 | `web/config/`、`web/src/app.tsx` | Hash 路由、ProLayout、导航、主题和 QueryClient |
| 页面 | `web/src/pages/` | 读取路由参数，组合查询、操作与共享 feature |
| 业务 feature | `web/src/features/` | 作者、帖子、项目关系、任务、报告和图片处理的复用交互 |
| 通用组件 | `web/src/components/` | 加载、失败、任务状态、进度、成功反馈和错误边界 |
| 数据访问 | `web/src/services/` | 类型化 HTTP、Query Key、轮询和失效 |
| 类型与纯函数 | `web/src/types.ts`、`web/src/utils/` | 契约类型、格式化、排序和派生判断 |

服务端状态只由 React Query 管理。共享对象列表优先修改 feature；页面只传递全局、项目或作者等上下文差异。

## 4. 任务执行服务

| `task_type` | 执行器 | 主要操作 | 关键限制 |
| --- | --- | --- | --- |
| `research` | research executor | 普通调研、作者更新、帖子详情更新 | 普通采集默认全局单线程；项目内 research 按创建顺序互斥 |
| `vision` | vision executor | OCR、Codex 图片理解 | 同一项目或作者最多一个活跃任务 |
| `ai_report` | report executor | 大模型报告、HTML 演示稿 | 任务开始时冻结证据；同一主体最多一个活跃任务 |
| `keyword_suggestions` | keyword executor | AI 关键词临时候选 | 用户确认后才写入项目关键词 |
| `comments` | research executor | 单帖分页评论采集 | 同一帖子最多一个活跃任务；检查点逐页提交 |

状态、恢复、取消和并发的完整规则只在 [ARCHITECTURE.md](../ARCHITECTURE.md) 维护，本文不复制状态机。

## 5. 关键调用链

### 5.1 读取服务端列表

```text
页面 useQuery
  → api.ts + queryKeys.ts
  → server.py：解析并校验 query
  → TaskRunner / Database：完整范围筛选、排序、派生状态
  → Database：分页查询和 total
  → API Page 响应
  → React Query 保留或替换上次成功结果
```

约束：不能在浏览器下载全部数据后只筛选当前页；后台刷新失败时保留上次成功结果；写操作成功后只失效受影响的 Query Key。

### 5.2 创建和执行持久化任务

```text
页面确认输入
  → POST 任务接口
  → ResearchApplication：校验主体、冲突和业务配置
  → Database：事务创建 queued 任务并冻结 input_json
  → 对应 executor
  → TaskRunner：写 running、阶段和事件
  → CapabilityRegistry / OCR / Codex 服务
  → Database：逐阶段结果、检查点和业务数据
  → 单事务提交终态、结果和必要业务版本
```

约束：HTTP 返回成功前任务必须持久化；可离开页面继续运行的批处理不能由前端循环临时请求代替；重试创建新任务而不覆盖历史。

### 5.3 调用采集能力

```text
TaskRunner：业务动作
  → CapabilityRegistry：读取任务启动时的路由顺序
  → 默认指令
      ├─ 成功 → 标准化结果
      ├─ 普通失败 → 下一降级指令
      └─ 登录/验证 → waiting_login → 人工恢复后重试当前指令
  → 保存 selected_provider、selected_command 和诊断
```

约束：任务不绑定整个采集引擎；Cookie、Token、验证码和原始敏感响应只在内存或外部工具内部使用。

### 5.4 取消、恢复和服务停止

```text
用户取消
  → Database 持久化 cancelled
  → 撤销排队 Future / 设置 Runner 取消信号
  → 终止当前 CLI 或 Codex 进程组

waiting_login 恢复
  → 写 manual_resume_requested
  → 唤醒同一 Runner
  → 重试当前来源，不创建新任务

SIGTERM
  → 停止接收新工作
  → 通知 Runner 与子进程停止
  → 执行器收尾并释放生命周期锁
```

SIGTERM 不把任务伪装成用户取消；服务重启时 queued / waiting_login 可恢复，遗留 running 转为 failed。

### 5.5 报告与演示稿提交

```text
创建报告/演示稿任务
  → 同事务创建任务 + generating 占位版本
  → 冻结证据或源报告全文
  → Codex 分批结构化处理
  → Schema / 引用范围 / 语义校验
  → 服务端确定性合成 Markdown 或 HTML
  → 同事务完成版本 + 任务终态
  → 失败/取消时同事务删除占位
```

数据摘要例外：在单一 SQLite 读快照中同步计算，不调用外部模型，也不创建后台任务。

### 5.6 开发数据发布

```text
GET preview
  → 检查开发库和稳定库身份、Schema 与活跃任务
  → 生成按稳定业务键合并的发布计划
  → 用户明确确认
  → POST publish
  → 非破坏性事务合并 + 媒体复制 + 审计记录
```

任何一端存在活跃任务时拒绝发布；不迁移活跃任务、不删除稳定数据。

## 6. 持久化与失败边界

| 行为 | 事务 / 一致性边界 | 失败后的可观察结果 |
| --- | --- | --- |
| 创建项目和关系 | Database 单写事务 | 全部成功或不产生部分关系 |
| 创建普通任务 | 任务输入持久化后才提交执行器 | 提交失败必须把任务收口为可诊断终态 |
| 评论分页 | 每页评论、任务关系和 cursor 同事务 | 已完成页保留，可从检查点继续 |
| 报告/演示稿创建 | 任务与 generating 占位同事务 | 版本号从排队起稳定可见 |
| 报告/演示稿完成 | 产物、版本状态和任务终态同事务 | 不出现已完成任务对应半成品 |
| 取消与最终提交 | 共用数据库写锁串行 | 只允许取消成功或完成提交其中一个先成立 |
| 项目删除 | 项目检查、关系清理和报告删除同事务 | 全局作者、帖子和已结束任务保留 |

## 7. 服务变更模板

修改或新增服务时记录：职责、调用入口、输入输出、持久化状态、事务边界、并发与幂等、取消和恢复、外部依赖、错误分类、日志与敏感信息、相邻测试、真实运行验收。
