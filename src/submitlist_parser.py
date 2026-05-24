"""
submitlist_parser.py — อ่าน submitList.pdf จาก e-GP

submitList = "บัญชีเอกสารส่วนที่ 1 และส่วนที่ 2" คือสารบัญทางการ
ที่บอกว่าผู้ยื่นได้แนบเอกสารอะไรบ้าง แทนการเดาจากชื่อไฟล์

โครงสร้าง:
  ส่วนที่ 1: 10 หมวดมาตรฐาน (row 1-10)
    1. หนังสือรับรองนิติบุคคล
    2. หนังสือบริคณห์สนธิ
    3. บัญชีรายชื่อกรรมการผู้จัดการ
    4. บัญชีผู้ถือหุ้นรายใหญ่
    5. ผู้มีอำนาจควบคุม
    6. เอกสารแสดงสิทธิประโยชน์
    7. งบแสดงฐานะการเงิน
    8. หนังสือรับรองวงเงินสินเชื่อ
    9. ใบทะเบียนพาณิชย์
    10. ใบทะเบียนภาษีมูลค่าเพิ่ม

  ส่วนที่ 2: 1 row พร้อม sub-items (catalogue, LINE License, SME, MIT, อื่นๆ)
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False


NO_DOC = "ไม่มีเอกสารแนบ"

# Thai digit conversion
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


# มาตรฐาน 10 หมวด ส่วนที่ 1
PART1_STANDARD = [
    "cert",            # 1
    "memo",            # 2
    "director_list",   # 3
    "shareholder_doc", # 4
    "authority_doc",   # 5
    "privilege",       # 6 — เอกสารสิทธิประโยชน์ (ไม่มี column ใน Excel ปัจจุบัน)
    "financial",       # 7 — งบการเงิน
    "credit",          # 8
    "trade_reg",       # 9
    "vat",             # 10
]


@dataclass
class SubmitEntry:
    """1 รายการในสารบัญ"""
    row_num: int = 0
    category_label: str = ""    # ชื่อหมวดที่ map ไป (เช่น 'cert', 'memo')
    raw_category: str = ""      # ข้อความหมวดดิบจาก PDF
    files: list[str] = field(default_factory=list)   # ชื่อไฟล์ที่ยื่น
    has_doc: bool = False       # True ถ้ามีไฟล์จริง (ไม่ใช่ 'ไม่มีเอกสารแนบ')


@dataclass
class SubmitList:
    """สารบัญทั้งหมดของผู้ยื่น 1 ราย"""
    part1: dict[str, SubmitEntry] = field(default_factory=dict)
    part2_files: list[str] = field(default_factory=list)
    part2_raw_rows: list[dict] = field(default_factory=list)  # debug
    parsed_ok: bool = False
    error: str = ""


# ─── helpers ──────────────────────────────────────────────────────────────────

def _thai_int(s: Optional[str]) -> Optional[int]:
    """แปลงเลขไทย/อาหรับ → int"""
    if not s:
        return None
    t = s.strip().translate(_THAI_DIGITS)
    m = re.match(r"^\d+$", t)
    return int(t) if m else None


def _clean_filename(raw: str) -> str:
    """รวมบรรทัดที่แตกของชื่อไฟล์ และตัด whitespace"""
    if not raw:
        return ""
    # แทน \n ด้วย '' เพราะชื่อไฟล์ใน PDF มัก wrap บรรทัด
    s = raw.replace("\r", "").strip()
    # ถ้าลงท้ายด้วยจุดแล้วบรรทัดถัดไปขึ้น pdf → รวม
    s = re.sub(r"\.\n+", ".", s)
    s = re.sub(r"\n+", "", s).strip()
    return s


def _split_entries(cell: str) -> list[str]:
    """
    แบ่ง cell ที่มีหลายไฟล์/หลายรายการ
    Heuristic: แบ่งที่ขอบเขตของ .pdf/.jpg/.png/.doc + 'ไม่มีเอกสารแนบ'
    """
    if not cell:
        return []
    s = cell.replace("\r", "")
    # split ตาม "ไม่มีเอกสารแนบ" (เก็บไว้)
    parts = re.split(rf"({re.escape(NO_DOC)})", s)
    entries: list[str] = []
    buf: list[str] = []

    def flush_buf():
        if not buf:
            return
        text = "\n".join(buf).strip()
        if not text:
            buf.clear()
            return
        # split ที่ extension — แทน extension ด้วย marker แล้ว split ด้วย marker
        marker = "<<<SPLIT>>>"
        marked = re.sub(
            r"(\.pdf|\.PDF|\.doc|\.docx|\.jpg|\.png|\.jpeg)\s*\n+",
            r"\1" + marker, text,
        )
        for p in marked.split(marker):
            p = _clean_filename(p)
            if p:
                entries.append(p)
        buf.clear()

    for part in parts:
        if part == NO_DOC:
            flush_buf()
            entries.append(NO_DOC)
        else:
            buf.append(part)
    flush_buf()
    return entries


# ─── parser ───────────────────────────────────────────────────────────────────

def parse_submitlist(pdf_path: str) -> SubmitList:
    """
    Parameters
    ----------
    pdf_path : path ของ submitList.pdf

    Returns
    -------
    SubmitList ที่มี mapping ส่วนที่ 1 (10 หมวด) และไฟล์ส่วนที่ 2
    """
    result = SubmitList()
    if not _HAS_PDFPLUMBER:
        result.error = "pdfplumber not installed"
        return result

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        result.error = f"open failed: {e}"
        return result

    tables: list[list[list]] = []
    try:
        for page in pdf.pages:
            for t in (page.extract_tables() or []):
                tables.append(t)
    finally:
        pdf.close()

    if not tables:
        result.error = "no tables found"
        return result

    # แยก section จากหัวตาราง
    sec1_table: Optional[list] = None
    sec2_table: Optional[list] = None

    for tbl in tables:
        # หัวตาราง 2-3 row แรก
        head_text = " ".join(
            str(c or "") for r in tbl[:3] for c in (r or [])
        )
        if "ส่วนที่ ๑" in head_text or "ส่วนที่ 1" in head_text:
            # อาจเจอ "ส่วนที่ ๑ และส่วนที่ ๒" ทั้งคู่ — ดูว่ามีคำว่า "พิจารณา" ไหม
            if "พิจารณา" in head_text and sec1_table is not None:
                sec2_table = tbl
            else:
                sec1_table = tbl
        if "ส่วนที่ ๒" in head_text or "ส่วนที่ 2" in head_text:
            # ถ้าหัวตารางมี "รายการพิจารณา" = ส่วนที่ 2
            if "พิจารณา" in head_text or sec2_table is None:
                sec2_table = tbl

    # ── parse ส่วนที่ 1 ────────────────────────────────────────────────────
    if sec1_table:
        for row in sec1_table:
            if not row or len(row) < 3:
                continue
            n = _thai_int(row[0])
            if n is None or n < 1 or n > 12:
                continue
            raw_cat = (row[1] or "").strip()
            file_cell = row[2] if len(row) > 2 else ""
            entries = _split_entries(file_cell or "")

            files = [e for e in entries if e and e != NO_DOC]
            has_doc = bool(files)

            cat_label = PART1_STANDARD[n - 1] if n - 1 < len(PART1_STANDARD) else ""
            result.part1[cat_label] = SubmitEntry(
                row_num=n,
                category_label=cat_label,
                raw_category=raw_cat,
                files=files,
                has_doc=has_doc,
            )

    # ── parse ส่วนที่ 2 ────────────────────────────────────────────────────
    if sec2_table:
        # ส่วนที่ 2 มี row เดียวมักจะ merged
        for row in sec2_table:
            if not row or len(row) < 4:
                continue
            n = _thai_int(row[0])
            if n is None:
                continue
            # col3 = ไฟล์ข้อมูล
            file_cell = row[3] if len(row) > 3 else ""
            cat_cell = row[2] if len(row) > 2 else ""
            entries = _split_entries(file_cell or "")
            cats = [c.strip() for c in (cat_cell or "").split("\n") if c.strip()]

            files = [e for e in entries if e and e != NO_DOC]
            result.part2_files.extend(files)
            result.part2_raw_rows.append({
                "row_num": n,
                "categories": cats,
                "entries": entries,
                "files": files,
            })

    result.parsed_ok = bool(sec1_table or sec2_table)
    return result


# ─── public helpers ──────────────────────────────────────────────────────────

def has_doc(sl: SubmitList, category: str) -> bool:
    """True ถ้าหมวด `category` ใน ส่วนที่ 1 มีเอกสารยื่นมา"""
    entry = sl.part1.get(category)
    return bool(entry and entry.has_doc)


def get_files(sl: SubmitList, category: str) -> list[str]:
    """คืนรายชื่อไฟล์ของหมวด `category` ใน ส่วนที่ 1"""
    entry = sl.part1.get(category)
    return entry.files if entry else []
