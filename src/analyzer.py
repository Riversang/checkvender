"""
analyzer.py — วิเคราะห์เอกสารของผู้ยื่น 1 ราย

ใช้ submitList.pdf เป็น source of truth สำหรับ ✓/- ใน Section 1
(ไม่เดาจากชื่อไฟล์เป็นหลัก เพราะ false positive ง่าย)

═══════════════════════════════════════════════════════════════════════════
  SOURCE MAPPING — ตรงตาม submitList ส่วนที่ 1 (10 หมวดมาตรฐาน)
═══════════════════════════════════════════════════════════════════════════
  ลำดับ  รายการ                                       → ใช้ดึงข้อมูล
  ─────  ───────────────────────────────────────────  ─────────────────
   ๑    สำเนาหนังสือรับรองการจดทะเบียนนิติบุคคล      → DIRECTORS (รายชื่อกรรมการ)
   ๒    สำเนาหนังสือบริคณห์สนธิ                       → ✓/- เท่านั้น
   ๓    บัญชีรายชื่อกรรมการผู้จัดการ                  → ✓/- + fallback ชื่อบริษัท
   ๔    บัญชีผู้ถือหุ้นรายใหญ่                        → SHAREHOLDERS (>25%)
   ๕    ผู้มีอำนาจควบคุม                              → AUTHORITY (ผู้มีอำนาจควบคุม)
   ๖    เอกสารแสดงสิทธิ/ประโยชน์                      → ✓/- เท่านั้น
   ๗    งบแสดงฐานะการเงิน                            → NET WORTH (มูลค่าสุทธิ)
   ๘    สำเนาหนังสือรับรองวงเงินสินเชื่อ             → ✓/- เท่านั้น
   ๙    สำเนาใบทะเบียนพาณิชย์                         → ✓/- เท่านั้น
   ๑๐   สำเนาใบทะเบียนภาษีมูลค่าเพิ่ม (ภพ.20)         → ✓/- เท่านั้น

  หมวด 3 ตัวที่ต้องดึงรายชื่อ — ใช้ไฟล์ในคอลัมน์ "ไฟล์ข้อมูล" ตามลำดับ:
    DIRECTORS    ← row 1 (cert)
    SHAREHOLDERS ← row 4 (shareholder_doc)  ถ้าไม่เจอ >25% → "-"
    AUTHORITY    ← row 5 (authority_doc)    ถ้า row 5 ว่าง → fallback scan filename

  Name prediction (text cleanup):
    OCR'd authority names → fuzzy-match กับ directors → ใช้ชื่อสะอาด
═══════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from .extractor import VendorFiles, find_file, find_files, list_files, find_by_original
from .pdf_reader import (
    read_pdf_text,
    read_pdf_tables,
    extract_net_worth,
    find_shareholder_over,
    extract_thai_number,
    force_ocr_pdf,
)
from .submitlist_parser import (
    parse_submitlist,
    has_doc as sl_has_doc,
    get_files as sl_get_files,
    SubmitList,
    NO_DOC,
)


CHECK = "✓"
DASH  = "-"


@dataclass
class VendorData:
    """ข้อมูลที่วิเคราะห์ได้ต่อ 1 ผู้ยื่นข้อเสนอ"""
    no: int
    name: str = ""
    tax_id: str = ""
    price: float = 0.0

    directors: list[str] = field(default_factory=list)
    authority: str = "-"
    shareholders: str = "-"

    net_worth: float = 0.0
    net_worth_sign: str = "ไม่ทราบ"

    # ส่วนที่ 1
    cert: str = DASH
    memo: str = DASH
    director_list: str = DASH
    authority_doc: str = DASH
    shareholder_doc: str = DASH
    trade_reg: str = DASH
    vat: str = DASH
    credit: str = DASH
    joint: str = DASH
    integrity: str = DASH
    anti_corrupt: str = DASH

    # ส่วนที่ 2
    poa: str = DASH
    guarantee: str = DASH       # หลักประกัน (สำคัญใน MA/งานจ้าง)
    sme: str = DASH
    mit: str = DASH
    catalogue: str = DASH
    work_cert: str = DASH       # หนังสือรับรองผลงาน
    line_license: str = DASH    # Certificate/License (generic — LINE/AWS/Microsoft/etc.)
    personnel: str = DASH       # บุคลากรหลัก (สำคัญใน MA)
    project_mgmt: str = DASH    # แผน/โครงสร้างการบริหารโครงการ (MA)
    other1: str = ""
    other1_note: str = ""

    _notes: list[str] = field(default_factory=list)
    unread_files: list[str] = field(default_factory=list)  # ไฟล์ที่อ่านไม่ออก (ต้อง OCR)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _read(path: Optional[str], unread: Optional[list] = None,
          label: str = "") -> str:
    """
    อ่าน PDF + track ถ้าอ่านไม่ออก (font แปลก/ภาพสแกน)

    Parameters
    ----------
    path   : path ของไฟล์
    unread : list สำหรับเก็บ description ไฟล์ที่อ่านไม่ออก (ถ้า pass มา)
    label  : ป้ายระบุประเภทไฟล์ (เช่น 'หนังสือรับรอง', 'ผู้ถือหุ้น')
    """
    if not path or not os.path.exists(path):
        return ""
    text, is_good = read_pdf_text(path, use_vision=True)
    if unread is not None and not is_good:
        tag = f"{label} - " if label else ""
        unread.append(f"{tag}{os.path.basename(path)}")
    return text


def _read_tables(path: Optional[str]) -> list:
    if not path or not os.path.exists(path):
        return []
    return read_pdf_tables(path)


def _norm(s: str) -> str:
    """normalize: lower, ตัด space"""
    return re.sub(r"\s+", "", (s or "").lower())


# ─── Thai date parsing (สำหรับเลือกไฟล์ใหม่ที่สุด) ─────────────────────────────

import datetime as _dt

_THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
    "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
    # short forms (no dot)
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4,
    "พ.ค.": 5, "มิ.ย.": 6, "ก.ค.": 7, "ส.ค.": 8,
    "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
}


def _normalize_year(y: int) -> int:
    """แปลง ปี พ.ศ. → ค.ศ. (ถ้า > 2400 ถือว่าเป็น พ.ศ.)"""
    return y - 543 if y > 2400 else y


def _extract_latest_date(text: str) -> Optional[_dt.date]:
    """หาวันที่ล่าสุดในข้อความ (รองรับทั้ง DD/MM/YYYY และ DD เดือนไทย YYYY)"""
    if not text:
        return None
    dates: list[_dt.date] = []
    # Pattern 1: DD/MM/YYYY
    for m in re.finditer(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
        try:
            d = _dt.date(_normalize_year(int(m.group(3))),
                          int(m.group(2)), int(m.group(1)))
            if 2010 <= d.year <= 2100:   # range filter
                dates.append(d)
        except ValueError:
            continue
    # Pattern 2: DD <Thai month> YYYY  (เช่น "13 มกราคม 2569")
    months_alt = "|".join(re.escape(m) for m in _THAI_MONTHS)
    for m in re.finditer(rf"(\d{{1,2}})\s+({months_alt})\s+(\d{{4}})", text):
        try:
            d = _dt.date(_normalize_year(int(m.group(3))),
                          _THAI_MONTHS[m.group(2)], int(m.group(1)))
            if 2010 <= d.year <= 2100:
                dates.append(d)
        except ValueError:
            continue
    return max(dates) if dates else None


def _pick_latest_file(vf: VendorFiles, fnames: list[str],
                      label: str = "",
                      unread: Optional[list] = None) -> Optional[str]:
    """
    ในกลุ่มไฟล์ที่ submitList ระบุไว้สำหรับหมวดเดียวกัน — เลือก path ที่ลง
    "วันที่ออกเอกสาร" / "ข้อมูล ณ วันที่" ใหม่ที่สุด

    Returns: path ของไฟล์ใหม่ที่สุด (หรือ first found ถ้าไม่มีวันที่)
    """
    if not fnames:
        return None
    candidates: list[tuple[Optional[_dt.date], str]] = []
    for fn in fnames:
        p = find_by_original(vf, fn)
        if not p:
            continue
        text = _read(p, unread=unread, label=label)
        d = _extract_latest_date(text)
        candidates.append((d, p))
    if not candidates:
        return None
    # เรียงโดย date desc (None ไปท้าย)
    candidates.sort(key=lambda x: x[0] or _dt.date.min, reverse=True)
    return candidates[0][1]


# ─── company name ────────────────────────────────────────────────────────────

_NAME_PATTERNS = [
    # juristic_information: "ชื่อสถานที่ประกอบการ บริษัท X จำกัด"
    r"ชื่อสถานที่ประกอบการ\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    r"ชื่อนิติบุคคล\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    r"ชื่อสถานประกอบการ\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    r"ชื่อผู้ประกอบการ\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    # หนังสือรับรองบริษัท: "1. ชื่อบริษัท บริษัท X จำกัด"
    r"ชื่อบริษัท\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    # Quotation: "ข้าพเจ้า บริษัท X จำกัด"
    r"ข้าพเจ้า\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    # shareholder/financial: "ชื่อ บริษัท X จำกัด"
    r"ชื่อ\s+(บริษัท[^\n]+?(?:จำกัด|มหาชน)(?:\s*\(มหาชน\))?)",
    # ภาษาไทย header
    r"ชื่อ\s*\(ภาษาไทย\)\s*[:：]?\s*(บริษัท[^\n]+|ห้างหุ้นส่วน[^\n]+)",
    # full line standalone
    r"^(บริษัท\s+[^\n]+?\s+จำกัด(?:\s*\(มหาชน\))?)\s*$",
    # ห้างหุ้นส่วน
    r"(ห้างหุ้นส่วน(?:จำกัด|สามัญ)[^\n]+?(?:จำกัด|$))",
]


def _extract_company_name(text: str) -> str:
    if not text:
        return ""
    for pat in _NAME_PATTERNS:
        for m in re.finditer(pat, text, re.MULTILINE):
            name = m.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            name = name.strip(" :-")
            # ถ้าตามด้วย "ชื่อสถานประกอบการ..." (text ติดมา) ตัด
            name = re.split(r"ชื่อสถาน|วันที่จดทะเบียน|ประเภท|ที่ตั้ง", name)[0].strip()
            if "บริษัท" in name or "ห้างหุ้นส่วน" in name or "หจก" in name:
                name = re.sub(r"\s+\d{13}.*$", "", name)
                return name
    return ""


def _extract_name_from_zip(zip_path: str) -> str:
    """fallback: ใช้ชื่อไฟล์ ZIP เช่น 'บริษัท วันม๊อบบี้ จำกัด.zip' → 'บริษัท วันม๊อบบี้ จำกัด'"""
    if not zip_path:
        return ""
    base = os.path.splitext(os.path.basename(zip_path))[0]
    # ตัด tax_id, bid_id ออก
    base = re.sub(r"\b\d{10,}\b", "", base).strip(" _-")
    if "บริษัท" in base or "ห้างหุ้นส่วน" in base or "หจก" in base:
        return re.sub(r"\s+", " ", base).strip()
    return ""


# ─── directors ───────────────────────────────────────────────────────────────

# Title prefix — รองรับ "น.." กรณี font subset (ตัว "ส" หาย)
# เช่น "น..มนต์ธีตา" จริงๆ คือ "น.ส.มนต์ธีตา"
_TITLE_ALT = r"(?:นาย|นาง|น\.ส?\.?|นางสาว|Mr\.?|Mrs\.?|Miss)"

_DIR_TITLE_RE = re.compile(r"^" + _TITLE_ALT + r"\s*\S")


def _extract_directors(text: str) -> list[str]:
    """ดึงรายชื่อกรรมการจาก juristic_information / หนังสือจดทะเบียน"""
    if not text:
        return []
    # block "รายชื่อกรรมการ" → "กรรมการซึ่งลงชื่อ" หรืออื่นๆ
    patterns = [
        r"รายชื่อกรรมการ\s+([\s\S]+?)(?:กรรมการซึ่งลงชื่อ|ข้อจำกัด|รายชื่อผู้|จำนวนกรรมการ\s+\d)",
        r"กรรมการ(?:บริษัท)?\s*[:：]\s*([\s\S]+?)(?:ข้อจำกัด|ลายมือชื่อ|ผู้มีอำนาจ)",
        # garbled-font variant: "รายชื่ĂดังตĂไปนี้" / "ตามรายชื่อดังต่อไปนี้"
        r"ตามรายชื่[^\s]{1,3}ดังต[^\s]{1,3}ไปนี้\s+([\s\S]+?)"
        r"(?:กรรมการ(?:ขĂง|ของ).+?ลง|ข้อจำกัด|จำนวนผู้ถือหุ้น|\Z)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        raw = m.group(1)
        dirs: list[str] = []
        for ln in raw.splitlines():
            ln = ln.strip().rstrip("/").strip()
            ln = re.sub(r"^\d+[\.\)]\s*", "", ln)
            ln = re.sub(r"\s+", " ", ln).strip()
            if not ln:
                continue
            if _DIR_TITLE_RE.match(ln):
                ln = re.split(r"[,/]", ln)[0].strip()
                ln = re.sub(r"\s+และ\s+.*$", "", ln).strip()
                # validate: ไม่ใช่ "นายทะเบียน", "นายหน้า" ฯลฯ
                if ln and _is_real_name(ln) and ln not in dirs:
                    dirs.append(ln)
        if dirs:
            return dirs[:20]

    # fallback (เผื่อ font subset): scan whole text สำหรับ pattern
    # "<n>. นาย/นาง/น.ส.<name> <lastname>" — title อาจติดชื่อ
    # รองรับ multi-column layout (เช่น "1. นายA B 2. นายC D" ในบรรทัดเดียว)
    dirs2: list[str] = []
    for m2 in re.finditer(
        # รองรับทั้งเลขอาหรับและเลขไทย
        r"[\d๐-๙]+\s*[\.\),:]\s*(" + _TITLE_ALT + r"\s*\S+\s+\S+)",
        text,
    ):
        name = re.sub(r"\s+", " ", m2.group(1)).strip()
        # ตัด trailing เลขลำดับ
        name = re.sub(r"\s+[\d๐-๙]+[\.\)]\s*$", "", name).strip()
        # ตัด trailing "เลขประจำตัวประชาชน..."
        name = re.split(r"เลข(?:ประจำ|ประจํา|ที่|ประชาชน|บัตร)", name, maxsplit=1)[0].strip()
        # ตัด trailing คำเชื่อม
        name = re.split(
            r"\s+(?:และ|หรือ|ลง|ที่|ซึ่ง|รับรอง|รวม)\b",
            name, maxsplit=1,
        )[0].strip()
        # validate: เป็นชื่อคนจริง (ไม่ใช่ นายทะเบียน, นายหน้า ฯลฯ)
        if name and _is_real_name(name) and name not in dirs2:
            dirs2.append(name)
    if len(dirs2) >= 1:
        return dirs2[:20]
    return []


# ─── authority (ผู้มีอำนาจควบคุม) ────────────────────────────────────────────

# คำที่ขึ้นต้นด้วย "นาย/นาง" แต่ไม่ใช่ชื่อคน
# ห้ามใส่ single chars (เช่น "ก") — จะ match ชื่อจริงที่ขึ้นต้นด้วย ก เช่น "กรวัฒน์"
_NOT_PERSON_WORDS = {
    "หน้า", "จ้าง", "ทะเบียน", "ทุน", "ห้าง",
    "ภาษี", "งาน", "เจตน์", "ภูมิ", "เวร",
    # คำในเอกสารราชการ
    "ทะเบียนอาจ", "ทะเบียนได้", "ทะเบียนใน",
    "หน้าที่",
}


def _name_key(name: str) -> str:
    """normalize ชื่อสำหรับ compare: ตัด title + space + dot + ส่วนที่ติด"""
    if not name:
        return ""
    # ตัด title (รวม "น..", "น.ส", ฯลฯ)
    n = re.sub(r"^(?:นางสาว|น\.ส?\.?|นาย|นาง|Mr\.?|Mrs\.?|Miss)\s*", "", name)
    # ตัด space / dot / dash / parens
    return re.sub(r"[\s\.\-\(\)\[\]]", "", n)


def _predict_name(ocr_name: str, references: list[str],
                  threshold: float = 0.55) -> tuple[str, float]:
    """
    คาดคะเนชื่อจริงจาก OCR text โดยเทียบกับ reference list (เช่น directors)

    เช่น OCR ได้ "นางสาวยงยุทธศายลำเพาะ" + refs=["น.ส.ยงยุทธ สายลำเพาะ"]
    → คืน ("น.ส.ยงยุทธ สายลำเพาะ", 0.85)

    Returns:
        (best_match, score) — ถ้า score < threshold คืน ocr_name เดิม
    """
    if not references:
        return ocr_name, 0.0
    ocr_key = _name_key(ocr_name)
    if not ocr_key:
        return ocr_name, 0.0
    best_ref = ocr_name
    best_score = 0.0
    for ref in references:
        ref_key = _name_key(ref)
        if not ref_key:
            continue
        score = SequenceMatcher(None, ocr_key, ref_key).ratio()
        if score > best_score:
            best_score = score
            best_ref = ref
    if best_score >= threshold:
        return best_ref, best_score
    return ocr_name, best_score


def _is_real_name(name: str) -> bool:
    """ตรวจว่า 'นายXXX' เป็นชื่อคนจริง (ไม่ใช่คำว่า นายหน้า, นายทะเบียน, นายจ้าง ฯลฯ)"""
    if not name or len(name) < 5:
        return False
    tokens = name.split()
    if len(tokens) < 1:
        return False
    title = tokens[0]
    first = tokens[1] if len(tokens) > 1 else ""
    # ตัดคำนำหน้าออก (กรณีติดกับชื่อ "นายX")
    # รองรับ "น.." (ตัว ส หาย จาก font subset) เช่น "น..มนต์ธีตา"
    for t in ("นางสาว", "น.ส.", "น..", "น.ส", "น.", "นาย", "นาง",
              "Mr.", "Mr", "Mrs.", "Mrs", "Miss"):
        if title.startswith(t):
            first_after = title[len(t):]
            if first_after:
                first = first_after
            break
    if not first:
        return False
    # คำหลังคำนำหน้าต้องไม่อยู่ใน stop-list / ไม่ขึ้นต้นด้วยคำใน stop-list
    for stop in _NOT_PERSON_WORDS:
        if first == stop or first.startswith(stop):
            return False
    # ต้องเป็นภาษาไทยอย่างน้อย 2 ตัวอักษร
    if not re.match(r"^[ก-๛]{2,}", first):
        return False
    return True


def _extract_authority(vf: VendorFiles,
                       sl_authority_files: list[str] = None,
                       unread: list = None,
                       directors: list[str] = None) -> str:
    """
    ดึงรายชื่อผู้มีอำนาจควบคุมจากไฟล์ที่ submitList ระบุไว้เท่านั้น

    Concepts (ต้องแยกให้ชัด — ห้ามปน):
      1. กรรมการ (registered directors)        ← juristic_information
      2. ผู้มีอำนาจควบคุม (controlling persons) ← submitList row "ผู้มีอำนาจควบคุม"
      3. ผู้ถือหุ้นรายใหญ่ (major shareholders) ← shareholder file >25%
      ── "ผู้มีอำนาจลงนาม" (signatory) ไม่เกี่ยวกับระบบนี้ ──

    Rule:
      - ใช้เฉพาะไฟล์ใน submitList หมวด "ผู้มีอำนาจควบคุม"
      - ไม่ใช้ "กรรมการซึ่งลงชื่อผูกพัน" (= ผู้มีอำนาจลงนาม คนละหมวด)
      - ไม่ใช้ directors เป็น fallback (กรรมการ ≠ ผู้มีอำนาจควบคุม)
      - ถ้าไม่มีไฟล์ใน submitList → "-"
      - ถ้ามีไฟล์แต่อ่านไม่ออก → "-" (มี warning ในหมายเหตุให้ user OCR เอง)

    Name prediction:
      - หลัง extract ชื่อจาก OCR ที่อาจเพี้ยน → fuzzy-match กับ `directors`
      - ถ้า similarity ≥ 0.55 → แทนด้วยชื่อสะอาดจาก directors list
      - ใช้แค่เป็น text cleanup — ไม่กระทบการตัดสิน ✓/-
    """
    # Fallback: ถ้า submitList ไม่มี → scan ไฟล์ใน ZIP ที่ชื่อมี "ผู้มีอำนาจ"/"ควบคุม"
    files_to_check = list(sl_authority_files or [])
    if not files_to_check:
        for safe, orig in vf.original_names.items():
            low_orig = orig.lower()
            if ("ผู้มีอำนาจ" in orig or "ผู้มีอำนาจ" in orig
                    or "ควบคุม" in orig
                    or "authority" in low_orig
                    or "controlling" in low_orig):
                # skip files ที่เป็น "ผู้มีอำนาจลงนาม" (signatory) — คนละหมวด
                if "ลงนาม" in orig and "ควบคุม" not in orig:
                    continue
                files_to_check.append(orig)

    if not files_to_check:
        return "-"

    names: list[str] = []
    for fname in files_to_check:
        p = find_by_original(vf, fname)
        if not p:
            continue
        t = _read(p, unread=unread, label="ผู้มีอำนาจควบคุม")
        if not t:
            continue
        # ดึงเฉพาะ section "ผู้มีอำนาจควบคุม" — หยุดที่ section อื่น
        # (กันไฟล์ที่รวม "ผู้มีอำนาจลงนาม" / "กรรมการ" / "ผู้ถือหุ้น" ไว้ด้วยกัน)
        block = t
        # หา "ผู้มีอำนาจควบคุม" → ไปจนถึง section ถัดไป
        sec_m = re.search(
            r"ผู้มี(?:อำนาจ|อํานาจ)ควบคุม\s*([\s\S]+?)"
            r"(?:รายชื่อ(?:ผู้มี)?(?:อำนาจ|อํานาจ)ลงนาม"
            r"|รายชื่อหุ้นส่วน"
            r"|รายชื่อกรรมการ"
            r"|รายชื่อผู้ถือ"
            r"|รายชื่อผู้จัด"
            r"|รับรองไว้\s*ณ"
            r"|รับรองว่า"
            r"|\Z)",
            t,
        )
        if sec_m:
            block = sec_m.group(1)
        # หา ชื่อในรูป "<n>. หรือ <n>) แล้ว นาย/นาง/น.ส./นางสาว <name>"
        # บังคับมี numbered prefix เพื่อกัน signature/footer ที่ใส่ชื่อซ้ำ
        # ขยาย char limit สูงขึ้น — กรณี OCR รวม first+last เป็นคำเดียว
        # (เช่น "นายธารินทร์จงประเจิด" = 20 chars, "นางชัยลดาตันติเวชกุล" = 20 chars)
        for nm in re.finditer(
            # numbered prefix: รองรับทั้งเลขอาหรับ (1.2.3) และเลขไทย (๑.๒.๓)
            r"[\d๐-๙]+\s*[\.\),:]\s*(" + _TITLE_ALT +
            r"\s*[ก-๛]{2,40}"
            r"(?:\s+(?!และ|หรือ|กับ|พร้อม|ลง|ที่|ซึ่ง|รับรอง|รวม|มี|ใน|ทั้ง|ขอ|ลายมือ"
            r"|กรรมการ|ประทับ|ลายมือชื่อ|ตา|คนใด|คนหนึ่ง|สำคัญ|เลข|ประจำ|ประชาชน)"
            r"[ก-๛]{1,40}){0,3}"
            r")",
            block,
        ):
            name = re.sub(r"\s+", " ", nm.group(1)).strip()
            # ตัด trailing "เลข..." (ส่วน "เลขประจำตัวประชาชน...")
            name = re.split(r"เลข(?:ประจำ|ประจํา|ที่|ประชาชน|บัตร)", name, maxsplit=1)[0].strip()
            name = re.split(
                r"\s+(?:และ|หรือ|กับ|พร้อม|ที่|ซึ่ง|ลง|ตา|รับรอง|มี|ใน|รวม|ทั้ง|ขอ|ลายมือ)",
                name, maxsplit=1,
            )[0].strip()
            name = re.split(r"(?:หรือ|และ)" + _TITLE_ALT, name, maxsplit=1)[0].strip()
            name = re.sub(r"\s+[ก-๛]{1}\.?$", "", name).strip()
            # ── คาดคะเนชื่อ: ถ้า fuzzy-match กับ directors ผ่าน threshold
            #    → ใช้ชื่อสะอาดจาก directors แทน OCR ที่อาจเพี้ยน
            if directors:
                predicted, score = _predict_name(name, directors)
                if score >= 0.55:
                    name = predicted
            # normalize spaces ก่อนเช็ค dup (เผื่อ PDF artifact "นายอภิศักด ิ์")
            norm = re.sub(r"\s+", "", name)
            if _is_real_name(name) and norm not in {re.sub(r"\s+", "", x) for x in names}:
                names.append(name)
        if names:
            break  # เจอชื่อแล้ว ไม่ต้องดูไฟล์อื่น

    if not names:
        return "-"
    return "\n".join(f"{i+1}. {n}" for i, n in enumerate(names[:10]))


# ─── price extraction ────────────────────────────────────────────────────────

_PRICE_CONTEXT_PATTERNS = [
    r"(?:ราคาที่เสนอ|ราคารวม|รวมทั้งสิ้น|รวมเป็นเงิน|ยอดรวม|จำนวนเงินที่เสนอ|เสนอราคาเป็นเงิน)"
    r"[^\d๐-๙]{0,30}([\d,๐-๙]+(?:\.[\d๐-๙]+)?)",
    r"([\d,๐-๙]+(?:\.[\d๐-๙]+)?)\s*บาท",
]

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def _extract_price(text: str, budget: float = 0) -> float:
    if not text:
        return 0.0
    candidates: dict[float, int] = {}
    for pat in _PRICE_CONTEXT_PATTERNS:
        for m in re.finditer(pat, text):
            raw = m.group(1).translate(THAI_DIGITS).replace(",", "")
            try:
                val = float(raw)
            except ValueError:
                continue
            if not (100_000 <= val <= 100_000_000):
                continue
            candidates[val] = candidates.get(val, 0) + 1

    if not candidates:
        return 0.0

    if budget > 0:
        near = {v: c for v, c in candidates.items() if v <= budget * 1.5}
        if near:
            candidates = near

    if budget > 0:
        return max(candidates.items(),
                   key=lambda kv: (kv[1], -abs(kv[0] - budget)))[0]
    return max(candidates.items(), key=lambda kv: kv[1])[0]


# ─── ส่วนที่ 2: identify by filename patterns ───────────────────────────────

# pattern เฉพาะของ LINE Corporation cert — ต้องเป็นเอกสารรับรอง "ตัวแทน/agency"
# ไม่ใช่แค่ไฟล์ที่มีคำว่า "LINE" (เช่น สเปคโครงการ "LINE Official Account")
_LINE_PATTERNS = [
    r"verified[_ ]agency",
    r"verfied[_ ]agency",      # typo
    r"verified[_ ]partner",
    r"b2b[_ ]verified",
    r"line[_ ]agency",
    r"agency[_ ]of[_ ]line",
    r"agency[_ ]of[_ ]line[_ ]service",
    r"เอกสารรับรองการเป็นเอเจนซี",
    r"รับรองเอเจนซี",
    r"รับรอง.*line[_ ]agency",
    r"หนังสือรับรอง.*line",
]

# ถ้า filename match patterns เหล่านี้ → ไม่นับเป็น LINE cert (เป็น catalogue/spec)
_LINE_NEGATIVE_PATTERNS = [
    r"คุณลักษณะ",          # รายละเอียดคุณลักษณะเฉพาะ
    r"แคตตาล็อ[กค]",
    r"catalogue",
    r"catalog",
    r"\bspec(ification)?\b",
    r"ข้อเสนอทางเทคนิค",
    r"google[_ ]slides",
    r"comply[_ ]tor",
    r"^qt\d",              # Quotation auto-named files
    r"obec[-_ ]line",      # OBEC spec files
]

_WORK_CERT_PATTERNS = [
    r"หนังสือรับรองผลงาน",
    r"รับรองผลงาน",
    r"รับรองคู่ฉบับ",
    r"รับรองสัญญา",
    r"ใบรับรองผลงาน",
]

_CATALOGUE_PATTERNS = [
    r"แคตตาล็อ[กค]",       # รองรับทั้ง 'แคตตาล็อก' และ 'แคตตาล็อค'
    r"แคตตาลอ[กค]",
    r"catalogue",
    r"catalog",
    r"คุณลักษณะ",
    r"คุณสมบัติเฉพาะ",     # MA: "ตารางเปรียบเทียบคุณสมบัติเฉพาะ"
    r"ตารางเปรียบเทียบ",
    r"ข้อเสนอทางเทคนิค",
    r"comply\s*tor",
    r"^qt\d",
    r"obec[-_ ]?line",     # LINE OA spec sheet (มักรวม catalogue)
    r"line[_ ]oa.*spec",
    r"google[_ ]slides",   # vendor บางรายส่ง slide เป็น catalogue
    r"spec[_ ]?sheet",
]

_SME_PATTERNS = [
    r"^sme[_\- ]",
    r"sme_\d{10,}",
    r"วิสาหกิจขนาดกลาง",
]

_MIT_PATTERNS = [
    r"made\s*in\s*thailand",
    r"\bmit\b",
    r"^mit[_\- ]",
]

_POA_PATTERNS = [
    r"มอบอำนาจ",
    r"^poa[-_ ]",
    r"power\s*of\s*attorney",
]

# หลักประกัน (bid guarantee / bank guarantee) — สำคัญใน MA/งานจ้าง
_GUARANTEE_PATTERNS = [
    r"หลักประกัน",
    r"bank[_ ]guarantee",
    r"bid[_ ]bond",
    r"performance[_ ]bond",
]

# บุคลากร (key personnel) — สำคัญใน MA, จ้างที่ปรึกษา
_PERSONNEL_PATTERNS = [
    r"บุคลากร",
    r"^\d*บุคลากร[_ ]",
    r"resume",
    r"cv[_ ]",
    r"key[_ ]personnel",
    r"ประวัติส่วนตัว",
    r"ประวัติบุคลากร",
]

# โครงสร้างบริหารโครงการ / แผนการดำเนินงาน
_MGMT_PATTERNS = [
    r"โครงสร้าง.*บริหาร",
    r"โครงสร้าง.*โครงการ",
    r"แผน(?:การดำเนินงาน|งาน|ปฏิบัติงาน)",
    r"project[_ ](?:management|structure|plan)",
    r"work[_ ]plan",
    r"วิธีการ(?:ทำงาน|ดำเนินงาน)",
    r"methodology",
]


def _any_match(text: str, patterns: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    for p in patterns:
        if re.search(p, low, re.IGNORECASE):
            return True
    return False


def _check_section2(sl_files: list[str], zip_files: list[str],
                    patterns: list[str],
                    negative_patterns: list[str] = None) -> tuple[str, str]:
    """
    ตัดสิน ✓/- สำหรับคอลัมน์ Section 2 — อ้าง submitList ก่อนเสมอ

    Logic:
      1. ถ้า submitList ส่วนที่ 2 มี file ที่ match pattern → ✓ (source = submitList)
      2. ถ้า submitList ส่วนที่ 2 ไม่มี match แต่มีไฟล์ระบุไว้บ้าง → "-"
         (vendor ไม่ได้ยื่นเอกสารหมวดนี้ตาม submitList)
      3. ถ้า submitList Section 2 ว่างเลย (parser ล้มเหลว / project ไม่มี Section 2)
         → fallback เช็คใน ZIP scan (relaxed)

    Returns:
        (status, source)  เช่น ("✓", "submitList") หรือ ("-", "")
    """
    if sl_files:
        # มีข้อมูล Section 2 จาก submitList — ใช้เป็น primary
        if _has_in_files(sl_files, patterns, negative_patterns):
            return "✓", "submitList"
        return "-", ""
    # fallback: ไม่มี Section 2 ใน submitList → scan ZIP
    if _has_in_files(zip_files, patterns, negative_patterns):
        return "✓", "ZIP scan (no submitList)"
    return "-", ""


def _has_in_files(file_list: list[str], patterns: list[str],
                  negative_patterns: list[str] = None) -> bool:
    """
    True ถ้ามีไฟล์ใดๆ ที่:
      - ชื่อ match `patterns` (positive)
      - และไม่ match `negative_patterns` (ใช้กรอง false positives)
    """
    for f in file_list:
        if not _any_match(f, patterns):
            continue
        if negative_patterns and _any_match(f, negative_patterns):
            continue   # skip — เป็น catalogue/spec ไม่ใช่ cert
        return True
    return False


def _collect_part2_candidates(sl: SubmitList, vf: VendorFiles) -> list[str]:
    """รวม filename จาก submitList ส่วนที่ 2 + ไฟล์จริงใน ZIP ที่ไม่อยู่ในส่วนที่ 1"""
    part1_files: set[str] = set()
    for entry in sl.part1.values():
        for f in entry.files:
            part1_files.add(_norm(f))

    candidates = list(sl.part2_files)
    # บวก ไฟล์ใน ZIP ที่ไม่ใช่ submitList และไม่อยู่ใน part1
    for safe, orig in vf.original_names.items():
        if orig.lower() == "submitlist.pdf":
            continue
        if _norm(orig) in part1_files:
            continue
        if orig not in candidates:
            candidates.append(orig)
    return candidates


# ─── main analyzer ───────────────────────────────────────────────────────────

def analyze_vendor(vf: VendorFiles, vendor_no: int, budget: float = 0) -> VendorData:
    d = VendorData(no=vendor_no, tax_id=vf.tax_id)

    # ── 0. parse submitList ─────────────────────────────────────────────────
    sl = parse_submitlist(vf.submitlist_path) if vf.submitlist_path else SubmitList()

    # ── 1. DIRECTORS (รายชื่อกรรมการ) ───────────────────────────────────────
    # ★ SOURCE: submitList row 1 "สำเนาหนังสือรับรองการจดทะเบียนนิติบุคคล"
    # อ่านไฟล์ในคอลัมน์ "ไฟล์ข้อมูล" ของบรรทัดที่ 1 → extract "รายชื่อกรรมการ"
    # (กัน OBJMGR/Objective — เป็นวัตถุประสงค์ ไม่ใช่ทะเบียนนิติบุคคล)
    info_text = ""
    cert_candidates: list[tuple[str, str]] = []  # (label, text)
    for fname in sl_get_files(sl, "cert"):  # ← submitList row 1
        p = find_by_original(vf, fname)
        if p:
            t = _read(p, unread=d.unread_files, label="หนังสือรับรอง")
            if t:
                cert_candidates.append((fname, t))

    # fallback: หา juristic_information แบบ keyword
    if not cert_candidates:
        p = find_file(vf, "juristic_information")
        if p:
            cert_candidates.append(("juristic_information",
                                    _read(p, unread=d.unread_files,
                                          label="หนังสือรับรอง")))

    # เลือกไฟล์ที่ extract directors ได้
    best_dirs: list[str] = []
    for label, t in cert_candidates:
        # skip OBJMGR/Objective — เป็นไฟล์วัตถุประสงค์ ไม่ใช่ทะเบียนกรรมการ
        if re.search(r"objmgr|objective|วัตถุประสงค์", label, re.IGNORECASE):
            continue
        dirs = _extract_directors(t)
        if len(dirs) > len(best_dirs):
            best_dirs = dirs
            info_text = t

    # ถ้ายังไม่เจอ → ใช้ตัวยาวที่สุด (เผื่อ extract directors ไม่ได้แต่ยังได้ชื่อ)
    if not info_text and cert_candidates:
        info_text = max(cert_candidates, key=lambda x: len(x[1]))[1]

    if info_text:
        d.name = _extract_company_name(info_text)
        d.directors = best_dirs or _extract_directors(info_text)

    # fallback ชื่อบริษัท — ลองหลายแหล่งตามลำดับความน่าเชื่อถือ
    fallback_sources: list[tuple[str, str]] = []
    # 1. Quotation (มี "ข้าพเจ้า บริษัท X" ชัดเจน)
    q = find_file(vf, "Quotation")
    if q:
        fallback_sources.append(("Quotation", _read(q)))
    # 2. shareholder file (มี "ชื่อ บริษัท X")
    for fname in sl_get_files(sl, "shareholder_doc"):
        p = find_by_original(vf, fname)
        if p:
            fallback_sources.append(("shareholder", _read(p)))
            break
    if not any(s == "shareholder" for s, _ in fallback_sources):
        p = find_file(vf, "shareholder")
        if p:
            fallback_sources.append(("shareholder", _read(p)))
    # 3. director_list file
    for fname in sl_get_files(sl, "director_list"):
        p = find_by_original(vf, fname)
        if p:
            fallback_sources.append(("director_list", _read(p)))
            break

    for _src, txt in fallback_sources:
        if d.name:
            break
        n = _extract_company_name(txt)
        if n:
            d.name = n

    # 4. ลองทุก PDF ที่เหลือ
    if not d.name:
        for safe, _orig in list_files(vf):
            p = os.path.join(vf.extract_dir, safe)
            if not p.lower().endswith(".pdf"):
                continue
            n = _extract_company_name(_read(p))
            if n:
                d.name = n
                break

    # 5. fallback สุดท้าย: ชื่อ ZIP file
    if not d.name:
        d.name = _extract_name_from_zip(vf.source_zip)

    # ── 2. AUTHORITY (ผู้มีอำนาจควบคุม) ─────────────────────────────────────
    # ★ SOURCE: submitList row 5 "ผู้มีอำนาจควบคุม"
    # ใช้ไฟล์ในคอลัมน์ "ไฟล์ข้อมูล" ของบรรทัดที่ 5 เท่านั้น
    #   - ไม่ใช้ "กรรมการลงชื่อผูกพัน" (= ผู้มีอำนาจลงนาม คนละหมวด)
    #   - ไม่ใช้ directors เป็น fallback (กรรมการ ≠ ผู้มีอำนาจควบคุม)
    # ส่ง directors เพื่อใช้ "คาดคะเน" ชื่อ OCR ที่เพี้ยน
    #   (เช่น "นางสาวยงยุทธศายลำเพาะ" → fuzzy match กับ directors
    #    ["น.ส.ยงยุทธ สายลำเพาะ"] → แทนด้วยชื่อสะอาด)
    d.authority = _extract_authority(
        vf,
        sl_authority_files=sl_get_files(sl, "authority_doc"),  # ← submitList row 5
        unread=d.unread_files,
        directors=d.directors,
    )

    # ── 3. SHAREHOLDERS (ผู้ถือหุ้นรายใหญ่) ─────────────────────────────────
    # ★ SOURCE: submitList row 4 "บัญชีผู้ถือหุ้นรายใหญ่"
    # ใช้ไฟล์ในคอลัมน์ "ไฟล์ข้อมูล" ของบรรทัดที่ 4
    # ลำดับ:
    #   1. ไฟล์ที่ submitList ระบุ (row 4)
    #      → เรียงตามวันที่ "ออกเอกสาร / ข้อมูล ณ" ใหม่สุดก่อน
    #      → ลองไฟล์ใหม่สุดก่อน; ถ้า extract ไม่ได้ ค่อยลองไฟล์เก่ากว่า
    #   2. ถ้าไม่มี → fallback ค้น keyword "ผู้ถือหุ้น" / "shareholder" / "บอจ5"
    has_major_holder = False
    holders: list = []
    sl_sh_files = sl_get_files(sl, "shareholder_doc")  # ← submitList row 4
    # สร้าง list (date, path) เรียงใหม่ก่อน
    sh_candidates: list[tuple[Optional[_dt.date], str]] = []
    if sl_sh_files:
        for fn in sl_sh_files:
            p = find_by_original(vf, fn)
            if not p:
                continue
            text_tmp = _read(p, unread=d.unread_files, label="ผู้ถือหุ้น")
            sh_candidates.append((_extract_latest_date(text_tmp), p))
    # fallback: ค้น keyword
    if not sh_candidates:
        for kw in ("ผู้ถือหุ้น", "shareholder", "บอจ5", "บอจ.5"):
            p = find_file(vf, kw)
            if p:
                sh_candidates.append((None, p))
                break
    # เรียงใหม่ก่อน (None ไปท้าย) แล้วลองทีละไฟล์
    sh_candidates.sort(key=lambda x: x[0] or _dt.date.min, reverse=True)
    for _date, p in sh_candidates:
        sh_text = _read(p, unread=d.unread_files, label="ผู้ถือหุ้น")
        sh_tables = _read_tables(p)
        h = find_shareholder_over(sh_text, threshold=25.0, tables=sh_tables)
        # ★ ถ้า text-based ไม่เจอ → force OCR (zoom DPI สูง)
        # เหตุผล: บอจ.5 บางฉบับฝัง font ปิด ทำให้ pdfplumber อ่านได้แต่ header
        # วน loop ไม่เห็นแถวจริง — ต้อง render เป็นภาพแล้ว OCR
        if not h:
            ocr_text = force_ocr_pdf(p, dpi=900)
            if ocr_text:
                h = find_shareholder_over(ocr_text, threshold=25.0, tables=None)
                if h:
                    # อ่านได้แล้ว — ลบ entry จาก unread_files
                    base = os.path.basename(p)
                    d.unread_files = [u for u in d.unread_files
                                      if not u.endswith(base)]
        if h:
            holders = h
            break  # ใช้ไฟล์ใหม่สุดที่ extract ได้
    if holders:
        has_major_holder = True
        d.shareholders = "\n".join(f"{n} ({p:.2f}%)" for n, p in holders)

    # ── 3. มูลค่าสุทธิ ──────────────────────────────────────────────────────
    fin_path = None
    for fname in sl_get_files(sl, "financial"):
        p = find_by_original(vf, fname)
        if p:
            fin_path = p
            break
    if not fin_path:
        fin_path = find_file(vf, "financial") or find_file(vf, "งบการเงิน")

    if fin_path:
        val, sign = extract_net_worth(
            _read(fin_path, unread=d.unread_files, label="งบการเงิน"))
        if val is not None:
            d.net_worth = val
            d.net_worth_sign = sign

    # ── 4. ราคาเสนอ ─────────────────────────────────────────────────────────
    q_path = find_file(vf, "Quotation")
    if q_path:
        d.price = _extract_price(_read(q_path), budget=budget)

    # ── 5. ส่วนที่ 1: ตรวจ ✓/- ───────────────────────────────────────────────
    # ★ RULE: อ้างอิง submitList ส่วนที่ 1 ก่อนเสมอ
    #   ★ row N ของ submitList = แต่ละคอลัมน์ใน Excel ส่วนที่ 1
    #     ✓ = submitList row N มีไฟล์ระบุไว้ (vendor ยื่นเอกสารหมวดนี้)
    #     - = row N ว่าง / "ไม่มีเอกสารแนบ"
    #   ZIP scan = fallback เฉพาะกรณี submitList parse ไม่ได้
    if sl.parsed_ok:
        d.cert            = CHECK if sl_has_doc(sl, "cert")            else DASH  # row 1
        d.memo            = CHECK if sl_has_doc(sl, "memo")            else DASH  # row 2
        d.director_list   = CHECK if sl_has_doc(sl, "director_list")   else DASH  # row 3
        d.authority_doc   = CHECK if sl_has_doc(sl, "authority_doc")   else DASH  # row 5
        d.credit          = CHECK if sl_has_doc(sl, "credit")          else DASH  # row 8
        d.trade_reg       = CHECK if sl_has_doc(sl, "trade_reg")       else DASH  # row 9
        d.vat             = CHECK if sl_has_doc(sl, "vat")             else DASH  # row 10
    else:
        # ⚠ fallback เฉพาะเมื่อ submitList parse ไม่ได้ — เดาจากชื่อไฟล์
        d.cert            = CHECK if find_file(vf, "juristic_information") else DASH
        d.memo            = CHECK if (find_file(vf, "juristic_document")
                                       or find_file(vf, "MEMIMG")
                                       or find_file(vf, "บริคณห์")) else DASH
        d.director_list   = d.cert
        d.authority_doc   = CHECK if (find_file(vf, "ผู้มีอำนาจควบคุม")
                                       or find_file(vf, "OBJMGR")) else DASH
        d.trade_reg       = CHECK if (find_file(vf, "ทะเบียนพาณิชย์")
                                       or find_file(vf, "ใบสำคัญ")) else DASH
        d.vat             = CHECK if (find_file(vf, "ภพ20") or find_file(vf, "ภพ.20")
                                       or find_file(vf, "ภ.พ.20")
                                       or find_file(vf, "ภ พ 20")) else DASH

    # ผู้ถือหุ้นรายใหญ่ — ✓ เฉพาะเมื่อมี holder > 25% จริง
    # (ไม่ใช่แค่ยื่นไฟล์ shareholder)
    d.shareholder_doc = CHECK if has_major_holder else DASH

    # ── 6. ส่วนที่ 2: ตรวจ ✓/- ───────────────────────────────────────────────
    # ★ RULE: อ้างอิง submitList ส่วนที่ 2 ก่อนเสมอ
    #   - ถ้า submitList ระบุไฟล์ตรง pattern → ✓
    #   - ถ้า submitList ระบุไฟล์ แต่ไม่มีไฟล์ตรง pattern → "-"
    #     (vendor ไม่ได้ยื่นเอกสารหมวดนี้ตามสารบัญ)
    #   - ถ้า submitList Section 2 ว่าง (parser ล้มเหลว) → fallback scan ZIP
    sl_part2 = list(sl.part2_files)            # ★ files จาก submitList Section 2
    zip_extras = _collect_part2_candidates(sl, vf)   # submitList + ZIP scan รวม

    d.catalogue,    _ = _check_section2(sl_part2, zip_extras, _CATALOGUE_PATTERNS)
    d.line_license, _ = _check_section2(sl_part2, zip_extras, _LINE_PATTERNS,
                                          _LINE_NEGATIVE_PATTERNS)
    d.sme,          _ = _check_section2(sl_part2, zip_extras, _SME_PATTERNS)
    d.mit,          _ = _check_section2(sl_part2, zip_extras, _MIT_PATTERNS)
    d.work_cert,    _ = _check_section2(sl_part2, zip_extras, _WORK_CERT_PATTERNS)
    d.poa,          _ = _check_section2(sl_part2, zip_extras, _POA_PATTERNS)
    d.guarantee,    _ = _check_section2(sl_part2, zip_extras, _GUARANTEE_PATTERNS)
    d.personnel,    _ = _check_section2(sl_part2, zip_extras, _PERSONNEL_PATTERNS)
    d.project_mgmt, _ = _check_section2(sl_part2, zip_extras, _MGMT_PATTERNS)

    # dedupe unread files (เก็บลำดับเดิม)
    if d.unread_files:
        seen: set = set()
        deduped: list[str] = []
        for f in d.unread_files:
            if f not in seen:
                seen.add(f)
                deduped.append(f)
        d.unread_files = deduped

    return d


def analyze_all(vendor_files: list[VendorFiles], budget: float = 0) -> list[VendorData]:
    results = []
    for i, vf in enumerate(vendor_files):
        print(f"  Analyzing {vf.vendor_id} (tax: {vf.tax_id})...")
        vd = analyze_vendor(vf, i + 1, budget=budget)
        results.append(vd)
        print(f"    -> {vd.name or '(ยังไม่ได้ชื่อ)'}, ราคา {vd.price:,.0f}")
    return results
