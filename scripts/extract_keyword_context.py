# -*- coding: utf-8 -*-
"""
Extract keyword-context excerpts from Wisers/慧科-style PDF clipping reports.

For each article in the PDF (article boundaries come from the PDF outline/TOC,
one entry per article, exactly matching "文章總數: N 篇"), find every run of
text that is BOTH colored red AND underlined with a red line (the highlighted
search keyword), then keep only the 3 sentences before and 3 sentences after
each keyword hit (merging overlapping windows). Everything else is discarded.

Files that have NO outline/TOC bookmarks are skipped entirely (not processed),
since article boundaries can't be reliably determined for them.

This is meant to shrink huge multi-hundred-page clipping PDFs down to just the
sentences relevant to the highlighted keywords, for RAG ingestion.

Usage:
    python extract_keyword_context.py input1.pdf input2.pdf ... --outdir out/ --format txt
    python extract_keyword_context.py --indir "811" --outdir out/ --format pdf
"""

from __future__ import annotations

import argparse
import re
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import fitz  # PyMuPDF
import jieba.analyse

RED = 0xFF0000
RED_TOL = 40  # allow slightly-off reds, just in case other files vary
HEADER_Y_MAX = 95.0   # lines whose top is above this = page header, skipped
FOOTER_Y_MIN = 783.0  # lines whose top is below this = page footer, skipped
UNDERLINE_Y_TOL = (0.0, 6.0)  # underline must sit 0-6pt below the span's baseline
CONTEXT_SENTENCES = 3  # N sentences before / after each keyword hit

SENTENCE_RE = re.compile(r"[^。！？!?]+[。！？!?]*")

# 自動關鍵字提取：每篇文章用 jieba TF-IDF 提取 N 個關鍵字
AUTO_KEYWORDS_TOP_N = 10

# ---------------------------------------------------------------------------
# 排除清單：紅字關鍵字如果「包含」以下任一模式，就視為雜訊，不算有效命中。
# 可自行新增。
# ---------------------------------------------------------------------------
EXCLUDE_PATTERNS = [
    "記者",       # 記者署名（各種格式）
    "報導",       # 報導署名
    "報道",       # 「報道」= 報導的另一寫法
    "圖/",        # 圖說來源
    "轉載",       # 「文章轉載請註明出處」
    "本報訊",     # 新聞來源
    "本報記者",   # 新聞來源
    "原文出處",   # 出處標註
    "編輯",       # 「威傳媒陳惠玲編輯」
    "整理報導",   # 「101新聞網整理報導」
    "請見文末",   # 「完整獲獎名單及獲獎亮點請見文末」
    "直擊",       # 「臺灣資安大會直擊」
    "採訪",       # 「採訪報導」
]


def is_excluded_keyword(text: str) -> bool:
    """判斷紅字內容是否為雜訊，應排除。"""
    for pat in EXCLUDE_PATTERNS:
        if pat in text:
            return True
    return False


def is_red(color: int) -> bool:
    if color == RED:
        return True
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    return r > 200 and g < RED_TOL and b < RED_TOL


def page_red_underlines(page: "fitz.Page") -> list[tuple[float, float, float, float]]:
    """Return bboxes of red horizontal line strokes on a page (candidate underlines)."""
    lines = []
    for d in page.get_drawings():
        color = d.get("color")
        if not color or len(color) < 3:
            continue
        r, g, b = color[0], color[1], color[2]
        if not (r > 0.75 and g < 0.25 and b < 0.25):
            continue
        for item in d.get("items", []):
            if item[0] == "l":  # straight line segment
                p1, p2 = item[1], item[2]
                x0, x1 = sorted((p1.x, p2.x))
                y0, y1 = sorted((p1.y, p2.y))
                if y1 - y0 <= 2.0 and x1 - x0 > 0:  # near-horizontal
                    lines.append((x0, y0, x1, y1))
        rect = d.get("rect")
        if rect is not None and rect.height <= 2.0 and rect.width > 0:
            lines.append((rect.x0, rect.y0, rect.x1, rect.y1))
    return lines


def has_underline(bbox: tuple[float, float, float, float], lines: list[tuple[float, float, float, float]]) -> bool:
    x0, _, x1, y1 = bbox
    span_w = max(x1 - x0, 1e-6)
    for lx0, ly0, lx1, _ in lines:
        if not (UNDERLINE_Y_TOL[0] - 1.0 <= ly0 - y1 <= UNDERLINE_Y_TOL[1]):
            continue
        overlap = min(x1, lx1) - max(x0, lx0)
        if overlap > 0.5 * min(span_w, max(lx1 - lx0, 1e-6)):
            return True
    return False


@dataclass
class Article:
    title: str
    start_page: int  # 0-indexed, inclusive
    end_page: int  # 0-indexed, inclusive
    text: str = ""
    keywords: list[tuple[int, int]] = field(default_factory=list)  # (start, end) offsets into text


def get_articles(doc: "fitz.Document") -> list[Article] | None:
    """Return one Article per TOC/outline entry. If the PDF has no bookmarks
    at all, fall back to treating the whole document as a single article
    (article boundaries can't be determined, so a keyword's "3 sentences
    before/after" window may cross into unrelated content)."""
    toc = doc.get_toc(simple=True)
    n_pages = len(doc)
    if not toc:
        return [Article(title=(doc.name or "document"), start_page=0, end_page=n_pages - 1)]
    articles = []
    for i, (_level, title, start_page_1idx) in enumerate(toc):
        start = max(0, start_page_1idx - 1)
        end = (toc[i + 1][2] - 1 - 1) if i + 1 < len(toc) else n_pages - 1
        end = max(start, end)
        articles.append(Article(title=title.strip(), start_page=start, end_page=end))
    return articles


def build_article_text(doc: "fitz.Document", article: Article) -> None:
    text_parts: list[str] = []
    offset = 0
    keywords: list[tuple[int, int]] = []

    for pno in range(article.start_page, article.end_page + 1):
        page = doc[pno]
        red_lines = page_red_underlines(page)
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                lbbox = line["bbox"]
                if lbbox[1] < HEADER_Y_MAX or lbbox[1] > FOOTER_Y_MIN:
                    continue
                for span in line["spans"]:
                    span_text = span["text"]
                    if not span_text:
                        continue
                    start = offset
                    text_parts.append(span_text)
                    offset += len(span_text)
                    if is_red(span["color"]) and has_underline(span["bbox"], red_lines):
                        if not is_excluded_keyword(span_text):
                            keywords.append((start, offset))
                if text_parts and not text_parts[-1].endswith((" ", "\n")):
                    text_parts.append(" ")
                    offset += 1
            if text_parts and not text_parts[-1].endswith((" ", "\n")):
                text_parts.append(" ")
                offset += 1

    article.text = "".join(text_parts)
    article.keywords = keywords


def split_sentences(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in SENTENCE_RE.finditer(text) if m.group().strip()]


def merge_windows(windows: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not windows:
        return []
    windows = sorted(windows)
    merged = [windows[0]]
    for s, e in windows[1:]:
        ls, le = merged[-1]
        if s <= le + 1:
            merged[-1] = (ls, max(le, e))
        else:
            merged.append((s, e))
    return merged


def render_excerpt(
    text: str, sentences: list[tuple[int, int]], win: tuple[int, int], keywords: list[tuple[int, int]]
) -> tuple[str, list[tuple[int, int]]]:
    """Return (plain excerpt text, [(start,end) keyword offsets local to excerpt])."""
    s_start = sentences[win[0]][0]
    s_end = sentences[win[1]][1]
    excerpt = text[s_start:s_end]
    local_kws = []
    for ks, ke in keywords:
        if ks < s_end and ke > s_start:
            local_kws.append((max(0, ks - s_start), min(len(excerpt), ke - s_start)))
    excerpt_stripped = excerpt.strip()
    lead_trim = len(excerpt) - len(excerpt.lstrip())
    n = len(excerpt_stripped)
    local_kws = [
        (max(0, s - lead_trim), min(n, max(0, e - lead_trim)))
        for s, e in local_kws
    ]
    local_kws = [(s, e) for s, e in local_kws if e > s]
    return excerpt_stripped, local_kws


def split_segments(text: str, spans: list[tuple[int, int]]) -> list[tuple[bool, str]]:
    """Split text into (is_keyword, segment) pieces at the given non-overlapping offsets."""
    segments = []
    pos = 0
    for s, e in sorted(spans):
        s, e = max(pos, s), max(pos, e)
        if s > pos:
            segments.append((False, text[pos:s]))
        if e > s:
            segments.append((True, text[s:e]))
        pos = e
    if pos < len(text):
        segments.append((False, text[pos:]))
    return segments


def process_article(article: Article) -> list[tuple[str, list[tuple[int, int]]]]:
    """Return the full article text with keyword offsets if it has any keywords.
    If no keywords, return empty (article will be skipped)."""
    if not article.keywords:
        return []
    # Return the entire article text with all keyword positions
    text = article.text.strip()
    if not text:
        return []
    # Adjust keyword offsets for any leading whitespace stripped
    lead_trim = len(article.text) - len(article.text.lstrip())
    local_kws = [
        (max(0, ks - lead_trim), min(len(text), ke - lead_trim))
        for ks, ke in article.keywords
    ]
    local_kws = [(s, e) for s, e in local_kws if e > s]
    return [(text, local_kws)]


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def extract_auto_keywords(text: str, top_n: int = AUTO_KEYWORDS_TOP_N) -> list[str]:
    """用 jieba TextRank 提取關鍵字（預設只取名詞/動詞，速度較快）。"""
    clean = re.sub(r"[【】]", "", text)
    if not clean.strip():
        return []
    keywords = jieba.analyse.textrank(clean, topK=top_n * 3, withWeight=False)
    stopwords = {
        "因為", "所以", "但是", "雖然", "而且", "如果", "然而", "因此",
        "不過", "或者", "以及", "並且", "由於", "對於", "關於", "透過",
        "進行", "表示", "指出", "認為", "強調", "提到", "希望", "期待",
        "可以", "能夠", "已經", "目前", "未來", "今年", "今日", "昨日",
        "方面", "部分", "方式", "情況", "問題", "過程", "其中", "相關",
        "持續", "推動", "提供", "辦理", "規劃", "包括", "成為", "打造",
        "需要", "應該", "必須", "這個", "那個", "他們", "我們", "大家",
    }
    filtered = [
        kw for kw in keywords
        if len(kw) >= 2 and not kw.isdigit() and kw not in stopwords
    ]
    return filtered[:top_n]


def write_txt(out_path: Path, pdf_name: str, total: int, with_kw: int, data: list[tuple[str, list]]) -> None:
    lines = [f"{pdf_name}", f"共 {total} 篇文章，其中 {with_kw} 篇含標記關鍵字（紅字+紅底線）", ""]
    for idx, (title, excerpts) in enumerate(data, 1):
        lines.append(f"■ [{idx}] {title}")
        lines.append("")
        for excerpt, kws in excerpts:
            # TXT 輸出不加【】標記，直接輸出純文字
            lines.append(excerpt)
            lines.append("")
        lines.append("-" * 40)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_md(out_path: Path, pdf_name: str, total: int, with_kw: int, data: list[tuple[str, list]]) -> None:
    chunks = [f"# {pdf_name}", "", f"共 {total} 篇文章，其中 {with_kw} 篇含標記關鍵字（紅字+紅底線）", ""]
    article_blocks = []
    for title, excerpts in data:
        body_parts = []
        for excerpt, kws in excerpts:
            marked = "".join(
                f"**{seg}**" if is_kw else seg for is_kw, seg in split_segments(excerpt, kws)
            )
            body_parts.append(marked)
        article_blocks.append(f"## {title}\n\n" + "\n\n".join(body_parts) + "\n")
    chunks.append("\n---\n\n".join(article_blocks))
    out_path.write_text("\n".join(chunks), encoding="utf-8")


# Non-embedded CID fonts (e.g. reportlab's built-in "MSung-Light") render as
# mojibake in most viewers other than Adobe Acrobat, because they rely on the
# viewer already having that exact font installed. Embed a real TTF instead.
_CJK_FONT_CANDIDATES = [
    (r"C:\Windows\Fonts\msjh.ttc", 0),   # Microsoft JhengHei (Traditional Chinese)
    (r"C:\Windows\Fonts\mingliu.ttc", 0),  # MingLiU fallback
    (r"C:\Windows\Fonts\kaiu.ttf", None),  # DFKai-SB fallback
]
PDF_FONT_NAME = "CJK"
_PDF_FONT_REGISTERED = False


def _ensure_pdf_font() -> None:
    global _PDF_FONT_REGISTERED
    if _PDF_FONT_REGISTERED:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path, subfont_index in _CJK_FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        try:
            kwargs = {"subfontIndex": subfont_index} if subfont_index is not None else {}
            pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, path, **kwargs))
            _PDF_FONT_REGISTERED = True
            return
        except Exception:
            continue
    raise RuntimeError(
        "No Traditional Chinese TrueType font found to embed. "
        "Install one (e.g. Microsoft JhengHei) or edit _CJK_FONT_CANDIDATES."
    )


def write_pdf(out_path: Path, pdf_name: str, total: int, with_kw: int, data: list[tuple[str, list]]) -> None:
    _ensure_pdf_font()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    title_style = ParagraphStyle("cn_title", fontName=PDF_FONT_NAME, fontSize=15, leading=20, spaceAfter=6)
    heading_style = ParagraphStyle("cn_heading", fontName=PDF_FONT_NAME, fontSize=12, leading=16, spaceBefore=10, spaceAfter=6)
    body_style = ParagraphStyle("cn_body", fontName=PDF_FONT_NAME, fontSize=10, leading=15, spaceAfter=8)

    story = [
        Paragraph(xml_escape(pdf_name), title_style),
        Paragraph(xml_escape(f"共 {total} 篇文章，其中 {with_kw} 篇含標記關鍵字（紅字+紅底線）"), body_style),
        Spacer(1, 8),
    ]
    for title, excerpts in data:
        story.append(Paragraph(xml_escape(title), heading_style))
        for excerpt, kws in excerpts:
            marked = "".join(
                f'<font color="red">{xml_escape(seg)}</font>' if is_kw else xml_escape(seg)
                for is_kw, seg in split_segments(excerpt, kws)
            )
            story.append(Paragraph(marked, body_style))
        story.append(HRFlowable(width="100%", color="#cccccc"))
        story.append(Spacer(1, 6))

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, topMargin=36, bottomMargin=36, leftMargin=42, rightMargin=42)
    doc.build(story)


def write_xlsx(out_path: Path, pdf_name: str, total: int, with_kw: int, data: list[tuple[str, list]]) -> None:
    """輸出為 Excel 檔，每篇文章一行，欄位：篇號、標題、全文。"""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "文章"

    # 表頭
    ws.append(["篇號", "標題", "全文內容"])

    for idx, (title, excerpts) in enumerate(data, 1):
        # 全文（保留【】標記）
        marked_text = ""
        for excerpt, kws in excerpts:
            marked_text += "".join(
                f"【{seg}】" if is_kw else seg for is_kw, seg in split_segments(excerpt, kws)
            ) + "\n"

        ws.append([idx, title, marked_text.strip()])

    # 調整欄寬
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 80

    wb.save(str(out_path))


WRITERS = {"txt": write_txt, "md": write_md, "pdf": write_pdf, "xlsx": write_xlsx}


def process_pdf(path: Path, outdir: Path, fmt: str) -> tuple[int, int]:
    doc = fitz.open(path)
    if not doc.get_toc(simple=True):
        print(f"WARN（無書籤/TOC，整份當一篇文章處理，前後文可能跨到不相關內容）: {path.name}")
    articles = get_articles(doc)

    data = []
    n_with_kw = 0
    for article in articles:
        build_article_text(doc, article)
        excerpts = process_article(article)
        if excerpts:
            data.append((article.title, excerpts))
            n_with_kw += 1
    doc.close()

    out_path = outdir / (path.stem + "." + fmt)
    WRITERS[fmt](out_path, path.name, len(articles), n_with_kw, data)
    return len(articles), n_with_kw


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdfs", nargs="*", type=Path, help="PDF files to process")
    ap.add_argument("--indir", type=Path, help="Process all *.pdf files in this directory")
    ap.add_argument("--outdir", type=Path, required=True, help="Directory to write excerpts to")
    ap.add_argument("--format", choices=["txt", "md", "pdf", "xlsx"], default="txt", help="Output file format (default: txt)")
    ap.add_argument("--workers", type=int, default=0,
                    help="並行處理的 worker 數量（預設 0 = CPU 核心數）")
    args = ap.parse_args()

    pdfs = list(args.pdfs)
    if args.indir:
        pdfs += sorted(args.indir.glob("*.pdf"))
    if not pdfs:
        print("No PDFs given. Use positional args or --indir.", file=sys.stderr)
        sys.exit(1)

    args.outdir.mkdir(parents=True, exist_ok=True)

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor, as_completed

    n_workers = args.workers if args.workers > 0 else min(multiprocessing.cpu_count(), 8)
    print(f"Processing {len(pdfs)} PDFs with {n_workers} workers...\n")

    total_in = total_out = 0
    done_count = 0

    if n_workers == 1:
        # 單進程模式（方便 debug）
        for pdf in pdfs:
            n_articles, n_kw = process_pdf(pdf, args.outdir, args.format)
            in_size = pdf.stat().st_size
            out_size = (args.outdir / (pdf.stem + "." + args.format)).stat().st_size
            total_in += in_size
            total_out += out_size
            done_count += 1
            print(f"[{done_count}/{len(pdfs)}] {pdf.name}: {n_articles} articles, {n_kw} with keywords | "
                  f"{in_size/1024:.0f} KB -> {out_size/1024:.0f} KB")
    else:
        # 多進程並行
        futures = {}
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            for pdf in pdfs:
                future = executor.submit(process_pdf, pdf, args.outdir, args.format)
                futures[future] = pdf

            for future in as_completed(futures):
                pdf = futures[future]
                try:
                    n_articles, n_kw = future.result()
                    in_size = pdf.stat().st_size
                    out_size = (args.outdir / (pdf.stem + "." + args.format)).stat().st_size
                    total_in += in_size
                    total_out += out_size
                    done_count += 1
                    print(f"[{done_count}/{len(pdfs)}] {pdf.name}: {n_articles} articles, {n_kw} with keywords | "
                          f"{in_size/1024:.0f} KB -> {out_size/1024:.0f} KB")
                except Exception as e:
                    done_count += 1
                    print(f"[{done_count}/{len(pdfs)}] ERROR {pdf.name}: {e}")

    print(f"\nTOTAL: {total_in/1024/1024:.1f} MB -> {total_out/1024/1024:.2f} MB "
          f"({100*total_out/max(total_in,1):.2f}%)")


if __name__ == "__main__":
    main()
