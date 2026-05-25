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

try:
    import pytesseract
    from PIL import Image
    _HAS_TESSERACT = True
except ImportError:
    _HAS_TESSERACT = False

# detect tesseract executable (Windows: ลองหาที่ install ทั่วไป)
_TESSERACT_CHECKED = False
_TESSERACT_OK = False


def _ensure_tesseract() -> bool:
    """ตรวจ + ตั้ง path ของ tesseract.exe (สำหรับ Windows)"""
    global _TESSERACT_CHECKED, _TESSERACT_OK
    if _TESSERACT_CHECKED:
        return _TESSERACT_OK
    _TESSERACT_CHECKED = True
    if not _HAS_TESSERACT:
        return False
    try:
        # ลองรัน tesseract เพื่อเช็คว่ามีไหม
        pytesseract.get_tesseract_version()
        _TESSERACT_OK = True
        return True
    except (pytesseract.TesseractNotFoundError, Exception):
        pass
    # ลองหาที่ install ทั่วไปบน Windows
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        # portable: ลองหา tesseract.exe ใน WinPython folder
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "tesseract", "tesseract.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            try:
                pytesseract.get_tesseract_version()
                _TESSERACT_OK = True
                return True
            except Exception:
                continue
    return False

# pattern ที่บ่งบอกว่า PDF เป็นภาพสแกน
_CID_PATTERN = re.compile(r"\(cid:\d+\)")

# threshold สำหรับ "ข้อความดีพอ"
MIN_TEXT_LEN = 50          # ตัวอักษรขั้นต่ำ
MAX_CID_RATIO = 0.05       # สัดส่วน (cid:xxx) สูงสุด

# Claude vision settings
CLAUDE_MODEL = "claude-sonnet-4-5"
CLAUDE_MAX_PAGES = 5       # อ่าน vision สูงสุด 5 หน้าต่อไฟล์ (ประหยัด token)
CLAUDE_DPI = 250           # 250 DPI (สูงกว่า 200 เดิม เพื่อให้ font เล็กชัด)

# Tesseract settings — สูง DPI = อ่านได้ละเอียดขึ้น (เสมือน zoom เอกสาร)
TESSERACT_LANG = "tha+eng"     # ใช้ทั้งไทย + อังกฤษ
TESSERACT_DPI = 400            # 400 DPI (เพิ่มจาก 300 เพื่อความแม่นกับ font เล็ก)
TESSERACT_MAX_PAGES = 8        # อ่าน OCR สูงสุด 8 หน้าต่อไฟล์


# ─── ระดับคุณภาพข้อความ ──────────────────────────────────────────────────────

_THAI_CHAR_RE = re.compile(r"[ก-๛]")
_THAI_RUN_RE = re.compile(r"[ก-๛]+")     # ลำดับ Thai chars ติดกัน (ไม่นับ space)
_GARBLED_CHARS_RE = re.compile(r"[+#%&*|<>~`@^]")
# Latin Extended chars ที่มัก override Thai glyphs ใน font subset
# (เช่น เลĂทัด, ýุภดิลก, บริþัท)
_LATIN_EXT_RE = re.compile(r"[À-ÿĀ-žƀ-ɏ]")
_COMMON_THAI_WORDS = (
    "บริษัท", "หจก", "ห้าง", "นาย", "นาง", "หุ้น", "กรรมการ",
    "ทะเบียน", "เลข", "ผู้", "ที่", "ใน", "การ", "ของ", "และ",
)


def _quality_ok(text: str) -> bool:
    """
    True ถ้า text 'ดีพอ' (อ่านได้จริง):
      - ยาวพอ
      - มี cid:xxx น้อย
      - มีตัวอักษรไทยในสัดส่วนที่สมเหตุสมผล
      - มีคำไทยทั่วไป (สำหรับ text ทุกความยาว)
      - มีคำไทยติดกันยาวพอ (ไม่ใช่ text ที่แตกตัวอักษรเป็นแนวตั้ง)
      - ไม่มี ASCII punctuation หนาแน่นเกินไป (custom font garbled)
      - ไม่มี Latin Extended แทรก Thai (font CMap substitution)
    """
    if not text or len(text.strip()) < MIN_TEXT_LEN:
        return False
    total = len(text)
    cid_count = len(_CID_PATTERN.findall(text))
    if cid_count / total > MAX_CID_RATIO:
        return False
    # ratio ตัวอักษรไทยต่ำ → likely garbled
    thai_chars = len(_THAI_CHAR_RE.findall(text))
    if thai_chars > 0 and total > 100 and thai_chars / total < 0.10:
        return False
    # text ที่ยาวพอแต่ไม่มีคำไทยทั่วไป → garbled หรือไม่ใช่เอกสารจริง
    if total > 50 and not any(w in text for w in _COMMON_THAI_WORDS):
        return False
    # ASCII punctuation หนาแน่น → likely garbled font output
    garbled = len(_GARBLED_CHARS_RE.findall(text))
    if total > 200 and garbled / total > 0.025:
        return False
    # Latin Extended chars แทรกใน Thai → font CMap substitution
    latin_ext = len(_LATIN_EXT_RE.findall(text))
    if total > 200 and latin_ext / total > 0.02:
        return False
    # ไม่มีคำไทยติดกันยาวพอ (≥ 4 chars) → likely vertically-broken text
    # เช่น "ง\nา\nจ\nด\nจั\nอ\nซื้" — chars แตกเป็นแนวตั้ง
    longest_run = 0
    for m in _THAI_RUN_RE.finditer(text):
        longest_run = max(longest_run, len(m.group(0)))
        if longest_run >= 5:
            break
    if thai_chars >= 10 and longest_run < 5:
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


# ─── ชั้นที่ 3: Tesseract OCR (ฟรี, ใช้ได้ local) ────────────────────────────

def _post_ocr_thai(text: str) -> str:
    """
    หลัง Tesseract OCR: รวมตัวอักษรไทยที่ถูกแยกด้วย space
    (Tesseract มัก output "ก ร ม พ ั ฒ น า" แทน "กรมพัฒนา")

    กฎ:
      - ถ้า Thai char ถูก space แยกจาก Thai char ตัวอื่น → รวม (ลบ space)
      - คง space ระหว่าง Thai-Eng/digit, Eng-Eng
    """
    # ลบ space ระหว่าง Thai char สองตัว (รวมถึงตัวที่เป็น vowel/tone)
    # pattern: <thai><spaces><thai> → <thai><thai>
    pattern = re.compile(r"([ก-๛])\s+(?=[ก-๛])")
    # apply ซ้ำเพราะ space ติดกันหลาย ๆ
    for _ in range(3):
        text = pattern.sub(r"\1", text)
    return text


def _read_tesseract(path: str) -> str:
    """
    OCR ด้วย Tesseract (ฟรี local) — ใช้กับ PDF ภาพสแกน + font ฝังที่อ่านไม่ออก
    ต้อง install tesseract.exe + tha.traineddata + pip install pytesseract Pillow
    """
    if not (_HAS_TESSERACT and _HAS_PYMUPDF):
        return ""
    if not _ensure_tesseract():
        return ""

    try:
        doc = pymupdf.open(path)
        n_pages = min(len(doc), TESSERACT_MAX_PAGES)
        texts: list[str] = []
        for i in range(n_pages):
            page = doc[i]
            pix = page.get_pixmap(dpi=TESSERACT_DPI)
            img_bytes = pix.tobytes("png")
            from io import BytesIO
            img = Image.open(BytesIO(img_bytes))
            try:
                t = pytesseract.image_to_string(img, lang=TESSERACT_LANG)
            except pytesseract.TesseractError:
                # fallback: ใช้แค่ eng ถ้าไม่มี tha pack
                t = pytesseract.image_to_string(img, lang="eng")
            # post-process รวมตัวอักษรไทยที่ถูก space แยก
            t = _post_ocr_thai(t)
            texts.append(t)
        doc.close()
        return "\n".join(texts).strip()
    except Exception as e:
        print(f"    [Tesseract error: {e}]")
        return ""


# ─── ชั้นที่ 4: Claude Vision ─────────────────────────────────────────────────

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
            pix = page.get_pixmap(dpi=CLAUDE_DPI)
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

def read_pdf_tables(path: str) -> list:
    """อ่านตารางทั้งหมดจาก PDF (ทุกหน้า) ใช้ pdfplumber"""
    if not _HAS_PDFPLUMBER:
        return []
    try:
        out: list = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for t in (page.extract_tables() or []):
                    out.append(t)
        return out
    except Exception:
        return []


def read_pdf_text(path: str, use_vision: bool = True) -> tuple[str, bool]:
    """
    อ่าน PDF แบบหลายชั้น คืน (text, is_good_quality)

    Parameters
    ----------
    path        : path ของ PDF
    use_vision  : เปิดใช้ Claude Vision ถ้า text-layer อ่านไม่ได้
                  ต้องมี ANTHROPIC_API_KEY ใน environment

    Returns
    -------
    text             : ข้อความที่อ่านได้
    is_good_quality  : True ถ้ามีชั้นใดผ่าน _quality_ok (อ่านได้สมบูรณ์)
                       False ถ้าทุกชั้น fail (text อาจอ่านได้บางส่วนแต่ขาดข้อมูล)
    """
    # ชั้นที่ 1: pdfplumber
    text = _read_pdfplumber(path)
    if _quality_ok(text):
        return _clean(text), True

    # ชั้นที่ 2: pymupdf
    text2 = _read_pymupdf(path)
    if _quality_ok(text2):
        return _clean(text2), True

    # เลือกตัวที่ยาวกว่าระหว่าง 2 ชั้นแรก (เผื่อมีข้อมูลบางส่วน)
    best = text if len(text) > len(text2) else text2

    # ชั้นที่ 3: Tesseract OCR (ฟรี, local)
    text3 = _read_tesseract(path)
    if _quality_ok(text3):
        return _clean(text3), True
    if len(text3) > len(best):
        best = text3

    # ชั้นที่ 4: Claude Vision (ถ้าเปิดและตั้ง API key)
    if use_vision:
        text4 = _read_claude_vision(path)
        if _quality_ok(text4):
            return text4, True
        if len(text4) > len(best):
            best = text4

    # ถ้ามาถึงตรงนี้แสดงว่า text ทุกชั้นไม่ดีพอ — แจ้ง user
    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()) or \
                  os.path.exists(os.path.join(
                      os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "config", "api_key.txt"))
    tess_ok = _ensure_tesseract()
    if not (tess_ok or api_key_set):
        print(f"    ⚠ อ่าน PDF ไม่ออก (font แปลก/ภาพสแกน): "
              f"{os.path.basename(path)}")
        print(f"      → ติดตั้ง Tesseract (install_tesseract.bat) "
              f"หรือตั้ง ANTHROPIC_API_KEY (set_api_key.bat)")
    elif not api_key_set and tess_ok:
        print(f"    ⚠ Tesseract อ่านไม่ออก: {os.path.basename(path)}")
        print(f"      → ลองตั้ง ANTHROPIC_API_KEY เพื่อใช้ Vision (แม่นกว่า)")

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


_TITLES = ("นาย", "นาง", "น.ส.", "นางสาว", "บริษัท", "บจก.", "บมจ.",
           "หจก.", "ห้างหุ้นส่วน", "Mr.", "Mrs.", "Ms.", "Miss")


def _parse_int(s: str) -> Optional[int]:
    """แปลง '1,127,370' → 1127370"""
    if not s:
        return None
    try:
        return int(re.sub(r"[,\s]", "", s))
    except ValueError:
        return None


def _find_total_shares(text: str) -> Optional[int]:
    """หา 'แบ่งออกเป็น X หุ้น' หรือ ทุนจดทะเบียน / มูลค่าหุ้น"""
    # แบ่งออกเป็น X หุ้น
    m = re.search(r"แบ่งออก(?:เป็น)?\s+([\d,]+)\s*หุ้น", text)
    if m:
        v = _parse_int(m.group(1))
        if v:
            return v
    # ทุนจดทะเบียน X บาท / มูลค่าหุ้นละ Y บาท → X/Y
    cap_m = re.search(r"ทุนจดทะเบียน\s+([\d,]+(?:\.\d+)?)\s*บาท", text)
    val_m = re.search(r"มูลค่าหุ้นละ\s+([\d,]+(?:\.\d+)?)\s*บาท", text)
    if cap_m and val_m:
        try:
            cap = float(cap_m.group(1).replace(",", ""))
            val = float(val_m.group(1).replace(",", ""))
            if val > 0:
                return int(cap / val)
        except (ValueError, ZeroDivisionError):
            pass
    return None


def find_shareholder_over(
    text: str,
    threshold: float = 25.0,
    tables: Optional[list] = None,
) -> list[tuple[str, float]]:
    """
    ค้นหาผู้ถือหุ้นที่ถือ > threshold%
    คืน list of (ชื่อ, %)

    strategy:
      1. ลองหา % โดยตรงในข้อความ
      2. ถ้าไม่เจอ → หา total shares + parse จำนวนหุ้นแต่ละราย แล้วคำนวณ %
      3. ถ้ามี `tables` ส่งมาด้วย (จาก pdfplumber) จะ parse แม่นยิ่งขึ้น
    """
    results: list[tuple[str, float]] = []

    # ── strategy 1: หา % ตรงๆ ────────────────────────────────────────────────
    for line in text.splitlines():
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if pct_match:
            pct = float(pct_match.group(1))
            if pct > threshold:
                name_part = re.sub(r"[\d,\.%]+", "", line).strip()
                name_part = re.sub(r"\s{2,}", " ", name_part).strip()
                if name_part and any(name_part.startswith(t) for t in _TITLES):
                    results.append((name_part, pct))
    if results:
        return results

    # ── strategy 2: คำนวณจาก จำนวนหุ้น / total ────────────────────────────────
    total = _find_total_shares(text)
    if not total or total <= 0:
        return results

    # parse tables ถ้ามี
    if tables:
        for tbl in tables:
            if not tbl:
                continue
            # ดู header เป็น "ลำดับที่ | ชื่อผู้ถือหุ้น | ... | จำนวนหุ้นที่ถือ"
            header = [str(c or "").strip() for c in tbl[0]] if tbl[0] else []
            name_col = None
            share_col = None
            for ci, h in enumerate(header):
                if "ชื่อ" in h:
                    name_col = ci
                if "จำนวนหุ้น" in h or "จํานวนหุ้น" in h:
                    share_col = ci
            if name_col is None or share_col is None:
                continue
            for row in tbl[1:]:
                if not row or len(row) <= max(name_col, share_col):
                    continue
                name = str(row[name_col] or "").strip()
                shares = _parse_int(str(row[share_col] or ""))
                if not name or not shares:
                    continue
                pct = shares * 100.0 / total
                if pct > threshold:
                    results.append((name, round(pct, 2)))
        if results:
            return results

    # parse fallback จาก text (ดู pattern: <ลำดับ> <ชื่อ> ... <หุ้น>)
    # หา block หลัง "รายชื่อผู้ถือหุ้น"
    block_start = text.find("รายชื่อผู้ถือหุ้น")
    block = text[block_start:] if block_start != -1 else text
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        # ตัด ลำดับที่ ออก
        ln = re.sub(r"^\d+\s+", "", line)
        # หาจำนวนหุ้นท้ายบรรทัด (เลขล้วน + อาจมี ,)
        sh_match = re.search(r"([\d,]{4,})\s*$", ln)
        if not sh_match:
            continue
        shares = _parse_int(sh_match.group(1))
        if not shares or shares <= 0:
            continue
        name_chunk = ln[:sh_match.start()].strip()
        # ตัด อาชีพ, สัญชาติ (heuristic: 2 คำสุดท้ายมักเป็น 'ไทย' หรือชื่อสัญชาติ)
        # ดึงเฉพาะส่วนที่ขึ้นต้นด้วยคำนำหน้า
        for t in _TITLES:
            idx = name_chunk.find(t)
            if idx != -1:
                name_chunk = name_chunk[idx:]
                break
        # ตัดท้าย: อาชีพ + สัญชาติ (มัก 2-3 คำท้าย)
        tokens = name_chunk.split()
        if len(tokens) >= 3:
            # เอาออก 2 token ท้ายเป็น default (อาชีพ + สัญชาติ)
            name = " ".join(tokens[:-2])
        else:
            name = name_chunk
        name = name.strip()
        if not name or not any(name.startswith(t) for t in _TITLES):
            continue
        pct = shares * 100.0 / total
        if pct > threshold:
            results.append((name, round(pct, 2)))

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
