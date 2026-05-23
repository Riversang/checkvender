"""
analyzer.py — วิเคราะห์เอกสารของผู้ยื่น 1 ราย (precision parsing)

รับ VendorFiles → คืน VendorData ที่มีข้อมูลครบสำหรับสร้าง Excel

ปรับปรุงจากเวอร์ชันก่อนหน้า:
  - ใช้หลาย regex pattern สำหรับชื่อบริษัท / กรรมการ / ราคา
  - ดึงราคาจาก Quotation แม่นกว่าเดิม (มอง context "ราคาที่เสนอ", "รวมเป็นเงิน", etc.)
  - แยกแยะ "หนังสือรับรองผลงาน" กับ "Certificate LINE" จาก content ไม่ใช่แค่ชื่อไฟล์
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from .extractor import VendorFiles, find_file, find_files, list_files
from .pdf_reader import (
    read_pdf_text,
    extract_net_worth,
    find_shareholder_over,
    extract_thai_number,
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

    # กรรมการ
    directors: list[str] = field(default_factory=list)
    authority: str = "-"
    shareholders: str = "-"

    # มูลค่าสุทธิ
    net_worth: float = 0.0
    net_worth_sign: str = "ไม่ทราบ"

    # เอกสารส่วนที่ 1
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

    # เอกสารส่วนที่ 2
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


# ─── helper ───────────────────────────────────────────────────────────────────

def _has(vf: VendorFiles, *keywords: str) -> bool:
    """True ถ้าพบไฟล์ที่ original name มี keyword ใดๆ"""
    for kw in keywords:
        if find_file(vf, kw):
            return True
    return False


def _read(path: Optional[str]) -> str:
    """อ่าน PDF คืน text หรือ '' ถ้าไม่มี/อ่านไม่ได้"""
    if not path:
        return ""
    text, _ = read_pdf_text(path)
    return text


def _read_first(vf: VendorFiles, *keywords: str) -> str:
    """หาไฟล์แรกที่ match แล้วอ่าน"""
    for kw in keywords:
        p = find_file(vf, kw)
        if p:
            return _read(p)
    return ""


# ─── keywords ที่ใช้ match ────────────────────────────────────────────────────

KW_CERT      = ["juristic_information", "หนังสือรับรอง"]
KW_MEMO      = ["juristic_document", "juristic_Objective", "MEMIMG", "บริคณห์"]
KW_DIRECTOR  = ["juristic_information"]
KW_AUTHORITY = ["ผู้มีอำนาจควบคุม", "OBJMGR"]
KW_SHAREHOLDER = ["shareholder", "ผู้ถือหุ้น"]
KW_TRADE_REG = ["พค", "ทะเบียนพาณิชย์", "ใบสำคัญ", "กรมการค้าธุรกิจ", "พาณิชย์"]
KW_VAT       = ["ภพ20", "ภพ.20", "ภ พ 20"]
KW_FINANCIAL = ["financial", "งบการเงิน"]
KW_POA       = ["มอบอำนาจ", "POA"]
KW_SME       = ["SME_", "SME_0"]
KW_CATALOGUE = ["แคตตาล็อก", "catalogue", "คุณลักษณะ", "คุณลักษณะเฉพาะ", "obec-line"]
KW_WORK_CERT = ["หนังสือรับรองผลงาน", "รับรองผลงาน", "รับรองคู่ฉบับ",
                "หนังสือรับรอง "]
KW_LINE_LIC  = ["Verified_Agency", "Verified Agency", "B2B_Verified",
                "รับรองการเป็นเอเจนซี", "รับรอง Line Agency",
                "Verfied Agency"]


# ─── precision name extraction ────────────────────────────────────────────────

_NAME_PATTERNS = [
    r"ชื่อสถานที่ประกอบการ\s+(.+?)(?:\n|$)",
    r"ชื่อนิติบุคคล\s+(.+?)(?:\n|$)",
    r"ชื่อผู้ประกอบการ\s+(.+?)(?:\n|$)",
    r"ชื่อ\s*\(ภาษาไทย\)\s*[:：]?\s*(บริษัท[^\n]+|ห้างหุ้นส่วน[^\n]+)",
    r"^(บริษัท\s+[^\n]+?\s+จำกัด(?:\s*\(มหาชน\))?)\s*$",
    r"ข้าพเจ้า\s+(บริษัท[^\s]+(?:\s+\S+){1,6}จำกัด)",
]


def _extract_company_name(text: str) -> str:
    """ดึงชื่อบริษัทจาก text หลาย pattern"""
    for pat in _NAME_PATTERNS:
        for m in re.finditer(pat, text, re.MULTILINE):
            name = m.group(1).strip()
            # ตัดข้อความรกๆ
            name = re.sub(r"\s+", " ", name)
            name = name.strip(" :-")
            # validate: ต้องมี "บริษัท" หรือ "ห้างหุ้นส่วน"
            if "บริษัท" in name or "ห้างหุ้นส่วน" in name or "หจก" in name:
                # ตัดทรงตัวเลขที่อาจติดมา
                name = re.sub(r"\s+\d{13}.*$", "", name)
                return name
    return ""


# ─── precision director extraction ────────────────────────────────────────────

def _extract_directors(text: str) -> list[str]:
    """ดึงรายชื่อกรรมการจาก juristic_information text"""
    # หา block "รายชื่อกรรมการ" → จนถึง "กรรมการซึ่งลงชื่อ" หรือ keyword อื่น
    patterns = [
        r"รายชื่อกรรมการ\s+([\s\S]+?)(?:กรรมการซึ่งลงชื่อ|ข้อจำกัด|รายชื่อผู้)",
        r"กรรมการ(?:บริษัท)?\s*[:：]\s*([\s\S]+?)(?:ข้อจำกัด|ลายมือชื่อ|ผู้มีอำนาจ)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        raw = m.group(1)
        dirs = []
        for ln in raw.splitlines():
            ln = ln.strip()
            # ตัดตัวเลขลำดับนำหน้า, ตัด หมายเหตุ
            ln = re.sub(r"^\d+[\.\)]\s*", "", ln)
            ln = re.sub(r"\s+", " ", ln).strip()
            if not ln:
                continue
            # ต้องเริ่มด้วยคำนำหน้าชื่อ
            if re.match(r"^(นาย|นาง|น\.ส\.|นางสาว|Mr\.?|Mrs\.?|Miss)", ln):
                dirs.append(ln)
            elif ln and len(ln) < 60 and re.search(r"[฀-๿]", ln):
                # บรรทัดที่เป็นภาษาไทยสั้นๆ ก็น่าจะใช่
                dirs.append(ln)
        if dirs:
            return dirs[:20]  # cap ที่ 20 คน
    return []


# ─── precision price extraction ───────────────────────────────────────────────

_PRICE_CONTEXT_PATTERNS = [
    # ราคาที่เสนอใน Quotation มักมาพร้อม keyword พวกนี้
    r"(?:ราคาที่เสนอ|ราคารวม|รวมทั้งสิ้น|รวมเป็นเงิน|ยอดรวม|จำนวนเงินที่เสนอ|เสนอราคาเป็นเงิน)"
    r"[^\d๐-๙]{0,30}([\d,๐-๙]+(?:\.[\d๐-๙]+)?)",
    # หรือมี "บาท" ตามหลัง
    r"([\d,๐-๙]+(?:\.[\d๐-๙]+)?)\s*บาท",
]

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def _extract_price(text: str, budget: float = 0) -> float:
    """
    ดึงราคาเสนอจาก Quotation text

    กลยุทธ์:
      1. หาตัวเลขที่มี context keyword เช่น "ราคาที่เสนอ", "รวมเป็นเงิน"
      2. กรองด้วย range ที่สมเหตุสมผล (ใกล้กับ budget ถ้ามี)
      3. เลือกตัวที่พบมากที่สุด (เพราะราคารวมมักโผล่หลายที่)
    """
    candidates: dict[float, int] = {}

    for pat in _PRICE_CONTEXT_PATTERNS:
        for m in re.finditer(pat, text):
            raw = m.group(1).translate(THAI_DIGITS).replace(",", "")
            try:
                val = float(raw)
            except ValueError:
                continue
            # range filter — ราคาประกวดราคา IT มักอยู่ระหว่าง 1 แสน - 100 ล้าน
            if not (100_000 <= val <= 100_000_000):
                continue
            candidates[val] = candidates.get(val, 0) + 1

    if not candidates:
        return 0.0

    # ถ้ามี budget ให้ priority ราคาที่ <= budget * 1.5
    if budget > 0:
        near_budget = {v: c for v, c in candidates.items() if v <= budget * 1.5}
        if near_budget:
            candidates = near_budget

    # เลือกตัวที่พบบ่อยที่สุด ถ้าเสมอกันให้เลือกค่าที่ใกล้ budget ที่สุด (ถ้ามี budget)
    if budget > 0:
        return max(candidates.items(),
                   key=lambda kv: (kv[1], -abs(kv[0] - budget)))[0]
    return max(candidates.items(), key=lambda kv: kv[1])[0]


# ─── content-based document classification ────────────────────────────────────

def _is_work_cert_content(text: str) -> bool:
    """ตรวจว่า text เป็นหนังสือรับรองผลงาน (จากเนื้อหา)"""
    markers = ["รับรองผลงาน", "ขอรับรองว่า", "ได้ดำเนินการ", "งานสำเร็จเรียบร้อย",
               "ได้ปฏิบัติงาน", "ผู้ว่าจ้าง", "คู่สัญญา"]
    hits = sum(1 for m in markers if m in text)
    return hits >= 2


def _is_line_license_content(text: str) -> bool:
    """ตรวจว่า text เป็น Certificate LINE (จากเนื้อหา)"""
    markers = ["LINE", "Official Account", "Verified Agency", "B2B Partner",
               "Certified", "Authorized", "Agency", "Partner"]
    hits = sum(1 for m in markers if m in text)
    return hits >= 2


# ─── main analyzer ────────────────────────────────────────────────────────────

def analyze_vendor(vf: VendorFiles, vendor_no: int, budget: float = 0) -> VendorData:
    """
    วิเคราะห์เอกสารจาก VendorFiles และคืน VendorData

    Parameters
    ----------
    vf         : VendorFiles ที่แตก ZIP แล้ว
    vendor_no  : ลำดับผู้ยื่น (1, 2, 3, ...)
    budget     : วงเงินงบประมาณ — ใช้ priority ราคาที่ใกล้เคียง
    """
    d = VendorData(no=vendor_no, tax_id=vf.tax_id)

    # ── 1. ชื่อบริษัท / กรรมการ ─────────────────────────────────────────────
    info_text = _read_first(vf, *KW_CERT)
    if info_text:
        d.name = _extract_company_name(info_text)
        d.directors = _extract_directors(info_text)

    # fallback ชื่อบริษัท: ลองจาก Quotation
    if not d.name:
        q_text = _read(find_file(vf, "Quotation"))
        if q_text:
            d.name = _extract_company_name(q_text)

    # fallback ชื่อบริษัท: ลองจากไฟล์อื่น
    if not d.name:
        for safe, _orig in list_files(vf):
            p = os.path.join(vf.extract_dir, safe)
            if not p.lower().endswith(".pdf"):
                continue
            t = _read(p)
            n = _extract_company_name(t)
            if n:
                d.name = n
                break

    # ── 2. ผู้ถือหุ้นรายใหญ่ ─────────────────────────────────────────────────
    sh_text = _read_first(vf, *KW_SHAREHOLDER)
    if sh_text:
        holders = find_shareholder_over(sh_text, threshold=25.0)
        if holders:
            d.shareholders = "\n".join(f"{n} ({p:.2f}%)" for n, p in holders)

    # ── 3. มูลค่าสุทธิ ───────────────────────────────────────────────────────
    fin_text = _read_first(vf, *KW_FINANCIAL)
    if fin_text:
        val, sign = extract_net_worth(fin_text)
        if val is not None:
            d.net_worth = val
            d.net_worth_sign = sign

    # ── 4. ราคา จาก Quotation (precision parsing) ────────────────────────────
    q_text = _read(find_file(vf, "Quotation"))
    if q_text:
        d.price = _extract_price(q_text, budget=budget)

    # ── 5. ส่วนที่ 1: ตรวจการมีไฟล์ ─────────────────────────────────────────
    d.cert            = CHECK if _has(vf, *KW_CERT)         else DASH
    d.memo            = CHECK if _has(vf, *KW_MEMO)         else DASH
    d.director_list   = CHECK if _has(vf, *KW_DIRECTOR)     else DASH
    d.authority_doc   = CHECK if _has(vf, *KW_AUTHORITY)    else DASH
    d.shareholder_doc = CHECK if _has(vf, *KW_SHAREHOLDER)  else DASH
    d.trade_reg       = CHECK if _has(vf, *KW_TRADE_REG)    else DASH
    d.vat             = CHECK if _has(vf, *KW_VAT)          else DASH

    # ── 6. ส่วนที่ 2 ─────────────────────────────────────────────────────────
    d.poa           = CHECK if _has(vf, *KW_POA)        else DASH
    d.sme           = CHECK if _has(vf, *KW_SME)        else DASH
    d.catalogue     = CHECK if _has(vf, *KW_CATALOGUE)  else DASH
    d.work_cert     = CHECK if _has(vf, *KW_WORK_CERT)  else DASH
    d.line_license  = CHECK if _has(vf, *KW_LINE_LIC)   else DASH

    # ── 6.5 content-based classification (เผื่อชื่อไฟล์ไม่ตรง) ─────────────
    if d.work_cert == DASH or d.line_license == DASH:
        for safe, _orig in list_files(vf):
            p = os.path.join(vf.extract_dir, safe)
            if not p.lower().endswith(".pdf"):
                continue
            t = _read(p)
            if not t:
                continue
            if d.work_cert == DASH and _is_work_cert_content(t):
                d.work_cert = CHECK
            if d.line_license == DASH and _is_line_license_content(t):
                d.line_license = CHECK
            if d.work_cert == CHECK and d.line_license == CHECK:
                break

    # ── 7. ผู้มีอำนาจควบคุม (text) ───────────────────────────────────────────
    auth_text = _read_first(vf, *KW_AUTHORITY)
    if auth_text:
        names = re.findall(r"((?:นาย|นาง|น\.ส\.|นางสาว)[^\n\t\d]{2,30})", auth_text)
        if names:
            d.authority = "\n".join(f"{i+1}. {n.strip()}" for i, n in enumerate(names[:5]))

    return d


def analyze_all(vendor_files: list[VendorFiles], budget: float = 0) -> list[VendorData]:
    """วิเคราะห์ทุกรายคืน list[VendorData]"""
    results = []
    for i, vf in enumerate(vendor_files):
        print(f"  Analyzing {vf.vendor_id} (tax: {vf.tax_id})...")
        vd = analyze_vendor(vf, i + 1, budget=budget)
        results.append(vd)
        print(f"    -> {vd.name or '(ยังไม่ได้ชื่อ)'}, ราคา {vd.price:,.0f}")
    return results
