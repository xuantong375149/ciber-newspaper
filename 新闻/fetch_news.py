#!/usr/bin/env python3
"""抓取各媒体 RSS，生成当天的新闻静态页面。

用法：python fetch_news.py
输出：site/index.html、site/archive/YYYY-MM-DD.html、data/YYYY-MM-DD.json、logs/run.log
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import config
import news_core as core

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 NewsDigest/1.0"
)
ACCEPT = "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"

WEEKDAYS = "一二三四五六日"

# 计划任务/旧版控制台可能是 GBK 编码，统一改为 UTF-8，避免中文与符号报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def log(message: str) -> None:
    line = f"[{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
    try:
        print(line, flush=True)
    except (UnicodeEncodeError, OSError):
        pass
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / "run.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _build_openers() -> list[urllib.request.OpenerDirector]:
    """优先使用显式代理，失败时回退到直连/系统代理。"""
    openers = []
    if config.PROXY:
        proxy = urllib.request.ProxyHandler({"http": config.PROXY, "https": config.PROXY})
        openers.append(urllib.request.build_opener(proxy))
    openers.append(urllib.request.build_opener())
    return openers


_GOOGLE_LOCK = threading.Lock()


def fetch_bytes(url: str) -> bytes:
    # Google News 对并发请求会返回 400，串行请求并加重试更稳定
    if "news.google.com" in url:
        with _GOOGLE_LOCK:
            return _fetch_with_retry(url)
    return _fetch_with_retry(url)


def _fetch_with_retry(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": ACCEPT})
    last_error: Exception | None = None
    for attempt in range(3):
        for opener in _build_openers():
            try:
                with opener.open(req, timeout=config.TIMEOUT) as resp:
                    return core.decode_response(resp.read())
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                time.sleep(0.6 * (attempt + 1))
    raise last_error or RuntimeError("unknown fetch error")


def load_source(source: dict) -> tuple[dict, list[dict], str | None]:
    """抓取并解析单个订阅源；失败时返回错误信息而不抛出。"""
    try:
        items = core.parse_feed(fetch_bytes(source["url"]))
        kept: list[dict] = []
        for item in items:
            publisher = item.get("publisher", "")
            item["title"] = core.strip_publisher_suffix(item["title"], publisher)
            item["source"] = source["name"]
            item["category"] = source["category"]
            # 人物检索结果只保留“人名 + 言论线索”的观点类内容，过滤影视、诉讼等事件新闻
            if source["category"] == "voices" and not core.is_opinion_item(
                item["title"], source["name"], tuple(source.get("aliases", ()))
            ):
                continue
            # Google News 的摘要有时只是媒体名或标题的重复，没有信息量
            summary = item["summary"].strip()
            if (
                core.summary_is_redundant(item["title"], summary)
                or (source["name"] == "CNN" and summary.endswith(" CNN"))
            ):
                item["summary"] = ""
            kept.append(item)
        return source, kept, None
    except Exception as exc:  # noqa: BLE001 - 单个源失败不应中断整次运行
        return source, [], f"{type(exc).__name__}: {exc}"


# 跨分类去重时，更具体的板块优先保留（AI 专属内容优先于泛科技）
MERGE_PRIORITY = ["ai", "voices", "world", "business", "tech", "sport"]


def build_sections(results, now: datetime):
    """按分类过滤出当天新闻，返回 (合并列表, 放宽窗口的分类)。"""
    by_category: dict[str, list[dict]] = {cat: [] for cat in core.CATEGORY_ORDER}
    for source, items, _error in results:
        by_category[source["category"]].extend(items)

    fallback_cats: list[tuple[str, int]] = []
    sections: dict[str, list[dict]] = {}
    for cat in core.CATEGORY_ORDER:
        items = by_category[cat]
        primary = config.CATEGORY_WINDOW.get(cat, config.WINDOW_HOURS)
        fallback = config.CATEGORY_FALLBACK.get(cat, config.FALLBACK_HOURS)
        recent = core.select_recent(items, now, primary)
        if len(recent) < config.CATEGORY_MIN_ITEMS and fallback > primary:
            wider = core.select_recent(items, now, fallback)
            if len(wider) > len(recent):
                recent = wider
                if recent:
                    fallback_cats.append((cat, fallback))
        recent = core.dedupe_items(recent)
        recent = core.limit_per_source(recent, config.PER_SOURCE_CAP[cat])
        recent.sort(key=lambda i: i["published"], reverse=True)
        sections[cat] = recent[: config.CATEGORY_CAP[cat]]

    merged: list[dict] = []
    seen_links: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    for cat in MERGE_PRIORITY:
        for item in sections.get(cat, []):
            link_key = item["link"].split("#", 1)[0].strip().lower()
            title_key = (item["source"], core.norm_title(item["title"]))
            if link_key in seen_links or title_key in seen_titles:
                continue
            seen_links.add(link_key)
            seen_titles.add(title_key)
            merged.append(item)
    merged.sort(key=lambda i: i["published"], reverse=True)
    return merged, fallback_cats


def build_statuses(results, merged) -> list[dict]:
    """按媒体聚合抓取状态，条数为最终页面上的条数。"""
    statuses: dict[str, dict] = {}
    for source, _items, error in results:
        status = statuses.setdefault(
            source["name"], {"name": source["name"], "ok": False, "count": 0, "error": ""}
        )
        if error is None:
            status["ok"] = True
        else:
            status["error"] = error
    counts: dict[str, int] = {}
    for item in merged:
        counts[item["source"]] = counts.get(item["source"], 0) + 1
    for name, status in statuses.items():
        status["count"] = counts.get(name, 0)
    order = []
    for source in config.SOURCES:
        if source["name"] not in order:
            order.append(source["name"])
    return [statuses[name] for name in order if name in statuses]


def archive_dates(today: str) -> list[str]:
    dates = {today}
    if config.ARCHIVE_DIR.exists():
        for path in config.ARCHIVE_DIR.glob("*.html"):
            if len(path.stem) == 10:
                dates.add(path.stem)
    return sorted(dates, reverse=True)[:30]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def serialize(items: list[dict]) -> list[dict]:
    return [
        {
            "title": i["title"],
            "link": i["link"],
            "summary": i["summary"],
            "published": i["published"].astimezone().isoformat(),
            "source": i["source"],
            "category": i["category"],
        }
        for i in items
    ]


def main() -> int:
    started = time.time()
    now = datetime.now(timezone.utc)
    local_now = now.astimezone()
    today = local_now.strftime("%Y-%m-%d")
    date_label = f"{local_now.strftime('%Y年%m月%d日')} 星期{WEEKDAYS[local_now.weekday()]}"

    for directory in (config.SITE_DIR, config.ARCHIVE_DIR, config.DATA_DIR, config.LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    log(f"开始抓取 {len(config.SOURCES)} 个订阅源（代理: {config.PROXY or '直连'}）")
    with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
        results = list(pool.map(load_source, config.SOURCES))
    for source, items, error in results:
        if error:
            log(f"  [FAIL] {source['name']}({source['category']}) 抓取失败: {error}")
        else:
            log(f"  [OK] {source['name']}({source['category']}) 原始 {len(items)} 条")

    merged, fallback_cats = build_sections(results, now)
    if not merged:
        log("没有抓取到任何新闻，保留上一次的页面，本次不覆盖输出。")
        return 1

    statuses = build_statuses(results, merged)
    window_note = (
        f"国际/商业/科技/体育 收录最近 {config.WINDOW_HOURS} 小时 · "
        f"AI 动态 最近 {config.CATEGORY_WINDOW['ai'] // 24} 天 · "
        f"人物观点 最近 {config.CATEGORY_WINDOW['voices'] // 24} 天"
    )
    if fallback_cats:
        details = "；".join(
            f"{core.CATEGORY_LABELS[cat]}放宽至 {hours} 小时" for cat, hours in fallback_cats
        )
        window_note += f"（{details}）"

    html = core.render_page(
        items=merged,
        statuses=statuses,
        generated_at=now,
        date_label=date_label,
        archive_dates=archive_dates(today),
        window_note=window_note,
        site_title=config.SITE_TITLE,
    )
    archive_html = core.render_page(
        items=merged,
        statuses=statuses,
        generated_at=now,
        date_label=date_label,
        archive_dates=archive_dates(today),
        window_note=window_note,
        site_title=config.SITE_TITLE,
        archive_prefix="../archive/",
        show_update=False,
    )

    (config.SITE_DIR / "index.html").write_text(html, encoding="utf-8")
    (config.ARCHIVE_DIR / f"{today}.html").write_text(archive_html, encoding="utf-8")
    write_json(
        config.DATA_DIR / f"{today}.json",
        {
            "generated_at": local_now.isoformat(),
            "window": window_note,
            "statuses": statuses,
            "items": serialize(merged),
        },
    )

    by_cat = {cat: sum(1 for i in merged if i["category"] == cat) for cat in core.CATEGORY_ORDER}
    ok_sources = sum(1 for s in statuses if s["ok"])
    log(
        f"完成：共 {len(merged)} 条（{by_cat['world']} 国际 / {by_cat['business']} 商业 / "
        f"{by_cat['tech']} 科技 / {by_cat['ai']} AI / {by_cat['voices']} 观点 / "
        f"{by_cat['sport']} 体育），"
        f"{ok_sources}/{len(statuses)} 家媒体成功，用时 {time.time() - started:.1f}s"
    )
    log(f"页面已更新：{config.SITE_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
