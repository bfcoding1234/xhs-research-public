# 小红书个人工作台

本目录包含统一 Python 服务和 Ant Design Pro v6 前端。服务通过可配置的数据采集 CLI 负责项目、帖子、作者、任务、报告、设置与本地媒体 API；前端只通过这些 API 读写真实数据。

本文只负责子工程目录、启动、构建和验证。项目文档职责、技术架构、页面、API、服务与外部依赖从 [文档中心](../../docs/README.md) 进入。

服务同时接入 Socai、`xiaohongshu-cli` 与 OpenCLI，并把采集拆成关键词搜帖子、关键词搜用户、读取用户主页帖子、读取搜索/作者帖子详情、直接读取指定帖子详情、读取指定帖子评论/楼中楼、媒体下载等业务原子能力。帖子列表既可更新选中帖子，也可按全局、项目或作者范围创建一个批量详情更新任务；评论补充仅允许单帖创建每次 1～20 页的独立任务，默认从已保存 cursor 续传。任务只调用业务能力；能力目录通过稳定指令 ID 映射到采集器方法和 CLI 命令模板。每个能力可在设置页调整默认指令和有序降级指令，任务启动时固定路由快照。能力状态与路由可从 `/api/health.capability_routes`、`/api/settings.collector_commands` 核对。

项目和任务是关联关系：项目创建只填写基础信息；采集任务既可以从“全部任务”独立发起，也可以从项目详情发起并关联到该项目。独立任务把结果写入全局帖子和作者表，不生成项目报告；删除项目时，已结束任务会解除项目关联并继续保留。

项目和作者的大模型报告可复选一份已完成数据摘要与任务启动时的当前明细；两者同时使用时，摘要固定统计口径，明细补充案例。已完成的文字报告可继续生成固定主题、自包含、可离线预览或下载的 HTML 演示稿；演示稿绑定具体文字报告版本并沿用持久化任务、取消、恢复和重试机制。

服务只接受回环地址监听与回环 `Host`。浏览器写请求必须来自本机可信 `Origin`，命令行客户端可以省略 `Origin`；POST 请求统一使用 JSON 对象。媒体接口只返回数据库已登记、仍位于规范数据目录内且通过内容识别为图片或视频的文件，数据库、日志、锁和临时文件始终禁止访问。

## 前端技术栈

- React 19
- Ant Design 6
- Ant Design Pro / ProComponents v3
- Umi Max 4
- TypeScript
- React Query
- Vitest、Biome、Ant Design CLI

## 目录

```text
web/
├── config/          # Umi 路由、主题、代理与 ProLayout 配置
├── public/          # 本地品牌资源
├── src/
│   ├── components/  # 通用状态与错误组件
│   ├── features/    # 帖子、作者、报告、任务、调研和图片理解模块
│   ├── pages/       # 总览、项目、任务、设置与异常页
│   ├── services/    # 类型化 API 与 React Query keys
│   └── utils/       # 格式化、作者排序等纯函数
├── tests/           # 前端测试初始化
└── dist/            # 提交到仓库的生产构建产物
```

旧的 `web/app.js`、`web/styles.css` 和 `web/client/Workspace.jsx` 已退役。Python 服务不会在新构建缺失时回退到旧界面。

## 开发与验证

后端与跨层回归从 Skill 根目录运行：

```bash
python3 -m compileall -q scripts/workbench/xhs_research scripts/xhs_research.py
python3 -m unittest discover -s tests
```

前端验证从 `scripts/workbench/web` 运行：

```bash
cd scripts/workbench/web
npm install
npx max setup
npm run typecheck
npm run lint
npm run lint:antd
npm test
npm run build
```

本地前端开发服务器默认把 `/api/` 和 `/media/` 代理到 `http://127.0.0.1:4319`。需要连接其他端口时设置：

```bash
XHS_RESEARCH_API_TARGET=http://127.0.0.1:4318 npm run dev
```

生产交付以 `web/dist/index.html` 为准。构建后还必须启动真实 Python 服务，验证 `/api/health`、真实数据库数据与浏览器核心交互；只通过 TypeScript 或静态构建不算完成。

后端升级会在初始化阶段修复旧库中的重复活跃图片理解/大模型报告任务，再用数据库唯一约束防止并发重复创建。SIGTERM 会触发完整的 Runner 与 Codex 子进程取消流程，并在执行器收尾后释放数据目录生命周期锁。
