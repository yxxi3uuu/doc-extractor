# -*- coding: utf-8 -*-
"""
從 PDF 提取全部文字並計算字數（不做任何過濾）。
用來跟 extracted/ 比較，看刪掉了多少字。

Usage:
    python count_pdf_chars.py --pdf-dir "慧科新聞" --sample 5
    python count_pdf_chars.py --pdf-dir "慧科新聞" --all
"""

import argparse
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


def count_pdf_chars(pdf_path: Path) -> int:
    """從 PDF 提取全部文字，計算字數。"""
    doc = fitz.open(pdf_path)
    total_chars = 0
    for page in doc:
        text = page.get_text()
        # 只計算中文字、英文字母、數字
        chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9]", text)
        total_chars += len(chars)
    doc.close()
    return total_chars


def count_txt_chars(txt_path: Path) -> int:
    """計算 txt 檔的字數。"""
    text = txt_path.read_text(encoding="utf-8")
    chars = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9]", text)
    return len(chars)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", type=Path, required=True)
    ap.add_argument("--extracted-dir", type=Path, default=None,
                    help="extracted 資料夾，用來比較")
    ap.add_argument("--sample", type=int, default=5,
                    help="抽樣幾個 PDF（預設 5，用 --all 跑全部）")
    ap.add_argument("--all", action="store_true", help="跑全部 PDF")
    args = ap.parse_args()

    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    if not pdfs:
        print("找不到 PDF", file=sys.stderr)
        sys.exit(1)

    if args.all:
        sample_pdfs = pdfs
    else:
        # 均勻抽樣
        step = max(1, len(pdfs) // args.sample)
        sample_pdfs = pdfs[::step][:args.sample]

    print(f"抽樣 {len(sample_pdfs)}/{len(pdfs)} 個 PDF 計算原始字數...\n")

    total_pdf_chars = 0
    total_ext_chars = 0

    for i, pdf in enumerate(sample_pdfs, 1):
        pdf_chars = count_pdf_chars(pdf)
        total_pdf_chars += pdf_chars

        ext_chars = 0
        if args.extracted_dir:
            ext_path = args.extracted_dir / (pdf.stem + ".txt")
            if ext_path.exists():
                ext_chars = count_txt_chars(ext_path)
                total_ext_chars += ext_chars

        ratio = f"→ extracted: {ext_chars:,} 字（{100*ext_chars/pdf_chars:.1f}%）" if ext_chars else ""
        print(f"  [{i}/{len(sample_pdfs)}] {pdf.name}: PDF 全文 {pdf_chars:,} 字 {ratio}")

    print(f"\n{'='*60}")
    print(f"抽樣結果（{len(sample_pdfs)} 個檔案）：")
    print(f"  PDF 原始總字數: {total_pdf_chars:,} 字")
    if total_ext_chars:
        print(f"  extracted 總字數: {total_ext_chars:,} 字")
        print(f"  字數縮減: {100*(1 - total_ext_chars/total_pdf_chars):.1f}%")

    if not args.all and len(pdfs) > len(sample_pdfs):
        avg_pdf = total_pdf_chars / len(sample_pdfs)
        avg_ext = total_ext_chars / len(sample_pdfs) if total_ext_chars else 0
        print(f"\n推估全部 {len(pdfs)} 個 PDF：")
        print(f"  PDF 原始總字數 ≈ {int(avg_pdf * len(pdfs)):,} 字")
        if avg_ext:
            print(f"  extracted 總字數 ≈ {int(avg_ext * len(pdfs)):,} 字")
            print(f"  字數縮減 ≈ {100*(1 - avg_ext/avg_pdf):.1f}%")


if __name__ == "__main__":
    main()
