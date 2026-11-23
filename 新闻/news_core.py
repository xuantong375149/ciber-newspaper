"""核心逻辑：RSS/Atom 解析、时间过滤、去重、HTML 页面生成。

只依赖 Python 标准库，便于在 Windows 计划任务中稳定运行。
"""
from __future__ import annotations

import gzip
import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

SUMMARY_LIMIT = 220

CATEGORY_LABELS = {
    "world": "国际",
    "business": "商业",
    "tech": "科技",
    "ai": "AI 动态",
    "voices": "人物观点",
    "sport": "体育",
}
CATEGORY_ORDER = ["world", "business", "tech", "ai", "voices", "sport"]

SOURCE_COLORS = {
    "BBC": "#bb1919",
    "CNN": "#cc0000",
    "卫报": "#052962",
    "半岛电视台": "#b45309",
    "NPR": "#0c6c9e",
    "TechCrunch": "#087a35",
    "The Verge": "#6d28d9",
    "Ars Technica": "#c2410c",
    "MIT科技评论": "#334155",
    "CNBC": "#0b5cad",
    "金融时报": "#a6332e",
    "商业内幕": "#1d4ed8",
    "OpenAI": "#0d8a72",
    "Anthropic": "#c15f3c",
    "Google DeepMind": "#2563eb",
    "Hugging Face": "#b45309",
    "Sam Altman": "#111827",
    "Dario Amodei": "#c15f3c",
    "Elon Musk": "#334155",
    "Ray Dalio": "#7c2d12",
    "Demis Hassabis": "#1d4ed8",
    "黄仁勋": "#067a46",
    "Ilya Sutskever": "#6d28d9",
    "李飞飞": "#b91c1c",
}

# 人物观点板块过滤影视/选角类噪音
_NOISE_TERMS = (
    "trailer",
    "movie",
    "film",
    "casting",
    "box office",
    "imdb",
    "garfield",
    "hollywood",
    "tv series",
    "biopic",
    "premiere",
    "guadagnino",
    "msci",
)


class FeedError(Exception):
    """订阅源无法下载或解析。"""


def decode_response(raw: bytes) -> bytes:
    """部分源（如 DeepMind）直接返回 gzip 数据而不声明编码，这里做兼容。"""
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def strip_publisher_suffix(title: str, publisher: str) -> str:
    """去掉 Google News 标题尾部的“ - 媒体名”。"""
    if publisher:
        suffix = f" - {publisher}"
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def is_entertainment_noise(title: str, publisher: str = "") -> bool:
    """判断人物检索结果是否属于影视/选角类无关内容。"""
    text = f"{title} {publisher}".lower()
    return any(term in text for term in _NOISE_TERMS)


# 标题里出现这些言论动词，才更可能是“观点”而非纯事件新闻
_OPINION_CUES = (
    "says",
    "said",
    "warns",
    "warned",
    "predicts",
    "predicted",
    "predicting",
    "interview",
    "explains",
    "explained",
    "believes",
    "thinks",
    "memo",
    "keynote",
    "remarks",
    "comments",
    "tells",
    "told",
    "argues",
    "argued",
    "calls for",
    "calling for",
    "urges",
    "proposes",
    "reveals",
)
_OPINION_CUE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(cue) for cue in _OPINION_CUES) + r")\b"
)


def is_opinion_item(title: str, person: str, aliases: tuple[str, ...] = ()) -> bool:
    """标题同时包含人物（或别名）与言论线索时，才视为“人物观点”。"""
    if is_entertainment_noise(title):
        return False
    low = title.lower()
    candidates = {person.lower(), person.split()[-1].lower()}
    candidates.update(alias.lower() for alias in aliases)
    name_hit = any(c and c in low for c in candidates)
    if not name_hit:
        return False
    # “X, says Bloomberg”这类是转述通讯社，不是人物本人的观点
    if re.search(r"\b(?:says|said|according to)\s+(?:bloomberg|reuters|report|reports)\b", low):
        return False
    prefix = re.match(r"^([^.!?]{0,80}):\s", title)
    colon_hit = bool(
        prefix and any(c and c in prefix.group(1).lower() for c in candidates)
    )
    cue_hit = (
        bool(_OPINION_CUE_RE.search(low))
        or colon_hit
        or title.lstrip()[:1] in "\"'“‘"
    )
    return cue_hit


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def clean_html(text: str | None) -> str:
    """去掉标签、反转义实体、压缩空白。"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, limit: int = SUMMARY_LIMIT) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut[limit // 2:]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:—-") + "…"


def parse_date(value: str | None) -> datetime | None:
    """解析 RFC 822（RSS）或 ISO 8601（Atom）时间，统一为 UTC。"""
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _child_text(node: ET.Element, *names: str) -> str:
    for name in names:
        for child in node:
            if _localname(child.tag) == name:
                if (child.text or "").strip():
                    return child.text
    return ""


def _atom_link(node: ET.Element) -> str:
    fallback = ""
    for child in node:
        if _localname(child.tag) != "link":
            continue
        href = child.get("href", "").strip()
        rel = child.get("rel", "alternate")
        if href and rel in ("alternate", "self"):
            return href
        fallback = fallback or href or (child.text or "").strip()
    return fallback


def _valid_link(link: str) -> bool:
    return link.startswith("https://") or link.startswith("http://")


def parse_feed(raw: bytes | str) -> list[dict]:
    """解析 RSS 2.0 或 Atom，返回 [{title, link, summary, published}]。"""
    try:
        if isinstance(raw, bytes):
            root = ET.fromstring(raw)
        else:
            root = ET.fromstring(raw.encode("utf-8"))
    except ET.ParseError as exc:
        raise FeedError(f"XML 解析失败: {exc}") from exc

    items: list[dict] = []
    for node in root.iter():
        kind = _localname(node.tag)
        if kind == "item":  # RSS 2.0
            title = clean_html(_child_text(node, "title"))
            link = _child_text(node, "link").strip() or _child_text(node, "guid").strip()
            summary = clean_html(_child_text(node, "description", "encoded", "summary"))
            published = parse_date(_child_text(node, "pubdate", "date", "published"))
            publisher = clean_html(_child_text(node, "source"))
        elif kind == "entry":  # Atom
            title = clean_html(_child_text(node, "title"))
            link = _atom_link(node)
            summary = clean_html(_child_text(node, "summary", "content"))
            published = parse_date(_child_text(node, "published", "updated"))
            publisher = clean_html(_child_text(node, "source"))
        else:
            continue

        if not title or not link or not published or not _valid_link(link):
            continue
        items.append(
            {
                "title": title,
                "link": link,
                "summary": truncate(summary),
                "published": published,
                "publisher": publisher,
            }
        )
    return items


def select_recent(items: list[dict], now: datetime, hours: int) -> list[dict]:
    """保留最近 hours 小时内的条目（允许未来 1 小时的时钟偏差）。"""
    cutoff = now - timedelta(hours=hours)
    latest = now + timedelta(hours=1)
    return [i for i in items if cutoff <= i["published"] <= latest]


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9一-鿿]+", "", title.lower())


def summary_is_redundant(title: str, summary: str) -> bool:
    """摘要为空、与标题相同或以标题开头时，视为没有信息量。"""
    if not summary.strip():
        return True
    summary_key = norm_title(summary)
    title_key = norm_title(title)
    return bool(title_key) and summary_key.startswith(title_key)


def dedupe_items(items: list[dict]) -> list[dict]:
    """同一链接去掉重复；同一来源的相同标题只保留一条。"""

    seen_links: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    kept: list[dict] = []
    for item in items:
        link_key = item["link"].split("#", 1)[0].strip().lower()
        title_key = (item["source"], norm_title(item["title"]))
        if link_key in seen_links or title_key in seen_titles:
            continue
        seen_links.add(link_key)
        seen_titles.add(title_key)
        kept.append(item)
    return kept


def limit_per_source(items: list[dict], cap: int) -> list[dict]:
    """按来源限制条数，避免单一媒体刷屏（输入按时间倒序时保留最新的）。"""
    counts: dict[str, int] = {}
    kept: list[dict] = []
    for item in sorted(items, key=lambda i: i["published"], reverse=True):
        source = item["source"]
        if counts.get(source, 0) >= cap:
            continue
        counts[source] = counts.get(source, 0) + 1
        kept.append(item)
    return kept


def _fmt_time(dt: datetime) -> str:
    """今天显示时分，更早的条目补上日期，避免 7 天窗口内的旧闻被误认为当天。"""
    local = dt.astimezone()
    if local.date() == datetime.now().astimezone().date():
        return local.strftime("%H:%M")
    return local.strftime("%m-%d %H:%M")


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


_CSS = """
:root{
  --bg:#f6f4ef; --surface:#ffffff; --ink:#191817; --muted:#6b675f;
  --line:#e3ded3; --accent:#b3261e; --chip:#efe9dd;
  --serif:"Noto Serif SC",Georgia,"Times New Roman",serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#151412; --surface:#1e1c19; --ink:#ece8e0; --muted:#a39d92;
         --line:#35312b; --accent:#e0574d; --chip:#2a2620; }
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
.site-header{border-bottom:1px solid var(--line);background:var(--surface);position:sticky;top:0;z-index:10}
.header-top{display:flex;justify-content:space-between;gap:12px;padding-top:10px;font-size:12px;color:var(--muted);letter-spacing:.08em}
.header-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.refresh{border:1px solid var(--accent);background:transparent;color:var(--accent);font:inherit;font-size:12px;letter-spacing:.02em;padding:3px 12px;border-radius:999px;cursor:pointer;white-space:nowrap}
.refresh:hover:not(:disabled){background:var(--accent);color:var(--bg)}
.refresh:disabled{opacity:.55;cursor:not-allowed}
.refresh-msg{font-size:11px;color:var(--muted);letter-spacing:0}
.refresh-msg.error{color:var(--accent)}
.kicker{text-transform:uppercase}
.stamp{white-space:nowrap}
.masthead{display:flex;align-items:baseline;justify-content:space-between;gap:20px;padding:6px 20px 12px}
.masthead h1{font-family:var(--serif);font-size:clamp(30px,4.6vw,46px);line-height:1.1;margin:0;letter-spacing:.02em}
.deck{font-size:12px;color:var(--muted);text-align:right;max-width:520px;margin:0}
.tabs{display:flex;gap:6px;overflow-x:auto;padding-bottom:10px;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{border:1px solid var(--line);background:transparent;color:var(--ink);font:inherit;font-size:14px;padding:6px 14px;border-radius:999px;cursor:pointer;white-space:nowrap}
.tab em{font-style:normal;color:var(--muted);font-size:12px;margin-left:4px}
.tab:hover{border-color:var(--muted)}
.tab.active{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.tab.active em{color:var(--bg);opacity:.7}
main{padding-top:22px;padding-bottom:40px}
.window-note{font-size:13px;color:var(--muted);margin:0 0 10px}
.sources{font-size:12px;color:var(--muted);margin:0 0 22px}
.sources summary{cursor:pointer;padding:2px 0;user-select:none}
.sources summary:hover{color:var(--ink)}
.sources[open] summary{margin-bottom:8px}
.status{display:flex;flex-wrap:wrap;gap:6px}
.status span{font-size:11px;padding:2px 9px;border-radius:999px;background:var(--chip);color:var(--muted)}
.status span.bad{background:transparent;border:1px dashed var(--accent);color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:18px;align-items:start}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px;display:flex;flex-direction:column;gap:8px}
.card[hidden]{display:none}
.card-meta{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
.badge{--badge:#555;background:var(--badge);color:#fff;font-weight:600;padding:1px 8px;border-radius:4px;letter-spacing:.02em}
.cat{border:1px solid var(--line);padding:0 7px;border-radius:4px}
.card-meta time{margin-left:auto;font-variant-numeric:tabular-nums}
.headline{font-family:var(--serif);font-size:19px;line-height:1.4;margin:0;font-weight:600}
.headline a{text-decoration:none}
.headline a:hover{color:var(--accent)}
.summary{font-size:13.5px;color:var(--muted);margin:0;flex:1}
.more{font-size:12px;color:var(--accent);text-decoration:none;align-self:flex-start}
.more:hover{text-decoration:underline}
.card.featured{grid-column:1/-1}
.card.featured .headline{font-size:clamp(21px,2.6vw,27px)}
.empty{text-align:center;color:var(--muted);padding:40px 0}
.archive{margin-top:44px;border-top:1px solid var(--line);padding-top:18px}
.archive h2{font-family:var(--serif);font-size:17px;margin:0 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chips a{font-size:13px;padding:4px 11px;border:1px solid var(--line);border-radius:999px;text-decoration:none;background:var(--surface)}
.chips a:hover{border-color:var(--muted)}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:12px;padding:18px 0 28px}
footer .wrap{display:flex;flex-wrap:wrap;gap:10px 24px;justify-content:space-between}
@media (max-width:640px){
  .masthead{flex-direction:column;gap:4px}
  .deck{text-align:left}
  .header-top{font-size:11px}
  .grid{grid-template-columns:1fr}
}
@media print{.tabs,.status,.more{display:none}.card{break-inside:avoid}}
"""

_JS = """
(function () {
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab'));
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var empty = document.getElementById('empty');
  function apply(cat) {
    var shown = 0;
    cards.forEach(function (card) {
      var ok = cat === 'all' || card.dataset.cat === cat;
      card.hidden = !ok;
      if (ok) shown++;
    });
    empty.hidden = shown !== 0;
    tabs.forEach(function (tab) {
      var on = tab.dataset.tab === cat;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-pressed', String(on));
    });
  }
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      apply(tab.dataset.tab);
      try { history.replaceState(null, '', '#' + tab.dataset.tab); } catch (e) {}
    });
  });
  var hash = location.hash.slice(1);
  if (hash && tabs.some(function (t) { return t.dataset.tab === hash; })) apply(hash);
})();

(function () {
  var btn = document.getElementById('refresh');
  if (!btn) return;
  var msg = document.getElementById('refresh-msg');
  if (location.protocol === 'file:') {
    btn.disabled = true;
    btn.title = '请先双击 start_server.bat 启动本地服务，再访问 http://127.0.0.1:8765/';
    if (msg) msg.textContent = '本地服务未启动';
    return;
  }
  var busy = false;
  function setMsg(text, isError) {
    if (!msg) return;
    msg.textContent = text;
    msg.classList.toggle('error', !!isError);
  }
  function fail(error) {
    busy = false;
    btn.disabled = false;
    btn.textContent = '立即更新';
    setMsg((error && error.message) || String(error), true);
  }
  function poll() {
    fetch('/api/status', { cache: 'no-store' })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        if (s.running) { setTimeout(poll, 2000); return; }
        if (s.last_ok) { location.reload(); }
        else { fail(new Error(s.last_message || '更新失败')); }
      })
      .catch(fail);
  }
  btn.addEventListener('click', function () {
    if (busy) return;
    busy = true;
    btn.disabled = true;
    btn.textContent = '更新中…';
    setMsg('正在抓取，约 20 秒…', false);
    fetch('/api/update', { method: 'POST', headers: { 'X-News-Update': '1' } })
      .then(function (r) {
        if (r.status === 202 || r.status === 409) { setTimeout(poll, 800); return; }
        throw new Error('服务返回 HTTP ' + r.status);
      })
      .catch(fail);
  });
})();
"""


def render_page(
    *,
    items: list[dict],
    statuses: list[dict],
    generated_at: datetime,
    date_label: str,
    archive_dates: list[str],
    window_note: str,
    site_title: str,
    archive_prefix: str = "archive/",
    show_update: bool = True,
) -> str:
    """生成完整的静态 HTML 页面。所有外部内容都经过转义。"""
    ordered = sorted(items, key=lambda i: i["published"], reverse=True)
    counts = {"all": len(ordered)}
    for cat in CATEGORY_ORDER:
        counts[cat] = sum(1 for i in ordered if i["category"] == cat)

    cards: list[str] = []
    for idx, item in enumerate(ordered):
        cat = item["category"]
        color = SOURCE_COLORS.get(item["source"], "#555555")
        featured = " featured" if idx == 0 else ""
        summary_html = (
            f'<p class="summary">{_esc(item["summary"])}</p>' if item["summary"] else ""
        )
        cards.append(
            f'<article class="card{featured}" data-cat="{_esc(cat)}">'
            f'<div class="card-meta"><span class="badge" style="--badge:{_esc(color)}">'
            f'{_esc(item["source"])}</span>'
            f'<span class="cat">{_esc(CATEGORY_LABELS.get(cat, cat))}</span>'
            f'<time datetime="{item["published"].astimezone().isoformat()}">'
            f'{_esc(_fmt_time(item["published"]))}</time></div>'
            f'<h2 class="headline"><a href="{_esc(item["link"])}" target="_blank" '
            f'rel="noopener noreferrer">{_esc(item["title"])}</a></h2>'
            f"{summary_html}"
            f'<a class="more" href="{_esc(item["link"])}" target="_blank" '
            f'rel="noopener noreferrer">阅读原文 ↗</a>'
            f"</article>"
        )

    tab_html = [f'<button class="tab active" data-tab="all" aria-pressed="true">全部 <em>{counts["all"]}</em></button>']
    for cat in CATEGORY_ORDER:
        tab_html.append(
            f'<button class="tab" data-tab="{cat}" aria-pressed="false">'
            f"{CATEGORY_LABELS[cat]} <em>{counts[cat]}</em></button>"
        )

    status_html = []
    for s in statuses:
        if s["ok"]:
            status_html.append(
                f'<span title="{_esc(s["name"])} · {s["count"]} 条">{_esc(s["name"])} · {s["count"]}</span>'
            )
        else:
            status_html.append(
                f'<span class="bad" title="{_esc(s["error"] or "抓取失败")}">{_esc(s["name"])} · 失败</span>'
            )

    archive_html = "".join(
        f'<a href="{_esc(archive_prefix)}{_esc(d)}.html">{_esc(d[5:])}</a>'
        for d in archive_dates
    )

    ok_sources = sum(1 for s in statuses if s["ok"])
    failed_count = sum(1 for s in statuses if not s["ok"])
    fail_note = f" · {failed_count} 个失败" if failed_count else ""
    refresh_html = (
        '<button class="refresh" id="refresh" type="button" title="重新抓取最新新闻">立即更新</button>'
        '<span class="refresh-msg" id="refresh-msg" role="status"></span>'
        if show_update
        else ""
    )
    update_time = generated_at.astimezone().strftime("%Y-%m-%d %H:%M")
    page_title = f"{site_title} · {date_label}"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_esc(page_title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header class="site-header">
  <div class="wrap header-top">
    <span class="kicker">Daily Briefing · {_esc(site_title)}</span>
    <span class="header-actions">
      {refresh_html}
      <span class="stamp">{_esc(date_label)} · 更新于 {_esc(update_time)}</span>
    </span>
  </div>
  <div class="wrap masthead">
    <h1>{_esc(site_title)}</h1>
    <p class="deck">BBC · CNN · 卫报 · 半岛电视台 · NPR · TechCrunch · The Verge · OpenAI · Anthropic · DeepMind 等</p>
  </div>
  <nav class="wrap tabs" aria-label="新闻分类">
    {"".join(tab_html)}
  </nav>
</header>
<main class="wrap">
  <p class="window-note">{_esc(window_note)} · 共 {counts["all"]} 条</p>
  <details class="sources">
    <summary>来源状态：{ok_sources}/{len(statuses)} 个来源成功{fail_note}</summary>
    <div class="status">{"".join(status_html)}</div>
  </details>
  <section class="grid">
    {"".join(cards) if cards else '<p class="empty">今天暂时没有抓取到新闻。</p>'}
  </section>
  <p class="empty" id="empty" hidden>该分类今天暂无更新。</p>
  <section class="archive">
    <h2>历史归档</h2>
    <div class="chips">{archive_html or '<span style="color:var(--muted);font-size:13px">暂无归档</span>'}</div>
  </section>
</main>
<footer>
  <div class="wrap">
    <span>数据来自各媒体公开 RSS，仅展示标题与摘要，点击“阅读原文”前往来源网站。</span>
    <span>生成于 {_esc(generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S"))}（北京时间）</span>
  </div>
</footer>
<script>{_JS}</script>
</body>
</html>
"""
