import tkinter as tk
from tkinter import filedialog, messagebox
import os
import math
import time
from spike_decompiler import decompile_spike_project
from spike_recompiler import recompile_python_to_wordblocks

# ─── Mode configuration ──────────────────────────────────────────────────────
MODES = {
    "blocks_to_python": {
        "label":       "Word Blocks → Python",
        "subtitle":    "Word Blocks (.llsp3)  ➔  Python (.llsp3)",
        "select_tip":  "Please select your SPIKE Prime Word Blocks project",
        "scanning":    "⚡ DECOMPILING & PACKAGING PROJECT...",
        "save_title":  "Save Converted Python Project",
        "save_suffix": "_python.llsp3",
        "filetypes":   [("SPIKE Prime Project (*.llsp3)", "*.llsp3")],
        "icon":        "🔷",
    },
    "python_to_blocks": {
        "label":       "Python → Word Blocks",
        "subtitle":    "Python (.llsp3)  ➔  Word Blocks (.llsp3)",
        "select_tip":  "Please select your SPIKE Prime Python project",
        "scanning":    "⚡ RECOMPILING TO WORD BLOCKS...",
        "save_title":  "Save Converted Word Blocks Project",
        "save_suffix": "_blocks.llsp3",
        "filetypes":   [("SPIKE Prime Python Project (*.llsp3)", "*.llsp3")],
        "icon":        "🔶",
    },
}


class ModernDecompilerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OhhChitss CONVERTER V1.4 (100% Absolute Match)")
        self.root.geometry("520x460")
        self.root.configure(bg="#0C0D0E")
        self.root.resizable(False, False)

        self.selected_file  = None
        self.pulse_phase    = 0.0
        self.is_scanning    = False
        self.scan_y         = 0
        self._current_mode  = "blocks_to_python"

        self.create_widgets()
        self.run_animations()

    # ─── widgets ─────────────────────────────────────────────────────────────

    def create_widgets(self):
        # Background canvas with tech grid
        self.bg_canvas = tk.Canvas(
            self.root, bg="#0C0D0E", bd=0, highlightthickness=0, width=520, height=460
        )
        self.bg_canvas.place(x=0, y=0)

        for i in range(0, 520, 40):
            self.bg_canvas.create_line(i, 0, i, 460, fill="#141619", width=1)
        for i in range(0, 460, 40):
            self.bg_canvas.create_line(0, i, 520, i, fill="#141619", width=1)

        # Hub glow circle
        self.hub_glow = self.bg_canvas.create_oval(230, 90, 290, 150, outline="", fill="#2D2510")
        self.hub_core = self.bg_canvas.create_oval(240, 100, 280, 140, outline="#F3BD41",
                                                    fill="#0F1115", width=3)
        self.led_light = self.bg_canvas.create_oval(253, 113, 267, 127, outline="", fill="#F3BD41")

        # Title
        tk.Label(self.root, text="SPIKE PRIME CONVERTER",
                 font=("Consolas", 18, "bold"), fg="#FFFFFF", bg="#0C0D0E"
                 ).place(x=0, y=25, width=520)

        # Subtitle (changes with mode)
        self.subtitle_label = tk.Label(
            self.root, text=MODES[self._current_mode]["subtitle"],
            font=("Segoe UI", 9), fg="#8A95A5", bg="#0C0D0E"
        )
        self.subtitle_label.place(x=0, y=55, width=520)

        # ── Mode toggle button ────────────────────────────────────────────
        self.mode_btn = tk.Button(
            self.root,
            text=f"🔄  Mode: {MODES[self._current_mode]['label']}",
            font=("Segoe UI", 9, "bold"),
            bg="#1A1D22", fg="#F3BD41",
            activebackground="#242730", activeforeground="#F3BD41",
            relief="flat", bd=0, cursor="hand2",
            command=self.toggle_mode,
        )
        self.mode_btn.place(x=40, y=160, width=440, height=34)
        self.mode_btn.bind("<Enter>", lambda e: self.mode_btn.config(bg="#242730"))
        self.mode_btn.bind("<Leave>", lambda e: self.mode_btn.config(bg="#1A1D22"))

        # ── File info card ────────────────────────────────────────────────
        self.card = tk.Frame(self.root, bg="#16181C", bd=1,
                             highlightbackground="#242730", highlightthickness=1)
        self.card.place(x=40, y=210, width=440, height=80)

        self.file_label = tk.Label(
            self.card,
            text=MODES[self._current_mode]["select_tip"],
            font=("Segoe UI", 10), fg="#9EA9B7", bg="#16181C", wraplength=400
        )
        self.file_label.pack(expand=True, fill="both", padx=10, pady=10)

        # ── Select button ─────────────────────────────────────────────────
        self.select_btn = tk.Button(
            self.root, text="📁  Select File",
            font=("Segoe UI", 10, "bold"),
            bg="#F3BD41", fg="#000000",
            activebackground="#D9A426", activeforeground="#000000",
            relief="flat", bd=0, cursor="hand2",
            command=self.select_file,
        )
        self.select_btn.place(x=40, y=310, width=440, height=42)
        self.select_btn.bind("<Enter>", lambda e: self._hover(self.select_btn, "#F5C75D"))
        self.select_btn.bind("<Leave>", lambda e: self._hover(self.select_btn, "#F3BD41"))

        # ── Convert button ────────────────────────────────────────────────
        self.convert_btn = tk.Button(
            self.root, text="⚡  Convert & Save",
            font=("Segoe UI", 10, "bold"),
            bg="#1D1F24", fg="#5C5E62",
            activebackground="#1D1F24", activeforeground="#5C5E62",
            relief="flat", bd=0, state="disabled",
            command=self.trigger_scan_and_convert,
        )
        self.convert_btn.place(x=40, y=364, width=440, height=42)

        # ── Footer ────────────────────────────────────────────────────────
        tk.Label(self.root, text="OhhChitss CONVERTER V1.4 (100% Absolute Match)",
                 font=("Consolas", 8), fg="#5A616A", bg="#0C0D0E"
                 ).place(x=0, y=430, width=520)





        # Scanner line
        self.scanner_line  = self.bg_canvas.create_line(0, -10, 520, -10, fill="#F3BD41", width=3)
        self.scanner_glow  = self.bg_canvas.create_polygon(
            0, -10, 520, -10, 520, -10, 0, -10, fill="#F3BD41", stipple="gray25"
        )

    # ─── mode toggle ─────────────────────────────────────────────────────────

    def toggle_mode(self):
        if self._current_mode == "blocks_to_python":
            self._current_mode = "python_to_blocks"
        else:
            self._current_mode = "blocks_to_python"
        self._apply_mode()

    def _apply_mode(self):
        m = MODES[self._current_mode]
        self.mode_btn.config(text=f"🔄  Mode: {m['label']}")
        self.subtitle_label.config(text=m["subtitle"])
        # Reset file selection
        self.selected_file = None
        self.file_label.config(text=m["select_tip"], fg="#9EA9B7", font=("Segoe UI", 10))
        self.card.config(highlightbackground="#242730")
        self.convert_btn.config(state="disabled", bg="#1D1F24", fg="#5C5E62")

    # ─── file selection ───────────────────────────────────────────────────────

    def select_file(self):
        m = MODES[self._current_mode]
        file_path = filedialog.askopenfilename(
            title=f"Open SPIKE Prime Project",
            filetypes=m["filetypes"]
        )
        if file_path:
            self.selected_file = file_path
            filename = os.path.basename(file_path)
            self.file_label.config(
                text=f"📂  SELECTED:\n{filename}",
                fg="#F3BD41", font=("Segoe UI", 10, "bold")
            )
            self.card.config(highlightbackground="#F3BD41")
            self.convert_btn.config(
                state="normal", bg="#F3BD41", fg="#000000",
                activebackground="#D9A426", activeforeground="#000000",
                cursor="hand2",
            )
            self.convert_btn.bind("<Enter>", lambda e: self._hover(self.convert_btn, "#F5C75D"))
            self.convert_btn.bind("<Leave>", lambda e: self._hover(self.convert_btn, "#F3BD41"))

    # ─── animation helpers ────────────────────────────────────────────────────

    def _hover(self, btn, color):
        if btn["state"] != "disabled":
            btn.config(bg=color)

    def run_animations(self):
        # Breathing LED
        self.pulse_phase += 0.08
        val = int((math.sin(self.pulse_phase) + 1) * 110) + 35
        self.bg_canvas.itemconfig(self.led_light, fill=f"#{val:02x}{int(val*0.78):02x}{val//10:02x}")
        self.bg_canvas.itemconfig(self.hub_glow,  fill=f"#{val//3:02x}{val//4:02x}00")

        # Scanner beam
        if self.is_scanning:
            self.scan_y += 8
            self.bg_canvas.coords(self.scanner_line, 0, self.scan_y, 520, self.scan_y)
            self.bg_canvas.coords(
                self.scanner_glow,
                0, self.scan_y - 20, 520, self.scan_y - 20,
                520, self.scan_y, 0, self.scan_y
            )
            if self.scan_y > 460:
                self.is_scanning = False
                self.bg_canvas.coords(self.scanner_line, 0, -10, 520, -10)
                self.bg_canvas.coords(self.scanner_glow, 0, -10, 520, -10, 520, -10, 0, -10)
                self.perform_save()

        self.root.after(30, self.run_animations)

    def trigger_scan_and_convert(self):
        if not self.selected_file:
            return
        m = MODES[self._current_mode]
        self.is_scanning = True
        self.scan_y = 0
        self.convert_btn.config(state="disabled", bg="#1D1F24", fg="#5C5E62")
        self.select_btn.config(state="disabled",  bg="#1D1F24", fg="#5C5E62")
        self.file_label.config(text=m["scanning"], fg="#F3BD41")

    # ─── save / convert ───────────────────────────────────────────────────────

    def perform_save(self):
        m = MODES[self._current_mode]
        default_name = (os.path.splitext(os.path.basename(self.selected_file))[0]
                        + m["save_suffix"])

        save_path = filedialog.asksaveasfilename(
            title=m["save_title"],
            initialfile=default_name,
            filetypes=[("SPIKE Prime Project (*.llsp3)", "*.llsp3")],
            defaultextension=".llsp3",
        )

        if save_path:
            if self._current_mode == "blocks_to_python":
                success, result = decompile_spike_project(self.selected_file, save_path)
                warnings = []
            else:
                success, result = recompile_python_to_wordblocks(self.selected_file, save_path)
                if success:
                    warnings = result  # result is list of warnings
                else:
                    warnings = []

            if success:
                msg = f"✅ แปลงและบันทึกสำเร็จ!\n\n📂 {save_path}"
                if warnings:
                    warn_text = "\n".join(f"  • {w}" for w in warnings[:10])
                    if len(warnings) > 10:
                        warn_text += f"\n  ... และอีก {len(warnings) - 10} รายการ"
                    messagebox.showwarning(
                        "⚠️ สำเร็จ (มีคำเตือน)",
                        f"{msg}\n\n"
                        f"⚠️ พบคำสั่งที่แปลงกลับไม่ได้ {len(warnings)} รายการ "
                        f"(ถูกข้ามไปในไฟล์บล็อก):\n\n{warn_text}"
                    )
                else:
                    messagebox.showinfo("✅ สำเร็จ!", msg)
            else:
                err = result if isinstance(result, str) else "\n".join(result)
                messagebox.showerror("❌ Error", f"แปลงไม่สำเร็จ:\n\n{err}")

        # Reset UI
        self.selected_file = None
        self.file_label.config(
            text=MODES[self._current_mode]["select_tip"],
            fg="#9EA9B7", font=("Segoe UI", 10)
        )
        self.card.config(highlightbackground="#242730")
        self.select_btn.config(state="normal",  bg="#F3BD41", fg="#000000")
        self.convert_btn.config(state="disabled", bg="#1D1F24", fg="#5C5E62")


if __name__ == "__main__":
    root = tk.Tk()
    app = ModernDecompilerGUI(root)
    root.mainloop()
