# -*- coding: utf-8 -*-
"""
streamlit_app.py — เว็บไซต์ตรวจเอกสารผู้ยื่นข้อเสนอ e-GP

รันใน local:
    streamlit run streamlit_app.py

Deploy:
    push ขึ้น GitHub แล้วใช้ https://share.streamlit.io
"""
import os
import sys
import tempfile
import shutil
from io import BytesIO

import streamlit as st

# ─── ให้ import จาก src/ ได้ ─────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.extractor import extract_all
from src.analyzer import analyze_all
from src.excel_builder import build_excel


# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ตรวจเอกสาร e-GP",
    page_icon="📋",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ─── Custom CSS (Soft Navy เหมือน gui.py) ────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #EEF2F7; }
    .stApp { background-color: #EEF2F7; }
    h1 { color: #0F172A; font-family: 'Sarabun', sans-serif; }
    .kicker {
        display: inline-block;
        background: #E0E7FF;
        color: #1E3A8A;
        padding: 4px 12px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: bold;
        margin-bottom: 8px;
    }
    .stButton button {
        background-color: #1E3A8A;
        color: white;
        border: none;
        padding: 10px 24px;
        font-weight: bold;
        border-radius: 8px;
    }
    .stButton button:hover {
        background-color: #172554;
        color: white;
    }
    .stDownloadButton button {
        background-color: #16A34A;
        color: white;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)


# ─── Header ──────────────────────────────────────────────────────────────────
st.markdown('<span class="kicker">e-GP • ตรวจเอกสารส่วนที่ 1 และ 2</span>',
            unsafe_allow_html=True)
st.title("📋 ตรวจเอกสารผู้ยื่นข้อเสนอ")
st.caption("อ่านไฟล์ ZIP จากระบบ e-bidding และสร้างไฟล์ Excel สรุปผลการตรวจเอกสาร")
st.divider()


# ─── Step 1: Upload ZIPs ─────────────────────────────────────────────────────
st.subheader("1️⃣ ไฟล์ ZIP ผู้ยื่นข้อเสนอ")
uploaded_files = st.file_uploader(
    "เลือกไฟล์ ZIP (เลือกได้หลายไฟล์)",
    type=["zip"],
    accept_multiple_files=True,
    help="ZIP ที่ดาวน์โหลดจากระบบ e-GP",
)

if uploaded_files:
    st.success(f"📦 พบไฟล์ ZIP {len(uploaded_files)} ราย")
    with st.expander("ดูรายการไฟล์"):
        for f in uploaded_files:
            st.text(f"• {f.name} ({f.size/1024:.1f} KB)")


# ─── Step 2: Project Info ────────────────────────────────────────────────────
st.subheader("2️⃣ ข้อมูลโครงการ")
col1, col2 = st.columns([3, 1])
with col1:
    project = st.text_input(
        "ชื่อโครงการ",
        placeholder="เช่น ประกวดราคาซื้อ LINE OA สพฐ. ปี 2569",
    )
with col2:
    budget = st.number_input(
        "วงเงิน (บาท)",
        min_value=0,
        value=0,
        step=10000,
        format="%d",
    )


# ─── Step 3: Run ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("3️⃣ ตรวจสอบและสร้าง Excel")

if st.button("▶ ตรวจเอกสาร", type="primary", use_container_width=True):
    # validate
    if not uploaded_files:
        st.error("กรุณาเลือกไฟล์ ZIP อย่างน้อย 1 ไฟล์")
        st.stop()
    if not project.strip():
        st.error("กรุณากรอกชื่อโครงการ")
        st.stop()
    if budget <= 0:
        st.error("กรุณากรอกวงเงินงบประมาณ")
        st.stop()

    # บันทึก uploaded files → temp directory
    with tempfile.TemporaryDirectory(prefix="vendor_") as tmpdir:
        zip_paths = []
        zip_dir = os.path.join(tmpdir, "zips")
        os.makedirs(zip_dir, exist_ok=True)
        for f in uploaded_files:
            p = os.path.join(zip_dir, f.name)
            with open(p, "wb") as out:
                out.write(f.getvalue())
            zip_paths.append(p)

        # ── progress UI ──
        progress = st.progress(0, text="กำลังเริ่ม...")
        log = st.empty()
        log_lines = []

        def log_msg(msg):
            log_lines.append(msg)
            log.code("\n".join(log_lines[-15:]), language=None)

        try:
            # 1. แตก ZIP
            progress.progress(15, text="📂 แตกไฟล์ ZIP...")
            log_msg(f"📦 พบไฟล์ ZIP {len(zip_paths)} ราย")
            work_base = os.path.join(tmpdir, "extracted")
            os.makedirs(work_base, exist_ok=True)
            vendor_files = extract_all(zip_paths, work_base)
            log_msg(f"✓ แตกครบ {len(vendor_files)} ราย")

            # 2. วิเคราะห์
            progress.progress(40, text="🔍 กำลังวิเคราะห์เอกสาร...")
            log_msg("")
            log_msg("🔍 วิเคราะห์เอกสาร:")
            vendors = []
            for i, vf in enumerate(vendor_files):
                from src.analyzer import analyze_vendor
                progress.progress(
                    40 + int(40 * (i+1) / len(vendor_files)),
                    text=f"🔍 วิเคราะห์ {vf.vendor_id} ({i+1}/{len(vendor_files)})",
                )
                vd = analyze_vendor(vf, i + 1, budget=float(budget))
                vendors.append(vd)
                log_msg(f"  {vf.vendor_id}: {vd.name or '(ไม่ทราบ)'} — "
                       f"ราคา {vd.price:,.0f}")

            # 3. สร้าง Excel
            progress.progress(90, text="📊 สร้างไฟล์ Excel...")
            log_msg("")
            log_msg("📊 สร้าง Excel...")
            output_path = os.path.join(tmpdir, "output.xlsx")
            build_excel(vendors, project, float(budget), output_path)

            # อ่านกลับเป็น bytes
            with open(output_path, "rb") as f:
                excel_bytes = f.read()

            progress.progress(100, text="✅ เสร็จสิ้น!")
            log_msg("✅ เสร็จสิ้น!")

        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")
            import traceback
            with st.expander("ดูรายละเอียด error"):
                st.code(traceback.format_exc())
            st.stop()

    # ── สรุปผล ──
    st.success("🎉 ตรวจเสร็จแล้ว!")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("ผู้ยื่นข้อเสนอ", f"{len(vendors)} ราย")
    col_b.metric("วงเงิน", f"{budget:,.0f}")
    in_budget = sum(1 for v in vendors if v.price <= budget)
    col_c.metric("ราคาไม่เกินวงเงิน", f"{in_budget}/{len(vendors)}")

    # ── เตือนไฟล์ที่อ่านไม่ออก ──
    vendors_with_unread = [v for v in vendors if v.unread_files]
    if vendors_with_unread:
        with st.expander(
            f"⚠ มีไฟล์ {sum(len(v.unread_files) for v in vendors_with_unread)} "
            f"ไฟล์ที่อ่านไม่ออก (ใน {len(vendors_with_unread)} บริษัท)",
            expanded=True,
        ):
            st.warning(
                "ไฟล์เหล่านี้ใช้ font ฝังเฉพาะ หรือเป็นภาพสแกน — "
                "ข้อมูลในช่องที่เกี่ยวข้องอาจไม่ปรากฏใน Excel"
            )
            for v in vendors_with_unread:
                st.markdown(f"**{v.name or '(ไม่ทราบชื่อ)'}**")
                for f in v.unread_files:
                    st.text(f"   • {f}")
            st.info(
                "วิธีแก้: ตั้งค่า `ANTHROPIC_API_KEY` ใน Streamlit Secrets "
                "เพื่อใช้ Claude Vision OCR (หรือถ้ารัน local ให้ใช้ Tesseract)"
            )

    # ตารางสรุป
    import pandas as pd
    df = pd.DataFrame([{
        "ลำดับ": v.no,
        "ชื่อบริษัท": v.name or "(ไม่ทราบ)",
        "เลขทะเบียน": v.tax_id,
        "ราคาที่เสนอ": f"{v.price:,.0f}",
        "ผ่าน/เกินวงเงิน": "✓" if v.price <= budget else "✗",
    } for v in sorted(vendors, key=lambda x: x.price)])
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Download button — ใส่ชื่อโครงการ + วันที่ + เวลา กันชนกันแน่นอน
    import datetime, re
    safe_name = re.sub(r'[<>:"/\\|?*]', "", project).strip()[:50].strip()
    if not safe_name:
        safe_name = "ตรวจเอกสาร"
    else:
        safe_name = f"ตรวจเอกสาร_{safe_name}"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    st.download_button(
        label="⬇ ดาวน์โหลด Excel",
        data=excel_bytes,
        file_name=f"{safe_name}_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ─── Footer ──────────────────────────────────────────────────────────────────
st.divider()
st.caption("💡 PDF ที่เป็นภาพสแกน: ตั้ง `ANTHROPIC_API_KEY` ใน Secrets เพื่อใช้ "
           "Claude Vision OCR (ไม่บังคับ)")
