# 文件提取服務

一個本地端的 Web 工具，把 PDF / Word / Excel / TXT 丟進去，自動幫你：
1. 提取文章內容
2. 用 jieba 產生關鍵字
3. 過濾不相關的文章（可自訂規則）
4. 去除重複文章
5. 清理正文雜訊
6. 整理成乾淨的 txt + xlsx 輸出

---

## 快速開始

### 1. 安裝 Python

需要 Python 3.10 以上。確認方式：

```bash
python --version
```

### 2. 安裝依賴套件

在專案資料夾內執行：

```bash
pip install -r requirements.txt
```

### 3. 啟動服務

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 4. 開始使用

瀏覽器打開 **http://localhost:8000**

---

## 使用方式

1. 把檔案（PDF / Word / Excel / TXT）拖到上傳區，或點選檔案
2. 勾選你要跑的步驟（預設全部打勾）
3. 選匯出格式（TXT / Excel / 兩個都要）
4. 按「開始處理」，等進度跑完
5. 下載 ZIP 或直接在網頁預覽結果

---

## 頁面說明

| 網址 | 功能 |
|------|------|
| `http://localhost:8000` | 主頁 — 上傳檔案、處理、下載 |
| `http://localhost:8000/settings` | 設定過濾關鍵字（決定哪些文章要刪掉） |
| `http://localhost:8000/stopwords` | 設定停用詞（哪些詞不要出現在關鍵字裡） |

---

## 處理步驟說明

| 步驟 | 做什麼 |
|------|--------|
| 1. 提取文章 | 從各種格式的檔案中抓出文章內容 |
| 2. 產生關鍵字 | 用 jieba 分詞自動幫每篇文章標關鍵字 |
| 3. 過濾不相關 | 根據你設定的關鍵字規則，刪掉不相關的文章 |
| 4. 去重複 | 跨檔比對，刪掉標題相同或相似的重複文章 |
| 5. 清理正文 | 移除 URL、email、版權聲明等雜訊 |
| 6. 整理格式 | 修正表頭、重新編號、同步產生 Excel |

步驟 1 和 2 是基本流程，3~6 可以依需求自行勾選。

---

## 資料夾結構

```
817/
├── app/                    # Web 應用程式
│   ├── main.py             # FastAPI 路由
│   ├── pipeline.py         # 處理流程邏輯
│   ├── config_manager.py   # 設定管理
│   ├── config.json         # 過濾關鍵字 + 停用詞設定
│   ├── history.json        # 處理歷史紀錄
│   ├── static/             # 前端頁面
│   │   ├── index.html
│   │   ├── settings.html
│   │   └── stopwords.html
│   └── temp/               # 暫存（處理中的檔案）
├── data/                   # 之前處理過的資料檔案
├── extract_keyword_context.py  # PDF 提取核心
├── add_keywords_fast.py        # jieba 關鍵字
├── filter_articles.py          # 文章過濾
├── dedup_articles.py           # 去重複
├── clean.py                    # 正文清理
├── fix_headers.py              # 表頭修正
├── count_pdf_chars.py          # 輔助：字數統計
├── requirements.txt
└── README.md
```

---

## 依賴套件

- **fastapi** + **uvicorn** — Web 服務
- **sse-starlette** — 即時進度推送
- **python-multipart** — 檔案上傳
- **PyMuPDF** — PDF 文字提取
- **python-docx** — Word 文件讀取
- **jieba** — 中文分詞 / 關鍵字
- **openpyxl** — Excel 讀寫
- **tqdm** — 命令列進度條

---

## 常見問題

**Q: 啟動後瀏覽器打不開？**
確認用的是 `http://localhost:8000`，不是 `http://0.0.0.0:8000`。

**Q: PyMuPDF 安裝失敗？**
不要鎖版本，直接 `pip install PyMuPDF` 讓它自動找相容的預編譯版本。

**Q: 處理完下載是空的？**
確認你上傳的 PDF 裡面有文字內容（掃描圖片的 PDF 沒辦法提取）。
