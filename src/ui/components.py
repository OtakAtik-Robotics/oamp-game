import customtkinter

# ─── Neon Arcade Palette (Light Mode) ────────────────────────────────────────

NEON_RED     = "#FF1744"
NEON_GREEN   = "#00897B"
NEON_CYAN    = "#0097A7"
NEON_ORANGE  = "#E65100"
NEON_YELLOW  = "#F9A825"

BG_VOID      = "#f5f5f5"
BG_CARD      = "#ffffff"
BORDER_DIM   = "#e0e0e0"
TEXT_WHITE   = "#1a1a1a"
TEXT_MUTED   = "#757575"
TEXT_DIM     = "#bdbdbd"

LEVEL_COLORS = {
    1: "#D32F2F", 2: "#E65100", 3: "#F9A825", 4: "#00897B",
    5: "#0097A7", 6: "#2979FF", 7: "#7B1FA2", 8: "#C2185B",
}


class TextFrame(customtkinter.CTkFrame):
    def __init__(self, master, title):
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        customtkinter.CTkLabel(
            self, text=title, fg_color=BG_CARD, corner_radius=6,
            font=("Helvetica", 13), text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")


class ImageFrame(customtkinter.CTkFrame):
    def __init__(self, master, title=""):
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        if title:
            customtkinter.CTkLabel(
                self, text=title, corner_radius=6,
                font=("Courier", 10, "bold"), text_color=NEON_RED,
            ).grid(row=0, column=0, padx=10, pady=(10, 0), sticky="ew")


class TimerDisplay(customtkinter.CTkFrame):
    COLOR_FAST   = NEON_GREEN
    COLOR_OK     = NEON_YELLOW
    COLOR_SLOW   = NEON_ORANGE
    COLOR_DANGER = NEON_RED

    def __init__(self, master, width=110, font_size=26):
        super().__init__(master, corner_radius=10, fg_color=BG_CARD,
                         border_width=2, border_color=BORDER_DIM, width=width)
        self.pack_propagate(False)
        self._label = customtkinter.CTkLabel(
            self, text="00:00.00",
            font=("Courier", font_size, "bold"),
            text_color=self.COLOR_FAST,
        )
        self._label.pack(expand=True, fill="both")
        self._pulsing = False
        self._border_bright = False

    def set_time(self, elapsed: float):
        m  = int(elapsed // 60)
        s  = int(elapsed % 60)
        ms = int((elapsed % 1) * 100)
        c  = (self.COLOR_FAST if elapsed < 10
              else self.COLOR_OK if elapsed < 25
              else self.COLOR_SLOW if elapsed < 40
              else self.COLOR_DANGER)
        self._label.configure(text=f"{m:02d}:{s:02d}.{ms:02d}", text_color=c)

        if elapsed >= 40:
            self.configure(border_color=c)
            if not self._pulsing:
                self._pulsing = True
                self._pulse()
        else:
            self._pulsing = False
            self.configure(border_color=BORDER_DIM)

    def _pulse(self):
        if not self._pulsing:
            self.configure(border_color=self.COLOR_DANGER)
            return
        self._border_bright = not self._border_bright
        self.configure(
            border_color=self.COLOR_DANGER if self._border_bright else BG_VOID
        )
        self.after(400, self._pulse)

    def reset(self):
        self._pulsing = False
        self._border_bright = False
        self._label.configure(text="00:00.00", text_color=self.COLOR_FAST)
        self.configure(border_color=BORDER_DIM)


class LevelBadge(customtkinter.CTkFrame):
    def __init__(self, master, max_level=8, **kw):
        super().__init__(master, corner_radius=12, fg_color=BG_CARD,
                         border_width=2, border_color=NEON_RED, **kw)
        self._max_level = max_level
        self.grid_columnconfigure(0, weight=1)

        customtkinter.CTkLabel(
            self, text="LEVEL",
            font=("Courier", 9, "bold"), text_color=NEON_RED,
        ).grid(row=0, column=0, pady=(10, 0))

        self._num = customtkinter.CTkLabel(
            self, text="—",
            font=("Helvetica", 44, "bold"), text_color=TEXT_WHITE,
        )
        self._num.grid(row=1, column=0)

        self._dots_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        self._dots_frame.grid(row=2, column=0, pady=(2, 10))
        self._dots = []
        for i in range(max_level):
            dot = customtkinter.CTkLabel(
                self._dots_frame, text="◆",
                font=("Helvetica", 9), text_color=TEXT_DIM, width=14,
            )
            dot.grid(row=0, column=i, padx=1)
            self._dots.append(dot)

    def set_level(self, level: int):
        color = LEVEL_COLORS.get(level, NEON_RED)
        self._num.configure(text=str(level), text_color=color)
        self.configure(border_color=color)
        for i, dot in enumerate(self._dots):
            lvl = i + 1
            if lvl < level:
                dot.configure(text_color=NEON_GREEN)
            elif lvl == level:
                dot.configure(text_color=color)
            else:
                dot.configure(text_color=TEXT_DIM)

    def set_completed(self, level: int):
        if 1 <= level <= len(self._dots):
            self._dots[level - 1].configure(text_color=NEON_GREEN)


class CameraPanel(customtkinter.CTkFrame):
    """Single camera panel for game feed only."""
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=BG_CARD, corner_radius=12,
                         border_width=1, border_color=BORDER_DIM, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        customtkinter.CTkLabel(
            self, text="◉ CAMERA — GAME",
            font=("Courier", 9, "bold"), text_color=NEON_RED,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 2))

        self._cam_label = customtkinter.CTkLabel(self, text="", anchor="center")
        self._cam_label.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def update_frame(self, pil_image):
        from PIL import ImageTk
        w = self._cam_label.winfo_width()
        h = self._cam_label.winfo_height()
        if w > 10 and h > 10:
            fw, fh = pil_image.size
            scale = min(w / fw, h / fh)
            if scale != 1.0:
                pil_image = pil_image.resize(
                    (int(fw * scale), int(fh * scale)), Image.Resampling.LANCZOS
                )
        tk_img = ImageTk.PhotoImage(image=pil_image)
        self._cam_label.imgtk = tk_img
        self._cam_label.configure(image=tk_img)


class StatusBar(customtkinter.CTkFrame):
    """Status bar: server indicator, FPS, attempts. No voice/face."""
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=BG_CARD, corner_radius=0, height=36, **kw)
        self.grid_propagate(False)
        self.grid_columnconfigure(3, weight=1)

        self._sdot = customtkinter.CTkLabel(
            self, text="●", font=("Helvetica", 12), text_color=TEXT_DIM, width=16,
        )
        self._sdot.grid(row=0, column=0, padx=(10, 2), pady=5)
        self._slbl = customtkinter.CTkLabel(
            self, text="Offline", font=("Courier", 10), text_color=TEXT_MUTED,
        )
        self._slbl.grid(row=0, column=1, padx=(0, 12), pady=5)

        self._fps = customtkinter.CTkLabel(
            self, text="FPS: —", font=("Courier", 10), text_color=TEXT_DIM,
        )
        self._fps.grid(row=0, column=2, padx=(0, 12), pady=5, sticky="e")
        self._att = customtkinter.CTkLabel(
            self, text="Percobaan: —", font=("Courier", 10), text_color=TEXT_DIM,
        )
        self._att.grid(row=0, column=3, padx=(0, 16), pady=5, sticky="e")

    def set_server_online(self, online: bool):
        if online:
            self._sdot.configure(text_color=NEON_GREEN)
            self._slbl.configure(text="Server online", text_color=NEON_GREEN)
        else:
            self._sdot.configure(text_color=NEON_RED)
            self._slbl.configure(text="Offline (buffer)", text_color=NEON_RED)

    def set_fps(self, fps: int):
        c = NEON_GREEN if fps >= 20 else NEON_ORANGE if fps >= 10 else NEON_RED
        self._fps.configure(text=f"FPS: {fps}", text_color=c)

    def set_attempts(self, n: int):
        self._att.configure(text=f"Percobaan: {n}", text_color=NEON_CYAN)