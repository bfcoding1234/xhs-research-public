from datetime import datetime
from typing import Any, Dict, List
import re


def build_report(project: Dict[str, Any], task_id: str, mode: str, posts: List[Dict[str, Any]],
                 authors: List[Dict[str, Any]], scoring: Dict[str, Any], warnings: List[str]):
    top = sorted(posts, key=lambda p: p.get("popularity_percentile") or 0, reverse=True)[:10]
    titles = [str(post.get("title") or "") for post in posts]
    numeric = sum(bool(re.search(r"\d", title)) for title in titles)
    questions = sum(any(mark in title for mark in ("?", "？", "怎么", "如何", "为什么")) for title in titles)
    actionable = sum(any(word in title.lower() for word in ("教程", "步骤", "搞定", "指南", "必备", "入门", "方法", "清单")) for title in titles)
    ocr_posts = [post for post in posts if str(post.get("ocr_text") or "").strip()]
    ocr_coverage = len(ocr_posts) / len(posts) if posts else 0
    vision_posts = [post for post in posts if post.get("vision_results")]
    lines = [
        f"# {project['name']} 调研报告",
        "",
        f"- 任务：`{task_id}`",
        f"- 模式：`{mode}`",
        f"- 帖子：{len(posts)} 篇",
        f"- 作者：{len(authors)} 位",
        f"- 热门判断：{scoring['method']}（{scoring['reason']}）",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 样本概览",
        "",
        "当前报告基于统一数据表中的最新帖子与作者信息生成；重复内容已按小红书 ID 去重。",
        "",
        "## 高表现帖子",
        "",
    ]
    for index, post in enumerate(top, 1):
        lines.append(f"{index}. **{post.get('title') or '无标题'}** — {post.get('author_name') or '未知作者'}，点赞 {post.get('likes_count') or 0}，{post.get('popularity_level') or ''}")
    lines.extend(["", "## 标题与选题规律", ""])
    image_count = sum(post.get("note_type") == "image" for post in posts)
    video_count = sum(post.get("note_type") == "video" for post in posts)
    lines.append(f"- 数字型标题 {numeric}/{len(posts)}，疑问型标题 {questions}/{len(posts)}，教程/清单/入门等行动型标题 {actionable}/{len(posts)}。")
    if top:
        lines.append(f"- 当前最高表现标题是“{top[0].get('title') or '无标题'}”，应把它作为证据样本，而不是直接把单篇表现外推为普遍规律。")
    lines.extend(["", "## 视觉与图片规律", ""])
    lines.append(f"- 内容形式：图文 {image_count} 篇，视频 {video_count} 篇；封面 OCR 有效覆盖 {len(ocr_posts)}/{len(posts)}（{ocr_coverage:.0%}）。")
    if ocr_posts:
        average = round(sum(len(str(post.get("ocr_text") or "")) for post in ocr_posts) / len(ocr_posts))
        lines.append(f"- 有文字封面的样本平均提取约 {average} 个字符，可用于识别封面钩子、承诺和信息密度。")
    if vision_posts:
        lines.append(f"- 已对 {len(vision_posts)} 篇执行大模型读图；具体结构化判断保存在帖子详情，报告只汇总可复用信号。")
    else:
        lines.append("- 本轮没有可用的大模型读图结果；视觉判断以封面 OCR 和内容形式为主，不能推断完整配色、版式和情绪表达。")
    lines.extend(["", "## 创作建议", ""])
    lines.append("1. 先复刻高表现样本的“明确对象 + 可验证结果”结构，再用自己的案例替换观点，避免只模仿标题表面。")
    lines.append("2. 封面优先保留一个核心承诺；当 OCR 文本很长时，把解释移到后续图片，减少首屏信息竞争。")
    lines.append("3. 用至少两种内容形式做小规模对照，并记录发布后互动；本报告是横截面证据，不能代替自己的账号实验。")
    lines.extend(["", "## 数据边界", ""])
    lines.append(f"- 互动详情覆盖率为 {scoring.get('coverage',{}).get('detail',0):.0%}；热门判断采用 `{scoring['method']}`，原因：{scoring['reason']}。")
    lines.append("- 帖子和作者仅保留最新值，不包含互动量历史快照；相关性、发布时间和账号体量仍可能影响横向比较。")
    if warnings:
        lines.extend(["", "## 数据警告", ""] + [f"- {warning}" for warning in warnings])
    summary = {
        "post_count": len(posts),
        "author_count": len(authors),
        "scoring_method": scoring["method"],
        "warning_count": len(warnings),
        "ocr_coverage": round(ocr_coverage, 4),
        "vision_post_count": len(vision_posts),
        "title_patterns": {"numeric": numeric, "question": questions, "actionable": actionable},
    }
    return "\n".join(lines) + "\n", summary
