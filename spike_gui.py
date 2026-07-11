import tkinter as tk
from tkinter import filedialog, messagebox
import os
import math
import time
from spike_decompiler import decompile_spike_project

class ModernDecompilerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("OhhChitss CONVERTER V1.0")
        self.root.geometry("520x420")
        self.root.configure(bg="#0C0D0E") # Ultra-dark slate background
        self.root.resizable(False, False)
        
        self.selected_file = None
        self.pulse_phase = 0.0
        self.is_scanning = False
        self.scan_y = 0
        
        self.create_widgets()
        self.run_animations()
        
    def create_widgets(self):
        # Background Canvas for custom abstract UI styling
        self.bg_canvas = tk.Canvas(self.root, bg="#0C0D0E", bd=0, highlightthickness=0, width=520, height=420)
        self.bg_canvas.place(x=0, y=0)
        
        # Draw techy background grid lines
        for i in range(0, 520, 40):
            self.bg_canvas.create_line(i, 0, i, 420, fill="#141619", width=1)
        for i in range(0, 420, 40):
            self.bg_canvas.create_line(0, i, 520, i, fill="#141619", width=1)

        # Draw a glowing center hub circle (Yellow themed glow)
        self.hub_glow = self.bg_canvas.create_oval(230, 90, 290, 150, outline="", fill="#2D2510")
        self.hub_core = self.bg_canvas.create_oval(240, 100, 280, 140, outline="#F3BD41", fill="#0F1115", width=3)
        # Pulsing LED light inside the hub
        self.led_light = self.bg_canvas.create_oval(253, 113, 267, 127, outline="", fill="#F3BD41")

        # Header Title
        self.title_label = tk.Label(
            self.root, 
            text="SPIKE PRIME CONVERTER", 
            font=("Consolas", 18, "bold"), 
            fg="#FFFFFF", 
            bg="#0C0D0E"
        )
        self.title_label.place(x=0, y=25, width=520)
        
        self.subtitle_label = tk.Label(
            self.root, 
            text="Word Blocks (.llsp3) ➔ Python (.llsp3)", 
            font=("Segoe UI", 9), 
            fg="#8A95A5", 
            bg="#0C0D0E"
        )
        self.subtitle_label.place(x=0, y=55, width=520)
        
        # Interactive Card-like Frame for file information
        self.card = tk.Frame(self.root, bg="#16181C", bd=1, highlightbackground="#242730", highlightthickness=1)
        self.card.place(x=40, y=170, width=440, height=80)
        
        self.file_label = tk.Label(
            self.card, 
            text="Please select your SPIKE Prime Word Blocks project", 
            font=("Segoe UI", 10), 
            fg="#9EA9B7", 
            bg="#16181C",
            wraplength=400
        )
        self.file_label.pack(expand=True, fill="both", padx=10, pady=10)

        # Select Button (Yellow themed)
        self.select_btn = tk.Button(
            self.root,
            text="📁 Select File",
            font=("Segoe UI", 10, "bold"),
            bg="#F3BD41", # SPIKE Yellow
            fg="#000000", # Dark text for yellow contrast
            activebackground="#D9A426",
            activeforeground="#000000",
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self.select_file
        )
        self.select_btn.place(x=40, y=270, width=440, height=42)
        
        # Bind hover effects
        self.select_btn.bind("<Enter>", lambda e: self.animate_button_hover(self.select_btn, "#F5C75D"))
        self.select_btn.bind("<Leave>", lambda e: self.animate_button_hover(self.select_btn, "#F3BD41"))

        # Convert Button (Initially greyed out)
        self.convert_btn = tk.Button(
            self.root,
            text="⚡ Convert & Save",
            font=("Segoe UI", 10, "bold"),
            bg="#1D1F24",
            fg="#5C5E62",
            activebackground="#1D1F24",
            activeforeground="#5C5E62",
            relief="flat",
            bd=0,
            state="disabled",
            command=self.trigger_scan_and_convert
        )
        self.convert_btn.place(x=40, y=325, width=440, height=42)
        
        # Footer (Renamed to OhhChitss CONVERTER V1.0)
        footer_label = tk.Label(
            self.root,
            text="OhhChitss CONVERTER V1.0",
            font=("Consolas", 8),
            fg="#5A616A",
            bg="#0C0D0E"
        )
        footer_label.place(x=0, y=390, width=520)
        
        # Scanner line (Yellow themed)
        self.scanner_line = self.bg_canvas.create_line(0, -10, 520, -10, fill="#F3BD41", width=3)
        self.scanner_glow = self.bg_canvas.create_polygon(0, -10, 520, -10, 520, -10, 0, -10, fill="#F3BD41", stipple="gray25")

    def animate_button_hover(self, btn, color):
        if btn["state"] != "disabled":
            btn.config(bg=color)

    def select_file(self):
        file_path = filedialog.askopenfilename(
            title="Open SPIKE Prime Word Blocks Project",
            filetypes=[("SPIKE Prime Project (*.llsp3)", "*.llsp3")]
        )
        
        if file_path:
            self.selected_file = file_path
            filename = os.path.basename(file_path)
            self.file_label.config(text=f"📂 SELECTED:\n{filename}", fg="#F3BD41", font=("Segoe UI", 10, "bold"))
            
            # Change card outline
            self.card.config(highlightbackground="#F3BD41")
            
            # Enable Convert Button
            self.convert_btn.config(
                state="normal", 
                bg="#F3BD41", 
                fg="#000000", 
                activebackground="#D9A426",
                activeforeground="#000000",
                cursor="hand2"
            )
            self.convert_btn.bind("<Enter>", lambda e: self.animate_button_hover(self.convert_btn, "#F5C75D"))
            self.convert_btn.bind("<Leave>", lambda e: self.animate_button_hover(self.convert_btn, "#F3BD41"))
            
    def run_animations(self):
        # 1. Pulsing LED animation (Yellow breathing)
        self.pulse_phase += 0.08
        val = int((math.sin(self.pulse_phase) + 1) * 110) + 35 # 35 to 255
        
        # Calculate beautiful golden yellow pulse
        color_hex = f"#{val:02x}{int(val*0.78):02x}{val//10:02x}"
        glow_hex = f"#{val//3:02x}{val//4:02x}00"
        
        self.bg_canvas.itemconfig(self.led_light, fill=color_hex)
        self.bg_canvas.itemconfig(self.hub_glow, fill=glow_hex)

        # 2. Scanning beam animation
        if self.is_scanning:
            self.scan_y += 8
            self.bg_canvas.coords(self.scanner_line, 0, self.scan_y, 520, self.scan_y)
            self.bg_canvas.coords(self.scanner_glow, 0, self.scan_y - 20, 520, self.scan_y - 20, 520, self.scan_y, 0, self.scan_y)
            
            if self.scan_y > 420:
                self.is_scanning = False
                self.bg_canvas.coords(self.scanner_line, 0, -10, 520, -10)
                self.bg_canvas.coords(self.scanner_glow, 0, -10, 520, -10, 520, -10, 0, -10)
                self.perform_save()

        self.root.after(30, self.run_animations)

    def trigger_scan_and_convert(self):
        if not self.selected_file:
            return
        
        self.is_scanning = True
        self.scan_y = 0
        self.convert_btn.config(state="disabled", bg="#1D1F24", fg="#5C5E62")
        self.select_btn.config(state="disabled", bg="#1D1F24", fg="#5C5E62")
        self.file_label.config(text="⚡ DECOMPILING & PACKAGING PROJECT...", fg="#F3BD41")

    def perform_save(self):
        default_name = os.path.splitext(os.path.basename(self.selected_file))[0] + "_python.llsp3"
        
        save_path = filedialog.asksaveasfilename(
            title="Save Converted SPIKE Python Project",
            initialfile=default_name,
            filetypes=[("SPIKE Prime Python Project (*.llsp3)", "*.llsp3")],
            defaultextension=".llsp3"
        )
        
        if save_path:
            success, err = decompile_spike_project(self.selected_file, save_path)
            if success:
                messagebox.showinfo("Success", f"Successfully converted and saved to:\n{save_path}")
            else:
                messagebox.showerror("Error", f"Failed to decompile project:\n{err}")
                
        # Reset UI states
        self.selected_file = None
        self.file_label.config(text="Please select your SPIKE Prime Word Blocks project", fg="#9EA9B7", font=("Segoe UI", 10))
        self.card.config(highlightbackground="#242730")
        
        self.select_btn.config(state="normal", bg="#F3BD41", fg="#000000")
        self.convert_btn.config(
            state="disabled",
            bg="#1D1F24",
            fg="#5C5E62"
        )

if __name__ == "__main__":
    root = tk.Tk()
    app = ModernDecompilerGUI(root)
    root.mainloop()
