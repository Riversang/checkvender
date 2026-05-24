# -*- coding: utf-8 -*-
"""
gui.py — หน้าต่างโปรแกรมตรวจเอกสารผู้ยื่นข้อเสนอ e-GP
ใช้งาน: ดับเบิลคลิก gui.bat หรือรัน python gui.py
"""
import os
import sys
import math
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ── ชี้ไปที่ project root ────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable

# ── สี / ฟอนต์ (Soft Navy palette) ──────────────────────────────────────────
BG          = "#EEF2F7"   # soft blue-gray canvas
SURFACE     = "#FFFFFF"   # card
SURFACE_ALT = "#F8FAFC"   # subtle alt
BORDER      = "#DBE3EF"   # hairline (navy-tinted)
BORDER_SOFT = "#E8EEF7"

TEXT        = "#0F172A"   # near-navy black
TEXT_MUTED  = "#64748B"   # slate
TEXT_FAINT  = "#94A3B8"

# Navy accents (soft → deep)
NAVY        = "#1E3A8A"   # primary navy
NAVY_DEEP   = "#172554"
NAVY_MID    = "#3B5BDB"
NAVY_SOFT   = "#E0E7FF"   # soft navy chip bg
NAVY_TINT   = "#F3F4FB"

ACCENT      = NAVY
ACCENT_HOV  = NAVY_DEEP
ACCENT_SOFT = NAVY_SOFT

DANGER      = "#B91C1C"
DANGER_SOFT = "#FEF2F2"

GHOST_HOV   = "#E2E8F0"

# Log panel — soft navy night
LOG_BG   = "#0F172A"
LOG_FG   = "#CBD5E1"
LOG_OK   = "#86EFAC"
LOG_ERR  = "#FCA5A5"
LOG_INFO = "#93C5FD"
LOG_DIM  = "#475569"

# Typography
FONT         = ("TH Sarabun New", 15)
FONT_B       = ("TH Sarabun New", 15, "bold")
FONT_LABEL   = ("TH Sarabun New", 13)
FONT_KICKER  = ("TH Sarabun New", 12, "bold")
FONT_H       = ("TH Sarabun New", 26, "bold")
FONT_SUB     = ("TH Sarabun New", 14)
FONT_BTN     = ("TH Sarabun New", 14, "bold")
FONT_BTN_BIG = ("TH Sarabun New", 17, "bold")
FONT_LOG     = ("Consolas", 11)
FONT_BADGE   = ("TH Sarabun New", 11, "bold")


# ── helpers ─────────────────────────────────────────────────────────────────
def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*[max(0, min(255, int(c))) for c in rgb])

def _lerp(a, b, t):
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ตรวจเอกสารผู้ยื่นข้อเสนอ e-GP")
        self.resizable(True, True)
        self.configure(bg=BG)
        self.zip_paths: list[str] = []
        self._pulse_widgets = []   # list of (widget, base_hex, peak_hex, prop)
        self._pulse_phase = 0.0
        self._status_state = "ready"   # ready | running | ok | err
        self._build_ui()
        self._start_pulse()

        # จัดให้อยู่กลางจอ
        self.update_idletasks()
        w = 900
        sh = self.winfo_screenheight()
        h = min(820, sh - 100)  # เว้น ~100px สำหรับ taskbar + title bar
        sw = self.winfo_screenwidth()
        x = (sw - w) // 2
        y = max(20, (sh - h) // 2 - 20)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(780, 580)

        self.lift()
        self.attributes("-topmost", True)
        self.after(500, lambda: self.attributes("-topmost", False))
        self.focus_force()

    # ── helpers ──────────────────────────────────────────────────────────────
    def _card(self, parent, number: str, title: str, subtitle: str = ""):
        """Hairline-bordered card with numbered chip header."""
        card = tk.Frame(parent, bg=SURFACE,
                        highlightbackground=BORDER,
                        highlightcolor=BORDER,
                        highlightthickness=1, bd=0)

        head = tk.Frame(card, bg=SURFACE)
        head.pack(fill="x", padx=22, pady=(18, 6))

        chip = tk.Frame(head, bg=ACCENT_SOFT, width=32, height=32)
        chip.pack(side="left", padx=(0, 14))
        chip.pack_propagate(False)
        tk.Label(chip, text=number, font=FONT_BADGE,
                 bg=ACCENT_SOFT, fg=ACCENT).place(relx=0.5, rely=0.5,
                                                  anchor="center")

        txt = tk.Frame(head, bg=SURFACE)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=title, font=FONT_B, bg=SURFACE, fg=TEXT,
                 anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(txt, text=subtitle, font=FONT_LABEL, bg=SURFACE,
                     fg=TEXT_MUTED, anchor="w").pack(fill="x")
        return card

    def _labeled_entry(self, parent, label: str):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", pady=(8, 4))
        tk.Label(row, text=label, font=FONT_LABEL,
                 bg=SURFACE, fg=TEXT_MUTED,
                 anchor="w").pack(fill="x", pady=(0, 4))
        wrap = tk.Frame(row, bg=BORDER)
        wrap.pack(fill="x")
        ent = tk.Entry(wrap, font=FONT, bg=SURFACE, fg=TEXT,
                       bd=0, relief="flat",
                       highlightthickness=0,
                       insertbackground=TEXT)
        ent.pack(fill="x", padx=1, pady=1, ipady=9, ipadx=12)

        def _focus_in(_):
            wrap.configure(bg=ACCENT)

        def _focus_out(_):
            wrap.configure(bg=BORDER)

        ent.bind("<FocusIn>", _focus_in)
        ent.bind("<FocusOut>", _focus_out)
        return ent

    def _btn(self, parent, text, cmd, style="primary", big=False):
        if style == "primary":
            bg, fg, hov = ACCENT, "#FFFFFF", ACCENT_HOV
        elif style == "ghost-danger":
            bg, fg, hov = SURFACE, DANGER, DANGER_SOFT
        else:
            bg, fg, hov = SURFACE, TEXT, GHOST_HOV

        font = FONT_BTN_BIG if big else FONT_BTN
        padx = 22 if big else 16
        pady = 14 if big else 9

        b = tk.Button(parent, text=text, font=font,
                      bg=bg, fg=fg,
                      activebackground=hov,
                      activeforeground=fg,
                      bd=0, padx=padx, pady=pady,
                      cursor="hand2", command=cmd,
                      relief="flat",
                      highlightthickness=0)

        if style != "primary":
            b.configure(highlightbackground=BORDER,
                        highlightcolor=BORDER,
                        highlightthickness=1)

        b._base_bg = bg
        b._hov_bg = hov

        def _enter(_):
            if str(b["state"]) != "disabled":
                b.configure(bg=hov)

        def _leave(_):
            if str(b["state"]) != "disabled":
                b.configure(bg=b._base_bg)

        b.bind("<Enter>", _enter)
        b.bind("<Leave>", _leave)
        return b

    # ── Pulse animation ──────────────────────────────────────────────────────
    def _start_pulse(self):
        """Soft sine-wave color cycle ~2 seconds; updates registered widgets."""
        def tick():
            self._pulse_phase = (self._pulse_phase + 0.05) % (math.tau)
            # 0..1 sine wave
            t = (math.sin(self._pulse_phase) + 1) / 2

            for widget, base, peak, prop in self._pulse_widgets:
                try:
                    if not widget.winfo_exists():
                        continue
                    rgb = _lerp(_hex_to_rgb(base), _hex_to_rgb(peak), t)
                    widget.configure(**{prop: _rgb_to_hex(rgb)})
                except tk.TclError:
                    pass

            # Status dot pulse — color depends on state
            try:
                if self._status_state == "ready":
                    base, peak = "#16A34A", "#86EFAC"
                elif self._status_state == "running":
                    base, peak = LOG_INFO, "#DBEAFE"
                elif self._status_state == "ok":
                    base, peak = LOG_OK, "#FFFFFF"
                else:  # err
                    base, peak = LOG_ERR, "#FFE4E6"
                rgb = _lerp(_hex_to_rgb(base), _hex_to_rgb(peak), t)
                self._status_dot.configure(fg=_rgb_to_hex(rgb))
            except (AttributeError, tk.TclError):
                pass

            self.after(40, tick)
        self.after(40, tick)

    def _add_pulse(self, widget, base_hex, peak_hex, prop="bg"):
        self._pulse_widgets.append((widget, base_hex, peak_hex, prop))

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Vertical.TScrollbar",
                        background=BG, troughcolor=BG,
                        bordercolor=BG, arrowcolor=TEXT_MUTED,
                        lightcolor=BG, darkcolor=BG)
        style.configure("Dark.Vertical.TScrollbar",
                        background=LOG_BG, troughcolor=LOG_BG,
                        bordercolor=LOG_BG, arrowcolor=LOG_DIM,
                        lightcolor=LOG_BG, darkcolor=LOG_BG)

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG)
        header.pack(side="top", fill="x", padx=32, pady=(24, 6))

        brand = tk.Frame(header, bg=BG)
        brand.pack(fill="x", anchor="w")

        badge = tk.Frame(brand, bg=ACCENT_SOFT, padx=12, pady=4)
        badge.pack(side="left")
        tk.Label(badge, text="e-GP", font=FONT_BADGE,
                 bg=ACCENT_SOFT, fg=ACCENT).pack()
        self._add_pulse(badge, ACCENT_SOFT, "#C7D2FE", "bg")

        tk.Label(brand, text="  •  ตรวจเอกสารส่วนที่ 1 และ 2",
                 font=FONT_KICKER, bg=BG, fg=TEXT_MUTED).pack(side="left")

        tk.Label(header, text="ตรวจเอกสารผู้ยื่นข้อเสนอ",
                 font=FONT_H, bg=BG, fg=NAVY_DEEP,
                 anchor="w").pack(fill="x", pady=(10, 2))
        tk.Label(header,
                 text="อ่านไฟล์ ZIP จากระบบ e-bidding และสร้างไฟล์ Excel สรุปผลการตรวจเอกสาร",
                 font=FONT_SUB, bg=BG, fg=TEXT_MUTED,
                 anchor="w", justify="left").pack(fill="x")

        # ── Log panel — pack BOTTOM first so it always shows ─────────────────
        log_outer = tk.Frame(self, bg=BG)
        log_outer.pack(side="bottom", fill="x", expand=False,
                       padx=32, pady=(0, 24))

        log_head = tk.Frame(log_outer, bg=BG)
        log_head.pack(fill="x", pady=(0, 6))
        tk.Label(log_head, text="บันทึกการทำงาน",
                 font=FONT_KICKER, bg=BG, fg=TEXT_MUTED).pack(side="left")
        self._status_dot = tk.Label(log_head, text="●  พร้อม",
                                    font=FONT_BADGE, bg=BG, fg=LOG_OK)
        self._status_dot.pack(side="right")

        log_frm = tk.Frame(log_outer, bg=LOG_BG, bd=0, relief="flat")
        log_frm.pack(fill="both", expand=False)
        self.log = tk.Text(log_frm, font=FONT_LOG, bg=LOG_BG, fg=LOG_FG,
                           bd=0, relief="flat", state="disabled",
                           wrap="word", height=6,
                           padx=18, pady=16,
                           insertbackground=LOG_FG,
                           highlightthickness=0,
                           selectbackground="#1E293B",
                           selectforeground="#FFFFFF")
        sb2 = ttk.Scrollbar(log_frm, orient="vertical",
                            style="Dark.Vertical.TScrollbar",
                            command=self.log.yview)
        self.log.configure(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.log.tag_config("ok",   foreground=LOG_OK)
        self.log.tag_config("err",  foreground=LOG_ERR)
        self.log.tag_config("info", foreground=LOG_INFO)
        self.log.tag_config("dim",  foreground=LOG_DIM)
        self._log("› พร้อมใช้งาน — เพิ่มไฟล์ ZIP และกรอกข้อมูลโครงการ แล้วกด ▶ ตรวจเอกสาร",
                  "info")

        # ── Action: Run — pack BOTTOM above log ──────────────────────────────
        action = tk.Frame(self, bg=BG)
        action.pack(side="bottom", fill="x", padx=32, pady=(4, 8))
        self.btn_run = self._btn(action, "▶  ตรวจเอกสาร", self._run,
                                 style="primary", big=True)
        self.btn_run.pack(fill="x")
        self._add_pulse(self.btn_run, NAVY, NAVY_MID, "bg")

        # ── Scrollable content area (cards 01-03) ────────────────────────────
        scroll_wrap = tk.Frame(self, bg=BG)
        scroll_wrap.pack(side="top", fill="both", expand=True,
                         padx=32, pady=(16, 0))

        _canvas = tk.Canvas(scroll_wrap, bg=BG, bd=0, highlightthickness=0)
        _vsb = ttk.Scrollbar(scroll_wrap, orient="vertical",
                              command=_canvas.yview,
                              style="Vertical.TScrollbar")
        _canvas.configure(yscrollcommand=_vsb.set)
        _vsb.pack(side="right", fill="y")
        _canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(_canvas, bg=BG)
        _cwin = _canvas.create_window((0, 0), window=content, anchor="nw")

        def _on_content_resize(e):
            _canvas.configure(scrollregion=_canvas.bbox("all"))
        content.bind("<Configure>", _on_content_resize)

        def _on_canvas_resize(e):
            _canvas.itemconfig(_cwin, width=e.width)
        _canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(e):
            _canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        _canvas.bind("<MouseWheel>", _on_mousewheel)
        content.bind("<MouseWheel>", _on_mousewheel)

        # ── Card 1: ZIP ─────────────────────────────────────────────────────
        zip_card = self._card(content, "01", "ไฟล์ ZIP ผู้ยื่นข้อเสนอ",
                              "เลือกไฟล์ .zip ที่ดาวน์โหลดจากระบบ e-bidding")
        zip_card.pack(fill="x", pady=(0, 12))

        btn_row = tk.Frame(zip_card, bg=SURFACE)
        btn_row.pack(fill="x", padx=22, pady=(2, 10))
        self._btn(btn_row, "＋  เพิ่มไฟล์ ZIP", self._add_zips,
                  style="primary").pack(side="left", padx=(0, 8))
        self._btn(btn_row, "ลบที่เลือก", self._remove_zip,
                  style="ghost").pack(side="left", padx=(0, 8))
        self._btn(btn_row, "ล้างทั้งหมด", self._clear_zips,
                  style="ghost-danger").pack(side="left")

        self.lbl_zip_count = tk.Label(btn_row, text="ยังไม่มีไฟล์",
                                      font=FONT_LABEL, bg=SURFACE,
                                      fg=TEXT_FAINT)
        self.lbl_zip_count.pack(side="right")

        list_wrap = tk.Frame(zip_card, bg=BORDER)
        list_wrap.pack(fill="x", padx=22, pady=(0, 18))
        list_inner = tk.Frame(list_wrap, bg=SURFACE_ALT)
        list_inner.pack(fill="x", padx=1, pady=1)

        self.lb_zips = tk.Listbox(list_inner, font=FONT, height=4,
                                  selectmode="extended",
                                  bg=SURFACE_ALT, fg=TEXT,
                                  selectbackground=ACCENT,
                                  selectforeground="#FFFFFF",
                                  activestyle="none",
                                  bd=0, relief="flat",
                                  highlightthickness=0)
        sb = ttk.Scrollbar(list_inner, orient="vertical",
                           command=self.lb_zips.yview)
        self.lb_zips.configure(yscrollcommand=sb.set)
        self.lb_zips.pack(side="left", fill="x", expand=True,
                          padx=(10, 0), pady=10)
        sb.pack(side="right", fill="y")

        # bind mousewheel on listbox to prevent stealing from canvas
        self.lb_zips.bind("<MouseWheel>", lambda e: "break")

        # ── Card 2: Project ─────────────────────────────────────────────────
        info_card = self._card(content, "02", "ข้อมูลโครงการ",
                               "กรอกชื่อโครงการและวงเงิน")
        info_card.pack(fill="x", pady=(0, 12))

        form = tk.Frame(info_card, bg=SURFACE)
        form.pack(fill="x", padx=22, pady=(2, 20))

        self.ent_project = self._labeled_entry(form, "ชื่อโครงการ")
        self.ent_budget  = self._labeled_entry(form, "วงเงิน (บาท)")

        # ── Card 3: Output ──────────────────────────────────────────────────
        out_card = self._card(content, "03", "บันทึกผลที่",
                              "ตำแหน่งไฟล์ Excel ผลลัพธ์")
        out_card.pack(fill="x", pady=(0, 16))

        out_row = tk.Frame(out_card, bg=SURFACE)
        out_row.pack(fill="x", padx=22, pady=(2, 20))

        ent_wrap = tk.Frame(out_row, bg=BORDER)
        ent_wrap.pack(side="left", fill="x", expand=True)
        self.ent_output = tk.Entry(ent_wrap, font=FONT, bg=SURFACE,
                                   fg=TEXT,
                                   bd=0, relief="flat",
                                   highlightthickness=0,
                                   insertbackground=TEXT)
        self.ent_output.insert(0, os.path.join(ROOT, "output", "ตรวจเอกสาร.xlsx"))
        self.ent_output.pack(fill="x", padx=1, pady=1, ipady=9, ipadx=12)

        def _out_fin(_):
            ent_wrap.configure(bg=ACCENT)

        def _out_fout(_):
            ent_wrap.configure(bg=BORDER)

        self.ent_output.bind("<FocusIn>", _out_fin)
        self.ent_output.bind("<FocusOut>", _out_fout)

        self._btn(out_row, "เลือกที่บันทึก", self._pick_output,
                  style="ghost").pack(side="left", padx=(10, 0))

        # Ensure canvas scrolls to top after all widgets are rendered
        self.after(100, lambda: _canvas.yview_moveto(0))

    # ── Actions ───────────────────────────────────────────────────────────────
    def _update_zip_count(self):
        n = len(self.zip_paths)
        self.lbl_zip_count.configure(
            text=f"{n} ไฟล์" if n else "ยังไม่มีไฟล์",
            fg=TEXT if n else TEXT_FAINT,
        )

    def _add_zips(self):
        files = filedialog.askopenfilenames(
            title="เลือกไฟล์ ZIP จาก e-GP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            initialdir=os.path.join(ROOT, "uploads") if os.path.exists(
                os.path.join(ROOT, "uploads")) else ROOT,
        )
        for f in files:
            if f not in self.zip_paths:
                self.zip_paths.append(f)
                self.lb_zips.insert("end", "  " + os.path.basename(f))
        self._update_zip_count()

    def _remove_zip(self):
        sel = list(self.lb_zips.curselection())
        for i in reversed(sel):
            self.lb_zips.delete(i)
            self.zip_paths.pop(i)
        self._update_zip_count()

    def _clear_zips(self):
        self.lb_zips.delete(0, "end")
        self.zip_paths.clear()
        self._update_zip_count()

    def _pick_output(self):
        f = filedialog.asksaveasfilename(
            title="บันทึก Excel ที่",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialdir=os.path.join(ROOT, "output"),
        )
        if f:
            self.ent_output.delete(0, "end")
            self.ent_output.insert(0, f)

    def _log(self, msg: str, tag: str = ""):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str, state: str):
        """state: ready | running | ok | err"""
        self._status_state = state
        self._status_dot.configure(text=f"●  {text}")

    def _run(self):
        if not self.zip_paths:
            messagebox.showerror("ข้อผิดพลาด", "กรุณาเพิ่มไฟล์ ZIP อย่างน้อย 1 ไฟล์")
            return
        project = self.ent_project.get().strip()
        if not project:
            messagebox.showerror("ข้อผิดพลาด", "กรุณากรอกชื่อโครงการ")
            return
        budget_str = self.ent_budget.get().strip().replace(",", "")
        try:
            budget = float(budget_str)
        except ValueError:
            messagebox.showerror("ข้อผิดพลาด", "วงเงินต้องเป็นตัวเลข เช่น 1391000")
            return
        output = self.ent_output.get().strip()
        if not output:
            messagebox.showerror("ข้อผิดพลาด", "กรุณาระบุที่บันทึกไฟล์ Excel")
            return

        self.btn_run.configure(state="disabled", text="⏳  กำลังประมวลผล...")
        self._set_status("กำลังประมวลผล", "running")
        self._log("─" * 64, "dim")
        self._log(f"โครงการ : {project}", "info")
        self._log(f"วงเงิน  : {budget:,.0f} บาท", "info")
        self._log(f"ผู้ยื่น  : {len(self.zip_paths)} ราย", "info")
        self._log("─" * 64, "dim")

        threading.Thread(
            target=self._run_main,
            args=(project, budget, output),
            daemon=True,
        ).start()

    def _run_main(self, project: str, budget: float, output: str):
        cmd = [
            PYTHON,
            os.path.join(ROOT, "main.py"),
            *self.zip_paths,
            "--project", project,
            "--budget", str(budget),
            "--output", output,
        ]
        try:
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=ROOT,
                env=env,
            )
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tag = "ok" if ("✅" in line or "🎉" in line) else \
                      "err" if ("❌" in line or "Error" in line or "error" in line) else ""
                self.after(0, self._log, line, tag)
            proc.wait()

            if proc.returncode == 0:
                self.after(0, self._log, "✅ เสร็จสิ้น! เปิดไฟล์ Excel...", "ok")
                self.after(0, self._set_status, "เสร็จสิ้น", "ok")
                self.after(500, lambda: os.startfile(output)
                           if os.path.exists(output) else None)
            else:
                self.after(0, self._log, "❌ เกิดข้อผิดพลาด ดู log ด้านบน", "err")
                self.after(0, self._set_status, "ผิดพลาด", "err")
        except Exception as e:
            self.after(0, self._log, f"❌ Exception: {e}", "err")
            self.after(0, self._set_status, "ผิดพลาด", "err")
        finally:
            self.after(0, self.btn_run.configure,
                       {"state": "normal", "text": "▶  ตรวจเอกสาร"})


if __name__ == "__main__":
    app = App()
    app.mainloop()
