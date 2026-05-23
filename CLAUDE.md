# vendor-doc-checker

ระบบตรวจสอบเอกสารผู้ยื่นข้อเสนอ e-GP → Excel อัตโนมัติ
สำหรับนักวิชาการพัสดุ สพฐ. (และหน่วยงานอื่น)

---

## วัตถุประสงค์

รับไฟล์ ZIP ที่ดาวน์โหลดจากระบบ e-GP (e-bidding) ของแต่ละผู้ยื่นข้อเสนอ
แล้วอ่าน PDF อัตโนมัติและสร้างไฟล์ Excel สรุป **"ตรวจเอกสารส่วนที่ 1 และ 2"**
พร้อมแยกคอลัมน์ **หนังสือรับรองผลงาน** กับ **Certificate/License (LINE)**
ให้ชัดเจน

---

## โครงสร้างโปรเจค

```
vendor-doc-checker/
├── CLAUDE.md               ← ไฟล์นี้
├── main.py                 ← entry point (CLI)
├── requirements.txt
├── src/
│   ├── extractor.py        ← แตก ZIP, สร้าง safe filename, file mapping
│   ├── pdf_reader.py       ← อ่าน PDF (pdfplumber + vision fallback)
│   ├── analyzer.py         ← วิเคราะห์เอกสารต่อ 1 ผู้ยื่น → VendorData
│   └── excel_builder.py    ← สร้าง Excel 4 sheets
├── config/
│   └── columns.py          ← ปรับ column labels + keywords ต่อโครงการ
└── output/                 ← ไฟล์ output (สร้างอัตโนมัติ)
```

---

## วิธีรัน

```bash
# ติดตั้ง dependencies
pip install -r requirements.txt

# รันพื้นฐาน
python main.py data/*.zip \
    --project "ชื่อโครงการเต็ม" \
    --budget 1391000

# ระบุ output path เอง
python main.py data/*.zip \
    --project "จัดซื้อ LINE OA สพฐ. ปี 2569" \
    --budget 1391000 \
    --output "output/ตรวจเอกสาร_LINE_OA_2569.xlsx"

# เก็บไฟล์ที่แตกแล้วไว้ (debug)
python main.py data/*.zip \
    --project "..." --budget 1391000 \
    --workdir /tmp/vendor_extracted
```

---

## Architecture

### Data flow

```
ZIP files (e-GP)
    │
    ▼ src/extractor.py
VendorFiles  (safe filenames + original name mapping)
    │
    ▼ src/analyzer.py
VendorData   (ชื่อ, กรรมการ, ผู้ถือหุ้น, มูลค่าสุทธิ, ราคา, ✓/- ทุกช่อง)
    │
    ▼ src/excel_builder.py
Excel (.xlsx) 4 sheets
```

### Key data classes

**`VendorFiles`** (extractor.py)
- `vendor_id`: "v1", "v2", ...
- `extract_dir`: path ที่แตกแล้ว
- `original_names`: dict `safe_name → original_name`
- `tax_id`: เลขทะเบียน 13 หลัก

**`VendorData`** (analyzer.py)
- ข้อมูลนิติบุคคลทั้งหมด + ✓/- สำหรับทุกช่อง
- `work_cert`: หนังสือรับรองผลงาน
- `line_license`: Certificate/License จาก LINE Corp.

---

## วิธีปรับแต่งสำหรับโครงการใหม่

### 1. เปลี่ยนชื่อคอลัมน์

แก้ `config/columns.py` → `PART2_COLUMNS`

### 2. เพิ่ม keyword สำหรับ detect เอกสาร

แก้ `src/analyzer.py` บรรทัด `KW_*` หรือเพิ่มใน `config/columns.py`

```python
# ตัวอย่าง: โครงการที่ใช้ AWS Certificate แทน LINE
KW_LINE_LIC = ["Verified_Agency", "AWS_Partner", "Microsoft_CSP"]
```

### 3. เพิ่มคอลัมน์ใหม่ใน Excel

1. เพิ่ม field ใน `VendorData` (analyzer.py)
2. เพิ่ม logic ตรวจใน `analyze_vendor()` (analyzer.py)
3. เพิ่มคอลัมน์ใน `_HEADERS_2` และ `_WIDTHS_2` (excel_builder.py)
4. เพิ่ม `_sc(ws, row, col, v.new_field, ...)` ใน `_build_sheet2()`

---

## ข้อจำกัดและ workaround

| ปัญหา | สาเหตุ | วิธีแก้ |
|-------|--------|---------|
| PDF อ่านไม่ออก (cid:xxx) | เป็น PDF ภาพสแกน | ใช้ Claude vision (Read tool) |
| ชื่อไฟล์ยาวเกิน 255 bytes | Linux limit | extractor.py rename เป็น `file_NNN.pdf` |
| ราคาดึงไม่ได้ | Quotation format ต่างกัน | แก้ regex ใน `analyze_vendor()` |
| ผู้ถือหุ้น % คำนวณไม่ได้ | งบดุลไม่มีตัวเลข % ตรงๆ | ดูจาก sys file + คำนวณ manual |

---

## การทดสอบ

```bash
# ทดสอบกับโปรเจค LINE OA สนามจริง
python main.py \
    "uploads/69059111894_0105564124978.zip" \
    "uploads/69059111894_0105558108028.zip" \
    "uploads/69059111894_0105557075681.zip" \
    "uploads/69059111894_0105550113634.zip" \
    "uploads/69059111894_0105539071246.zip" \
    "uploads/69059111894_0105533094368.zip" \
    --project "ประกวดราคาซื้อ LINE OA สพฐ. e-bidding" \
    --budget 1391000 \
    --output "output/test_run.xlsx"
```

ผลลัพธ์ที่ถูกต้องเทียบได้กับ:
`ตรวจเอกสารส่วนที่ 1 และ 2 (LINE OA v2).xlsx`

---

## Dependencies

- `pdfplumber` — อ่าน PDF text-based
- `openpyxl` — สร้าง Excel
- Python ≥ 3.10

---

## TODO / Next steps

- [ ] รองรับ PDF ภาพสแกนด้วย OCR (pytesseract หรือ Claude vision API)
- [ ] เพิ่ม `--manual` mode: ให้ user แก้ไขผลผ่าน interactive prompt
- [ ] สร้าง test suite สำหรับ parser แต่ละประเภท
- [ ] รองรับโครงการ IT อื่น (ไม่ใช่แค่ LINE OA)
- [ ] สร้าง web UI อย่างง่าย (Flask/FastAPI)
