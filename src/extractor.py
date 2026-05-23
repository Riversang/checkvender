"""
extractor.py — แตก ZIP และทำ file map ต่อ 1 ผู้ยื่นข้อเสนอ

ปัญหาที่แก้:
  - ชื่อไฟล์ภาษาไทยยาวเกิน 255 bytes → rename เป็น file_NNN.pdf
  - ฟัง submitList.pdf เพื่อสร้าง mapping ชื่อเดิม → ชื่อใหม่
"""
import os
import zipfile
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VendorFiles:
    """ผลจากการแตก ZIP ของผู้ยื่น 1 ราย"""
    vendor_id: str                      # v1, v2, ...
    extract_dir: str                    # path ที่แตกแล้ว
    original_names: dict = field(default_factory=dict)  # safe_name → original_name
    tax_id: str = ""                    # ดึงจากชื่อไฟล์ ZIP เช่น 0105564124978


def _safe_name(index: int, original: str) -> str:
    """สร้างชื่อไฟล์ปลอดภัย เก็บ extension เดิม"""
    ext = os.path.splitext(original)[1]
    return f"file_{index:03d}{ext}"


def extract_zip(zip_path: str, out_base: str, vendor_id: str) -> VendorFiles:
    """
    แตก ZIP ไฟล์เดียว → VendorFiles

    Parameters
    ----------
    zip_path  : path ของไฟล์ .zip
    out_base  : base directory ที่จะสร้าง subfolder
    vendor_id : ชื่อ id เช่น "v1"
    """
    # ดึง tax_id จากชื่อไฟล์ ZIP (format: <bid_id>_<tax_id>.zip)
    basename = os.path.basename(zip_path)
    parts = os.path.splitext(basename)[0].split("_")
    tax_id = parts[-1] if len(parts) >= 2 else ""

    out_dir = os.path.join(out_base, vendor_id, "1")
    os.makedirs(out_dir, exist_ok=True)

    original_names: dict[str, str] = {}

    with zipfile.ZipFile(zip_path) as z:
        for i, info in enumerate(z.infolist()):
            if info.filename.endswith("/"):   # skip directories
                continue
            orig = info.filename
            # ใช้ basename เท่านั้น (ตัด subfolder ออก)
            orig_base = os.path.basename(orig)
            safe = _safe_name(i, orig_base)
            target = os.path.join(out_dir, safe)
            with z.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            original_names[safe] = orig_base

    return VendorFiles(
        vendor_id=vendor_id,
        extract_dir=out_dir,
        original_names=original_names,
        tax_id=tax_id,
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
    """คืน list of (safe_name, original_name)"""
    return sorted(vf.original_names.items())
