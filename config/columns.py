"""
columns.py — ปรับแต่งคอลัมน์ส่วนที่ 2 สำหรับแต่ละประเภทโครงการ

วิธีใช้:
  แก้ไขไฟล์นี้ให้ตรงกับ TOR ของโครงการที่กำลังตรวจสอบ
  แล้ว import ใน analyzer.py หรือ excel_builder.py ตามต้องการ
"""

# ── ชื่อคอลัมน์ส่วนที่ 2 ─────────────────────────────────────────────────────
# แก้ตรงนี้ถ้าโครงการอื่นใช้ชื่อต่างกัน

PART2_COLUMNS = {
    "poa":          "หนังสือ\nมอบอำนาจ",
    "guarantee":    "หลักประกัน",
    "sme":          "SMEs",
    "mit":          "Made in\nThailand",
    "catalogue":    "แคตตาล็อก/\nคุณลักษณะเฉพาะ",
    "work_cert":    "หนังสือรับรอง\nผลงาน",
    "line_license": "หนังสือรับรอง\nCertificate/\nLicense (LINE)",
    "other1":       "อื่นๆ",
    "other2":       "อื่นๆ",
    "note":         "หมายเหตุ",
}

# ── keywords สำหรับ matching ไฟล์ ─────────────────────────────────────────────
# เพิ่ม / แก้ไข keyword ที่ใช้ detect เอกสารแต่ละประเภท
# (ดู src/analyzer.py สำหรับ default keywords)

EXTRA_WORK_CERT_KEYWORDS = [
    # เพิ่ม keyword เพิ่มเติมถ้า TOR โครงการอื่นใช้ชื่อต่าง
    # เช่น "หนังสือรับรองสัญญา",
]

EXTRA_LINE_LICENSE_KEYWORDS = [
    # เพิ่ม keyword เพิ่มเติมสำหรับ Certificate จาก partner อื่น
    # เช่น "Partner Certificate",
]

# ── project template ──────────────────────────────────────────────────────────
# ตัวอย่าง config สำเร็จรูปสำหรับโครงการ LINE OA สพฐ.
LINE_OA_OBEC = {
    "project_name": "ประกวดราคาซื้อการจัดซื้อสิทธิ์ในการใช้บริการ Line Official Account (LINE OA) เพื่อการสื่อสารของ สพฐ. ด้วยวิธีประกวดราคาอิเล็กทรอนิกส์ (e-bidding)",
    "budget": 1_391_000.0,
    "part2_other_label": "เอกสารรับรองตัวแทน LINE OA",
}
