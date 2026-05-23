"""
pdf_reader.py — อ่าน PDF แบบ 3 ชั้น (precision reading)

ชั้นที่ 1: pdfplumber       — text-based PDF ทั่วไป
ชั้นที่ 2: pymupdf (fitz)   — PDF font แปลก / encoding ซับซ้อน
ชั้นที่ 3: Claude Vision    — PDF สแกน/ภาพ (ต้องตั้ง ANTHROPIC_API_KEY)

ตัวอ่านแต่ละชั้นจะถูกเรียกเรียงลำดับ ถ้าชั้นก่อนหน้าได้ผลที่ "ดีพอ" จะหยุด
"ดีพอ" = ข้อความยาวพอ ไม่มี (cid:xxx) เกินสัดส่วน ไม่ว่างเปล่า
"""
from __future__ import annotations
import base64
import os
import re
from typing import Optional

# ── lib detection ────────────────────────────────────────────────────────────
try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

try:
    import pymupdf  # PyMuPDF (fitz)
    _HAS_PYMUPDF = True
except ImportError:
    _HAS_PYMUPDF = False

try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

# pattern ที่บ่งบอกว่า PDF เป็นภาพสแกน
_CID_PATTERN = re.compile(r"\(cid:\d+\)")

# threshold สำหรับ "ข้อความดีพอ"
MIN_TEXT_LEN = 50          # ตัวอักษรขั้นต่ำ
MAX_CID_RATIO = 0.05       # สัดส่วน (cid:xxx) สูงสุด

# Claude vision settings
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_MAX_PAGES = 5       # อ่าน vision สูงสุด 5 หน้าต่อไฟล์ (ประหยัด token)


# ─── ระดับคุณภาพข้อความ ──────────────────────────────────────────────────────

def _quality_ok(text: str) -> bool:
    """True ถ้า text 'ดีพอ' = ยาวพอ และมี cid น้อย"""
    if not text or len(text.strip()) < MIN_TEXT_LEN:
        return False
    cid_count = len(_CID_PATTERN.findall(text))
    total = len(text)
    if total > 0 and cid_count / total > MAX_CID_RATIO:
        return False
    return True


def _clean(text: str) -> str:
    """ตัด (cid:xxx) ออก เผื่อกรณีอ่านได้บางส่วน"""
    return _CID_PATTERN.sub("", text)


# ─── ชั้นที่ 1: pdfplumber ────────────────────────────────────────────────────

def _read_pdfplumber(path: str) -> str:
    if not _HAS_PDFPLUMBER:
        return ""
    try:
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                pages.append(t)
        return "\n".join(pages).strip()
    except Exception:
        return ""


# ─── ชั้นที่ 2: pymupdf (fitz) ────────────────────────────────────────────────

def _read_pymupdf(path: str) -> str:
    if not _HAS_PYMUPDF:
        return ""
    try:
        doc = pymupdf.open(path)
        pages = []
        for page in doc:
            t = page.get_text("text") or ""
            pages.append(t)
        doc.close()
        return "\n".join(pages).strip()
    except Exception:
        return ""


# ─── ชั้นที่ 3: Claude Vision ─────────────────────────────────────────────────

def _read_claude_vision(path: str) -> str:
    """
    ส่งหน้า PDF เป็นภาพให้ Claude อ่าน (OCR คุณภาพสูงสำหรับภาษาไทย)
    ต้องตั้ง environment variable: ANTHROPIC_API_KEY
    """
    if not (_HAS_ANTHROPIC and _HAS_PYMUPDF):
        return ""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    # fallback: อ่านจาก config/api_key.txt (ติดไปกับ HDD)
    if not api_key:
        key_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "api_key.txt",
        )
        if os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    api_key = f.read().strip()
            except Exception:
                api_key = ""
    if not api_key:
        return ""

    try:
        # render PDF เป็นภาพ PNG ต่อหน้า
        doc = pymupdf.open(path)
        n_pages = min(len(doc), CLAUDE_MAX_PAGES)
        images = []
        for i in range(n_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=200)   # 200 DPI สำหรับ OCR ละเอียด
            img_bytes = pix.tobytes("png")
            images.append(base64.standard_b64encode(img_bytes).decode())
        doc.close()

        # ส่งภาพไปให้ Claude
        client = anthropic.Anthropic(api_key=api_key)
        content = []
        for b64 in images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                },
            })
        content.append({
            "type": "text",
            "text": (
                "อ่านข้อความทั้งหมดจากภาพ PDF นี้ออกมาเป็น plain text "
                "โดยรักษาโครงสร้าง ขึ้นบรรทัดใหม่ตามต้นฉบับ "
                "ถ้ามีตารางให้แยกคอลัมน์ด้วย tab "
                "ห้ามสรุป ห้ามแปล ห้ามอธิบาย — ส่งคืนแค่ข้อความล้วน"
            ),
        })

        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"    [Claude Vision error: {e}]")
        return ""


# ─── Public API ───────────────────────────────────────────────────────────────

def read_pdf_text(path: str, use_vision: bool = True) -> tuple[str, bool]:
    """
    อ่าน PDF แบบหลายชั้น คืน (text, used_vision)

    Parameters
    ----------
    path        : path ของ PDF
    use_vision  : เปิดใช้ Claude Vision ถ้า text-layer อ่านไม่ได้
                  ต้องมี ANTHROPIC_API_KEY ใน environment

    Returns
    -------
    text         : ข้อความที่อ่านได้
    used_vision  : True ถ้าใช้ Claude Vision (ใช้สำหรับ debug)
    """
    # ชั้นที่ 1: pdfplumber
    text = _read_pdfplumber(path)
    if _quality_ok(text):
        return _clean(text), False

    # ชั้นที่ 2: pymupdf
    text2 = _read_pymupdf(path)
    if _quality_ok(text2):
        return _clean(text2), False

    # เลือกตัวที่ยาวกว่าระหว่าง 2 ชั้นแรก (เผื่อมีข้อมูลบางส่วน)
    best = text if len(text) > len(text2) else text2

    # ชั้นที่ 3: Claude Vision (ถ้าเปิดและตั้ง API key)
    if use_vision:
        text3 = _read_claude_vision(path)
        if _quality_ok(text3):
            return text3, True
        if len(text3) > len(best):
            best = text3

    return _clean(best), False


# ─── helper เดิม (คงไว้เพื่อ backward compat) ──────────────────────────────────

def extract_thai_number(text: str) -> Optional[float]:
    """
    แปลงตัวเลขไทย/อาหรับในข้อความเป็น float
    รองรับ: ๑,๒๓๔,๕๖๗.๘๙ หรือ 1,234,567.89
    """
    THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
    cleaned = text.translate(THAI_DIGITS).replace(",", "")
    nums = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if nums:
        return float(nums[0])
    return None


def find_shareholder_over(text: str, threshold: float = 25.0) -> list[tuple[str, float]]:
    """
    ค้นหาผู้ถือหุ้นที่ถือ > threshold%
    คืน list of (ชื่อ, %)
    ใช้กับ text จาก juristic_shareholder sys
    """
    results = []
    lines = text.splitlines()
    for line in lines:
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if pct_match:
            pct = float(pct_match.group(1))
            if pct > threshold:
                name_part = re.sub(r"[\d,\.%]+", "", line).strip()
                name_part = re.sub(r"\s{2,}", " ", name_part).strip()
                if name_part:
                    results.append((name_part, pct))
    return results


def extract_net_worth(text: str) -> tuple[Optional[float], str]:
    """
    หามูลค่าสุทธิ (ส่วนของผู้ถือหุ้น) จาก financial statement text
    คืน (value, "บวก"/"ลบ"/"ไม่ทราบ")
    """
    keywords = ["ส่วนของผู้ถือหุ้น", "equity", "net worth", "ส่วนของเจ้าของ"]
    for kw in keywords:
        idx = text.lower().find(kw.lower())
        if idx != -1:
            snippet = text[idx: idx + 200]
            val = extract_thai_number(snippet)
            if val is not None:
                sign = "ลบ" if val < 0 else "บวก"
                return abs(val), sign
    return None, "ไม่ทราบ"
