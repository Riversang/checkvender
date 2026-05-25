"""
extractor.py — แตก ZIP และทำ file map ต่อ 1 ผู้ยื่นข้อเสนอ

ปัญหาที่แก้:
  - ชื่อไฟล์ภาษาไทยยาวเกิน 255 bytes → rename เป็น file_NNN.pdf
  - เก็บ original name + subfolder path
  - หา submitList.pdf เพื่อใช้เป็น source of truth
  - ดึง tax_id ทั้งจากชื่อ ZIP และจากชื่อไฟล์ภายใน (สำหรับชื่อ ZIP ไม่มีตัวเลข)
"""
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VendorFiles:
    """ผลจากการแตก ZIP ของผู้ยื่น 1 ราย"""
    vendor_id: str                                  # v1, v2, ...
    extract_dir: str                                # path ที่แตกแล้ว
    original_names: dict = field(default_factory=dict)  # safe_name → original_basename
    full_paths: dict = field(default_factory=dict)  # safe_name → original full path in zip
    tax_id: str = ""                                # 13-digit เลขนิติบุคคล
    submitlist_path: Optional[str] = None           # path ของ submitList.pdf (ถ้ามี)
    source_zip: str = ""                            # path ของ ZIP ต้นทาง


_TAX_ID_RE = re.compile(r"(?<!\d)(\d{13})(?!\d)")


def _safe_name(index: int, original: str) -> str:
    """สร้างชื่อไฟล์ปลอดภัย เก็บ extension เดิม"""
    ext = os.path.splitext(original)[1]
    return f"file_{index:03d}{ext}"


def _detect_tax_id(zip_path: str, filenames: list[str]) -> str:
    """
    หา tax_id (13 หลัก):
      1. จากชื่อไฟล์ ZIP
      2. จากชื่อไฟล์ภายใน ZIP (e.g., 0105539071246_juristic_information.pdf)
    """
    # 1. จากชื่อ ZIP
    basename = os.path.basename(zip_path)
    m = _TAX_ID_RE.search(basename)
    if m:
        return m.group(1)

    # 2. จากชื่อไฟล์ภายใน
    for fn in filenames:
        m = _TAX_ID_RE.search(os.path.basename(fn))
        if m:
            return m.group(1)
    return ""


def extract_zip(zip_path: str, out_base: str, vendor_id: str) -> VendorFiles:
    """
    แตก ZIP ไฟล์เดียว → VendorFiles
    """
    out_dir = os.path.join(out_base, vendor_id)
    os.makedirs(out_dir, exist_ok=True)

    original_names: dict[str, str] = {}
    full_paths: dict[str, str] = {}
    submitlist_path: Optional[str] = None

    with zipfile.ZipFile(zip_path) as z:
        infos = [i for i in z.infolist() if not i.filename.endswith("/")]
        # ใช้ชื่อทุกไฟล์ในการหา tax_id
        tax_id = _detect_tax_id(zip_path, [i.filename for i in infos])

        for i, info in enumerate(infos):
            orig_full = info.filename
            orig_base = os.path.basename(orig_full)
            safe = _safe_name(i, orig_base)
            target = os.path.join(out_dir, safe)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            original_names[safe] = orig_base
            full_paths[safe] = orig_full

            # submitList detection (basename match)
            if orig_base.lower() == "submitlist.pdf":
                submitlist_path = target

    return VendorFiles(
        vendor_id=vendor_id,
        extract_dir=out_dir,
        original_names=original_names,
        full_paths=full_paths,
        tax_id=tax_id,
        submitlist_path=submitlist_path,
        source_zip=zip_path,
    )


def extract_all(zip_paths: list[str], out_base: str) -> list[VendorFiles]:
    """แตก ZIP ทุกราย คืน list[VendorFiles] เรียงตามลำดับ"""
    results = []
    for i, zp in enumerate(zip_paths):
        vid = f"v{i+1}"
        results.append(extract_zip(zp, out_base, vid))
    return results


def find_file(vf: VendorFiles, keyword: str) -> Optional[str]:
    """
    หา path ของไฟล์ที่ชื่อ original มี keyword (case-insensitive)
    คืน full path หรือ None
    """
    kw = keyword.lower()
    for safe, orig in vf.original_names.items():
        if kw in orig.lower():
            return os.path.join(vf.extract_dir, safe)
    return None


def find_files(vf: VendorFiles, keyword: str) -> list[str]:
    """หาหลายไฟล์ที่ match keyword"""
    kw = keyword.lower()
    return [
        os.path.join(vf.extract_dir, safe)
        for safe, orig in vf.original_names.items()
        if kw in orig.lower()
    ]


def list_files(vf: VendorFiles) -> list[tuple[str, str]]:
    """คืน list of (safe_name, original_basename)"""
    return sorted(vf.original_names.items())


def find_by_original(vf: VendorFiles, original_name: str) -> Optional[str]:
    """
    หา file path จากชื่อ original (basename) ที่ระบุใน submitList
    รองรับ fuzzy match:
      - submitList ระบุ "X.pdf" แต่ไฟล์จริงเป็น "X_<hash>.pdf"
      - มี space ต่างกัน
    """
    def _norm(s: str) -> str:
        return re.sub(r"\s+", "", s).lower()

    def _stem(s: str) -> str:
        # ตัด extension + ตัด hash suffix แบบ "_<hex>"
        base = os.path.splitext(s)[0]
        # ตัด trailing "_<hex chars>" ที่ระบบ e-GP เพิ่ม
        base = re.sub(r"_[0-9a-f]{8,}(?:_\d+_sys)?$", "", base, flags=re.IGNORECASE)
        return _norm(base)

    target_full = _norm(original_name)
    target_stem = _stem(original_name)

    # 1. exact match (full filename รวม .pdf)
    for safe, orig in vf.original_names.items():
        if _norm(orig) == target_full:
            return os.path.join(vf.extract_dir, safe)
    # 2. stem match (ตัด hash suffix และ extension)
    for safe, orig in vf.original_names.items():
        if _stem(orig) == target_stem:
            return os.path.join(vf.extract_dir, safe)
    # 3. substring (full)
    for safe, orig in vf.original_names.items():
        if target_full in _norm(orig):
            return os.path.join(vf.extract_dir, safe)
    # 4. substring (stem)
    for safe, orig in vf.original_names.items():
        if target_stem and target_stem in _stem(orig):
            return os.path.join(vf.extract_dir, safe)
    return None
