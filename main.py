#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vendor-doc-checker — ตรวจสอบเอกสารผู้ยื่นข้อเสนอจากระบบ e-GP

วิธีใช้:
    python main.py <zip1> <zip2> ... --project "ชื่อโครงการ" --budget 1391000

ตัวอย่าง:
    python main.py data/*.zip \\
        --project "จัดซื้อ LINE OA สพฐ ปี 2569" \\
        --budget 1391000 \\
        --output "output/ตรวจเอกสาร_LINE_OA.xlsx"

Output:
    ไฟล์ Excel 4 sheets:
      - เอกสารส่วนที่2    (แยก หนังสือรับรองผลงาน / Certificate LINE)
      - เอกสารส่วนที่ 1
      - กรรมการ
      - ราคา
"""
import argparse
import glob
import io
import os
import sys
import tempfile

# Force UTF-8 output (แก้ปัญหา emoji บน Windows console cp874)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# เพิ่ม project root เข้า path
sys.path.insert(0, os.path.dirname(__file__))

from src.extractor import extract_all
from src.analyzer import analyze_all
from src.excel_builder import build_excel


def parse_args():
    parser = argparse.ArgumentParser(
        description="ตรวจสอบเอกสารผู้ยื่นข้อเสนอ e-GP → Excel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "zips",
        nargs="+",
        help="ไฟล์ ZIP จาก e-GP (รองรับ glob เช่น data/*.zip)",
    )
    parser.add_argument(
        "--project", "-p",
        required=True,
        help="ชื่อโครงการเต็ม (ใส่ในเครื่องหมายคำพูด)",
    )
    parser.add_argument(
        "--budget", "-b",
        type=float,
        required=True,
        help="วงเงินงบประมาณ (บาท) เช่น 1391000",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="path ของไฟล์ output .xlsx (default: output/<project_short>.xlsx)",
    )
    parser.add_argument(
        "--workdir", "-w",
        default=None,
        help="โฟลเดอร์ชั่วคราวสำหรับแตก ZIP (default: ใช้ tempdir)",
    )
    return parser.parse_args()


def resolve_zips(patterns: list[str]) -> list[str]:
    """ขยาย glob patterns → list ของ path จริง"""
    paths = []
    for pat in patterns:
        matched = glob.glob(pat)
        if matched:
            paths.extend(matched)
        elif os.path.exists(pat):
            paths.append(pat)
        else:
            print(f"  ⚠️  ไม่พบไฟล์: {pat}", file=sys.stderr)
    return sorted(set(paths))


def default_output(project: str) -> str:
    # ตัดอักขระพิเศษออก ใช้เป็นชื่อไฟล์
    safe = "".join(c for c in project if c.isalnum() or c in " _()-")[:40].strip()
    return os.path.join("output", f"ตรวจเอกสาร_{safe}.xlsx")


def main():
    args = parse_args()

    # ── 1. resolve ZIP paths ─────────────────────────────────────────────────
    zip_paths = resolve_zips(args.zips)
    if not zip_paths:
        print("❌ ไม่พบไฟล์ ZIP เลย", file=sys.stderr)
        sys.exit(1)

    print(f"\n📦 พบไฟล์ ZIP {len(zip_paths)} ราย:")
    for zp in zip_paths:
        print(f"   {os.path.basename(zp)}")

    # ── 2. แตก ZIP ──────────────────────────────────────────────────────────
    if args.workdir:
        work_base = args.workdir
        os.makedirs(work_base, exist_ok=True)
        cleanup = False
    else:
        _tmpdir = tempfile.mkdtemp(prefix="vendor_docs_")
        work_base = _tmpdir
        cleanup = True

    print(f"\n📂 แตกไฟล์ → {work_base}")
    vendor_files = extract_all(zip_paths, work_base)
    print(f"   ✓ แตกครบ {len(vendor_files)} ราย\n")

    # ── 3. วิเคราะห์เอกสาร ──────────────────────────────────────────────────
    print("🔍 กำลังวิเคราะห์เอกสาร...")
    vendors = analyze_all(vendor_files, budget=args.budget)

    # ── 4. สร้าง Excel ──────────────────────────────────────────────────────
    out_path = args.output or default_output(args.project)
    print(f"\n📊 สร้าง Excel → {out_path}")
    build_excel(vendors, args.project, args.budget, out_path)
    print(f"   ✅ บันทึกแล้ว: {out_path}")

    # ── 5. cleanup ──────────────────────────────────────────────────────────
    if cleanup:
        import shutil
        shutil.rmtree(work_base, ignore_errors=True)

    print("\n🎉 เสร็จสิ้น!")
    print(f"   โครงการ : {args.project}")
    print(f"   วงเงิน  : {args.budget:,.0f} บาท")
    print(f"   ผู้ยื่น  : {len(vendors)} ราย")
    print(f"   Output  : {os.path.abspath(out_path)}")

    # ── สรุปไฟล์ที่อ่านไม่ออก (ถ้ามี) ───────────────────────────────────────
    vendors_with_unread = [v for v in vendors if v.unread_files]
    if vendors_with_unread:
        print()
        print("⚠  ไฟล์ที่อ่านไม่ออก (ข้อมูลในช่องเกี่ยวข้องอาจไม่ปรากฏใน Excel)")
        for v in vendors_with_unread:
            print(f"   • {v.name or '(ไม่ทราบชื่อ)'}:")
            for f in v.unread_files:
                print(f"       - {f}")
        print()
        print("   วิธีแก้: ติดตั้ง Tesseract OCR (install_tesseract.bat)")
        print("           หรือตั้ง ANTHROPIC_API_KEY (set_api_key.bat)")


if __name__ == "__main__":
    main()
