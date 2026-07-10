#!/usr/bin/env python3
"""
샤인비드 발주서/견적서 xlsx 폴더를 파싱해서 Brightbeed data/orders.json 생성.
"""

import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import openpyxl


def nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s

FOLDER = Path(os.path.expanduser("~/Dropbox/쟌뚜비/샤인비드 발주"))
OUT = Path(__file__).resolve().parent.parent / "data" / "orders.json"

VENDOR_KEYWORDS = [
    ("콰이디", "콰이디"),
    ("콰이지", "콰이디"),
    ("코페리", "코페리"),
    ("아페티", "아페티"),
    ("퍼스트큐", "퍼스트큐"),
    ("퍼큐", "퍼스트큐"),
    ("코발트니", "코발트니"),
    ("hobin", "호빈"),
    ("호빈", "호빈"),
    ("hallo", "hallo stud"),
    ("SORBET", "SORBET"),
    ("sorbet", "SORBET"),
    ("에어건", "에어건"),
]


def classify_doc_type(name: str) -> str:
    if "발주" in name:
        return "발주서"
    if "견적" in name:
        return "견적서"
    if "주문" in name:
        return "주문서"
    if "샘플" in name:
        return "샘플"
    if "문의" in name:
        return "문의"
    return "기타"


def guess_vendor(name: str) -> str:
    for kw, label in VENDOR_KEYWORDS:
        if kw in name:
            return label
    return ""


DATE_A1 = re.compile(r"(\d{4})[년/. -]+(\d{1,2})[월/. -]+(\d{1,2})")
FNAME_DATE = re.compile(r"[Ss][Bb]?(\d{2})(\d{2})(\d{2})")
FNAME_DATE2 = re.compile(r"(?<!\d)(2[56])(\d{2})(\d{2})(?!\d)")


def parse_date_from_a1(val) -> str:
    if val is None:
        return ""
    if hasattr(val, "isoformat"):
        try:
            return val.date().isoformat()
        except Exception:
            pass
    s = str(val).strip()
    m = DATE_A1.search(s)
    if m:
        y, mm, dd = m.groups()
        try:
            return datetime(int(y), int(mm), int(dd)).date().isoformat()
        except Exception:
            return ""
    return ""


def parse_date_from_filename(name: str) -> str:
    m = FNAME_DATE.search(name) or FNAME_DATE2.search(name)
    if not m:
        return ""
    y, mm, dd = m.groups()
    try:
        year = 2000 + int(y)
        return datetime(year, int(mm), int(dd)).date().isoformat()
    except Exception:
        return ""


LABEL_KEYS = {
    "총수량": "total_qty",
    "상품가": "goods_krw",
    "구매대행수수료": "fee",
    "총입금하실금액": "total_krw",
    "총입금": "total_krw",
    "세금계산서발행금액": "invoice_krw",
    "세금계산서": "invoice_krw",
}


def to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("￦", "").replace("￥", "").replace("원", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def parse_workbook(path: Path):
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception as e:
        return {"error": f"open failed: {e}"}

    fname = nfc(path.name)
    result = {
        "file": fname,
        "size": path.stat().st_size,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "type": classify_doc_type(fname),
        "vendor": guess_vendor(fname),
        "date": "",
        "items": [],
        "item_count": 0,
        "total_qty": None,
        "goods_krw": None,
        "fee": None,
        "total_krw": None,
        "invoice_krw": None,
    }

    shname = wb.sheetnames[0]
    ws = wb[shname]

    # 첫 시트만, 첫 40 컬럼만, 최대 400 행만 스캔
    MAX_COLS = 40
    MAX_ROWS = 400

    header_row = None
    col_map = {}
    a1_seen = False
    summary_started = False

    for r_idx, row in enumerate(ws.iter_rows(values_only=True, max_col=MAX_COLS), start=1):
        if r_idx > MAX_ROWS:
            break
        row = list(row[:MAX_COLS])
        # A1 날짜
        if r_idx == 1 and not result["date"]:
            result["date"] = parse_date_from_a1(row[0]) if row else ""
            a1_seen = True

        row_s = [nfc(str(v)).strip() if v is not None else "" for v in row]

        if header_row is None:
            if "번호" in row_s and ("수량" in row_s or "상품링크" in row_s):
                header_row = r_idx
                for i, s in enumerate(row_s):
                    if not s:
                        continue
                    key = s.replace(" ", "").replace("\n", "")
                    col_map[key] = i
            continue

        # 합계 라인 감지
        if row_s and (row_s[0] == "합계" or (row_s[0] and "합계" in row_s[0])):
            summary_started = True

        if summary_started:
            # 요약 라벨 매칭 (앞 20 컬럼만)
            for i in range(min(len(row_s), 20)):
                cleaned = row_s[i].replace(" ", "").replace("\n", "")
                if not cleaned:
                    continue
                for label, key in LABEL_KEYS.items():
                    if cleaned.startswith(label):
                        for j in range(i + 1, min(len(row), i + 6)):
                            n = to_num(row[j])
                            if n is not None:
                                if result.get(key) is None:
                                    result[key] = n
                                break
                        break
            continue

        # 아이템 행
        c_no = col_map.get("번호")
        c_link = col_map.get("상품링크")
        c_kor = col_map.get("한글옵션명") or col_map.get("한글옵션")
        c_1688 = col_map.get("1688옵션명") or col_map.get("1668옵션명")
        c_memo = col_map.get("메모")
        c_qty = col_map.get("수량")
        c_price = None
        for k in col_map:
            if k.startswith("1688") and "단가" in k:
                c_price = col_map[k]
                break

        no = row_s[c_no] if c_no is not None and c_no < len(row_s) else ""
        qty = to_num(row[c_qty]) if c_qty is not None and c_qty < len(row) else None
        price = to_num(row[c_price]) if c_price is not None and c_price < len(row) else None
        if not no and qty is None and price is None:
            continue

        def get(cidx, limit=200):
            if cidx is None or cidx >= len(row_s):
                return ""
            return row_s[cidx][:limit]

        result["items"].append({
            "no": no[:20],
            "link": get(c_link, 400),
            "kor": get(c_kor),
            "cn": get(c_1688),
            "memo": get(c_memo),
            "qty": qty,
            "price_cny": price,
        })

    if not result["date"]:
        result["date"] = parse_date_from_filename(fname)

    result["item_count"] = len(result["items"])
    if result["total_qty"] is None and result["items"]:
        s = sum(it["qty"] for it in result["items"] if it["qty"] is not None)
        if s > 0:
            result["total_qty"] = s

    try:
        wb.close()
    except Exception:
        pass
    return result


def main():
    files = sorted(FOLDER.glob("*.xls*"))
    files = [f for f in files if not f.name.startswith("~$") and not f.name.endswith(".part")]
    print(f"parsing {len(files)} files", file=sys.stderr, flush=True)

    orders = []
    errors = []
    for i, f in enumerate(files, 1):
        try:
            row = parse_workbook(f)
            if "error" in row:
                errors.append({"file": f.name, "error": row["error"]})
                print(f"  [{i}/{len(files)}] ERR {f.name}: {row['error']}", file=sys.stderr, flush=True)
                continue
            orders.append(row)
            if i % 10 == 0 or i == len(files):
                print(f"  [{i}/{len(files)}] {f.name[:40]}", file=sys.stderr, flush=True)
        except Exception as e:
            errors.append({"file": f.name, "error": str(e)})
            print(f"  [{i}/{len(files)}] EXC {f.name}: {e}", file=sys.stderr, flush=True)

    orders.sort(key=lambda x: (x.get("date") or "0000-00-00"), reverse=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_folder": str(FOLDER),
        "count": len(orders),
        "errors": errors,
        "orders": orders,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(orders)} orders, {len(errors)} errors)", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
