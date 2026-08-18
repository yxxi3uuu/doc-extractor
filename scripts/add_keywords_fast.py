# -*- coding: utf-8 -*-
"""
極速版：對已提取的 txt 加上 jieba 自動關鍵字，輸出 txt + xlsx。
使用 jieba.cut 精確模式 + 詞頻統計，不做詞性標注，速度極快。

Usage:
    python add_keywords_fast.py --indir extracted --outdir with_keywords --format both
"""

import argparse
import re
import sys
from pathlib import Path

import jieba
from tqdm import tqdm

AUTO_KEYWORDS_TOP_N = 10

ARTICLE_SEPARATOR = re.compile(r"^-{10,}$", re.MULTILINE)
ARTICLE_TITLE_RE = re.compile(r"^■\s*(?:\[\d+\]\s*)?(.+)$", re.MULTILINE)

STOPWORDS = {
    "因為", "所以", "但是", "雖然", "而且", "如果", "然而", "因此",
    "不過", "或者", "以及", "並且", "由於", "對於", "關於", "透過",
    "進行", "表示", "指出", "認為", "強調", "提到", "希望", "期待",
    "可以", "能夠", "已經", "目前", "未來", "今年", "今日", "昨日",
    "方面", "部分", "方式", "情況", "問題", "過程", "其中", "相關",
    "持續", "推動", "提供", "辦理", "規劃", "包括", "成為", "打造",
    "需要", "應該", "必須", "這個", "那個", "他們", "我們", "大家",
    # 量詞/數字/金額
    "萬元", "美元", "億元",
    # URL 殘渣
    "e5%", "e6%", "e7%", "e8%", "e9%",
    "E5%", "E6%", "E7%", "E8%", "E9%",
    "https", "com", "tw", "80%", "www", "81%", "b0%",
    # 代詞/虛詞
    "自己", "一個", "而是",
    # 太泛的動詞/形容詞
    "發展", "合作", "活動", "提升", "協助", "整合", "支持", "成長",
    "成果", "展現", "分享", "可能",
    # 虛詞/無意義
    "不是", "共同", "重要", "關鍵", "基礎", "核心", "穩定",
    "投入", "建立", "使用", "成功", "最高",
    # 身份/職稱
    "記者", "校長", "董事", "代表", "教授", "市長", "縣長", "同仁", "人員",
    # 太泛的名詞
    "中心", "計畫", "服務", "方案", "制度", "資源", "系統", "機會", "領域",
    "時間", "年度", "行動", "行政", "報告",
    # 文字殘渣
    "文字", "報導", "報名", "現場", "快照",
    # 斷詞殘渣
    "半導", "職者", "中小",
    # 時間/程度/無意義短詞
    "天前", "中市", "職得", "期間", "必然", "今天", "以上",
    "以下", "之間", "左右", "目標", "透過", "經過", "之後",
    "之前", "當中", "至少", "至今", "近年", "當天", "去年",
    # 職稱/身份（補充）
    "執行長", "理事長", "秘書長", "副院長", "院長", "局長", "處長",
    "主任", "總經理", "副總", "總監",
    # 大學/機構名（對判斷文章主題沒幫助）
    "大學", "元智大學", "中央大學", "庚大學", "長庚大學", "科大",
    "學院", "研究所",
    # 其他無意義
    "非紅供", "中央",
    # 斷詞殘渣/亂切
    "新小龍", "超過出現理器", "職民眾",
    # 太泛的人稱
    "朋友", "民眾", "老師", "家長", "業者", "廠商", "夥伴",
    "長官", "來賓", "嘉賓", "同學", "師生",
    # 太泛的動詞（補充）
    "參加", "參與", "辦理", "舉辦", "加入", "帶來", "完成",
    "進入", "開始", "結合", "實現", "強化", "促進", "鼓勵",
    "期許", "呼籲", "歡迎", "感謝", "肯定",
    # 太泛的形容/副詞
    "積極", "優質", "豐富", "特別", "更多", "不同", "許多",
    "各項", "全面", "深入", "充分", "有效", "具體", "完善",
    # 太泛的名詞（補充）
    "單位", "項目", "內容", "對象", "主題", "特色", "優勢",
    "目的", "成效", "經驗", "意見", "建議", "觀點",
}


def extract_auto_keywords(text: str, top_n: int = AUTO_KEYWORDS_TOP_N) -> list[str]:
    """使用極速 jieba.cut + 詞頻統計抽取關鍵字"""
    clean = re.sub(r"[【】]", "", text)
    if not clean.strip():
        return []

    word_count = {}
    # 使用一般分詞 (精確模式)，速度極快
    for word in jieba.cut(clean):
        word = word.strip()
        if len(word) < 2 or word.isdigit() or word in STOPWORDS:
            continue
        # 排除結尾是「元」的金額詞（萬元、美元、億元、千元...）
        if word.endswith("元"):
            continue
        # 排除純百分比（如 82%、90%...）
        if word.endswith("%"):
            continue
        # 排除結尾是連接詞/虛字的斷詞殘渣（如「勞工及」「產業與」）
        if word[-1] in "及與和或之等的了在為從到並且而是":
            continue
        # 排除開頭是連接詞/虛字的斷詞殘渣（如「及產業」「與技術」）
        if word[0] in "及與和或之等的了在為從到並且而是":
            continue
        # 排除含「大學」的詞（各種大學名）
        if "大學" in word:
            continue
        # 排除長度超過 6 個字的詞（通常是亂切殘渣）
        if len(word) > 6:
            continue
        word_count[word] = word_count.get(word, 0) + 1

    sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:top_n]]


def parse_txt(text: str) -> list[tuple[str, str]]:
    sections = ARTICLE_SEPARATOR.split(text)
    articles = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        m = ARTICLE_TITLE_RE.search(section)
        if m:
            title = m.group(1).strip()
            body = section[m.end():].strip()
        else:
            if len(section) > 200:
                title = section[:50].replace("\n", " ").strip()
                body = section
            else:
                continue
        if body:
            articles.append((title, body))
    return articles


def write_txt_with_keywords(out_path: Path, source_name: str,
                            articles: list[tuple[str, str, list[str]]]) -> None:
    lines = [f"{source_name}", f"共 {len(articles)} 篇文章", ""]
    for idx, (title, body, kws) in enumerate(articles, 1):
        lines.append(f"■ [{idx}] {title}")
        if kws:
            lines.append(f"[關鍵字] {', '.join(kws)}")
        lines.append("")
        lines.append(body)
        lines.append("")
        lines.append("-" * 40)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_xlsx_with_keywords(out_path: Path, source_name: str,
                             articles: list[tuple[str, str, list[str]]]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "文章"
    ws.append(["篇號", "標題", "自動關鍵字(jieba)", "全文內容"])

    for idx, (title, body, kws) in enumerate(articles, 1):
        ws.append([idx, title, ", ".join(kws), body])

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 40
    ws.column_dimensions["C"].width = 50
    ws.column_dimensions["D"].width = 80
    wb.save(str(out_path))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="極速版：對已提取的 txt 加上 jieba 自動關鍵字"
    )
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--indir", type=Path, help="讀取此資料夾下所有 .txt 檔")
    ap.add_argument("--outdir", type=Path, required=True, help="輸出資料夾")
    ap.add_argument("--format", choices=["txt", "xlsx", "both"], default="both",
                    help="輸出格式（預設 both）")
    args = ap.parse_args()

    files = list(args.files)
    if args.indir:
        files += sorted(args.indir.glob("*.txt"))
    if not files:
        print("沒有指定檔案。", file=sys.stderr)
        sys.exit(1)

    args.outdir.mkdir(parents=True, exist_ok=True)

    # 預熱字典
    list(jieba.cut("測試文字"))

    print(f"🚀 開始極速處理 {len(files)} 個檔案...\n")

    for f in tqdm(files, desc="總進度", unit="檔"):
        raw = f.read_text(encoding="utf-8")
        articles_raw = parse_txt(raw)
        articles_with_kw = [(t, b, extract_auto_keywords(b)) for t, b in articles_raw]

        if args.format in ("txt", "both"):
            write_txt_with_keywords(args.outdir / (f.stem + "_kw.txt"), f.name, articles_with_kw)
        if args.format in ("xlsx", "both"):
            write_xlsx_with_keywords(args.outdir / (f.stem + "_kw.xlsx"), f.name, articles_with_kw)

    print(f"\n✅ 全部 {len(files)} 個檔案處理完成！")


if __name__ == "__main__":
    main()
