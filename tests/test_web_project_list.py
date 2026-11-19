import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "scripts" / "workbench" / "web"
SRC = WEB / "src"


class AntDesignProProjectTests(unittest.TestCase):
    def test_frontend_is_a_complete_ant_design_pro_v6_project(self):
        package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
        self.assertIn("@umijs/max", package["devDependencies"])
        self.assertIn("@ant-design/pro-components", package["dependencies"])
        self.assertIn("@tanstack/react-query", package["dependencies"])
        self.assertIn("typescript", package["devDependencies"])
        self.assertRegex(package["dependencies"]["antd"], r"6\.")
        self.assertEqual(package["scripts"]["build"], "max build")
        self.assertEqual(
            package["description"], "基于 Ant Design Pro v6 的小红书个人工作台"
        )

    def test_frontend_uses_the_personal_workbench_brand(self):
        config = (WEB / "config" / "config.ts").read_text(encoding="utf-8")
        settings = (WEB / "config" / "defaultSettings.ts").read_text(encoding="utf-8")
        logo = (WEB / "public" / "logo.svg").read_text(encoding="utf-8")

        self.assertIn("title: '小红书个人工作台'", config)
        self.assertIn("title: '小红书个人工作台'", settings)
        self.assertIn('aria-label="小红书个人工作台"', logo)

    def test_routes_cover_every_workbench_area_with_hash_history(self):
        config = (WEB / "config" / "config.ts").read_text(encoding="utf-8")
        routes = (WEB / "config" / "routes.ts").read_text(encoding="utf-8")
        self.assertIn("history: { type: 'hash' }", config)
        self.assertIn("reactQuery: {}", config)
        self.assertIn("component: './Landing'", routes)
        self.assertIn("path: '/overview'", routes)
        self.assertIn("redirect: '/my-projects'", routes)
        self.assertRegex(
            routes,
            r"path: '/overview',\s+redirect: '/my-projects',\s+hideInMenu: true",
        )
        for path in (
            "/overview",
            "/my-projects",
            "/my-projects/:tab",
            "/projects",
            "/projects/new",
            "/projects/:id/:tab",
            "/projects/:projectId/tasks/:taskId",
            "/posts",
            "/posts/:id",
            "/authors",
            "/authors/:id",
            "/authors/:id/:tab",
            "/tasks",
            "/tasks/new",
            "/tasks/:id",
            "/settings",
        ):
            self.assertIn(f"path: '{path}'", routes)

    def test_me_module_has_first_run_setup_and_reuses_author_detail(self):
        page = (SRC / "pages" / "MyProjects" / "index.tsx").read_text(encoding="utf-8")
        settings = (SRC / "pages" / "Settings" / "index.tsx").read_text(encoding="utf-8")
        routes = (WEB / "config" / "routes.ts").read_text(encoding="utf-8")
        self.assertIn("name: '个人'", routes)
        self.assertIn("AuthorDetailPage", page)
        self.assertIn("my_author_id", page)
        self.assertIn("apiService.setupMyAuthor", page)
        self.assertIn("只保存配置，不会创建抓取任务", page)
        self.assertIn("设置并开始抓取", page)
        self.assertIn('routeBase="/my-projects"', page)
        self.assertNotIn("createProject", page)
        self.assertIn("apiService.authors", page)
        self.assertIn("apiService.authors", settings)
        self.assertIn("从已有作者中选择一位个人作者", settings)
        self.assertIn('id="settings-me"', settings)

    def test_detail_tabs_follow_global_information(self):
        author = (SRC / "pages" / "Authors" / "Detail.tsx").read_text(encoding="utf-8")
        project = (SRC / "pages" / "Projects" / "Detail.tsx").read_text(encoding="utf-8")
        author_tabs = author.index('<Tabs\n          className="detail-section-tabs"')
        project_tabs = project.index('<Tabs\n          className="detail-section-tabs"')

        self.assertLess(author.index("<Descriptions"), author_tabs)
        self.assertLess(project.index("<ActiveTaskPanel"), project_tabs)
        self.assertNotIn("<StatisticCard.Group", project)
        self.assertIn("label: `报告 ${value.report_count ?? 0}`", project)
        self.assertNotIn("tabList=", author)
        self.assertNotIn("tabList=", project)

    def test_tab_routes_do_not_create_breadcrumb_levels(self):
        routes = (WEB / "config" / "routes.ts").read_text(encoding="utf-8")

        for path in ("/my-projects/:tab", "/projects/:id/:tab", "/authors/:id/:tab"):
            route_start = routes.index(f"path: '{path}'")
            route_end = routes.index("  },", route_start)
            self.assertIn("hideInBreadcrumb: true", routes[route_start:route_end])

    def test_direct_post_detail_keeps_the_posts_parent_breadcrumb(self):
        detail = (SRC / "pages" / "Posts" / "Detail.tsx").read_text(encoding="utf-8")

        self.assertIn(": '帖子';", detail)
        self.assertIn("{ title: <Link to={returnPath}>{parentLabel}</Link> }", detail)

    def test_project_detail_uses_url_tabs_and_all_business_panels(self):
        source = (SRC / "pages" / "Projects" / "Detail.tsx").read_text(encoding="utf-8")
        self.assertIn("history.push(`${detailBase}/${next}`)", source)
        self.assertIn("ProjectPostsTable", source)
        self.assertIn("ProjectAuthorsTable", source)
        self.assertIn("ProjectReferencePickerModal", source)
        self.assertIn("onLink={() => setReferenceType('post')}", source)
        self.assertIn("onLink={() => setReferenceType('author')}", source)
        self.assertIn("ProjectTasksTable", source)
        self.assertIn("ReportPanel", source)
        self.assertIn("RerunResearchModal", source)
        self.assertIn("VisionRunModal", source)
        self.assertIn("ReportRunModal", source)
        self.assertIn("history.push(`${detailBase}/tasks/${taskId}`)", source)
        self.assertNotIn("title: '最新任务状态'", source)
        self.assertIn("<ActiveTaskPanel", source)
        self.assertIn("请输入完整项目名称以确认", source)
        self.assertIn("deleteName === value.name", source)
        self.assertIn("label: '按上次配置重跑'", source)
        self.assertIn("key: 'rerun'", source)

    def test_project_list_uses_compact_in_table_toolbar_controls(self):
        source = (SRC / "pages" / "Projects" / "index.tsx").read_text(encoding="utf-8")
        styles = (SRC / "pages" / "Projects" / "index.css").read_text(encoding="utf-8")

        self.assertIn("search={false}", source)
        self.assertIn('className="projects-page__toolbar"', source)
        self.assertIn('aria-label="项目列表查询与操作"', source)
        self.assertIn("搜索项目名称或说明", source)
        self.assertNotIn("title: '调研类型'", source)
        self.assertNotIn("全部类型", source)
        self.assertNotIn('aria-label="按项目类型筛选"', source)
        self.assertIn("title: '任务状态与进度'", source)
        self.assertIn("width: 228", source)
        self.assertIn("scroll={{ x: 960 }}", source)
        self.assertNotIn("title: '活跃任务进度'", source)
        self.assertIn('className="projects-page__task-status-summary"', source)
        self.assertNotIn("cancelTask", source)
        self.assertNotIn("取消这个任务", source)
        self.assertIn("全部任务状态", source)
        self.assertIn("正在更新列表…", source)
        self.assertIn("refreshProjects", source)
        self.assertIn("history.push('/projects/new')", source)
        self.assertIn("App.useApp()", source)
        self.assertIn('className="projects-page__name-link"', source)
        self.assertIn("ellipsis={{ tooltip: description }}", source)
        self.assertIn('<Link key="open" to={`/projects/${project.id}`}>', source)
        self.assertNotIn('target="_blank"', source)
        self.assertIn(".projects-page__toolbar", styles)
        self.assertIn("grid-template-columns: minmax(220px, 320px) 156px auto auto", styles)
        self.assertIn(".projects-page__name-link:hover", styles)

    def test_post_detail_reads_the_real_analysis_json_contract(self):
        vision_source = (SRC / "features" / "posts" / "VisionAnalysisSection.tsx").read_text(
            encoding="utf-8"
        )
        drawer_source = (SRC / "features" / "posts" / "PostDetailDrawer.tsx").read_text(
            encoding="utf-8"
        )
        content_source = (SRC / "features" / "posts" / "PostDetailContent.tsx").read_text(
            encoding="utf-8"
        )
        self.assertIn("analysis.analysis_json.cover_hook", vision_source)
        self.assertIn("analysis.analysis_json.reusable_patterns", vision_source)
        self.assertIn("activeMedia.ocr_text", content_source)
        self.assertIn('<PostDetailContent mode="drawer" post={value} />', drawer_source)
        self.assertNotIn("result_json", vision_source)
        detail_page = (SRC / "pages" / "Posts" / "Detail.tsx").read_text(encoding="utf-8")
        self.assertIn('<PostDetailContent mode="page" post={value} />', detail_page)

    def test_author_updates_match_operation_frequency_and_post_depth(self):
        author_list = (SRC / "pages" / "Authors" / "index.tsx").read_text(
            encoding="utf-8"
        )
        author_detail = (SRC / "pages" / "Authors" / "Detail.tsx").read_text(
            encoding="utf-8"
        )
        update_modal = (
            SRC / "features" / "authors" / "AuthorUpdateModal.tsx"
        ).read_text(encoding="utf-8")
        batch_control = (
            SRC / "features" / "authors" / "AuthorBatchUpdateControl.tsx"
        ).read_text(encoding="utf-8")
        batch_modal = (
            SRC / "features" / "authors" / "AuthorBatchUpdateModal.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("AuthorBatchUpdateControl", author_list)
        self.assertIn("AuthorListActions", author_list)
        self.assertNotIn("buildAuthorBasicInfoUpdateConfiguration", author_list)
        self.assertNotIn("更新基础信息", author_list)
        self.assertNotIn("<Link to={`/tasks/${task.id}`}>", author_list)
        self.assertIn("更新帖子信息", author_detail)
        self.assertIn("scopes: ['preview_posts']", update_modal)
        self.assertIn("帖子基础信息（批量预览）", update_modal)
        self.assertIn("帖子详细信息（逐篇打开）", update_modal)
        self.assertIn("批量更新", batch_control)
        self.assertIn("MAX_AUTHOR_BATCH_SIZE", batch_control)
        self.assertIn("submitAuthorUpdateBatch", batch_modal)
        self.assertIn("系统将为每位作者创建一个独立任务", batch_modal)

        self.assertIn("ReportPanel", author_detail)
        self.assertIn("ReportRunModal", author_detail)
        self.assertIn("queryKeys.authorReports(id)", author_detail)
        self.assertIn('scopeLabel="作者"', author_detail)
        self.assertIn("apiService.authorReportStatus", author_detail)

    def test_all_post_lists_share_search_filters_sorting_and_vision_status(self):
        filters = (SRC / "features" / "posts" / "PostListFilters.tsx").read_text(
            encoding="utf-8"
        )
        sources = (
            (SRC / "pages" / "Posts" / "index.tsx").read_text(encoding="utf-8"),
            (
                SRC / "features" / "posts" / "ProjectPostsTable.tsx"
            ).read_text(encoding="utf-8"),
            (SRC / "pages" / "Authors" / "Detail.tsx").read_text(
                encoding="utf-8"
            ),
        )

        for label in (
            "搜索标题、正文、作者、来源或帖子 ID",
            "全部类型",
            "全部信息状态",
            "全部图片理解状态",
        ):
            self.assertIn(label, filters)
        for source in sources:
            self.assertIn("PostListFilters", source)
            self.assertIn("PostVisionStatus", source)
            self.assertIn("sorter:", source)
            self.assertIn("has_vision_result", source)
            self.assertIn("title: '收藏'", source)
            self.assertIn("title: '评论'", source)
            self.assertIn("是否已有图片理解", source)
        self.assertNotIn("VisionRunModal", sources[0])
        self.assertIn("VisionRunModal", sources[2])
        self.assertIn("apiService.authorVisionStatus", sources[2])

    def test_research_forms_enforce_source_limits_and_ocr_only_collection(self):
        fields = (SRC / "features" / "research" / "ResearchFields.tsx").read_text(
            encoding="utf-8"
        )
        configuration = (
            SRC / "features" / "research" / "configuration.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("AuthorCandidatePicker", fields)
        self.assertIn("max_keywords_per_task", configuration)
        self.assertIn("max_authors_per_task", configuration)
        self.assertIn("image_analysis: { mode: 'ocr-only'", configuration)

    def test_task_and_settings_pages_cover_runtime_operations(self):
        tasks = (SRC / "pages" / "Tasks" / "Detail.tsx").read_text(encoding="utf-8")
        task_list = (SRC / "pages" / "Tasks" / "index.tsx").read_text(encoding="utf-8")
        task_styles = (SRC / "pages" / "Tasks" / "index.css").read_text(encoding="utf-8")
        settings = (SRC / "pages" / "Settings" / "index.tsx").read_text(encoding="utf-8")
        self.assertIn("waiting_login", tasks)
        self.assertIn("apiService.cancelTask", tasks)
        self.assertIn("apiService.retryTask", tasks)
        self.assertIn("Timeline", tasks)
        self.assertIn("projectContextId", tasks)
        self.assertIn("`/projects/${projectContextId}/tasks`", tasks)
        self.assertIn("`/projects/${projectContextId}/tasks/${nextTaskId}`", tasks)
        self.assertIn("返回项目任务列表", tasks)
        self.assertIn("apiService.projects", task_list)
        self.assertIn("projectNameById.get(task.project_id)", task_list)
        self.assertIn("to={`/projects/${task.project_id}`}", task_list)
        self.assertIn("title: '任务 ID'", task_list)
        self.assertIn("title: '关联对象'", task_list)
        self.assertIn("task.task_type === 'vision' ? 'posts' : 'reports'", task_list)
        self.assertIn("to={`/authors/${task.author_id}/${tab}`}", task_list)
        self.assertIn("title={task.id}", task_list)
        self.assertIn("{ key: 'research', label: '采集任务' }", task_list)
        self.assertIn("{ key: 'vision', label: '图片理解' }", task_list)
        self.assertIn("{ key: 'ai_report', label: '大模型报告' }", task_list)
        self.assertIn("task.task_type !== activeTaskType", task_list)
        self.assertIn("<Tabs", task_list)
        self.assertIn("activeTaskType === 'research'", task_list)
        self.assertIn("create-research-task", task_list)
        self.assertIn("toolbar.unshift", task_list)
        self.assertRegex(
            task_styles,
            r"\.tasks-page-id\s*\{[^}]*display: block;[^}]*width: 100%;[^}]*max-width: 100%;",
        )
        for section in ("settings-service", "settings-defaults", "settings-source", "settings-vision", "settings-refresh", "settings-storage"):
            self.assertIn(section, settings)
        self.assertIn("最高处理数量不能小于最低处理数量", settings)

    def test_legacy_dual_frontends_are_retired(self):
        for relative in (
            "index.html",
            "app.js",
            "styles.css",
            "client/src/Workspace.jsx",
        ):
            self.assertFalse((WEB / relative).exists(), relative)
        cli = (ROOT / "scripts" / "workbench" / "xhs_research" / "cli.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Ant Design Pro 工作台尚未构建", cli)
        self.assertNotIn("else web_root", cli)

    def test_built_frontend_has_hashed_assets_and_no_legacy_bundle(self):
        dist = WEB / "dist"
        html = (dist / "index.html").read_text(encoding="utf-8")
        self.assertIn("id=\"root\"", html)
        self.assertRegex(html, r"umi\.[0-9a-f]{8}\.js")
        self.assertFalse(any(path.name.startswith("index-") for path in dist.rglob("*.js")))


if __name__ == "__main__":
    unittest.main()
