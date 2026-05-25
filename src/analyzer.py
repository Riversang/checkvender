"""
analyzer.py — วิเคราะห์เอกสารของผู้ยื่น 1 ราย

ใช้ submitList.pdf เป็น source of truth สำหรับการตรวจ ✓/-
(ไม่เดาจากชื่อไฟล์เป็นหลัก เพราะ false positive ง่าย)

content extraction ยังคงใช้ regex/pattern parsing สำหรับ:
  - ชื่อบริษัท / กรรมการ
  - ผู้ถือหุ้นรายใหญ่ (>25%) — คำนวณจากจำนวนหุ้น
  - ผู้มีอำนาจควบคุม
  - มูลค่าสุทธิ
  - ราคาเสนอ
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .extractor import VendorFiles, find_file, find_files, list_files, find_by_original
from .pdf_reader import (
    read_pdf_text,
    read_pdf_tables,
    extract_net_worth,
    find_shareholder_over,
    extract_thai_number,
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
    guarantee: str = DASH
    sme: str = DASH
    mit: str = DASH
    catalogue: str = DASH
    work_cert: str = DASH       # หนังสือรับรองผลงาน
    line_license: str = DASH    # Certificate/License (LINE)
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

_DIR_TITLE_RE = re.compile(
    r"^(นาย|นาง|น\.ส\.|นางสาว|Mr\.?|Mrs\.?|Miss)\s*\S"
)


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
                if ln and ln not in dirs:
                    dirs.append(ln)
        if dirs:
            return dirs[:20]

    # fallback (เผื่อ font subset): scan whole text สำหรับ pattern
    # "<n>. นาย/นาง/น.ส.<name> <lastname>" — title อาจติดชื่อ
    # รองรับ multi-column layout (เช่น "1. นายA B 2. นายC D" ในบรรทัดเดียว)
    # → ไม่ใช้ ^ anchor + จำกัด 2 tokens (firstname + lastname)
    dirs2: list[str] = []
    for m2 in re.finditer(
        r"\d+[\.\)]\s+((?:นาย|นาง|น\.ส\.|นางสาว|Mr\.?|Mrs\.?)"
        r"\s*\S+\s+\S+)",                 # title + firstname + lastname only
        text,
    ):
        name = re.sub(r"\s+", " ", m2.group(1)).strip()
        # ตัด trailing ตัวเลขลำดับที่หลุดมา (เช่น "นายA B 2.")
        name = re.sub(r"\s+\d+[\.\)]\s*$", "", name).strip()
        # ตัด trailing คำเชื่อม
        name = re.split(
            r"\s+(?:และ|หรือ|ลง|ที่|ซึ่ง|รับรอง|รวม)\b",
            name, maxsplit=1,
        )[0].strip()
        if name and name not in dirs2:
            dirs2.append(name)
    if len(dirs2) >= 2:
        return dirs2[:20]
    return []


# ─── authority (ผู้มีอำนาจควบคุม) ────────────────────────────────────────────

# คำที่ขึ้นต้นด้วย "นาย/นาง" แต่ไม่ใช่ชื่อคน
_NOT_PERSON_WORDS = {
    "หน้า", "จ้าง", "ทะเบียน", "ทุน", "ห้าง", "ก", "ข", "ค", "ทาน", "เวร",
    "ภาษี", "การ", "งาน", "เจตน์", "ภูมิ",
}


def _is_real_name(name: str) -> bool:
    """ตรวจว่า 'นายXXX' เป็นชื่อคนจริง (ไม่ใช่คำว่า นายหน้า, นายจ้าง ฯลฯ)"""
    if not name or len(name) < 5:
        return False
    # ต้องมีชื่อ + นามสกุล (อย่างน้อย 2 token)
    tokens = name.split()
    if len(tokens) < 2:
        return False
    title = tokens[0]
    first = tokens[1] if len(tokens) > 1 else ""
    # ตัดคำนำหน้าออก
    for t in ("นาย", "นาง", "น.ส.", "นางสาว", "Mr.", "Mr", "Mrs.", "Mrs", "Miss"):
        if title.startswith(t):
            first_after = title[len(t):]
            if first_after:
                first = first_after
            break
    # คำหลัง "นาย/นาง" ต้องไม่อยู่ใน stop-list
    if first in _NOT_PERSON_WORDS:
        return False
    # คำต้องเป็นภาษาไทยอย่างน้อย 2 ตัวอักษร
    if not re.match(r"^[ก-๛]{2,}", first):
        return False
    return True


def _extract_authority(vf: VendorFiles, info_text: str = "",
                       sl_authority_files: list[str] = None,
                       directors: list[str] = None,
                       unread: list = None) -> str:
    """
    ดึงรายชื่อผู้มีอำนาจควบคุมจาก:
      1. กรรมการที่ลงชื่อผูกพันบริษัท (จาก juristic_information)
      2. ไฟล์ "บัญชีผู้มีอำนาจควบคุม" (ที่ submitList ระบุไว้)
      3. ถ้าบริษัทใช้สูตร "กรรมการ X คนลงลายมือชื่อร่วมกัน" → คืน directors ทุกคน

    ไม่อ่าน OBJMGR — เพราะเป็นไฟล์ "วัตถุประสงค์" ไม่ใช่อำนาจ
    """
    names: list[str] = []
    use_all_dirs = False

    def _scan_text_for_names(text: str, into: list[str]):
        """หาชื่อในข้อความและเติมใส่ list (dedupe)"""
        # negative lookahead: หยุดถ้าคำถัดไปเป็น connector (และ/หรือ/etc)
        for nm in re.finditer(
            r"((?:นาย|นาง|น\.ส\.|นางสาว|Mr\.?|Mrs\.?)"
            r"\s*[ก-๛]{2,15}"           # first name
            r"(?:\s+(?!และ|หรือ|กับ|พร้อม|ลง|ที่|ซึ่ง|รับรอง|รวม|มี|ใน|ทั้ง|ขอ|ลายมือ"
            r"|กรรมการ|ประทับ|ลายมือชื่อ|ตา|คนใด|คนหนึ่ง|สำคัญ)"
            r"[ก-๛]{2,25}){0,2}"        # last name (+ optional middle), max 2 tokens
            r")",
            text,
        ):
            name = re.sub(r"\s+", " ", nm.group(1)).strip()
            # ตัด trailing: คำเชื่อม + ข้อความติดมา (รองรับทั้งกรณีมี space และไม่มี)
            name = re.split(
                r"\s+(?:และ|หรือ|กับ|พร้อม|ที่|ซึ่ง|ลง|ตา|รับรอง|มี|ใน|รวม|ทั้ง|ขอ|ลายมือ)",
                name, maxsplit=1,
            )[0].strip()
            # ตัด ถ้ามีคำว่า "หรือ"+คำนำหน้าติดกัน (เช่น "หรือนางสาว")
            name = re.split(r"(?:หรือ|และ)(?:นาย|นาง|น\.ส\.|นางสาว)", name, maxsplit=1)[0].strip()
            # ตัด suffix เป็นตัวเลข/คำสั้น (เช่น "5", "ก.")
            name = re.sub(r"\s+[ก-๛]{1}\.?$", "", name).strip()
            if _is_real_name(name) and name not in into:
                into.append(name)

    # 1. จาก info_text — "กรรมการซึ่งลงชื่อผูกพัน..."
    if info_text:
        m = re.search(
            r"กรรมการซึ่งลงชื่อผูกพัน(?:บริษัท)?ได้\s+([\s\S]+?)"
            r"(?:พร้อม|ประทับ|ข้อจำกัด|สำคัญของบริษัท|รายชื่อผู้|\Z)",
            info_text,
        )
        if m:
            block = m.group(1)
            _scan_text_for_names(block, names)
            # ถ้า block บอกว่า "กรรมการ X คนลงลายมือชื่อร่วมกัน" (ไม่เจาะจง)
            # → ใช้ directors ทุกคน
            if not names and re.search(
                r"กรรมการ(?:สอง|สาม|สี่|ห้า|หก|\d+)\s*คน(?:ใด)?\s*ลง"
                r"|กรรมการลงลายมือชื่อร่วมกัน"
                r"|กรรมการคนใดคนหนึ่ง",
                block,
            ):
                use_all_dirs = True

    # 2. จากไฟล์ที่ submitList ระบุ (authority_doc) — เสริมถ้าเจอเพิ่ม
    if sl_authority_files:
        for fname in sl_authority_files:
            p = find_by_original(vf, fname)
            if not p:
                continue
            t = _read(p, unread=unread, label="ผู้มีอำนาจควบคุม")
            if not t:
                continue
            # หา section ผู้มีอำนาจ ในไฟล์
            # ลอง pattern หลาย รูป
            block = t
            section_m = re.search(
                r"(?:ผู้มีอำนาจ|ลายมือชื่อผู้|กรรมการผู้มีอำนาจ)[\s\S]{0,2000}",
                t,
            )
            if section_m:
                block = section_m.group(0)
            _scan_text_for_names(block, names)
            if len(names) >= 2:
                break

    # 3. fallback: ใช้ directors ทั้งหมด (กรณีบริษัทใช้สูตร "กรรมการ X คน")
    if not names and use_all_dirs and directors:
        return "\n".join(f"{i+1}. {n}" for i, n in enumerate(directors[:10])) \
               + "\n(กรรมการลงลายมือชื่อร่วมกัน)"

    # 4. fallback: บริษัทกรรมการคนเดียว → director นั้นคือ authority
    if not names and directors and len(directors) == 1:
        return f"1. {directors[0]}"

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
    r"ข้อเสนอทางเทคนิค",
    r"comply\s*tor",
    r"^qt\d",
    r"obec[-_ ]?line",     # LINE OA spec sheet (มักรวม catalogue)
    r"line[_ ]oa.*spec",
    r"google[_ ]slides",   # vendor บางรายส่ง slide เป็น catalogue
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


def _any_match(text: str, patterns: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    for p in patterns:
        if re.search(p, low, re.IGNORECASE):
            return True
    return False


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

    # ── 1. ชื่อบริษัท / กรรมการ / authority ─────────────────────────────────
    # อ่านไฟล์ cert จาก submitList แล้ว pick ตัวที่ extract directors ได้มากสุด
    # (กัน OBJMGR/Objective ซึ่งเป็นไฟล์วัตถุประสงค์ ไม่ใช่ทะเบียนนิติบุคคล)
    info_text = ""
    cert_candidates: list[tuple[str, str]] = []  # (label, text)
    for fname in sl_get_files(sl, "cert"):
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

    # authority
    d.authority = _extract_authority(
        vf, info_text,
        sl_authority_files=sl_get_files(sl, "authority_doc"),
        directors=d.directors,
        unread=d.unread_files,
    )

    # ── 2. ผู้ถือหุ้น >25% ──────────────────────────────────────────────────
    sh_path = None
    for fname in sl_get_files(sl, "shareholder_doc"):
        p = find_by_original(vf, fname)
        if p:
            sh_path = p
            break
    if not sh_path:
        sh_path = find_file(vf, "shareholder")

    if sh_path:
        sh_text = _read(sh_path, unread=d.unread_files, label="ผู้ถือหุ้น")
        sh_tables = _read_tables(sh_path)
        holders = find_shareholder_over(sh_text, threshold=25.0, tables=sh_tables)
        if holders:
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

    # ── 5. ส่วนที่ 1: ใช้ submitList ────────────────────────────────────────
    if sl.parsed_ok:
        d.cert            = CHECK if sl_has_doc(sl, "cert")            else DASH
        d.memo            = CHECK if sl_has_doc(sl, "memo")            else DASH
        d.director_list   = CHECK if sl_has_doc(sl, "director_list")   else DASH
        d.shareholder_doc = CHECK if sl_has_doc(sl, "shareholder_doc") else DASH
        d.authority_doc   = CHECK if sl_has_doc(sl, "authority_doc")   else DASH
        d.credit          = CHECK if sl_has_doc(sl, "credit")          else DASH
        d.trade_reg       = CHECK if sl_has_doc(sl, "trade_reg")       else DASH
        d.vat             = CHECK if sl_has_doc(sl, "vat")             else DASH
    else:
        # fallback: เดาจากไฟล์
        d.cert            = CHECK if find_file(vf, "juristic_information") else DASH
        d.memo            = CHECK if (find_file(vf, "juristic_document")
                                       or find_file(vf, "MEMIMG")
                                       or find_file(vf, "บริคณห์")) else DASH
        d.director_list   = d.cert
        d.shareholder_doc = CHECK if find_file(vf, "shareholder") else DASH
        d.authority_doc   = CHECK if (find_file(vf, "ผู้มีอำนาจควบคุม")
                                       or find_file(vf, "OBJMGR")) else DASH
        d.trade_reg       = CHECK if (find_file(vf, "ทะเบียนพาณิชย์")
                                       or find_file(vf, "ใบสำคัญ")) else DASH
        d.vat             = CHECK if (find_file(vf, "ภพ20") or find_file(vf, "ภพ.20")
                                       or find_file(vf, "ภ.พ.20")
                                       or find_file(vf, "ภ พ 20")) else DASH

    # ── 6. ส่วนที่ 2: filename pattern matching ─────────────────────────────
    candidates = _collect_part2_candidates(sl, vf)

    d.catalogue    = CHECK if _has_in_files(candidates, _CATALOGUE_PATTERNS) else DASH
    d.line_license = CHECK if _has_in_files(candidates, _LINE_PATTERNS,
                                             _LINE_NEGATIVE_PATTERNS)         else DASH
    d.sme          = CHECK if _has_in_files(candidates, _SME_PATTERNS)       else DASH
    d.mit          = CHECK if _has_in_files(candidates, _MIT_PATTERNS)       else DASH
    d.work_cert    = CHECK if _has_in_files(candidates, _WORK_CERT_PATTERNS) else DASH
    d.poa          = CHECK if _has_in_files(candidates, _POA_PATTERNS)       else DASH

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
