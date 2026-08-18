# -*- coding: utf-8 -*-
"""
filter_articles.py
讀取輸入資料夾內所有 .txt 新聞檔，依規則刪除特定類別文章，
把過濾後結果寫到輸出資料夾。

規則優先順序：
  第一步（標題關鍵字）：暑期寒假工讀 → 房仲房地產 → 競選政見 → 軟性離題新聞
  第二步（內文密度）：廠商產品廣告（僅未被第一步命中的文章才進入）

Usage:
    python filter_articles.py --indir deduped --outdir filtered
"""

import argparse
import csv
import re
import sys
from pathlib import Path

# ===========================================================================
# 第一步：標題關鍵字字典（依優先順序排列）
# ===========================================================================

# 暑期/寒假工讀類（最高優先，命中一個即刪）
KW_PARTTIME = [
    "暑期工讀", "暑期打工", "暑假打工", "工讀生", "暑期實習",
    "寒假打工", "寒假工讀", "寒期打工",
]

# 房仲/房地產類（命中一個即刪）
KW_REALESTATE = [
    "房仲", "房地產", "不動產", "建案", "廠辦", "售屋", "租屋",
    "戴德梁行", "仲量聯行", "預售屋", "房價",
]

# 競選/政見/政策宣示類（獨立開關控制，命中一個即刪）
KW_POLITICS = [
    "競選", "政見", "候選人", "選舉", "造勢", "投票",
    "選戰", "參選", "連任", "施政", "政見發表",
]

# 軟性/離題新聞排除（命中一個即刪）
KW_OFFTOPIC = [
    "緝毒犬", "寵物", "狗狗", "明星", "八卦",
    "離婚", "臉書帳號", "演唱會",
]

# 銀行/信用卡/金控類（需命中兩個以上才刪）
KW_BANK = [
    "信用卡", "卡友", "刷卡回饋", "辦卡", "紅利點數",
    "分期0利率", "金控", "獲利王", "金控榜單",
]

# ===========================================================================
# 第二步：廠商產品廣告（內文密度判定）
# ===========================================================================

# 規格類特徵詞
AD_SPEC_WORDS = [
    "處理器", "晶片組", "螢幕", "面板", "解析度", "電池", "續航",
    "記憶體", "鏡頭", "相機", "充電", "機身", "重量", "尺寸",
    "搭載", "規格", "效能", "散熱", "按鍵",
]

# 行銷類特徵詞
AD_MARKETING_WORDS = [
    "售價", "建議售價", "上市", "開賣", "預購", "購買", "選購",
    "優惠", "促銷", "折扣", "限量", "限時", "旗艦", "新色",
    "版本", "入手", "到手價", "官網", "門市",
]

# 判定門檻
AD_THRESHOLD = 6

# 正文截斷標記：遇到這些標記時，只取標記之前的正文做判定
# （避免「相關報導」段落汙染主題文章）
CONTENT_CUTOFF_PATTERNS = [
    r"更多.*報導", r"相關內容", r"相關新聞", r"延伸閱讀",
    r"【推薦", r"看更多", r"其他人也在看",
]

# 主題保護清單：正文前 30% 命中這些詞 → 即使後段有規格詞也不判為廣告
# （僅作用於第二步，不影響第一步任何規則）
TOPIC_PROTECT_WORDS = [
    "人才", "培育", "產學", "競賽", "大賞", "年會", "獎學金",
    "政策", "部長", "總統", "勞動部", "教育部", "分署", "工研院", "國科會",
]

# ===========================================================================
# 開關設定
# ===========================================================================
FILTER_POLITICS = True    # True = 刪除政治相關；False = 保留
REQUIRE_TWO_HITS = True   # True = 銀行信用卡金控類需命中兩個以上才刪

# ===========================================================================
# 第一步類別定義（按優先順序排列）
# (類別名稱, 關鍵字清單, 是否需要兩次命中, 是否受政治開關控制)
# ===========================================================================
TITLE_CATEGORIES_ORDERED = [
    ("暑期寒假工讀", KW_PARTTIME, False, False),
    ("房仲房地產", KW_REALESTATE, False, False),
    ("銀行信用卡金控", KW_BANK, REQUIRE_TWO_HITS, False),
    ("競選政見", KW_POLITICS, False, True),       # 受 FILTER_POLITICS 開關控制
    ("軟性離題新聞", KW_OFFTOPIC, False, False),
]

# ===========================================================================
# 正規表達式
# ===========================================================================
ARTICLE_RE = re.compile(r"^■\s*\[(\d+)\]\s*(.+)$", re.MULTILINE)
SEPARATOR_RE = re.compile(r"^-{10,}$", re.MULTILINE)

# 編譯截斷正規式
_CUTOFF_RE = re.compile(
    "|".join(CONTENT_CUTOFF_PATTERNS),
    re.IGNORECASE
)


# ===========================================================================
# 工具函數
# ===========================================================================

def normalize_title(title: str) -> str:
    """正規化標題：去空白（含全形）、去標點。"""
    title = re.sub(r"[\s\u3000]+", "", title)
    title = re.sub(r"[，。！？、；：「」『』（）【】\-—…·．/\\|｜×#&~～《》〈〉()\[\]]", "", title)
    return title


def check_title_step1(title: str) -> tuple[str, str] | None:
    """
    第一步：依優先順序檢查標題關鍵字。
    命中即回傳 (類別名, 命中關鍵字)，不再往下判。
    回傳 None 表示未命中任何標題規則。
    """
    norm = normalize_title(title)
    title_lower = title.lower()
    norm_lower = norm.lower()

    for cat_name, kw_list, need_two, is_political in TITLE_CATEGORIES_ORDERED:
        # 跳過被關閉的政治類
        if is_political and not FILTER_POLITICS:
            continue

        # 收集命中的關鍵字
        hits = []
        for kw in kw_list:
            kw_lower = kw.lower()
            if kw in title or kw in norm or kw_lower in title_lower or kw_lower in norm_lower:
                hits.append(kw)

        if need_two:
            if len(hits) >= 2:
                return (cat_name, " + ".join(hits))
        else:
            if hits:
                return (cat_name, hits[0])

    return None


def extract_main_body(content: str) -> str:
    """
    從文章內容中擷取正文主體，截斷「相關報導」等段落。
    取第一個截斷標記之前的正文。
    """
    m = _CUTOFF_RE.search(content)
    if m:
        return content[:m.start()]
    return content


def check_topic_protection(main_body: str) -> bool:
    """
    檢查正文前 30%（導言）是否命中主題保護詞。
    回傳 True = 觸發保護（不判為廣告）。
    """
    # 取前 30% 正文
    lead_end = max(1, int(len(main_body) * 0.3))
    lead = main_body[:lead_end]

    for word in TOPIC_PROTECT_WORDS:
        if word in lead:
            return True
    return False


def check_ad_by_content(content: str) -> tuple[bool, int, int, int, list[str], int, bool]:
    """
    第二步：依內文特徵詞密度判斷是否為產品推廣文。
    只採計正文主體（截斷相關報導後）。
    
    回傳: (是否為廣告, 規格命中數, 行銷命中數, 總命中數, 命中詞列表, 正文長度, 是否觸發主題保護)
    """
    # 擷取正文主體
    main_body = extract_main_body(content)
    body_len = len(main_body)

    # 檢查主題保護
    protected = check_topic_protection(main_body)
    if protected:
        # 觸發保護 → 不判為廣告
        return (False, 0, 0, 0, [], body_len, True)

    # 統計不重複命中
    spec_hits = [w for w in AD_SPEC_WORDS if w in main_body]
    marketing_hits = [w for w in AD_MARKETING_WORDS if w in main_body]

    spec_count = len(spec_hits)
    marketing_count = len(marketing_hits)
    total_hits = spec_count + marketing_count
    all_hit_words = spec_hits + marketing_hits

    # 判定條件 1：總命中數 >= 門檻
    if total_hits >= AD_THRESHOLD:
        return (True, spec_count, marketing_count, total_hits, all_hit_words, body_len, False)

    # 判定條件 2（強訊號）：規格>=3 且 行銷>=2
    if spec_count >= 3 and marketing_count >= 2:
        return (True, spec_count, marketing_count, total_hits, all_hit_words, body_len, False)

    return (False, spec_count, marketing_count, total_hits, all_hit_words, body_len, False)


def parse_articles(text: str) -> list[tuple[str, str, str]]:
    """
    解析 txt 檔，回傳 [(編號, 標題, 整篇內容含標題行), ...]
    """
    sections = SEPARATOR_RE.split(text)
    articles = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        m = ARTICLE_RE.search(section)
        if m:
            num = m.group(1)
            title = m.group(2).strip()
            articles.append((num, title, section))
        else:
            # 非文章段落（檔頭），保留但不檢查
            articles.append(("0", "__HEADER__", section))

    return articles


# ===========================================================================
# 主程式
# ===========================================================================

def process_file(path: Path, outdir: Path, log_rows: list,
                 removed_ad_articles: list, removed_offtopic_articles: list) -> dict:
    """處理單一 txt 檔。"""
    raw = path.read_text(encoding="utf-8")
    articles = parse_articles(raw)

    stats = {"total": 0, "kept": 0, "removed_by_cat": {}}
    kept_sections = []

    for num, title, content in articles:
        # 檔頭段落直接保留
        if title == "__HEADER__":
            kept_sections.append(content)
            continue

        stats["total"] += 1
        removed = False

        # ===== 第一步：標題關鍵字（依優先順序，命中即停止）=====
        title_result = check_title_step1(title)
        if title_result:
            category, keyword = title_result
            log_rows.append([path.name, num, title, category, keyword, "", "", "", ""])
            stats["removed_by_cat"][category] = stats["removed_by_cat"].get(category, 0) + 1
            removed = True
            # 收集軟性離題被刪的文章
            if category == "軟性離題新聞":
                removed_offtopic_articles.append((path.name, num, title, content))

        # ===== 第二步：產品廣告內文密度（僅未被第一步命中者）=====
        if not removed:
            is_ad, spec_n, mkt_n, total_n, hit_words, body_len, protected = check_ad_by_content(content)
            if is_ad:
                category = "廠商產品廣告"
                keyword_desc = f"規格{spec_n}+行銷{mkt_n}=共{total_n}詞"
                hit_words_str = ", ".join(hit_words)
                protected_str = "是" if protected else "否"
                log_rows.append([
                    path.name, num, title, category, keyword_desc,
                    str(total_n), hit_words_str, str(body_len), protected_str
                ])
                stats["removed_by_cat"][category] = stats["removed_by_cat"].get(category, 0) + 1
                removed = True
                # 收集廣告被刪的文章
                removed_ad_articles.append((path.name, num, title, content))

        if not removed:
            kept_sections.append(content)
            stats["kept"] += 1

    # 重新組裝並重新編號
    output = ("\n\n" + "-" * 40 + "\n\n").join(kept_sections)

    idx = 0
    def renumber(match):
        nonlocal idx
        idx += 1
        title_text = match.group(2).strip()
        return f"■ [{idx}] {title_text}"

    output = ARTICLE_RE.sub(renumber, output)

    # 寫入
    out_path = outdir / path.name
    out_path.write_text(output, encoding="utf-8")

    return stats


def main():
    ap = argparse.ArgumentParser(
        description="過濾文章：依優先順序刪除特定類別新聞"
    )
    ap.add_argument("--indir", type=Path, required=True, help="輸入資料夾")
    ap.add_argument("--outdir", type=Path, required=True, help="輸出資料夾")
    args = ap.parse_args()

    files = sorted(args.indir.glob("*.txt"))
    if not files:
        print("找不到 txt 檔案", file=sys.stderr)
        sys.exit(1)

    args.outdir.mkdir(parents=True, exist_ok=True)

    # 準備 log 和收集
    log_rows: list[list[str]] = []
    removed_ad_articles: list[tuple[str, str, str, str]] = []
    removed_offtopic_articles: list[tuple[str, str, str, str]] = []

    # 印出設定
    print(f"處理 {len(files)} 個檔案")
    print(f"\n第一步 — 標題關鍵字過濾（依優先順序）：")
    for cat_name, kw_list, need_two, is_political in TITLE_CATEGORIES_ORDERED:
        if is_political and not FILTER_POLITICS:
            status = "（已停用）"
        elif need_two:
            status = f"（{len(kw_list)}詞, 需命中≥2個）"
        else:
            status = f"（{len(kw_list)}詞, 命中1個即刪）"
        print(f"  {cat_name} {status}")
    print(f"\n第二步 — 內文密度過濾（僅未被第一步命中者）：")
    print(f"  廠商產品廣告（規格詞{len(AD_SPEC_WORDS)}個 + 行銷詞{len(AD_MARKETING_WORDS)}個, "
          f"門檻≥{AD_THRESHOLD}詞 或 規格≥3且行銷≥2）")
    print(f"  正文截斷標記: {len(CONTENT_CUTOFF_PATTERNS)} 種")
    print(f"  主題保護詞: {len(TOPIC_PROTECT_WORDS)} 個")
    print(f"{'='*70}\n")

    # 總計
    g_total = 0
    g_kept = 0
    g_removed_by_cat: dict[str, int] = {}

    for f in files:
        stats = process_file(f, args.outdir, log_rows, removed_ad_articles, removed_offtopic_articles)
        g_total += stats["total"]
        g_kept += stats["kept"]
        for cat, cnt in stats["removed_by_cat"].items():
            g_removed_by_cat[cat] = g_removed_by_cat.get(cat, 0) + cnt

        removed = stats["total"] - stats["kept"]
        if removed > 0:
            details = [f"{cat}{cnt}" for cat, cnt in stats["removed_by_cat"].items()]
            print(f"  {f.name}: {stats['total']}篇 → 保留{stats['kept']}篇, "
                  f"刪除{removed}篇 ({', '.join(details)})")

    # 總計
    g_removed = g_total - g_kept
    print(f"\n{'='*70}")
    print(f"過濾結果統計：")
    print(f"  總文章數:     {g_total:,} 篇")
    print(f"  保留:         {g_kept:,} 篇")
    print(f"  刪除合計:     {g_removed:,} 篇（{100*g_removed/max(g_total,1):.1f}%）")
    for cat, cnt in sorted(g_removed_by_cat.items(), key=lambda x: -x[1]):
        print(f"    - {cat}: {cnt:,} 篇")
    print(f"{'='*70}")

    # 寫入 filter_log.csv
    log_path = args.outdir / "filter_log.csv"
    with open(log_path, "w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "來源檔", "編號", "標題", "命中類別", "命中關鍵字/描述",
            "特徵詞命中數", "命中詞列表", "採計正文長度", "觸發主題保護"
        ])
        writer.writerows(log_rows)
    print(f"\n刪除紀錄已存到: {log_path}")

    # 輸出被刪的廣告文章（獨立檔案，供複查）
    if removed_ad_articles:
        ad_path = args.outdir / "_被刪除_廠商產品廣告.txt"
        lines = [f"被刪除的廠商產品廣告文章（共 {len(removed_ad_articles)} 篇）\n{'='*60}\n"]
        for src, num, title, content in removed_ad_articles:
            lines.append(f"[來源: {src}, 編號: {num}]")
            lines.append(content)
            lines.append("\n" + "-" * 40 + "\n")
        ad_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"廣告被刪文章已存到: {ad_path}")

    # 輸出被刪的軟性離題文章（獨立檔案）
    if removed_offtopic_articles:
        ot_path = args.outdir / "_被刪除_軟性離題新聞.txt"
        lines = [f"被刪除的軟性離題新聞（共 {len(removed_offtopic_articles)} 篇）\n{'='*60}\n"]
        for src, num, title, content in removed_offtopic_articles:
            lines.append(f"[來源: {src}, 編號: {num}]")
            lines.append(content)
            lines.append("\n" + "-" * 40 + "\n")
        ot_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"軟性離題被刪文章已存到: {ot_path}")


if __name__ == "__main__":
    main()
