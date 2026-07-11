"""
오늘의 브리핑을 정적 HTML 페이지로 렌더링하는 모듈

카카오톡 메시지의 구조화된 link 필드는 사전 등록된 도메인만 허용하므로,
매일 바뀌는 언론사 링크를 직접 담을 수 없다. 대신 이 페이지 하나를
GitHub Pages로 배포해 카카오 메시지에는 이 페이지 링크만 담고,
실제 기사 링크는 이 페이지의 일반 <a> 태그로 제공한다.
"""
from html import escape
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from ecos_client import EcosSnapshot, Indicator
from formatter import KST, CategoryBriefing
from news_service import Article

# 코스피/코스닥/환율 변동률이 이 값(%) 이상이면 강조 표시합니다.
_ECOS_EMPHASIZE_THRESHOLD = 1.0

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{
    --bg: #f4f4f6;
    --card-bg: #ffffff;
    --text: #1c1c1e;
    --muted: #70707a;
    --font-serif: Georgia, "Noto Serif KR", "Nanum Myeongjo", serif;
    --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
    --font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 28px 16px 56px;
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-sans);
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; }}

  .masthead {{
    text-align: center;
    margin-bottom: 32px;
  }}
  .masthead h1 {{
    font-family: var(--font-serif);
    font-size: 30px;
    margin: 0 0 10px;
    letter-spacing: -0.02em;
  }}
  .masthead .meta {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    flex-wrap: wrap;
  }}
  .masthead .date {{
    font-family: var(--font-mono);
    color: var(--muted);
    font-size: 13px;
  }}
  .masthead .badge {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: #fff;
    background: #1c1c1e;
    padding: 3px 10px;
    border-radius: 999px;
  }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
  }}
  @media (max-width: 760px) {{
    .grid {{ grid-template-columns: 1fr; }}
  }}

  .column h2 {{
    font-size: 16px;
    margin: 0 0 14px;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--accent);
    color: var(--accent);
  }}

  .card {{
    background: var(--card-bg);
    border-left: 4px solid var(--accent);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 10px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  }}
  .card.headline {{
    border-left-width: 6px;
    background: color-mix(in srgb, var(--accent) 8%, white);
  }}
  .card .badge-headline {{
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    background: var(--accent);
    padding: 2px 7px;
    border-radius: 4px;
    margin-bottom: 6px;
    letter-spacing: 0.04em;
  }}
  .card .badge-source {{
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--muted);
    background: rgba(0,0,0,0.05);
    padding: 2px 7px;
    border-radius: 4px;
    margin-bottom: 6px;
  }}
  .card a.title {{
    display: block;
    color: var(--text);
    text-decoration: none;
    font-family: var(--font-sans);
    font-weight: 600;
    font-size: 14.5px;
    line-height: 1.4;
    margin-bottom: 6px;
  }}
  .card.headline a.title {{
    font-family: var(--font-serif);
    font-weight: 700;
    font-size: 17px;
  }}
  .card a.title:hover {{ text-decoration: underline; }}
  .card p.description {{
    margin: 0 0 8px;
    color: #444;
    font-size: 13px;
    line-height: 1.5;
  }}
  .card .source-line {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--muted);
  }}
  .empty {{ color: var(--muted); font-size: 13px; }}

  .stat-block {{
    background: var(--card-bg);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 14px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
  }}
  .stat-row {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 5px 0;
    border-bottom: 1px solid #eee;
  }}
  .stat-row:last-of-type {{ border-bottom: none; }}
  .stat-row.emphasize {{
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    border-radius: 6px;
    padding: 5px 6px;
    font-weight: 700;
  }}
  .stat-label {{ font-family: var(--font-sans); font-size: 12.5px; color: #444; }}
  .stat-value {{ font-family: var(--font-mono); font-size: 13.5px; margin-left: auto; margin-right: 8px; }}
  .stat-change {{ font-family: var(--font-mono); font-size: 12px; }}
  .stat-change.up {{ color: #d92626; }}
  .stat-change.down {{ color: #2563d9; }}
  .stat-source {{
    font-family: var(--font-mono);
    font-size: 10px;
    color: var(--muted);
    margin-top: 8px;
  }}

  footer {{ margin-top: 40px; color: #a1a1a6; font-size: 12px; text-align: center; font-family: var(--font-mono); }}
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <h1>오늘의 브리핑</h1>
    <div class="meta">
      <span class="date">{today}</span>
      <span class="badge">09:00 KST 갱신</span>
    </div>
  </header>
  <main class="grid">
    {columns}
  </main>
  <footer>매일 아침 자동 생성됩니다.</footer>
</div>
</body>
</html>
"""


def _source_domain(url: str) -> str:
    netloc = urlparse(url).netloc
    return netloc[4:] if netloc.startswith("www.") else netloc


def _source_line(article: Article) -> str:
    domain = _source_domain(article.link)
    time_str = article.published_at.astimezone(KST).strftime("%H:%M")
    return f"{domain} · {time_str}"


def _render_card(article: Article, is_headline: bool, headline_source: str = "") -> str:
    title = escape(article.title)
    link = escape(article.link, quote=True)
    description = escape(article.description) if article.description else ""
    description_html = f'<p class="description">{description}</p>' if description else ""
    if is_headline:
        badge_html = f'<span class="badge-headline">{escape(headline_source)}</span>'
    else:
        badge_html = '<span class="badge-source">언론사</span>'
    card_class = "card headline" if is_headline else "card"
    return (
        f'<div class="{card_class}">{badge_html}'
        f'<a class="title" href="{link}" target="_blank" rel="noopener">{title}</a>'
        f"{description_html}"
        f'<div class="source-line">{escape(_source_line(article))}</div>'
        f"</div>"
    )


def _format_stat_value(indicator: Indicator) -> str:
    if "환율" in indicator.label:
        return f"{indicator.value:,.1f}원"
    if "기준금리" in indicator.label:
        return f"{indicator.value:.2f}%"
    return f"{indicator.value:,.2f}"


def _render_stat_row(indicator: Indicator) -> str:
    emphasize = indicator.change_pct is not None and abs(indicator.change_pct) >= _ECOS_EMPHASIZE_THRESHOLD
    row_class = "stat-row emphasize" if emphasize else "stat-row"

    change_html = ""
    if indicator.change_pct is not None:
        direction = "up" if indicator.change_pct >= 0 else "down"
        sign = "+" if indicator.change_pct >= 0 else ""
        change_html = f'<span class="stat-change {direction}">{sign}{indicator.change_pct:.2f}%</span>'

    return (
        f'<div class="{row_class}">'
        f'<span class="stat-label">{escape(indicator.label)}</span>'
        f'<span class="stat-value">{escape(_format_stat_value(indicator))}</span>'
        f"{change_html}"
        f"</div>"
    )


def _render_stat_block(snapshot: EcosSnapshot) -> str:
    indicators = (snapshot.kospi, snapshot.kosdaq, snapshot.usd_krw, snapshot.base_rate)
    rows = "".join(_render_stat_row(i) for i in indicators)
    as_of = snapshot.kospi.as_of
    as_of_fmt = f"{as_of[:4]}-{as_of[4:6]}-{as_of[6:]}" if len(as_of) == 8 else as_of
    return f'<div class="stat-block">{rows}<div class="stat-source">한국은행(ECOS) 공식 통계 · {escape(as_of_fmt)} 기준</div></div>'


def _render_column(briefing: CategoryBriefing, ecos_snapshot: Optional[EcosSnapshot]) -> str:
    label = escape(briefing.category.label)
    color = escape(briefing.category.color, quote=True)

    stat_html = ""
    if briefing.category.key == "economy" and ecos_snapshot is not None:
        stat_html = _render_stat_block(ecos_snapshot)

    if briefing.headline is None:
        body = '<p class="empty">관련 소식을 찾지 못했습니다.</p>'
    else:
        cards = [_render_card(briefing.headline, is_headline=True, headline_source=briefing.headline_source)]
        cards += [_render_card(article, is_headline=False) for article in briefing.rest]
        body = "\n".join(cards)

    return f'<section class="column" style="--accent: {color}"><h2>{label}</h2>{stat_html}{body}</section>'


def render_page(briefings: List[CategoryBriefing], today: str, ecos_snapshot: Optional[EcosSnapshot] = None) -> str:
    """카테고리별 헤드라인/기사 목록과 경제 지표를 담은 단일 HTML 페이지 문자열을 생성합니다."""
    columns = "\n".join(_render_column(b, ecos_snapshot) for b in briefings)
    return _PAGE_TEMPLATE.format(title=f"오늘의 브리핑 - {today}", today=escape(today), columns=columns)


def write_page(html: str, output_path: Path = Path("docs/index.html")) -> None:
    """생성된 HTML을 파일로 저장합니다 (상위 폴더가 없으면 생성)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
