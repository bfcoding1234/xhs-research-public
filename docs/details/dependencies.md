# 底层依赖与外部能力

## 1. 文档定位

本文对应传统开发中的第三方系统集成说明和底层依赖能力清单。运行参数、安装方式和默认路由以 [configuration.md](./configuration.md) 为准。xiaohongshu-cli 指定版本的命令契约与真实调用证据见 [能力实测报告](./xiaohongshu-cli-capability-report.md)；本文维护跨版本、可复用且由当前实现验证的稳定能力边界。

业务任务只依赖“搜索帖子、读取作者资料、读取帖子详情、读取评论、下载媒体”等原子能力。Provider 是可替换实现，不能进入项目、页面或任务类型的业务语义。

## 2. 采集 Provider

| 依赖 | 当前用途 | 主要优势 | 已知限制与失败处理 |
| --- | --- | --- | --- |
| Socai | 搜索帖子、作者主页帖子、帖子详情、媒体和部分 OCR | 与现有浏览器采集流程兼容，能力覆盖较完整 | 登录或验证页进入 `waiting_login`；普通失败按能力路由降级 |
| `xiaohongshu-cli` | 搜索用户、读取作者、分页作者帖子、帖子详情、评论和楼中楼 | 稳定 JSON envelope，适合定向读取和分页 | 不提供 Socai 式 OCR；能力和筛选差异必须形成警告，认证错误进入等待登录 |
| OpenCLI | 关键词搜索、作者、帖子详情和媒体下载的后备能力 | 复用用户 Chrome 登录态 | 依赖 Browser Bridge 和带 token 的上下文；退出码按认证、超时和合法空结果分类 |

路由原则：默认指令成功即结束；普通失败才进入下一候选；登录、验证码或安全验证优先进入 `waiting_login`，人工恢复后先重试当前指令。

### 2.1 原子能力与默认路由

| 业务能力 | 默认与降级指令 | 输入 / 输出要点 | 当前限制 |
| --- | --- | --- | --- |
| `search_users_by_keyword` | xiaohongshu-cli | 关键词、数量 → 稳定作者 ID 与资料 | 每页 20 位，按 ID 去重；无其他 Provider 后备 |
| `read_author_profile` | xiaohongshu-cli → Socai | 稳定作者 ID → 作者最新资料 | 认证问题进入 waiting_login |
| `search_posts_by_keyword` | Socai → xiaohongshu-cli → OpenCLI | 关键词、数量、排序/时间条件 → 帖子索引 | Provider 支持的排序和发布时间筛选不完全一致，必须记录警告 |
| `list_author_posts` | Socai → xiaohongshu-cli → OpenCLI | 作者 ID、数量 → 主页帖子列表 | 请求超过 30 篇时可临时优先 xiaohongshu-cli 分页指令，并记录实际快照 |
| `read_keyword_post_details` | Socai → xiaohongshu-cli → OpenCLI | 搜索发现的帖子上下文 → 标准帖子详情 | OpenCLI 需要包含 xsec_token 的上下文 URL |
| `read_author_post_details` | Socai → xiaohongshu-cli → OpenCLI | 作者帖子索引 → 标准帖子详情 | 详情数量受任务输入快照限制 |
| `read_post_detail` | xiaohongshu-cli → OpenCLI | 已存帖子 ID/运行时 URL → 正文、互动、媒体地址 | 成功还要求有效封面落地，敏感 URL 不写任务输入 |
| `read_post_comments` | xiaohongshu-cli | 帖子运行时上下文、cursor、页数 → 评论页与 next_cursor | 单任务 1～20 页；同帖只有一个活跃任务 |
| `download_media` | OpenCLI 等已注册指令 | 远程媒体上下文 → 数据目录内普通文件 | 下载结果仍需路径与媒体内容校验 |

路由的持久化配置位于 `app_settings.capability_routes`；任务启动时读取一次并把实际顺序保存到结果。历史任务中的任务级 `collector` 仅兼容读取，新任务不再写入或使用。

### 2.2 外部错误归一化

| 外部情况 | 统一结果 | 后续行为 |
| --- | --- | --- |
| 登录失效、验证码、安全验证或已知验证页 | `waiting_login` | 阻塞当前任务；自动检测或人工恢复后先重试当前指令 |
| 合法空结果 | 成功但结果为空 | 根据业务阶段继续、告警或形成 partial，不误判为认证失败 |
| 普通命令失败或能力不支持 | 可降级失败 | 记录诊断并尝试下一指令 |
| 超时 | 可诊断失败 | 终止进程组；按任务/能力策略决定重试或降级 |
| 用户取消 | cancelled | 停止 Provider 和 Runner，禁止后续业务提交 |
| 非结构化或 Schema 无效输出 | 适配失败 | 不直接入库；记录脱敏错误摘要并降级或失败 |

## 3. AI、OCR 与报告依赖

| 依赖 | 用途 | 输入身份与缓存 | 运行边界 |
| --- | --- | --- | --- |
| RapidOCR | 本地媒体 OCR | 以媒体内容和 OCR 完成状态判断 | 固定 OCR 实现，不提供页面级 Provider 选择 |
| Codex CLI | 关键词候选、图片理解和大模型报告 | 模型、推理强度、Prompt 版本及输入哈希参与缓存或任务快照 | 通过统一子进程管理超时、取消和进程组清理；浏览器不直接调用 |
| 报告模板与 Schema | 结构化报告、演示稿 JSON 校验 | Schema、Prompt 版本与证据快照 | 模型文本必须校验和转义；演示稿 HTML 由服务端可信模板渲染 |

## 4. 数据与运行依赖

| 依赖 | 用途 | 关键边界 |
| --- | --- | --- |
| SQLite | 全局主数据、关系、任务、设置、缓存和报告事实来源 | Schema 与兼容迁移同步；写入通过 Database 事务；一个数据目录只允许一个服务持有 |
| 本地媒体目录 | 封面、正文图片、视频封面和处理输入 | `/media/` 只提供已登记、仍在规范目录内且内容合法的媒体 |
| Python 标准 HTTP 服务 | 回环 API、静态前端和媒体服务 | 校验 Host、Origin、JSON 和路径，不提供公网监听语义 |
| 文件锁与进程信号 | 数据目录生命周期和安全停止 | SIGTERM 不伪装成用户取消；停止后不得遗留采集或 Codex 子进程 |

## 5. 前端基础依赖

| 依赖 | 用途 | 项目约束 |
| --- | --- | --- |
| React 19 + TypeScript | 页面与业务组件 | API 契约类型化；不维护服务端状态副本 |
| Ant Design 6 / ProComponents | 布局、表格、表单和反馈 | 使用当前版本组件 API 和 token；通过 `lint:antd` 与真实页面审查 |
| Umi Max 4 | Hash 路由、构建和应用运行时 | 只使用受支持的运行时导出；生产服务只托管 `web/dist/` |
| React Query | 查询、Mutation、轮询与缓存失效 | 只轮询活跃任务；后台刷新保留上次成功数据 |
| Vitest / Biome / Ant Design CLI | 前端测试和静态门禁 | 与 typecheck、build 共同作为前端交付门禁 |

## 6. 新依赖接入检查

新增依赖前必须说明：解决的业务能力、现有能力为何不足、安装和授权方式、输入输出契约、敏感信息边界、错误分类、超时取消、降级顺序、可观测性、兼容和移除策略、测试方式。安装依赖和登录外部系统仍需用户确认。

## 7. 依赖就绪与验证入口

| 依赖 | 就绪信号 | 主要配置 / 实现 | 验证方式 |
| --- | --- | --- | --- |
| Socai | 二进制可解析且健康检查列为可用 | `SOCIAI_BIN`、`socai.py` | 环境检查 + 真实只读能力调用 |
| xiaohongshu-cli | `xhs` 可执行、结构化 status 证明有效登录 | `XIAOHONGSHU_CLI_BIN`、`xiaohongshu_cli.py` | `xhs status --json` + 目标能力实测 |
| OpenCLI | `opencli doctor` 通过且 Browser Bridge 可用 | `OPENCLI_BIN`、`opencli.py` | 用户 Chrome 登录态下的真实只读调用 |
| Codex CLI | 二进制可解析；所选模型支持对应输入 | `CODEX_BIN`、`codex_process.py` | 模型目录读取 + 最小结构化调用 |
| RapidOCR | Python 依赖可导入并能处理本地测试图片 | `ocr.py` | OCR 相邻测试 + 本地媒体样本 |
| SQLite / 数据目录 | Schema 初始化成功并取得唯一生命周期锁 | `config.py`、`db.py`、`lifecycle_lock.py` | 临时库迁移测试 + `/api/health` |
| 前端构建 | `web/dist/index.html` 与资源清单来自当前源码 | Umi / package scripts | typecheck、lint、test、build + 真实 Python 静态服务 |
