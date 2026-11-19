# HTTP API 详细设计

## 1. 文档定位

本文对应传统开发中的 API 设计文档或接口控制文档（ICD），逐项记录当前本地 HTTP 接口的用途、输入、输出和主要业务错误。

事实来源：后端路由、校验与错误映射以 [server.py](../../scripts/workbench/xhs_research/server.py) 为准；前端请求封装和数据契约以 [api.ts](../../scripts/workbench/web/src/services/api.ts)、[types.ts](../../scripts/workbench/web/src/types.ts) 与 [queryKeys.ts](../../scripts/workbench/web/src/services/queryKeys.ts) 为准；跨层代码和测试入口见 [CODEMAP.md](../CODEMAP.md)。

## 2. 通用契约

- 服务只接受回环地址和可信回环 `Host`；浏览器写请求还必须通过本机可信 `Origin` 校验。
- JSON 写请求必须使用对象型请求体，并受请求体大小限制。GET 只读；创建、更新、删除使用 POST、PATCH 或 DELETE。
- 除下表列出的业务错误外，所有接口都可能返回：`400` 请求或 JSON 无效、`403` 请求上下文不可信、`404` 路由不存在、`500` 未归类服务错误。
- 分页响应至少包含 `items`、`total`、`page`、`page_size`；服务端必须在完整范围内先筛选和排序，再返回当前页。
- 长任务创建返回 `202 TaskReceipt`，客户端通过任务和事件接口读取后续状态，不保持同步长连接。
- 错误响应不得泄露 Cookie、Token、验证码、完整敏感 stderr、个人数据或不必要的绝对路径。

## 3. 完整接口契约

### 3.1 运行状态

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/health` | 服务版本、运行锁、数据目录、采集器和原子能力路由 | 无请求体 | `Health`：status、version、data_dir、collectors、capability_routes、ai_capabilities | `403` Host 或请求上下文不可信 |
| GET `/api/stats` | 项目、作者、帖子、任务、报告、媒体和磁盘体积统计 | 无请求体 | `Stats`：projects、global_posts、global_authors、tasks、reports、media_assets、database_bytes、media_bytes | — |

### 3.2 设置与个人

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/settings` | 组合持久化设置、运行环境、指令目录、能力路由和报告模板 | 无请求体 | `AppSettings` | — |
| POST `/api/settings` | 更新白名单设置并逐项校验数值、延迟、路由和个人作者 | `Partial<AppSettings>` | 更新后的 `AppSettings` | `400` 字段、范围、模板或路由无效 |
| GET `/api/settings/vision-models` | 发现当前 Codex 环境中支持图片输入的模型 | 无请求体 | `VisionModelsResponse`：models、default_model、provider_available、message | Provider 失败以可解释响应降级 |
| POST `/api/me/setup` | 选择已有个人作者，或初始化外部作者并创建首次更新任务 | `{ author_id: number }` 或 `{ external_author_id: string }` | `MyAuthorSetupResult`：author_id、task；已有作者时 task 为 null | `400` 参数无效；`404` 作者不存在 |

### 3.3 项目、关系与关键词

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/projects` | 读取项目基础信息及帖子、作者、关键词、报告和最新任务摘要 | 无请求体 | `Project[]` | — |
| POST `/api/projects` | 只创建项目基础信息，不创建任务或复制实体 | name、research_type、description?、config? | `201 Project` | `400` 名称、类型、说明或配置无效 |
| GET `/api/projects/:id` | 读取单项目及关联数量和最新任务状态 | Path：id | `Project` | `404` 项目不存在 |
| PATCH `/api/projects/:id` | 修改名称和说明，保持类型、配置与已积累资产不变 | Path：id；Body：`{ name, description }` | `Project` | `400` 名称为空或长度超限；`404` 项目不存在 |
| DELETE `/api/projects/:id` | 事务删除项目关系和报告；已结束任务脱离项目保留；不删全局实体 | Path：id；Query：require_empty? | `DeleteProjectResult` | `409` 有活跃任务或不满足 require_empty；`404` 项目不存在 |
| GET `/api/projects/:id/posts` | 项目帖子服务端筛选、排序、分页及增强状态 | Path：id；Query：page、page_size、query、type、detail、ocr、vision、popularity、sort | `ProjectPostPage` | `400` 缺少分页参数；`404` 项目不存在 |
| GET `/api/projects/:id/post-coverage` | 独立计算详情、媒体、OCR、图片理解和评论覆盖 | Path：id | `ProjectPostCoverage` | `404` 项目不存在 |
| GET `/api/projects/:id/authors` | 项目作者关系、项目帖子数量和作者最新资料 | Path：id | `Author[]`，含 relation_type、project_post_count | `404` 项目不存在 |
| GET `/api/projects/:id/reports` | 项目摘要、模板报告、大模型报告及 generating 版本 | Path：id | `Report[]` | `404` 项目不存在 |
| GET `/api/projects/:id/tasks` | 项目下未取消任务，按创建时间倒序 | Path：id | `Task[]` | `404` 项目不存在 |
| GET `/api/projects/:id/reference-ids` | 为反向选择提供已关联帖子和作者 ID | Path：id | `ProjectReferenceIds` | `404` 项目不存在 |
| GET `/api/projects/:id/keywords` | 项目关键词及手动/AI 确认来源 | Path：id | `ProjectKeyword[]` | `404` 项目不存在 |
| POST `/api/projects/:id/keywords` | 标准化、去重并添加关键词；手动来源优先 | Path：id；Body：keywords、source? | 更新后的 `ProjectKeyword[]` | `400` 关键词或来源无效 |
| DELETE `/api/projects/:id/keywords` | 删除当前项目的关键词关系 | Path：id；Body：`{ keyword_ids: number[] }` | 更新后的 `ProjectKeyword[]` | — |
| POST `/api/projects/:id/references` | 关联全局帖子或作者；关联帖子时同步作者关系 | Path：id；Body：post_ids?、author_ids? | `ProjectReferenceResult` | `404` 项目或实体不存在 |
| DELETE `/api/projects/:id/references` | 只解除项目关系，不删除全局实体 | Path：id；Body：post_ids、author_ids、confirm_remove_author_posts | `ProjectReferenceRemovalResult` | `409` 作者仍有关联帖子且未确认 |
| POST `/api/projects/:id/keyword-suggestions` | 创建持久化关键词候选任务；候选不自动写入项目 | Path：id；Body：reference_sources | `202 TaskReceipt` | `400` 参考来源无效；`409` 已有活跃候选任务 |
| POST `/api/projects/:id/run` | 从历史 research 任务复制并允许调整配置后创建新任务 | Path：id；Body：source_task_id、configuration、force_refresh? | `202 TaskReceipt` | `400` 来源任务无效或不属于项目 |
| POST `/api/projects/:id/author-updates` | 固定作者清单后创建一个可恢复的批量更新任务 | Path：id；Body：created_from、configuration | `202 TaskReceipt` | `400` 批次或数量无效；`409` 存在冲突任务 |

### 3.4 帖子与评论

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/posts` | 全局帖子筛选、排序和分页，可排除某项目已关联帖子 | Query：`PostQuery`；page、page_size 必填，page_size 最大 100 | `PostPage` | `400` 缺少分页参数 |
| GET `/api/posts/:id` | 帖子、作者、项目关系、媒体/OCR 和当前图片理解结果 | Path：id | `Post`，含 media、vision、projects | `404` 帖子不存在 |
| POST `/api/post-detail-updates` | 固定全局、项目或作者范围目标并创建详情更新任务 | Body：created_from、`PostDetailUpdateConfiguration` | `202 TaskReceipt` | `400` 范围、目标或批次无效；`409` 任务冲突 |
| GET `/api/posts/:id/comments` | 本地一级评论、回复预览及续跑检查点分页 | Path：id；Query：page、page_size | `PostCommentsPage`：items、total、checkpoint | `404` 帖子不存在 |
| POST `/api/posts/:id/comment-tasks` | 创建单帖评论任务，从持久化 cursor 继续指定页数 | Path：id；Body：created_from、configuration | `202 TaskReceipt` | `400` 页数或能力无效；`404` 帖子不存在；`409` 已有活跃评论任务 |

### 3.5 作者

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/authors` | 全局作者最新资料、已存帖子和项目数量 | 无请求体 | `Author[]` | — |
| GET `/api/authors/:id` | 作者资料、全部已采集帖子、项目关系及增强状态 | Path：id | `Author`，含 posts、projects | `404` 作者不存在 |
| GET `/api/authors/:id/reports` | 作者或个人的数据摘要和大模型报告版本 | Path：id | `Report[]` | `404` 作者不存在 |
| GET `/api/authors/:id/report-status` | 当前帖子、OCR 与图片理解覆盖 | Path：id | `ReportStatus` | `404` 作者不存在 |
| GET `/api/authors/:id/vision-status` | 作者范围按图片作用域计算可处理、完成和待处理数量 | Path：id | `VisionStatus` | `404` 作者不存在 |

### 3.6 任务生命周期

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/tasks` | 未取消任务列表，输入和结果 JSON 解析为结构化对象 | 无请求体 | `Task[]` | — |
| POST `/api/tasks` | 校验 ResearchRequest、持久化输入快照并提交执行器 | project_id?、mode、created_from、topic、source、各类 limits、force_refresh | `202 TaskReceipt` | `400` 输入模型无效；`409` 项目任务冲突 |
| GET `/api/tasks/:id` | 任务输入、状态、阶段、进度、错误和结果 | Path：id | `Task` | `404` 任务不存在 |
| GET `/api/tasks/:id/events` | 按事件 ID 增量读取执行轨迹 | Path：id；Query：after，默认 0 | `TaskEvent[]` | — |
| POST `/api/tasks/:id/cancel` | 持久化取消并撤销 Future 或通知 Runner/子进程 | Path：id；Body：`{}` | `{ id, status: cancelled }` | `404` 任务不存在；`409` 终态不可取消 |
| POST `/api/tasks/:id/resume` | 唤醒当前进程内 waiting_login 任务，不创建新任务 | Path：id；Body：`{}` | `{ id, status: resuming }` | `409` 任务不是 waiting_login |
| POST `/api/tasks/:id/retry` | 从 failed 或 partial 和原输入创建新任务 ID | Path：id；Body：`{}` | `202 TaskReceipt` | `404` 任务不存在；`409` 状态不允许重试 |
| DELETE `/api/keyword-suggestions/:taskId` | 兼容旧调用方式并复用统一取消逻辑 | Path：taskId | `{ id, status: cancelled }` | `404` 任务不存在或类型不匹配 |

### 3.7 图片处理、报告与演示稿

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/projects/:id/vision-status` | 项目范围 OCR/图片理解 Provider 与处理覆盖 | Path：id | `VisionStatus` | `404` 项目不存在 |
| GET `/api/projects/:id/report-status` | 项目帖子、作者、OCR 和图片理解报告证据状态 | Path：id | `ReportStatus` | `404` 项目不存在 |
| POST `/api/projects/:id/vision` | 按处理方法与图片范围冻结配置并创建任务 | Path：id；Body：created_from、`VisionTaskConfiguration` | `202 TaskReceipt` | `400` Provider 不可用或无媒体；`409` 同类任务活跃 |
| POST `/api/authors/:id/vision` | 在作者已存帖子范围内创建图片处理任务 | Path：id；Body：created_from、`VisionTaskConfiguration` | `202 TaskReceipt` | `400` Provider 不可用或无媒体；`404` 作者不存在；`409` 同类任务活跃 |
| POST `/api/projects/:id/ai-report` | 原子创建任务和 generating 报告版本，执行时冻结证据 | Path：id；Body：created_from、`ReportGenerationConfiguration` | `202 TaskReceipt` | `400` 配置无效；`409` 有活跃报告任务 |
| POST `/api/projects/:id/data-summary` | 同一 SQLite 读快照生成确定性项目摘要，不创建任务 | Path：id；Body：`{}` | `201 Report` | `404` 项目不存在 |
| POST `/api/authors/:id/ai-report` | 为作者创建持久化报告任务和 generating 占位 | Path：id；Body：created_from、`ReportGenerationConfiguration` | `202 TaskReceipt` | `404` 作者不存在；`409` 有活跃报告任务 |
| POST `/api/authors/:id/data-summary` | 同一 SQLite 读快照生成确定性作者摘要 | Path：id；Body：`{}` | `201 Report` | `404` 作者不存在 |
| GET `/api/projects/:id/reports/:reportId/presentations` | 项目报告的演示稿版本和生成状态 | Path：id、reportId | `ReportPresentation[]` | `404` 项目或报告不存在 |
| POST `/api/projects/:id/reports/:reportId/presentations` | 从已完成项目报告创建 HTML 演示稿任务 | Path：id、reportId；Body：created_from、page_mode | `202 TaskReceipt` | `400` 报告或配置无效；`409` 有活跃演示稿任务 |
| GET `/api/authors/:id/reports/:reportId/presentations` | 作者报告的演示稿版本和生成状态 | Path：id、reportId | `ReportPresentation[]` | `404` 作者或报告不存在 |
| POST `/api/authors/:id/reports/:reportId/presentations` | 从已完成作者报告创建 HTML 演示稿任务 | Path：id、reportId；Body：created_from、page_mode | `202 TaskReceipt` | `400` 报告或配置无效；`409` 有活跃演示稿任务 |
| GET `/api/report-presentations/:id/html` | 用 private/no-store 和严格 CSP 预览或下载 HTML | Path：id；Query：download? | `text/html` | `404` 演示稿不存在、未完成或无 HTML |

### 3.8 开发数据发布

| 方法与路径 | 用途 | 输入 | 输出 | 主要业务错误 |
| --- | --- | --- | --- | --- |
| GET `/api/data-release/preview` | 比较开发与稳定库，检查活跃任务并生成发布计划 | 无请求体 | `DataReleasePreview` | 目标不可用时返回可解释失败 |
| GET `/api/data-releases` | 发布审计历史；当前设置页未直接展示 | 无请求体 | `DataRelease[]` | — |
| POST `/api/data-release/publish` | 按稳定业务键非破坏性合并实体、项目和媒体 | Body：`{ confirm: true }` | `DataReleaseResult` | `400` 未确认；`409` 两端有活跃任务或目标不可用 |

## 4. 跨层实现规则

新增或改变接口时必须同步：

1. `server.py` 路由、输入校验、安全检查和错误映射。
2. `ResearchApplication`、`TaskRunner`、专题服务或 `Database` 的业务实现。
3. `api.ts`、`types.ts`、`queryKeys.ts` 和调用页面/feature。
4. API、数据事务、前端契约及真实运行测试。
5. 本文、页面实现闭环表和 CODEMAP；影响稳定边界时再更新 ARCHITECTURE。

没有后端调用的页面行为应明确写“纯本地行为”，例如官网页内滚动和列表展示偏好。分页接口必须说明筛选、排序、总数和稳定次级排序；异步接口必须说明幂等、任务状态、取消、恢复和重试。
