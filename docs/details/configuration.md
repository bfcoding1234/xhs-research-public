# 运行配置与环境详细设计

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `XHS_RESEARCH_APP_DIR` | Skill 内置 `scripts/workbench` | 可选的开发或排障覆盖路径；设置后必须包含 `xhs_research/cli.py` |
| `XHS_RESEARCH_DATA_DIR` | 主 worktree：`~/Documents/Codex/xhs-research-data`；linked 开发 worktree：`~/Documents/Codex/xhs-research-data-develop` | 数据库、媒体、采集 CLI 运行文件和日志目录 |
| `XHS_RESEARCH_HOST` | `127.0.0.1` | 本地服务地址 |
| `XHS_RESEARCH_PORT` | 主 worktree：`4318`；linked 开发 worktree：`4319` | 本地服务端口 |
| `XHS_RESEARCH_COLLECTOR` | `socai` | 旧版兼容变量；新任务忽略此值并统一使用原子能力路由 |
| `SOCAI_BIN` | 自动查找 | Socai 可执行文件 |
| `XIAOHONGSHU_CLI_BIN` | 自动查找 `xhs` | `xiaohongshu-cli` 可执行文件 |
| `OPENCLI_BIN` | 自动查找 `opencli` | OpenCLI 可执行文件 |
| `CODEX_BIN` | 自动查找 | Codex CLI，可选，用于关键词生成、图片理解和大模型报告 |
| `XHS_RESEARCH_RESEARCH_WORKERS` | `1` | 数据采集队列并发数；建议保持 1，范围 1～4 |
| `XHS_RESEARCH_VISION_WORKERS` | `1` | 图片理解队列并发数，范围 1～4 |
| `XHS_RESEARCH_REPORT_WORKERS` | `1` | 大模型报告队列并发数，范围 1～4 |
| `XHS_RESEARCH_MAX_KEYWORDS_PER_TASK` | `5` | 单项任务最多接受的去重关键词数，范围 1～20 |
| `XHS_RESEARCH_MAX_AUTHORS_PER_TASK` | `5` | 单项任务最多接受的去重作者数，范围 1～20 |

通过 `scripts/xhs_research.py` 启动时，主 worktree 默认使用 `4318` 和 `~/Documents/Codex/xhs-research-data`，linked 开发 worktree 默认使用 `4319` 和 `~/Documents/Codex/xhs-research-data-develop`。识别依据是 worktree 类型而不是分支名，所以在开发 worktree 内切换到功能分支不会切换运行环境。显式设置 `XHS_RESEARCH_PORT` 或 `XHS_RESEARCH_DATA_DIR` 时保留调用方配置，不使用自动默认值。

两套服务可以同时运行，但不会自动同步项目、任务、媒体或设置。开发数据需要以正式数据为初始样本时，应在两个服务均停止后复制一次数据快照，随后各自独立演进。不要让两个服务共享同一个数据目录；新版服务会为 `XHS_RESEARCH_DATA_DIR` 持有生命周期锁，同一数据目录同时只允许一个 Python 服务。

服务启动时会把 `XHS_RESEARCH_DATA_DIR` 展开并解析为规范绝对路径，数据库、媒体、采集运行目录、日志和生命周期锁都使用同一个根目录。服务只允许监听回环地址；HTTP 请求的 `Host` 也必须是回环地址。浏览器发起写请求时，`Origin` 必须是可信的本机 `http`/`https` 地址，并拒绝 `Sec-Fetch-Site: cross-site`；命令行客户端可以不发送 `Origin`。所有 POST 请求必须使用 `application/json` 且顶层为对象，不能提交数组、标量、`NaN` 或任何层级的无限值。请求体最大为 2,000,000 字节，超出时返回 HTTP 413。

## 数据采集 CLI

服务启动后会同时注册 Socai、`xiaohongshu-cli` 与 OpenCLI。安装可用的提供方后正常启动：

```bash
python3 scripts/xhs_research.py start
```

使用 `xiaohongshu-cli` 前先安装并登录：

```bash
uv tool install xiaohongshu-cli
xhs login
python3 scripts/xhs_research.py start
```

如可执行文件不在 `PATH`，设置 `SOCAI_BIN` 或 `XIAOHONGSHU_CLI_BIN=/绝对路径/xhs`。二进制路径在服务启动时读取，修改路径需要安全重启。Web 与命令入口不再提供任务级采集引擎选择，也不再向新任务写入 `tasks.input_json.collector`；历史字段读取和重跑保持兼容，但不会影响路由。

使用 OpenCLI 前要求 Node.js 20 或更高版本，并需安装官方 npm 包和 Browser Bridge Chrome 扩展：

```bash
npm install -g @jackwener/opencli
opencli doctor
```

Chrome 中还要保持小红书登录态；如可执行文件不在 `PATH`，设置 `OPENCLI_BIN=/绝对路径/opencli`。工作台不会自动安装浏览器扩展。

Runner 将采集拆成业务语义原子能力，并通过稳定的采集指令 ID 映射到具体 CLI 方法。默认指令成功后不再调用其他指令，失败时才按设置顺序降级；该能力的全部候选都失败时任务才失败。系统默认路由为：`search_users_by_keyword` 使用 `xiaohongshu-cli.search_users_by_keyword`；`read_author_profile` 使用 `xiaohongshu-cli.read_author_profile` → `socai.read_author_profile`；`search_posts_by_keyword`、`list_author_posts`、`read_keyword_post_details`、`read_author_post_details` 使用对应的 `socai.*` → `xiaohongshu-cli.*` → `opencli.*` 指令；直接更新已存帖子的 `read_post_detail` 使用 `xiaohongshu-cli.read_post_detail` → `opencli.read_post_detail`；`read_post_comments` 仅使用 `xiaohongshu-cli.read_post_comments`；`download_media` 可使用 `opencli.download_media`。作者模块的批量帖子预览是完整性例外：请求超过 30 篇且当前 `list_author_posts` 路由包含 `xiaohongshu-cli` 时，本次任务临时把该分页指令提升到首位；不修改后台持久化顺序，但在任务事件和 `capability_routes` 快照中记录实际顺序。

评论任务固定为单帖、每次 1～20 页，不使用 `--all`。默认 `collection_mode=continue` 从帖子已保存 cursor 续传；`refresh` 从首页更新近期评论且不回退有效深度检查点。连续请求默认随机等待 1～2 秒，可设 1～60 秒。`include_sub_comments=false` 时只保存内嵌回复预览；开启后串行调用 `xhs sub-comments`，`sub_comment_page_limit` 默认 20、可设 1～100。

在“后台配置 → 原子能力路由”中可以分别调整每个能力的默认指令与降级指令顺序。设置以 `app_settings.capability_routes` 保存；每个普通调研任务启动时读取一次并固定路由快照，因此运行中修改只影响后续任务。报告摘要的 `capability_usage` 记录最终 `selected_provider` 与 `selected_command`，`capability_routes` 保存该任务实际使用的路由快照，任务事件同时记录 `capability`、`command`、`instruction` 和 `collector`。按关键词搜索用户得到的资料使用 `keyword_discovered` 关系写入项目，随后将稳定作者 ID 交给主页帖子能力。

`/api/health.routing_mode` 固定为 `capability`。`/api/health.capability_routes` 与 `/api/settings.capability_routes` 返回业务能力、默认/降级指令和系统默认顺序；`/api/settings.collector_commands` 返回指令 ID、提供方、能力、展示名称、实际命令模板和可用状态；`/api/settings.collectors` 返回提供方及二进制状态。通过 `POST /api/settings` 提交 `capability_routes` 对象或列表即可持久化调整，服务端会拒绝未知指令、重复指令和能力不匹配。

三个提供方都实现关键词帖子发现、作者主页帖子发现和帖子详情读取，但能力不是完全等价：

- `socai` 支持现有浏览器采集、封面 OCR、媒体下载和筛选参数。
- `xiaohongshu-cli` 使用稳定的 `ok/schema_version/data/error` JSON envelope，支持综合、最新、最热排序；当前不支持发布时间筛选。请求了非“不限”的发布时间时，任务继续执行但会记录明确警告。
- `xiaohongshu-cli` 当前不提供 Socai 式 OCR，也不下载完整轮播媒体。工作台仍会保存可访问的列表封面；深度读取会保存正文、互动数与远程图片地址，报告和图片理解必须按实际本地媒体、OCR 覆盖率判断。
- OpenCLI 使用用户 Chrome 中的小红书登录态，通过 `xiaohongshu search`、`user`、`note` 和 `download` 适配器执行；结构化输出使用 `-f json`。搜索结果不支持排序和发布时间筛选，详情读取依赖搜索结果中带 `xsec_token` 的完整 URL。退出码 66 视为合法空结果，69 表示 Browser Bridge 不可用，75 表示超时，77 表示需要登录。
- 首选提供方需要登录而后续提供方成功时会降级继续；若最终候选仍需要登录或验证，则进入 `waiting_login`。取消任务都会终止当前子进程。

接口响应统一带有禁止 MIME 猜测、拒绝外部嵌入和不发送来源页的安全响应头。`/media/` 除了要求文件已在数据库登记并位于规范数据目录内，还会永久拒绝数据库、WAL、SHM、锁、日志和临时文件；文件只有通过实际内容识别为受支持图片或视频时才会返回，并使用内容对应的 MIME 类型，而不是信任扩展名。

## 默认调研参数

- 发现数量：50。`limits.discovery`、`keyword_limits.discovery` 和 `author_limits.discovery` 最少为 1，不设系统固定上限；作者采集还受用户配置的单作者帖子上限约束。
- 深度分析数量：0，范围为 0～对应的发现数量，不设系统固定上限；默认不打开详情页。
- 图片处理：固定为 `ocr-only`，新建和更新调研都不能在采集任务中启用图片理解。
- 帖子详情有效期：30 天。
- 作者资料有效期：7 天。
- 单个作者帖子上限：默认 300，可配置为任意正整数，不设系统固定上限。

调研数量默认值在“后台配置 → 调研默认参数”中编辑，有效期和作者帖子上限在“后台配置 → 刷新策略”中编辑。设置保存到本地数据库，新建任务在开始执行时读取最新值；修改设置不会改变已经运行中的任务。单个作者帖子上限会同时限制该任务的发现数量和深度分析数量。

## “个人”的作者配置

`app_settings.my_author_id` 保存代表当前用户的全局作者主键，可空。首次进入“个人”且尚未配置时，可以从已有作者列表选择，也可以输入新的稳定作者 ID。选择已有作者只保存 `my_author_id`，不会创建任务；输入新 ID 会通过 `POST /api/me/setup` 创建或复用作者记录，保存 `my_author_id`，并创建一次 `basic_info` + `preview_posts` 更新任务，预览数量使用当时的默认发现数量且仍受单作者帖子上限约束。

首次初始化接口只允许在 `my_author_id` 为空时调用，配置后再次调用必须拒绝。后续更换作者只能在“后台配置 → 个人设置”从已有作者中选择；个人详情页本身不展示更换入口。

列表模式仍会保存封面并执行封面 OCR。只有明确需要正文、评论、详情互动数或完整轮播图片时才将深度分析设置为 3～5 等小值。

## 独立图片理解参数

- 图片范围：`cover`（封面图）与 `detail`（详情图片）可复选，至少一项；每次新建任务默认只选封面图。详情图片包含正文图片和视频封面帧。
- 处理范围：默认 `vision-selective`，也可设为 `vision-all`。
- 选择比例：默认 20%。
- 最低处理数量：默认 10 篇。
- 最高处理数量：默认 30 篇。
- 每批帖子数：默认 5 篇，范围 1～20。
- 图片理解模型：默认留空并跟随 Codex 当前默认模型；下拉只列出本机 Codex 目录中可见且支持图片输入的模型。
- 推理强度：默认使用模型默认值；选择明确模型后可选该模型声明支持的强度。
- 调用超时：默认 600 秒，范围 60～3600 秒。
- 每次只处理当前图片哈希和处理版本下尚无结果的图片。

这些参数只在“后台配置 → 图片理解”中编辑，只供项目或作者范围的“补充图片理解”操作使用。图片范围是每次任务的临时选择，不写回后台默认值；模型、推理强度和超时不在执行任务窗口展示，新任务从后台设置冻结，重试沿用原任务快照。选择性分析时，每个所选图片范围分别以“待处理图片帖子数 × 比例（向上取整）”与最低数量中的较大值，再受最高处理数量限制；选择“优先分析全部未处理图片”时直接处理所选范围的全部待处理图片。每批帖子数控制一次 Codex 调用包含的帖子数，默认 5 篇；封面与详情分批调用，结果分别保存。OCR 固定使用 RapidOCR，大模型理解固定使用 Codex，不提供图片处理 Provider 配置。

## 任务并发与顺序

- 数据采集、图片理解、大模型报告和关键词建议分别提交到独立线程池，不再共用单个全局执行线程；单个采集任务可以按动作调用多个提供方的不同能力。
- 不同项目的不同类型任务可以并行，例如项目 A 采集时，项目 B 可以生成报告或补充图片理解。
- 同一项目中，图片理解与大模型报告互不阻塞，可以同时运行；报告只读取启动时已经完成的图片理解结果。
- 只要前序或当前任务有一项是普通采集任务，同一项目仍按创建时间和任务 ID稳定排序；后创建任务保持 `queued`，直到冲突的前序任务结束或取消。
- `waiting_login` 同时覆盖登录、验证码、安全验证、Socai 返回的已知验证页/异常页信号和 `xiaohongshu-cli` 的结构化认证错误。当前服务进程仍在运行时，服务每隔约 15 秒检测一次；用户也可以在任务详情确认“已完成验证，继续任务”，通过 `POST /api/tasks/{task_id}/resume` 立即唤醒同一任务。此时只重试当前中断来源，已完成来源和任务进度继续保留；在成功或取消之前仍阻塞同项目后续任务，避免读取或改写不完整数据。服务在等待期间重启时仍按原配置重新入队，不提供来源级检查点续跑。
- 服务启动时按创建顺序恢复 `queued` 与 `waiting_login`；无法确认是否安全续跑的历史 `running` 会转为带中断说明的 `failed`，由用户确认后重试。
- 同一项目不允许重复创建活跃的图片理解任务，也不允许重复创建活跃的大模型报告任务。
- 新任务的数据库创建和执行器入队按同一顺序串行，服务重启恢复任务时也使用这条提交顺序，避免较新任务占住单线程队列等待尚未入队的前序任务。
- “重试”只接受 `failed` 或 `partial` 任务；活跃任务和已完成任务返回冲突，不会创建重复执行。
- 收到 SIGTERM 或正常停止请求时，服务先停止接收新工作，再取消运行中的 Codex 关键词、图片理解和报告子进程；子进程在宽限期后仍未退出时才强制终止，最后等待任务执行器收尾并释放数据目录锁。

## 参数联动

- 作者调研：支持逐行输入多个作者主页 URL 或作者 ID；隐藏并忽略排序方式、发布日期范围。发现数量和深度分析数量按每位作者分别应用。
- 作者详情更新：必须在“基础信息”和“详细的帖子”中至少选择一项。基础信息只刷新作者资料；详细帖子显示最多处理数量，范围 1～后台 `max_author_notes`，发现到的帖子全部读取详情。两项可同时选择。
- 关键词调研：显示排序方式、发布日期范围。
- 关键词采集：使用同一组关键词，分别提供“采集相关帖子”和“采集相关作者”开关，两项至少开启一项。仅在帖子采集开启时显示帖子数量与筛选条件；作者数量最少为 1、不设固定上限，默认 5，不受后台单次作者来源上限约束。`xiaohongshu-cli` 用户搜索按每页 20 位自动翻页并按稳定作者 ID 去重，直到达到设置数量、返回不足一页或当前页没有新增作者。
- 综合调研：同时显示关键词、作者、关键词筛选条件，以及两类来源各自的发现数量与深度分析数量。主题必填；关键词和作者至少填写一类。
- 普通调研：固定 `ocr-only`，不显示图片理解参数。
- 独立图片理解使用 `vision-selective` 时显示选择比例和最低数量。
- 独立图片理解使用 `vision-all` 时隐藏比例、最低和最高处理数量，处理全部未分析图片。

作者来源只接受两种形式：其一是匹配 `[A-Za-z0-9_-]{3,128}` 的稳定作者 ID；其二是 `http`/`https` 的小红书主页 URL，主机必须是 `xiaohongshu.com` 或其子域名，不能包含用户名、密码或非标准端口，路径必须为 `/user/profile/{作者ID}`（允许末尾 `/` 和平台附带的查询参数）。其他网站 URL、昵称、搜索链接和任意路径都会返回输入错误。

## Codex 增强功能的输入与超时

- AI 候选关键词默认超时 120 秒。请求始终包含项目最新名称和说明；`reference_sources` 只能从 `manual`、`ai_generated` 中选择，也可以为空，前端默认只选 `manual`。仅选中来源的项目关键词进入生成上下文，全部已有项目关键词只用于去重。每个项目同时最多运行一个生成请求，不创建任务记录或数据库候选记录。前端按项目将最后一次成功结果保存在 `sessionStorage`，关闭弹窗、站内跳转和刷新不会清空；成功重新生成或删除项目时清理旧结果，浏览器会话结束后自然失效。
- 大模型报告可复选一份同范围的已完成数据摘要与任务启动时的当前明细，至少选择一项。所选摘要完整内容、版本、时间和哈希随任务冻结；同时选择时摘要负责统计数字、趋势和分布，当前明细只补充案例、原文和定性证据。当前明细的代表帖子按作者、来源、时间、热度、内容类型和证据完整度分层选择，不只截取热度最高内容；用户补充要求最多 1000 字。
- 报告证据超过单次字符预算时由后端自动分批，单批约 2 万字符，Codex 子进程全局最多并发 2 个。批次默认超时 240 秒，最终合成默认超时 480 秒，失败最多重试一次；批次结果按输入哈希、模型和 Prompt 版本缓存在 SQLite。Web 创建表单不展示这些内部参数。
- “后台配置 → 报告提示词”可以同时编辑分批提示词和最终报告提示词。分批模板可使用 `{{allowed_post_ids}}`、`{{subject_name}}`、`{{evidence_json}}`、`{{user_instructions}}`，并且必须同时包含 `{{allowed_post_ids}}` 与 `{{evidence_json}}`；最终模板可使用 `{{scope_label}}`、`{{subject_name}}`、`{{report_title}}`、`{{context_label}}`、`{{user_instructions}}`、`{{evidence_json}}`，并且必须包含 `{{evidence_json}}`。每个模板最长 12000 字，两份模板原子保存。新建报告任务会把完整模板和哈希写入任务快照，配置修改不影响已经排队或运行的任务，重试沿用原任务快照；批次缓存键包含模板哈希与本次分析要求。
- 图片理解运行超时由后台配置，默认 600 秒且限制在 60～3600 秒。关键词、图片理解和报告进程都支持用户取消与服务安全停止，超时或取消后不会遗留 Codex 子进程。
- HTML 演示稿沿用报告执行器和 Provider 超时，不增加运行配置。创建时可选精简 6～8 页、标准 9～12 页或完整 13～16 页；Provider 返回结构化幻灯片 JSON，HTML 由服务端固定模板渲染并且不加载远程资源。

## 更新调研的参数来源与确认

更新已有项目时，参数来源是该项目按创建时间排序的最近一次普通调研任务，不是后台当前默认值。必须先展示并确认调研类型、作者列表或关键词、发现与深度分析数量、关键词筛选和强制刷新设置，再创建新任务。图片理解不属于更新配置。

大模型报告创建表单允许填写最长 200 字的报告名称。服务端为空时回退为“项目名 + 大模型报告”，并把最终名称同时写入 `tasks.input_json.report_generation.title`、`reports.title` 和 `reports.generation_config_json.title`。

命令入口先运行不带 `--confirm` 的 `update`，此时只返回配置且不创建任务；用户明确确认后执行返回的 `confirm_command`，并通过 `--source-task-id` 锁定已展示的配置。

工作台点击“更新调研”后展示以最近配置预填的可编辑表单。项目名称和调研类型属于项目级字段，只读且服务端拒绝覆盖；作者、帖子关键词、用户关键词、发现与深度分析数量、关键词筛选和强制刷新属于任务级字段，可以修改。服务端始终把普通调研强制为 `ocr-only`。作者调研根据每个稳定作者 ID 生成并展示标准主页 URL `https://www.xiaohongshu.com/user/profile/{作者ID}`；编辑多行 URL 或 ID 时同步刷新识别结果。关闭或取消不会创建任务；确认提交时携带来源任务 ID 和修改后的任务配置，避免并发新任务改变配置来源。

## 依赖安装原则

环境检查只生成建议，不会自动执行。至少一个采集 CLI 可用时基础采集环境可以就绪；缺少提供方造成的能力缺口应在设置页明确显示，例如没有 `xiaohongshu-cli` 时“关键词搜索用户”不可用。缺少 Chrome 或 Codex 时，引导用户安装或打开对应产品。采集与采集 CLI 自带的 OCR 不要求 Codex CLI。

用户确认后可运行：

```bash
python3 scripts/xhs_research.py install-deps --dependency socai --confirm
# 或
python3 scripts/xhs_research.py install-deps --dependency xiaohongshu-cli --confirm
# 或
python3 scripts/xhs_research.py install-deps --dependency opencli --confirm
```

不带 `--confirm` 时返回 `confirmation_required`，不会执行任何安装。自动安装仅使用程序内置白名单，不接受任意命令文本。

## 分发与升级

分发时复制完整的 `xhs-research` Skill 文件夹即可，不需要另外安装 `~/.codex/apps/xhs-research`。数据库、媒体、缓存和日志位于 `XHS_RESEARCH_DATA_DIR`，删除或覆盖 Skill 时不要删除该数据目录。

覆盖升级前先停止正在运行的旧服务，完成覆盖后再从新 Skill 入口启动。`XHS_RESEARCH_APP_DIR` 只用于开发或排障；普通用户不需要设置。
