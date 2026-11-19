# xhs-research 代码导航

## 使用方法

1. 不确定该读哪份文档时先看 [文档中心](./README.md)；明确开发需求后在本文按“需求类型”定位入口、共享实现、后端实现和测试。
2. 产品行为先读 [PRODUCT_RULES.md](./PRODUCT_RULES.md) 的相关小节；涉及系统边界时再读 [ARCHITECTURE.md](./ARCHITECTURE.md) 的相关小节，涉及实现风险时读 [ENGINEERING_GUARDRAILS.md](./ENGINEERING_GUARDRAILS.md)。
3. 从最小调用链开始阅读；只有发现共享边界、契约不一致或文档过期时才扩大搜索。
4. 修改路由、模块职责或文件归属后同步更新本文，并运行 `python3 scripts/validate_architecture_docs.py`。

本文记录的是导航入口，不替代源码。默认搜索顺序：

```text
页面/业务名称
  → 路由或页面
  → features 共享模块
  → services/api.ts + types.ts
  → server.py API
  → ResearchApplication / TaskRunner / Database
  → 对应前后端测试
```

### 变更影响速查

| 要改什么 | 先确认 | 主要实现入口 | 必须检查 |
| --- | --- | --- | --- |
| 页面布局、字段或操作 | 产品规则、[页面细节](./details/pages.md)、对应[页面规范](./page-specs/README.md) | `web/src/pages/` + `web/src/features/` | 页面测试、API 是否已有、真实页面状态 |
| 搜索、筛选、排序或分页 | 产品规则、列表页规范、API 分页语义 | 共享列表 feature + `api.ts` + `server.py` + `db.py` | 先筛选排序再分页、总数、稳定次级排序、偏好恢复 |
| 新增或改变 API | 变更方案、[API 详细设计](./details/api.md) | `server.py` + `api.ts` + `types.ts` + `queryKeys.ts` | 输入校验、错误、缓存失效、前后端契约测试 |
| 服务、任务或并发 | ARCHITECTURE、[服务详细设计](./details/services.md) | `server.py` / `runner.py` / 专题服务 | 状态机、事务、幂等、取消、恢复和真实运行 |
| 表、字段或关系 | ARCHITECTURE、[数据模型详细设计](./details/data-model.md) | `schema.sql` + `Database.initialize()` + `db.py` | 新库、旧库迁移、索引、事务、接口类型和数据测试 |
| Provider、OCR 或 Codex | [依赖能力](./details/dependencies.md)、配置参考 | `collector.py` + 适配器 / `ocr.py` / `vision.py` / `ai_reporting.py` | 登录阻塞、降级、超时取消、敏感信息和能力实测 |
| 测试或质量门禁 | ENGINEERING_GUARDRAILS | 相邻前后端测试、package scripts | 自动化门禁、构建产物和对应真实流程 |

## 一、项目入口

| 目的 | 首先阅读 |
|---|---|
| 所有任务的系统边界与交付规则 | [AGENTS.md](../AGENTS.md) |
| 文档角色、阅读顺序与权威来源 | [docs/README.md](./README.md) |
| 产品术语、作用范围和默认行为 | [PRODUCT_RULES.md](./PRODUCT_RULES.md) |
| 页面、API、服务与底层依赖细节 | [details/README.md](./details/README.md) |
| 列表页的共性布局与交互规范 | [page-specs/list-page.md](./page-specs/list-page.md) |
| 测试层级、门禁与验收职责 | [TESTING.md](./TESTING.md) |
| 实现层高风险约束 | [ENGINEERING_GUARDRAILS.md](./ENGINEERING_GUARDRAILS.md) |
| Skill 对话工作流与产品边界 | [SKILL.md](../SKILL.md) |
| 历史规则原因与来源日期 | [LEARNED_RULES_HISTORY.md](./history/LEARNED_RULES_HISTORY.md)（仅按关键词查阅） |
| 命令行薄入口与 worktree 默认值 | [scripts/xhs_research.py](../scripts/xhs_research.py) |
| Python 服务组装和启动 | [cli.py](../scripts/workbench/xhs_research/cli.py) |
| Web 路由 | [routes.ts](../scripts/workbench/web/config/routes.ts) |
| 前端 API 契约 | [api.ts](../scripts/workbench/web/src/services/api.ts)、[types.ts](../scripts/workbench/web/src/types.ts) |
| 后端 HTTP API | [server.py](../scripts/workbench/xhs_research/server.py) |
| 数据库 Schema 与访问 | [schema.sql](../scripts/workbench/xhs_research/schema.sql)、[db.py](../scripts/workbench/xhs_research/db.py) |
| 任务业务执行 | [runner.py](../scripts/workbench/xhs_research/runner.py) |

## 二、页面路由到代码

| 页面/路由 | 页面入口 | 主要共享模块 | 主要 API |
|---|---|---|---|
| `/` | [Landing/index.tsx](../scripts/workbench/web/src/pages/Landing/index.tsx) | 独立官网布局与品牌样式，不进入 Ant Design Pro 工作台布局 | 无 |
| `/my-projects`、`/my-projects/:tab` | [MyProjects/index.tsx](../scripts/workbench/web/src/pages/MyProjects/index.tsx) | 复用作者详情 [Authors/Detail.tsx](../scripts/workbench/web/src/pages/Authors/Detail.tsx)，包括作者范围图片理解 | `settings`、`authors`、`setupMyAuthor`、`authorVisionStatus` |
| `/authors` | [Authors/index.tsx](../scripts/workbench/web/src/pages/Authors/index.tsx) | [AuthorView.tsx](../scripts/workbench/web/src/features/authors/AuthorView.tsx)、[AuthorBatchUpdateControl.tsx](../scripts/workbench/web/src/features/authors/AuthorBatchUpdateControl.tsx) | `authors`、`createTask`、项目关系 |
| `/authors/:id/:tab?` | [Authors/Detail.tsx](../scripts/workbench/web/src/pages/Authors/Detail.tsx) | 作者更新、帖子列表、图片理解、报告、项目关联 | `author`、`authorVisionStatus`、`startAuthorVision`、`authorReports`、`startAuthorReport` |
| `/projects` | [Projects/index.tsx](../scripts/workbench/web/src/pages/Projects/index.tsx) | 项目编辑、删除、任务状态 | `projects`、`tasks`、`updateProject`、`deleteProject` |
| `/projects/new` | [Projects/Create.tsx](../scripts/workbench/web/src/pages/Projects/Create.tsx) | — | `createProject` |
| `/projects/:id/:tab?` | [Projects/Detail.tsx](../scripts/workbench/web/src/pages/Projects/Detail.tsx) | 项目帖子、作者、关键词、任务、报告、图片理解 | `project*` 系列接口 |
| `/posts` | [Posts/index.tsx](../scripts/workbench/web/src/pages/Posts/index.tsx) | 帖子共享列表、详情更新、项目关联 | `posts`、`startPostDetailUpdate` |
| `/posts/:id` | [Posts/Detail.tsx](../scripts/workbench/web/src/pages/Posts/Detail.tsx) | 图片理解展示、项目关联 | `post` |
| `/tasks` | [Tasks/index.tsx](../scripts/workbench/web/src/pages/Tasks/index.tsx) | 状态与进度组件 | `tasks`、`cancelTask`、`retryTask` |
| `/tasks/new` | [Tasks/Create.tsx](../scripts/workbench/web/src/pages/Tasks/Create.tsx) | 调研表单 | `createTask` |
| `/tasks/:id`、项目任务详情 | [Tasks/Detail.tsx](../scripts/workbench/web/src/pages/Tasks/Detail.tsx) | 输入展示、事件、进度 | `task`、`taskEvents`、取消/恢复/重试 |
| `/settings` | [Settings/index.tsx](../scripts/workbench/web/src/pages/Settings/index.tsx) | 设置分区、能力路由、数据发布 | `settings`、`health`、`stats`、`dataRelease*` |

路由、菜单和布局一起修改时，同时查看：

- [config/routes.ts](../scripts/workbench/web/config/routes.ts)
- [src/app.tsx](../scripts/workbench/web/src/app.tsx)
- [utils/menu.ts](../scripts/workbench/web/src/utils/menu.ts)
- [tests/test_web_project_list.py](../tests/test_web_project_list.py)

所有带批量选择的分页列表统一通过
[persistentRowSelection.ts](../scripts/workbench/web/src/features/selection/persistentRowSelection.ts)
保留跨页选择；卡片视图的当前页全选与逐项选择分别由 `AuthorView.tsx` 和
`PostView.tsx` 维护。

所有允许用户调整排序的核心列表统一通过
[listSortPreferences.ts](../scripts/workbench/web/src/features/preferences/listSortPreferences.ts)
按入口类型保存受控排序状态；帖子每页数量继续由
[postListPreferences.ts](../scripts/workbench/web/src/features/posts/postListPreferences.ts)
在各帖子入口间共享。

## 三、按需求类型定位

### 1. 作者列表和作者详情

| 层 | 文件 |
|---|---|
| 全局作者列表页 | [pages/Authors/index.tsx](../scripts/workbench/web/src/pages/Authors/index.tsx) |
| 共享列表/卡片视图 | [features/authors/AuthorView.tsx](../scripts/workbench/web/src/features/authors/AuthorView.tsx) |
| 项目作者表 | [features/authors/ProjectAuthorsTable.tsx](../scripts/workbench/web/src/features/authors/ProjectAuthorsTable.tsx) |
| 作者详情与“个人”复用 | [pages/Authors/Detail.tsx](../scripts/workbench/web/src/pages/Authors/Detail.tsx)、[pages/MyProjects/index.tsx](../scripts/workbench/web/src/pages/MyProjects/index.tsx) |
| 快速详情抽屉 | [features/authors/AuthorDetailDrawer.tsx](../scripts/workbench/web/src/features/authors/AuthorDetailDrawer.tsx) |
| 单作者/批量更新 | [features/authors](../scripts/workbench/web/src/features/authors) |
| API 与业务创建 | `GET /api/authors*`、`POST /api/tasks`、`POST /api/projects/:id/author-updates` in [server.py](../scripts/workbench/xhs_research/server.py) |
| 执行与持久化 | `TaskRunner._run_author_update()`、`run_project_author_update()`；`Database.upsert_author()` |
| 后端测试 | [test_author_update.py](../tests/test_author_update.py)、[test_author_post_counts.py](../tests/test_author_post_counts.py) |

“改作者列表”默认检查全局列表、项目作者列表和共享卡片/选择能力，除非需求明确限定入口。

### 2. 帖子列表、详情和详情更新

| 层 | 文件 |
|---|---|
| 全局帖子页 | [pages/Posts/index.tsx](../scripts/workbench/web/src/pages/Posts/index.tsx) |
| 作者帖子入口 | [pages/Authors/Detail.tsx](../scripts/workbench/web/src/pages/Authors/Detail.tsx) |
| 项目帖子入口 | [features/posts/ProjectPostsTable.tsx](../scripts/workbench/web/src/features/posts/ProjectPostsTable.tsx) |
| 共享列表/卡片/筛选 | [features/posts/PostView.tsx](../scripts/workbench/web/src/features/posts/PostView.tsx)、[PostListFilters.tsx](../scripts/workbench/web/src/features/posts/PostListFilters.tsx) |
| 共享分页偏好 | [postListPreferences.ts](../scripts/workbench/web/src/features/posts/postListPreferences.ts) |
| 详情页与抽屉 | [pages/Posts/Detail.tsx](../scripts/workbench/web/src/pages/Posts/Detail.tsx)、[PostDetailDrawer.tsx](../scripts/workbench/web/src/features/posts/PostDetailDrawer.tsx)；共用 [PostDetailContent.tsx](../scripts/workbench/web/src/features/posts/PostDetailContent.tsx) |
| 评论入口与展示 | [PostCommentCollectionAction.tsx](../scripts/workbench/web/src/features/posts/PostCommentCollectionAction.tsx)、[PostCommentsPanel.tsx](../scripts/workbench/web/src/features/posts/PostCommentsPanel.tsx) |
| 媒体与图片理解展示 | [PostMediaPreview.tsx](../scripts/workbench/web/src/features/posts/PostMediaPreview.tsx)、[VisionAnalysisSection.tsx](../scripts/workbench/web/src/features/posts/VisionAnalysisSection.tsx) |
| 详情更新入口 | [PostDetailUpdateControl.tsx](../scripts/workbench/web/src/features/posts/PostDetailUpdateControl.tsx) |
| API | `GET /api/posts*`、`GET /api/projects/:id/posts`、`POST /api/post-detail-updates`、`GET /api/posts/:id/comments`、`POST /api/posts/:id/comment-tasks` |
| 数据与执行 | `attention.py` 统一关注分公式；`Database.list_posts_page()`、`list_project_posts_page()`（项目实时关注分与服务端排序）、`select_post_detail_update_candidates()`、`save/list_post_comments()`；`TaskRunner.run_post_detail_update()`、`run_post_comment_collection()` |
| 后端测试 | [test_global_entities.py](../tests/test_global_entities.py)、[test_post_detail_update.py](../tests/test_post_detail_update.py)、[test_post_comments.py](../tests/test_post_comments.py)、[test_post_sorting.py](../tests/test_post_sorting.py) |

“改帖子列表”默认检查全局、项目、作者和“个人”四类入口。

### 3. 项目、关键词和实体关系

| 需求 | 入口与实现 | 后端与测试 |
|---|---|---|
| 项目创建、编辑、删除 | `pages/Projects/*`、`features/projects/ProjectEditModal.tsx`、`ProjectDeleteAction.tsx` | `ResearchApplication` 项目 API、`Database.create/update/delete_project()`；[test_project_delete_atomicity.py](../tests/test_project_delete_atomicity.py) |
| 项目关键词 | [ProjectKeywordsTable.tsx](../scripts/workbench/web/src/features/projects/ProjectKeywordsTable.tsx) | `Database.list/add/remove_project_keywords()`；[test_global_entities.py](../tests/test_global_entities.py) |
| AI 关键词候选 | [KeywordSuggestionsModal.tsx](../scripts/workbench/web/src/features/projects/KeywordSuggestionsModal.tsx)、[keywordSuggestionCache.ts](../scripts/workbench/web/src/features/projects/keywordSuggestionCache.ts) | `ResearchApplication.generate_keyword_suggestions()`、[keyword_generation.py](../scripts/workbench/xhs_research/keyword_generation.py)、[test_keyword_suggestions.py](../tests/test_keyword_suggestions.py) |
| 帖子/作者关联项目 | [features/references](../scripts/workbench/web/src/features/references) | `POST/DELETE /api/projects/:id/references`、`Database.attach/detach_project_references()`；[test_global_entities.py](../tests/test_global_entities.py) |

关系需求先确认修改的是全局实体还是 `project_posts` / `project_authors`，不要复制作者或帖子。

### 4. 调研任务创建与更新

| 层 | 文件 |
|---|---|
| 新建任务页 | [pages/Tasks/Create.tsx](../scripts/workbench/web/src/pages/Tasks/Create.tsx) |
| 项目内创建/重跑 | [CreateResearchTaskModal.tsx](../scripts/workbench/web/src/features/research/CreateResearchTaskModal.tsx)、[RerunResearchModal.tsx](../scripts/workbench/web/src/features/research/RerunResearchModal.tsx) |
| 表单与参数转换 | [features/research](../scripts/workbench/web/src/features/research) |
| 输入校验模型 | [models.py](../scripts/workbench/xhs_research/models.py) |
| 创建与恢复编排 | `ResearchApplication.create_task()`、`build_rerun_payload()`、`_recovery_invocation()` |
| 普通执行 | `TaskRunner.run()` |
| 测试 | [test_models.py](../tests/test_models.py)、[test_mixed_research.py](../tests/test_mixed_research.py)、[test_rerun.py](../tests/test_rerun.py)、[test_source_limits.py](../tests/test_source_limits.py) |

新建入口只公开关键词和作者采集；`mixed` 保留给历史数据、兼容 API 和历史任务重跑。修改共享表单或模型时必须继续覆盖历史 `mixed` 测试，但不得重新加入新建类型选项。

### 5. 任务状态、并发、取消和恢复

| 需求 | 实现 | 测试 |
|---|---|---|
| 状态与事件展示 | `pages/Tasks/*`、`features/tasks/*`、`components/TaskStatusTag.tsx`、`TaskProgress.tsx` | 前端相邻测试 |
| 创建和线程池选择 | `ResearchApplication.create_*_task()`、`_submit()`、`_recovery_invocation()` | [test_task_type.py](../tests/test_task_type.py)、[test_task_scheduling.py](../tests/test_task_scheduling.py) |
| 项目内顺序 | `ResearchApplication._run_in_project_order()`、`Database.has_active_task_predecessor()` | [test_task_scheduling.py](../tests/test_task_scheduling.py) |
| 取消、恢复、重试 | `ResearchApplication.cancel_task()`、`resume_task()`、HTTP task action routes | [test_task_cancel.py](../tests/test_task_cancel.py) |
| 服务重启恢复 | `ResearchApplication.recover_interrupted_tasks()` | [test_task_recovery.py](../tests/test_task_recovery.py) |
| 创建原子性 | `Database.create_task()` 与部分唯一索引 | [test_task_atomicity.py](../tests/test_task_atomicity.py) |

### 6. 采集能力和外部 CLI

| 需求 | 首先阅读 | 测试 |
|---|---|---|
| 能力目录、默认/降级路由 | [collector.py](../scripts/workbench/xhs_research/collector.py) | [test_mixed_research.py](../tests/test_mixed_research.py)、[test_settings_api.py](../tests/test_settings_api.py) |
| Socai 适配 | [socai.py](../scripts/workbench/xhs_research/socai.py) | [test_socai_cancel.py](../tests/test_socai_cancel.py) |
| `xiaohongshu-cli` 适配与登录态 | [xiaohongshu_cli.py](../scripts/workbench/xhs_research/xiaohongshu_cli.py) | [test_xiaohongshu_cli.py](../tests/test_xiaohongshu_cli.py) |
| OpenCLI 适配 | [opencli.py](../scripts/workbench/xhs_research/opencli.py) | [test_opencli.py](../tests/test_opencli.py) |
| 采集结果入库和降级 | `TaskRunner._route_capability()`、`_collect_source()`、`_ingest_*()` | [test_mixed_research.py](../tests/test_mixed_research.py) |
| 环境检查和安装 | [envcheck.py](../scripts/workbench/xhs_research/envcheck.py) | `test_entry.py`、Provider 对应测试 |

### 7. 图片理解与 OCR

| 层 | 文件 |
|---|---|
| 前端创建 | [VisionRunModal.tsx](../scripts/workbench/web/src/features/vision/VisionRunModal.tsx) |
| 后台模型配置 | [Settings/index.tsx](../scripts/workbench/web/src/pages/Settings/index.tsx)、`GET /api/settings/vision-models`；任务创建窗口不展示模型参数 |
| 状态展示 | 项目详情、作者详情（个人复用）、帖子详情、`VisionAnalysisSection.tsx` |
| 任务创建 | `ResearchApplication.create_vision_task()`、`create_author_vision_task()`；全局帖子列表不创建图片理解任务 |
| 候选与固定处理能力 | [vision.py](../scripts/workbench/xhs_research/vision.py)、[ocr.py](../scripts/workbench/xhs_research/ocr.py)；OCR 固定 RapidOCR，图片理解固定 Codex，模型目录从 Codex CLI 读取，Prompt 与 cache key 均包含封面/详情范围 |
| 当前缓存判定 | [vision_state.py](../scripts/workbench/xhs_research/vision_state.py)，统一定义 `cover/detail` 媒体归类与范围级 current 判定 |
| 执行 | `TaskRunner.run_vision()`、`run_ocr()` |
| 测试 | [test_vision_task.py](../tests/test_vision_task.py)、[test_vision_selection.py](../tests/test_vision_selection.py)、[test_vision_provider_concurrency.py](../tests/test_vision_provider_concurrency.py) |

### 8. 项目/作者报告

| 层 | 文件 |
|---|---|
| 共享展示与创建 | [features/reports](../scripts/workbench/web/src/features/reports)，其中 `ReportRunModal.tsx` 选择摘要/明细复选来源，`ReportPresentationModal.tsx` 创建 HTML 演示稿；`DataSummaryView.tsx` 兼容历史摘要，`DataSummaryV2View.tsx` 组织当前结构化摘要模块，`DataSummaryCharts.tsx` 展示帖子多指标趋势、业务分布和作者地区图表 |
| 项目/作者入口 | `pages/Projects/Detail.tsx`、`pages/Authors/Detail.tsx` |
| 数据摘要生成 | `TaskRunner.create_*_data_summary()`、[data_summary.py](../scripts/workbench/xhs_research/data_summary.py)，schema v5 拆分封面/详情处理覆盖 |
| 任务创建 | `ResearchApplication.create_ai_report_task()`、`create_author_ai_report_task()`、`create_report_presentation_task()` |
| 证据、分批与 Provider | [ai_reporting.py](../scripts/workbench/xhs_research/ai_reporting.py) |
| HTML 演示稿结构与渲染 | [report_presentation.py](../scripts/workbench/xhs_research/report_presentation.py)、[report-presentation-schema.json](../scripts/workbench/xhs_research/report-presentation-schema.json) |
| 旧版采集模板报告 | [reporting.py](../scripts/workbench/xhs_research/reporting.py) |
| 执行与快照 | `TaskRunner._capture_*_report_evidence()`、`_report_evidence_for_sources()`、`run_*_ai_report()`、`run_report_presentation()` |
| 持久化 | `Database.create_data_summary()`、`Database.create_task()` 的报告/演示稿占位、`create_report()`、`create_author_report()`、`complete_report_presentation()`、`report_chunks`、`report_presentations` |
| 测试 | [test_data_summary.py](../tests/test_data_summary.py)、[test_ai_report.py](../tests/test_ai_report.py)、[test_codex_process.py](../tests/test_codex_process.py) |

### 9. 设置、运行环境和数据发布

| 需求 | 实现 | 测试 |
|---|---|---|
| 设置 UI 与 API | `pages/Settings/index.tsx`、`GET/POST /api/settings`、`Database.get_app_settings()`、`set_app_settings()` | [test_settings_api.py](../tests/test_settings_api.py) |
| 环境变量和路径 | [config.py](../scripts/workbench/xhs_research/config.py)、`scripts/xhs_research.py` | [test_config.py](../tests/test_config.py)、[test_entry.py](../tests/test_entry.py) |
| 生命周期锁与安全停止 | [lifecycle_lock.py](../scripts/workbench/xhs_research/lifecycle_lock.py)、`ResearchApplication.acquire/release_runtime_lock()` | [test_lifecycle_lock.py](../tests/test_lifecycle_lock.py)、[test_task_recovery.py](../tests/test_task_recovery.py) |
| 开发数据发布 | [release.py](../scripts/workbench/xhs_research/release.py) | [test_data_release.py](../tests/test_data_release.py) |
| HTTP、静态资源和媒体安全 | `server.py` 的 handler、`_serve_media()`、`_serve_static()` | [test_web_static.py](../tests/test_web_static.py) |

## 四、API 路由导航

所有 API 当前集中在 [server.py](../scripts/workbench/xhs_research/server.py) 的 handler 中。

| API 组 | 主要应用/数据方法 |
|---|---|
| `/api/health`、`/api/stats` | 应用运行状态、数据库轻量统计 |
| `/api/projects*` | `Database` 项目、关系、关键词、分页和报告查询；`ResearchApplication` 任务创建 |
| `/api/posts*` | `TaskRunner.posts_page/get_post`、评论任务与评论查询、`Database` 帖子分页；不提供全局图片理解创建接口 |
| `/api/authors*` | `TaskRunner.author/author_vision_status`、作者范围图片理解、`Database` 作者与作者报告 |
| `/api/tasks*` | `ResearchApplication` 创建/取消/恢复/重试；`Database` 任务与事件 |
| `/api/settings` | 应用设置、Provider 指令目录和能力路由 |
| `/api/me/setup` | `ResearchApplication.setup_my_author()` |
| `/api/post-detail-updates` | `ResearchApplication.create_post_detail_update_task()` |
| `/api/data-release*` | `DataReleaseService` |

新增 API 时通常需要同步：

1. `server.py` 路由、输入校验和错误映射。
2. `db.py` 或 `runner.py` 的业务实现。
3. `web/src/services/api.ts`。
4. `web/src/types.ts` 和 `queryKeys.ts`。
5. 页面/feature 调用与前后端测试。

## 五、数据库导航

| 数据主题 | 主要表 | `db.py` 入口 |
|---|---|---|
| 全局作者与帖子 | `authors`、`posts` | `upsert_author/post`、`list_authors`、`list_posts_page` |
| 项目关系 | `project_posts`、`project_authors` | `attach/detach_project_references`、项目分页和统计 |
| 项目关键词 | `project_keywords` | `list/add/remove_project_keywords` |
| 任务与事件 | `tasks`、`task_events`、`task_posts`、`task_comments` | `create/update/cancel_task`、`append/list_task_events` |
| 帖子评论 | `post_comments`、`task_comments`、`post_comment_checkpoints` | `save_post_comment_page()`、`get/mark_post_comment_checkpoint*()`、`list_post_comments()` |
| 媒体和图片理解 | `media_assets`、`vision_analyses` | `upsert_media`、OCR 与 vision 查询/保存 |
| 报告 | `reports`、`author_reports`、`report_chunks`、`report_presentations` | 报告/演示稿占位、创建、失败清理、批次缓存与 HTML 产物 |
| 设置与发布 | `app_settings`、`data_releases` | 设置读写、`DataReleaseService` |

修改表结构时同时检查：

- [schema.sql](../scripts/workbench/xhs_research/schema.sql) 的新库定义。
- `Database.initialize()` 的旧库迁移与索引创建。
- [details/data-model.md](./details/data-model.md) 的业务语义。
- API 类型、真实数据库测试和运行时重启验收。

## 六、验证入口

### 后端与跨层

```bash
python3 -m compileall -q scripts/workbench/xhs_research scripts/xhs_research.py
python3 -m unittest discover -s tests
```

### 前端

```bash
cd scripts/workbench/web
npm run typecheck
npm run lint
npm run lint:antd
npm test
npm run build
```

### 文档导航

```bash
python3 scripts/validate_architecture_docs.py
```

运行完整测试前，可从本文对应小节选择相邻测试快速反馈；最终验证范围仍遵循 [AGENTS.md](../AGENTS.md) 和改动风险。

## 七、维护规则

- 新增页面或路由：更新“页面路由到代码”。
- 移动共享组件或改变模块职责：更新对应需求小节。
- 新增 API、表、任务类型或 Provider：同时更新本文、[详细设计](./details/README.md) 和 [ARCHITECTURE.md](./ARCHITECTURE.md) 中受影响的稳定边界。
- 改变术语、默认行为或跨页面交互：更新 [PRODUCT_RULES.md](./PRODUCT_RULES.md)；实现边界变化时更新 [ENGINEERING_GUARDRAILS.md](./ENGINEERING_GUARDRAILS.md)。
- 仅实现细节变化且入口和边界不变：不为更新而更新文档。
- 文档与代码不一致时，先以代码和测试确认真实行为，再修正文档；不要按过期文档强行修改代码。
