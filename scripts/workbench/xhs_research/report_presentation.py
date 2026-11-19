"""Structured report-to-HTML presentation generation and safe rendering."""

from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


PRESENTATION_PROMPT_VERSION = "report-presentation-v1"
PRESENTATION_PAGE_RANGES = {
    "concise": (6, 8, "精简"),
    "standard": (9, 12, "标准"),
    "complete": (13, 16, "完整"),
}
PRESENTATION_MAX_REPORT_CHARS = 60_000
PRESENTATION_MAX_INSTRUCTIONS = 1_000
PRESENTATION_SLIDE_TYPES = {
    "title", "section", "bullets", "metrics", "comparison", "quote", "closing",
}


def normalize_presentation_configuration(value: Any = None) -> Dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("演示稿配置必须是对象")
    unknown = sorted(set(value) - {"title", "page_mode", "instructions"})
    if unknown:
        raise ValueError(f"演示稿配置包含未知字段：{', '.join(unknown)}")
    title = str(value.get("title") or "").strip()[:200]
    page_mode = str(value.get("page_mode") or "standard").strip().lower()
    if page_mode not in PRESENTATION_PAGE_RANGES:
        raise ValueError("演示稿页数必须是 concise、standard 或 complete")
    instructions = str(value.get("instructions") or "").strip()
    if len(instructions) > PRESENTATION_MAX_INSTRUCTIONS:
        raise ValueError(f"演示稿补充要求最多 {PRESENTATION_MAX_INSTRUCTIONS} 个字符")
    return {"title": title, "page_mode": page_mode, "instructions": instructions}


def _text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def validate_presentation_deck(value: Any, page_mode: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("演示稿返回值必须是对象")
    slides = value.get("slides")
    if not isinstance(slides, list):
        raise ValueError("演示稿 slides 必须是数组")
    minimum, maximum, _label = PRESENTATION_PAGE_RANGES[page_mode]
    if not minimum <= len(slides) <= maximum:
        raise ValueError(f"{page_mode} 演示稿必须包含 {minimum}～{maximum} 页")
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            raise ValueError(f"第 {index} 页必须是对象")
        slide_type = str(slide.get("type") or "").strip().lower()
        if slide_type not in PRESENTATION_SLIDE_TYPES:
            raise ValueError(f"第 {index} 页类型无效")
        title = _text(slide.get("title"), 160)
        if not title:
            raise ValueError(f"第 {index} 页缺少标题")
        bullets = slide.get("bullets") or []
        metrics = slide.get("metrics") or []
        columns = slide.get("columns") or []
        source_refs = slide.get("source_refs") or []
        if not all(isinstance(items, list) for items in (bullets, metrics, columns, source_refs)):
            raise ValueError(f"第 {index} 页的列表字段无效")
        normalized_slides.append({
            "type": slide_type,
            "eyebrow": _text(slide.get("eyebrow"), 80),
            "title": title,
            "subtitle": _text(slide.get("subtitle"), 240),
            "body": _text(slide.get("body"), 800),
            "bullets": [_text(item, 220) for item in bullets[:6] if _text(item, 220)],
            "metrics": [{
                "value": _text(item.get("value"), 40),
                "label": _text(item.get("label"), 80),
                "context": _text(item.get("context"), 160),
            } for item in metrics[:4] if isinstance(item, dict)],
            "columns": [{
                "title": _text(item.get("title"), 80),
                "items": [
                    _text(entry, 180) for entry in (item.get("items") or [])[:5]
                    if _text(entry, 180)
                ],
            } for item in columns[:2] if isinstance(item, dict)],
            "source_refs": [_text(item, 80) for item in source_refs[:6] if _text(item, 80)],
        })
    if normalized_slides[0]["type"] != "title":
        raise ValueError("演示稿第一页必须是标题页")
    if normalized_slides[-1]["type"] != "closing":
        raise ValueError("演示稿最后一页必须是结论页")
    return {
        "title": _text(value.get("title"), 200) or normalized_slides[0]["title"],
        "subtitle": _text(value.get("subtitle"), 300),
        "slides": normalized_slides,
    }


def build_presentation_prompt(report: Dict[str, Any], configuration: Dict[str, Any]) -> str:
    minimum, maximum, label = PRESENTATION_PAGE_RANGES[configuration["page_mode"]]
    requested_title = configuration["title"] or str(report.get("title") or "HTML 演示稿")
    instructions = configuration["instructions"] or "无"
    markdown = str(report.get("content_markdown") or "").strip()
    if not markdown:
        raise ValueError("源大模型报告没有正文")
    markdown = markdown[:PRESENTATION_MAX_REPORT_CHARS]
    return (
        "你是严谨的数据研究演示稿编辑。请把下面的中文 Markdown 调研报告改写为一份"
        "可直接演示的结构化幻灯片。只使用源报告中已有的事实、数字、结论和帖子引用，"
        "不得补造证据。每页只表达一个核心结论，标题应是观点句而非栏目名；正文精炼，"
        "数字优先使用 metrics，比较关系使用 columns。第一页 type=title，最后一页"
        " type=closing。source_refs 只填写源报告中真实出现的引用，例如“帖子 #123”。"
        "所有字段都必须提供；不适用的数组填 []，不适用的文本填空字符串。"
        f"输出 {minimum}～{maximum} 页（{label}版），只输出符合 schema 的 JSON。\n"
        f"演示稿标题：{requested_title}\n"
        f"补充要求：{instructions}\n"
        "源大模型报告：\n" + markdown
    )


def generate_presentation_deck(
    provider: Any,
    report: Dict[str, Any],
    configuration: Dict[str, Any],
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    configuration = normalize_presentation_configuration(configuration)
    if hasattr(provider, "generate_presentation"):
        raw = provider.generate_presentation(report, configuration, should_cancel=should_cancel)
        if isinstance(raw, tuple):
            value, diagnostics = raw
        else:
            value, diagnostics = raw, {}
        return validate_presentation_deck(value, configuration["page_mode"]), diagnostics
    if not hasattr(provider, "_invoke"):
        raise RuntimeError("当前报告 Provider 不支持 HTML 演示稿")
    output_root = Path(getattr(provider, "work_dir", None) or Path.cwd())
    output_root.mkdir(parents=True, exist_ok=True)
    content, diagnostics = provider._invoke(
        build_presentation_prompt(report, configuration),
        output_root,
        f"presentation-{report.get('id')}",
        float(getattr(provider, "timeout", 480)),
        Path(__file__).with_name("report-presentation-schema.json"),
        should_cancel,
    )
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("演示稿没有返回有效 JSON") from exc
    return validate_presentation_deck(value, configuration["page_mode"]), diagnostics


def _list(items: List[str], class_name: str = "bullet-list") -> str:
    return f'<ul class="{class_name}">' + "".join(
        f"<li>{escape(item)}</li>" for item in items
    ) + "</ul>"


def _render_slide(slide: Dict[str, Any], index: int) -> str:
    slide_type = slide["type"]
    parts = [f'<section class="slide slide-{slide_type}" data-slide="{index}">', '<div class="slide-content">']
    if slide["eyebrow"]:
        parts.append(f'<p class="eyebrow">{escape(slide["eyebrow"])}</p>')
    heading = "h1" if slide_type == "title" else "h2"
    parts.append(f'<{heading}>{escape(slide["title"])}</{heading}>')
    if slide["subtitle"]:
        parts.append(f'<p class="subtitle">{escape(slide["subtitle"])}</p>')
    if slide["body"]:
        parts.append(f'<p class="body-copy">{escape(slide["body"])}</p>')
    if slide["metrics"]:
        parts.append('<div class="metric-grid">')
        for metric in slide["metrics"]:
            parts.append(
                '<article class="metric-card">'
                f'<strong>{escape(metric["value"])}</strong>'
                f'<span>{escape(metric["label"])}</span>'
                f'<small>{escape(metric["context"])}</small>'
                '</article>'
            )
        parts.append('</div>')
    if slide["columns"]:
        parts.append('<div class="column-grid">')
        for column in slide["columns"]:
            parts.append('<article class="column-card">')
            parts.append(f'<h3>{escape(column["title"])}</h3>')
            parts.append(_list(column["items"]))
            parts.append('</article>')
        parts.append('</div>')
    if slide["bullets"]:
        parts.append(_list(slide["bullets"]))
    if slide["source_refs"]:
        parts.append('<div class="source-refs">' + "".join(
            f'<span>{escape(item)}</span>' for item in slide["source_refs"]
        ) + '</div>')
    parts.extend(['</div>', '</section>'])
    return "".join(parts)


def render_presentation_html(deck: Dict[str, Any]) -> str:
    slides = "".join(_render_slide(slide, index) for index, slide in enumerate(deck["slides"], 1))
    title = escape(deck["title"])
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>{title}</title>
<style>
:root{{--bg:#07111f;--panel:#0f2038;--text:#f7fbff;--muted:#9fb3c8;--accent:#ff365f;--accent2:#35d6c1;--line:rgba(255,255,255,.12);--shadow:0 28px 80px rgba(0,0,0,.38);--radius:24px;font-family:Inter,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}}
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;background:#02070d;color:var(--text);overflow:hidden}}button{{font:inherit}}
.deck{{position:absolute;inset:0;margin:auto;width:min(100vw,calc(100vh * 16 / 9));height:min(100vh,calc(100vw * 9 / 16));overflow:hidden;background:var(--bg);box-shadow:var(--shadow)}}
.deck:before{{content:"";position:absolute;inset:-30%;background:radial-gradient(circle at 15% 20%,rgba(255,54,95,.20),transparent 30%),radial-gradient(circle at 85% 80%,rgba(53,214,193,.18),transparent 30%);pointer-events:none}}
.slide{{position:absolute;inset:0;padding:6.2% 7%;display:flex;opacity:0;visibility:hidden;transform:translateY(18px);transition:.32s ease;overflow:hidden}}
.slide.active{{opacity:1;visibility:visible;transform:none}}.slide-content{{position:relative;z-index:1;width:100%;max-height:100%;display:flex;flex-direction:column;justify-content:center;gap:clamp(10px,1.7vh,22px);overflow:hidden}}
.slide-title .slide-content,.slide-closing .slide-content{{align-items:center;text-align:center;padding-inline:7%}}
.eyebrow{{margin:0;color:var(--accent2);font-weight:800;letter-spacing:.16em;text-transform:uppercase;font-size:clamp(11px,1.2vw,18px)}}
h1,h2,h3,p{{margin:0}}h1{{font-size:clamp(34px,5.2vw,78px);line-height:1.08;letter-spacing:-.04em;max-width:14ch}}h2{{font-size:clamp(28px,4vw,60px);line-height:1.12;letter-spacing:-.03em;max-width:18ch}}h3{{font-size:clamp(16px,1.8vw,27px)}}
.subtitle{{font-size:clamp(16px,2vw,30px);line-height:1.45;color:var(--muted);max-width:38ch}}.body-copy{{font-size:clamp(14px,1.55vw,24px);line-height:1.65;color:#dbe8f4;max-width:60ch}}
.bullet-list{{display:grid;gap:clamp(8px,1.2vh,16px);margin:0;padding:0;list-style:none;max-width:68ch}}.bullet-list li{{position:relative;padding-left:1.4em;font-size:clamp(14px,1.55vw,24px);line-height:1.45}}.bullet-list li:before{{content:"";position:absolute;left:0;top:.55em;width:.55em;height:.55em;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent2))}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1.4vw}}.metric-card,.column-card{{background:linear-gradient(145deg,rgba(255,255,255,.09),rgba(255,255,255,.035));border:1px solid var(--line);border-radius:var(--radius);padding:clamp(16px,2vw,30px)}}.metric-card{{display:flex;flex-direction:column;gap:.5em}}.metric-card strong{{font-size:clamp(28px,4vw,60px);color:var(--accent2);letter-spacing:-.04em}}.metric-card span{{font-size:clamp(13px,1.4vw,21px);font-weight:700}}.metric-card small{{color:var(--muted);font-size:clamp(11px,1.05vw,16px);line-height:1.4}}
.column-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2vw}}.column-card{{display:grid;gap:1em}}.column-card:first-child{{border-top:4px solid var(--accent)}}.column-card:last-child{{border-top:4px solid var(--accent2)}}
.source-refs{{display:flex;flex-wrap:wrap;gap:8px;margin-top:.5em}}.source-refs span{{border:1px solid var(--line);border-radius:999px;padding:.35em .7em;color:var(--muted);font-size:clamp(10px,.9vw,14px)}}
.progress{{position:fixed;top:0;left:0;height:4px;background:linear-gradient(90deg,var(--accent),var(--accent2));z-index:20;transition:width .25s}}.controls{{position:fixed;z-index:30;left:50%;bottom:max(18px,3vh);transform:translateX(-50%);display:flex;align-items:center;gap:14px;padding:8px 12px;border:1px solid var(--line);border-radius:999px;background:rgba(2,7,13,.72);backdrop-filter:blur(16px)}}.controls button{{width:38px;height:38px;border:0;border-radius:50%;color:var(--text);background:rgba(255,255,255,.10);cursor:pointer}}.controls button:hover{{background:rgba(255,255,255,.20)}}.counter{{min-width:72px;text-align:center;color:var(--muted);font-size:13px}}.fullscreen{{position:fixed;right:22px;bottom:22px;z-index:30;border:1px solid var(--line);border-radius:999px;padding:10px 14px;color:var(--text);background:rgba(2,7,13,.72);cursor:pointer}}
@media(max-width:700px){{.slide{{padding:10% 7% 18%}}.metric-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.column-grid{{gap:12px}}.controls{{bottom:12px}}.fullscreen{{display:none}}}}
@media(prefers-reduced-motion:reduce){{.slide{{transition:none}}}}
@media print{{html,body{{overflow:visible;background:white}}.deck{{position:static;width:auto;height:auto;box-shadow:none}}.slide{{position:relative;width:100vw;height:56.25vw;opacity:1;visibility:visible;transform:none;break-after:page}}.controls,.progress,.fullscreen{{display:none}}}}
</style>
</head>
<body>
<div class="progress" id="progress"></div>
<main class="deck" aria-label="{title}">{slides}</main>
<nav class="controls" aria-label="幻灯片导航"><button id="prev" aria-label="上一页">←</button><span class="counter"><span id="current">1</span> / <span id="total">{len(deck['slides'])}</span></span><button id="next" aria-label="下一页">→</button></nav>
<button class="fullscreen" id="fullscreen">全屏</button>
<script>
(()=>{{const slides=[...document.querySelectorAll('.slide')],current=document.getElementById('current'),progress=document.getElementById('progress');let index=0;const show=n=>{{index=Math.max(0,Math.min(slides.length-1,n));slides.forEach((slide,i)=>{{slide.classList.toggle('active',i===index);slide.setAttribute('aria-hidden',i===index?'false':'true')}});current.textContent=String(index+1);progress.style.width=((index+1)/slides.length*100)+'%';location.hash='slide-'+(index+1)}};document.getElementById('prev').addEventListener('click',()=>show(index-1));document.getElementById('next').addEventListener('click',()=>show(index+1));document.getElementById('fullscreen').addEventListener('click',()=>document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen());document.addEventListener('keydown',event=>{{if(event.key==='ArrowRight'||event.key===' '||event.key==='PageDown'){{event.preventDefault();show(index+1)}}if(event.key==='ArrowLeft'||event.key==='PageUp'){{event.preventDefault();show(index-1)}}if(event.key==='Home')show(0);if(event.key==='End')show(slides.length-1)}});const requested=Number(location.hash.replace('#slide-',''));show(Number.isFinite(requested)&&requested>0?requested-1:0)}})();
</script>
</body>
</html>'''
