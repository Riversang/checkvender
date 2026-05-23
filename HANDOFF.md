# 🤝 คุยกับ Claude ใน Chat ใหม่

ก็อปข้อความข้างล่างนี้ทั้งบล็อก วางเป็นข้อความแรกในแชทใหม่
แล้วต่อด้วยสิ่งที่อยากให้ทำต่อท้าย

---

## 📋 ข้อความเริ่มต้น (ก็อปทั้งหมด)

```
โปรเจคของฉันอยู่ที่ E:\claude\ตรวจสอบข้อมูลผู้ขาย\
อ่าน CLAUDE.md และ HANDOFF.md ในโฟลเดอร์นั้นก่อนนะ

ข้อมูลสำคัญ:
- Python: E:\WinPython\WPy64-313130\python\python.exe (portable)
- GitHub: https://github.com/Riversang/checkvender
- เว็บ: https://checkvender.streamlit.app (Streamlit Cloud)
- update เว็บ: ดับเบิลคลิก update_web.bat ในโฟลเดอร์

โครงสร้าง:
- streamlit_app.py = เว็บ
- gui.py = โปรแกรม desktop
- main.py = CLI
- src/ = logic หลัก (extractor, pdf_reader, analyzer, excel_builder)
- config/columns.py = ปรับชื่อคอลัมน์
- config/api_key.txt = Anthropic API key (ถ้ามี)

ที่อยากให้ทำต่อ:
[เขียนสิ่งที่อยากให้ทำตรงนี้]
```

---

## 💡 ตัวอย่างที่อยากให้ทำ

### แก้ปัญหา / bug
```
v4 ใน ZIP อ่านชื่อบริษัทไม่ได้ ช่วยดูให้หน่อย
ไฟล์อยู่ที่ C:\Users\Admin\Downloads\69059111894_0105557075681.zip
```

### เพิ่ม feature
```
อยากเพิ่มคอลัมน์ใหม่ใน Excel "เลขที่ใบอนุญาต"
ดึงจากเอกสารบริษัทถ้ามี
```

### ปรับ UI
```
อยากให้หน้าเว็บมีปุ่มดาวน์โหลด CSV ด้วย ไม่ใช่แค่ Excel
```

### Deploy / Update
```
แก้ src/analyzer.py แล้ว ช่วย push ขึ้น GitHub ที
```

### ทดสอบ
```
รันทดสอบกับ ZIP ใน C:\Users\Admin\Downloads\69059111894_*.zip
ดูว่าออก Excel ถูกไหม
```

---

## 🔑 ข้อมูลที่ Claude ต้องรู้

| รายการ | ค่า |
|--------|-----|
| Project root | `E:\claude\ตรวจสอบข้อมูลผู้ขาย\` |
| Python | `E:\WinPython\WPy64-313130\python\python.exe` |
| GitHub repo | `Riversang/checkvender` |
| Web URL | `https://checkvender.streamlit.app` |
| Run web local | `streamlit run streamlit_app.py` (ผ่าน Python นี้) |
| Push update | `update_web.bat` (ดับเบิลคลิก) |
| Open GUI | `gui.bat` |
| Set API key | `set_api_key.bat` |

---

## 📝 หมายเหตุ

- **อย่าลบ HANDOFF.md** — ใช้เริ่มต้นบทสนทนาใหม่
- ถ้าย้าย HDD ไปเครื่องอื่น drive letter อาจเปลี่ยน (E: → F:) แต่ bat ทั้งหมด
  ออกแบบให้ auto-detect แล้ว ใช้ได้เลย
- ถ้า package หาย (เกิดขึ้นได้ตอนย้ายเครื่อง) → ดับเบิลคลิก `setup.bat`
