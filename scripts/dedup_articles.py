# -*- coding: utf-8 -*-
"""
dedup_articles.py
讀取 filtered/ 內所有 .txt，做去重複（單檔內 + 跨檔），輸出到 deduped/。

去重邏輯：
1. 標題正規化後完全相同 → 重複
2. 短標題完整包含於長標題中，且短標題長度 >= THRESHOLD → 重複
3. 每組重複只保留內文最長的那篇

Usage:
    python dedup_articles.py --indir filtered --outdir deduped
"""

import argparse
import csv
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

# ===========================================================================
# 可調常數
# ===========================================================================
THRESHOLD = 8  # 短字串長度門檻：短標題至少要這麼長才會觸發「包含即重複」規則
FUZZY_THRESHOLD = 0.90  # 標題相似度門檻（0~1）：同一來源檔內，相似度 >= 此值視為重複

# ===========================================================================
# 正規表達式
# ===========================================================================
ARTICLE_RE = re.compile(r"^■\s*\[(\d+)\]\s*(.+)$", re.MULTILINE)
SEPARATOR_RE = re.compile(r"^-{10,}$", re.MULTILINE)

# 媒體來源後綴分隔符號
MEDIA_SUFFIX_RE = re.compile(r"\s*[-|｜]\s*[^-|｜]+$")


# ===========================================================================
# 工具函數
# ===========================================================================

def normalize_title(title: str) -> str:
    """
    標題正規化：
    1. 去媒體來源後綴（" - 聯合報"、" | ETtoday" 等）
    2. 去所有空白（含全形 \u3000）
    3. 去標點
    4. 轉小寫
    """
    # 移除媒體來源後綴（偵測最後一個 " - " 或 " | " 或 "｜" 之後的部分）
    title = MEDIA_SUFFIX_RE.sub("", title)

    # 去除所有空白
    title = re.sub(r"[\s\u3000]+", "", title)

    # 去除標點符號
    title = re.sub(r"[（）()\[\]【】「」『』：:，,。！!？?、／/×#&.｜|\-—…·．~～《》〈〉]+", "", title)

    # 轉小寫
    title = title.lower()

    return title


def is_duplicate(norm_a: str, norm_b: str) -> bool:
    """
    判斷兩個正規化標題是否為重複：
    1. 完全相同
    2. 短字串完整包含於長字串中，且短字串長度 >= THRESHOLD
    """
    if norm_a == norm_b:
        return True

    short, long = (norm_a, norm_b) if len(norm_a) <= len(norm_b) else (norm_b, norm_a)
    if len(short) >= THRESHOLD and short in long:
        return True

    return False


# ===========================================================================
# 文章資料結構
# ===========================================================================

class Article:
    """一篇文章的資料。"""
    def __init__(self, source_file: str, num: str, title: str, content: str):
        self.source_file = source_file  # 來源檔名
        self.num = num                  # 原始編號
        self.title = title              # 原始標題
        self.content = content          # 整段內容（含標題行）
        self.norm_title = normalize_title(title)  # 正規化標題
        self.content_len = len(content) # 內文長度（用來決定保留哪篇）
        self.group_id = -1             # 重複組 ID（-1 = 尚未分組）
        self.keep = True               # 是否保留


def parse_file(path: Path) -> list[Article]:
    """解析一個 txt 檔，回傳文章列表。"""
    raw = path.read_text(encoding="utf-8")
    sections = SEPARATOR_RE.split(raw)
    articles = []

    for section in sections:
        section = section.strip()
        if not section:
            continue

        m = ARTICLE_RE.search(section)
        if m:
            num = m.group(1)
            title = m.group(2).strip()
            articles.append(Article(path.name, num, title, section))
        else:
            # 非文章段落（檔頭），用特殊標記保留
            articles.append(Article(path.name, "0", "__HEADER__", section))

    return articles


# ===========================================================================
# 去重複核心邏輯
# ===========================================================================

def find_duplicates(all_articles: list[Article], fuzzy_threshold: float | None = FUZZY_THRESHOLD) -> list[list[int]]:
    """
    找出所有重複組。
    回傳 [[idx1, idx2, ...], [...], ...] 每組是一群互為重複的文章索引。
    使用 Union-Find 方式分組。

    fuzzy_threshold: 若非 None，額外做「同一來源檔內」的標題相似度比對
    （處理錯字、用詞小差異、媒體分類標籤不同等 exact/containment 抓不到的重複）。
    設 None 可關閉此比對（回到原本只做完全比對 + 包含比對）。
    """
    n = len(all_articles)

    # 建立正規化標題 → 索引的映射（完全匹配快速查找）
    norm_to_indices: dict[str, list[int]] = {}
    for i, art in enumerate(all_articles):
        if art.title == "__HEADER__":
            continue
        norm = art.norm_title
        if norm not in norm_to_indices:
            norm_to_indices[norm] = []
        norm_to_indices[norm].append(i)

    # Union-Find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    # 第一輪：完全匹配的分組
    for indices in norm_to_indices.values():
        if len(indices) > 1:
            for i in range(1, len(indices)):
                union(indices[0], indices[i])

    # 第二輪：包含關係（短包含於長）
    # 為了效率，只在不同 norm_title 之間比較
    norms = list(norm_to_indices.keys())
    # 按長度排序，短的在前
    norms.sort(key=len)

    for i in range(len(norms)):
        if len(norms[i]) < THRESHOLD:
            continue
        for j in range(i + 1, len(norms)):
            if norms[i] in norms[j]:
                # 短標題包含於長標題中
                idx_short = norm_to_indices[norms[i]][0]
                idx_long = norm_to_indices[norms[j]][0]
                union(idx_short, idx_long)

    # 第三輪：同一來源檔內的標題相似度比對（抓錯字、用詞差異等近似重複）
    # 僅限同檔比對，避免跨兩百多個檔案做 O(n^2) 相似度計算導致過慢，
    # 也符合「同一天內同一新聞被重複收錄」是最常見、最該清的重複型態。
    if fuzzy_threshold is not None:
        by_file: dict[str, list[int]] = {}
        for i, art in enumerate(all_articles):
            if art.title == "__HEADER__":
                continue
            by_file.setdefault(art.source_file, []).append(i)

        for indices in by_file.values():
            m = len(indices)
            for a in range(m):
                ia = indices[a]
                # 已經在同一組的不用再比
                title_a = all_articles[ia].norm_title
                len_a = len(title_a)
                if len_a == 0:
                    continue
                for b in range(a + 1, m):
                    ib = indices[b]
                    if find(ia) == find(ib):
                        continue
                    title_b = all_articles[ib].norm_title
                    len_b = len(title_b)
                    if len_b == 0:
                        continue
                    # 長度差太多必定不相似，先跳過以加速
                    if abs(len_a - len_b) > max(len_a, len_b) * 0.5:
                        continue
                    ratio = SequenceMatcher(None, title_a, title_b).ratio()
                    if ratio >= fuzzy_threshold:
                        union(ia, ib)

    # 收集重複組（只收 size > 1 的）
    groups: dict[int, list[int]] = {}
    for i in range(n):
        if all_articles[i].title == "__HEADER__":
            continue
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(i)

    # 只回傳有重複的組（size > 1）
    return [indices for indices in groups.values() if len(indices) > 1]


def mark_duplicates(all_articles: list[Article], dup_groups: list[list[int]]) -> None:
    """在每組重複中，保留內文最長的那篇，其餘標記為 keep=False。"""
    for group in dup_groups:
        # 找出內文最長的
        best_idx = max(group, key=lambda i: all_articles[i].content_len)
        for idx in group:
            if idx == best_idx:
                all_articles[idx].keep = True
            else:
                all_articles[idx].keep = False


# ===========================================================================
# 輸出
# ===========================================================================

def write_output(all_articles: list[Article], file_order: list[str], outdir: Path) -> None:
    """依原始檔案分組，寫出保留的文章。"""
    # 按來源檔分組
    file_articles: dict[str, list[Article]] = {}
    for art in all_articles:
        if art.source_file not in file_articles:
            file_articles[art.source_file] = []
        file_articles[art.source_file].append(art)

    for fname in file_order:
        if fname not in file_articles:
            continue
        arts = file_articles[fname]
        kept = [a for a in arts if a.keep]

        # 重新組裝
        sections = [a.content for a in kept]
        output = ("\n\n" + "-" * 40 + "\n\n").join(sections)

        # 重新編號
        idx = 0
        def renumber(match):
            nonlocal idx
            idx += 1
            title = match.group(2).strip()
            return f"■ [{idx}] {title}"

        output = ARTICLE_RE.sub(renumber, output)

        out_path = outdir / fname
        out_path.write_text(output, encoding="utf-8")


def write_log(all_articles: list[Article], dup_groups: list[list[int]], outdir: Path) -> None:
    """產生 dedup_log.csv。"""
    log_path = outdir / "dedup_log.csv"
    with open(log_path, "w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["重複組", "狀態", "來源檔", "編號", "標題", "內文長度"])

        for gid, group in enumerate(dup_groups, 1):
            for idx in group:
                art = all_articles[idx]
                status = "KEEP" if art.keep else "DROP"
                writer.writerow([gid, status, art.source_file, art.num, art.title, art.content_len])

    print(f"\n去重紀錄已存到: {log_path}")


# ===========================================================================
# 主程式
# ===========================================================================

def main():
    global THRESHOLD
    ap = argparse.ArgumentParser(description="文章去重複（單檔內 + 跨檔）")
    ap.add_argument("--indir", type=Path, required=True, help="輸入資料夾（filtered）")
    ap.add_argument("--outdir", type=Path, required=True, help="輸出資料夾（deduped）")
    ap.add_argument("--threshold", type=int, default=THRESHOLD,
                    help=f"短標題包含門檻（預設 {THRESHOLD}）")
    ap.add_argument("--fuzzy-threshold", type=float, default=FUZZY_THRESHOLD,
                    help=f"同檔內標題相似度門檻，0~1（預設 {FUZZY_THRESHOLD}）")
    ap.add_argument("--no-fuzzy", action="store_true",
                    help="關閉相似度比對，只做完全比對 + 包含比對")
    args = ap.parse_args()

    threshold_val = args.threshold
    fuzzy_threshold_val = None if args.no_fuzzy else args.fuzzy_threshold

    files = sorted(args.indir.glob("*.txt"))
    if not files:
        print("找不到 txt 檔案", file=sys.stderr)
        sys.exit(1)

    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"讀取 {len(files)} 個檔案...")
    print(f"短標題包含門檻: {threshold_val} 字")
    print(f"相似度門檻（同檔內）: {'關閉' if fuzzy_threshold_val is None else fuzzy_threshold_val}\n")

    # 讀取所有文章
    all_articles: list[Article] = []
    file_order: list[str] = []

    for f in files:
        arts = parse_file(f)
        all_articles.extend(arts)
        file_order.append(f.name)

    # 統計（不含 HEADER）
    total = sum(1 for a in all_articles if a.title != "__HEADER__")
    print(f"總文章數: {total:,} 篇")
    print(f"開始比對重複...\n")

    # 套用使用者指定的門檻
    THRESHOLD = threshold_val

    # 找重複組
    dup_groups = find_duplicates(all_articles, fuzzy_threshold=fuzzy_threshold_val)
    print(f"找到 {len(dup_groups)} 組重複")

    # 標記保留/刪除
    mark_duplicates(all_articles, dup_groups)

    # 統計刪除數
    removed = sum(1 for a in all_articles if a.title != "__HEADER__" and not a.keep)
    kept = total - removed

    print(f"\n{'='*60}")
    print(f"去重結果：")
    print(f"  總文章數:   {total:,} 篇")
    print(f"  重複組數:   {len(dup_groups):,} 組")
    print(f"  刪除篇數:   {removed:,} 篇（{100*removed/max(total,1):.1f}%）")
    print(f"  最終保留:   {kept:,} 篇")
    print(f"{'='*60}")

    # 寫出結果
    write_output(all_articles, file_order, args.outdir)
    write_log(all_articles, dup_groups, args.outdir)

    print(f"\n過濾後檔案已存到: {args.outdir}")


if __name__ == "__main__":
    main()
