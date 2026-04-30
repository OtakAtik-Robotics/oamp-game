import customtkinter
from typing import Optional

customtkinter.set_appearance_mode("Light")
customtkinter.set_default_color_theme("blue")

RED       = "#FF1744"
RED_DARK  = "#B71C1C"
RED_LIGHT = "#FF5252"
BG_DARK   = "#f5f5f5"
BG_CARD   = "#ffffff"
BG_INPUT  = "#eeeeee"
BORDER    = "#e0e0e0"
WHITE     = "#1a1a1a"
MUTED     = "#757575"
GREEN     = "#00897B"


class StyledEntry(customtkinter.CTkFrame):
    def __init__(self, master, label: str, placeholder: str = "", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self._label = customtkinter.CTkLabel(
            self, text=label,
            font=("Helvetica", 12, "bold"),
            text_color=MUTED,
            anchor="w",
        )
        self._label.grid(row=0, column=0, sticky="ew", padx=2, pady=(0, 4))

        self._entry = customtkinter.CTkEntry(
            self,
            placeholder_text=placeholder,
            font=("Helvetica", 20),
            height=48,
            corner_radius=8,
            border_color=BORDER,
            fg_color=BG_INPUT,
            text_color=WHITE,
            border_width=2,
        )
        self._entry.grid(row=1, column=0, sticky="ew")

        self._error_label = customtkinter.CTkLabel(
            self, text="",
            font=("Helvetica", 10),
            text_color=RED_LIGHT,
            anchor="w",
        )
        self._error_label.grid(row=2, column=0, sticky="ew", padx=2, pady=(2, 0))

        self._entry.bind("<FocusIn>",  self._on_focus)
        self._entry.bind("<FocusOut>", self._on_blur)

    def get(self) -> str:
        return self._entry.get().strip()

    def set_error(self, msg: str):
        self._error_label.configure(text=msg)
        self._entry.configure(border_color=RED_LIGHT)

    def clear_error(self):
        self._error_label.configure(text="")
        self._entry.configure(border_color=BORDER)

    def focus(self):
        self._entry.focus()

    def bind_entry(self, event, handler):
        self._entry.bind(event, handler)

    def _on_focus(self, _):
        self._entry.configure(border_color=RED)
        self._label.configure(text_color=RED_LIGHT)

    def _on_blur(self, _):
        self._entry.configure(border_color=BORDER)
        self._label.configure(text_color=MUTED)


class GenderSelector(customtkinter.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure((0, 1), weight=1)

        self._value = customtkinter.StringVar(value="")
        self._error_label = customtkinter.CTkLabel(
            self, text="",
            font=("Helvetica", 10),
            text_color=RED_LIGHT,
            anchor="w",
        )
        self._error_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=2, pady=(4, 0))

        self._btn_male = customtkinter.CTkButton(
            self, text="Laki-laki",
            font=("Helvetica", 14),
            height=48,
            corner_radius=8,
            fg_color=BG_INPUT,
            hover_color="#e0e0e0",
            border_width=2,
            border_color=BORDER,
            text_color=MUTED,
            command=lambda: self._select("male"),
        )
        self._btn_male.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self._btn_female = customtkinter.CTkButton(
            self, text="Perempuan",
            font=("Helvetica", 14),
            height=48,
            corner_radius=8,
            fg_color=BG_INPUT,
            hover_color="#e0e0e0",
            border_width=2,
            border_color=BORDER,
            text_color=MUTED,
            command=lambda: self._select("female"),
        )
        self._btn_female.grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _select(self, value: str):
        self._value.set(value)
        self.clear_error()
        for btn in (self._btn_male, self._btn_female):
            btn.configure(fg_color=BG_INPUT, border_color=BORDER, text_color=MUTED)
        btn = self._btn_male if value == "male" else self._btn_female
        btn.configure(fg_color=RED_DARK, border_color=RED, text_color=WHITE)

    def get(self) -> str:
        return self._value.get()

    def set_error(self, msg: str):
        self._error_label.configure(text=msg)

    def clear_error(self):
        self._error_label.configure(text="")


class InputWindow(customtkinter.CTk):
    def __init__(self, server_client=None):
        super().__init__()
        self._result: Optional[dict] = None
        self._server = server_client
        self._auth_data: Optional[dict] = None

        self.title("Otak Atik Merah Putih — Registrasi")
        self.geometry("520x620+580+80")
        self.resizable(False, False)
        self.configure(fg_color=BG_DARK)

        self._build_ui()
        self._bind_keys()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = customtkinter.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=80)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)

        strip = customtkinter.CTkFrame(header, fg_color=RED, height=4, corner_radius=0)
        strip.pack(fill="x", side="top")

        customtkinter.CTkLabel(
            header,
            text="OTAK ATIK MERAH PUTIH",
            font=("Courier", 16, "bold"),
            text_color=WHITE,
        ).pack(pady=(12, 2))

        customtkinter.CTkLabel(
            header,
            text="Masukkan data peserta untuk memulai",
            font=("Courier", 11),
            text_color=MUTED,
        ).pack()

        form = customtkinter.CTkScrollableFrame(
            self, fg_color=BG_DARK, scrollbar_button_color=BG_CARD,
        )
        form.grid(row=1, column=0, sticky="nsew", padx=32, pady=(24, 0))
        form.grid_columnconfigure(0, weight=1)

        # UID / RFID
        self._uid = StyledEntry(form, label="UID / RFID (opsional)", placeholder="Tap kartu atau ketik UID...")
        self._uid.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self._uid_btn = customtkinter.CTkButton(
            form, text="Cari", width=80, height=36,
            font=("Helvetica", 12), corner_radius=6,
            fg_color=BG_INPUT, hover_color="#1e1e2e",
            border_width=1, border_color=BORDER, text_color=MUTED,
            command=self._lookup_uid,
        )
        self._uid_btn.grid(row=0, column=1, padx=(8, 0), pady=(20, 0), sticky="e")

        # Nama
        self._nama = StyledEntry(form, label="NAMA PANGGILAN", placeholder="Masukkan nama...")
        self._nama.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        # Usia
        self._usia = StyledEntry(form, label="USIA (TAHUN)", placeholder="Contoh: 10")
        self._usia.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 16))

        # Jenis kelamin
        customtkinter.CTkLabel(
            form, text="JENIS KELAMIN",
            font=("Helvetica", 12, "bold"),
            text_color=MUTED, anchor="w",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=(0, 4))

        self._gender = GenderSelector(form)
        self._gender.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        footer = customtkinter.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=80)
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.grid_columnconfigure(0, weight=1)

        self._submit_btn = customtkinter.CTkButton(
            footer,
            text="MULAI BERMAIN",
            font=("Helvetica", 16, "bold"),
            height=48,
            corner_radius=8,
            fg_color=RED,
            hover_color=RED_DARK,
            text_color=WHITE,
            command=self._submit,
        )
        self._submit_btn.grid(row=0, column=0, padx=32, pady=16, sticky="ew")

        self.after(100, self._uid.focus)

    def _bind_keys(self):
        self.bind("<Return>", lambda _: self._submit())

    def _lookup_uid(self):
        uid = self._uid.get()
        if not uid:
            return
        self._uid_btn.configure(text="...", state="disabled")
        self.update()

        data = None
        if self._server:
            data = self._server.authenticate(uid)

        if data:
            self._auth_data = data
            self._nama._entry.delete(0, "end")
            self._nama._entry.insert(0, str(data.get("name", "")))
            usia_val = data.get("age", "")
            self._usia._entry.delete(0, "end")
            self._usia._entry.insert(0, str(usia_val) if usia_val else "")
            gender_val = data.get("gender", "").lower()
            if gender_val in ("male", "female"):
                self._gender._select(gender_val)
            print(f"[Input] Auto-fill dari server: {data.get('name') or uid}")
        else:
            self._auth_data = None
            print(f"[Input] UID '{uid}' tidak ditemukan / server offline")

        self._uid_btn.configure(text="Cari", state="normal")

    def _submit(self):
        self._nama.clear_error()
        self._usia.clear_error()
        self._gender.clear_error()

        nama   = self._nama.get()
        usia   = self._usia.get()
        gender = self._gender.get()

        errors = False
        if not nama:
            self._nama.set_error("Nama tidak boleh kosong")
            errors = True
        if not usia.isdigit():
            self._usia.set_error("Usia harus berupa angka bulat")
            errors = True
        elif not (4 <= int(usia) <= 18):
            self._usia.set_error("Usia peserta antara 4 – 18 tahun")
            errors = True
        if not gender:
            self._gender.set_error("Pilih jenis kelamin")
            errors = True

        if errors:
            return

        self._result = {
            "name":   nama,
            "age":    int(usia),
            "gender": gender,
        }
        if self._auth_data and self._auth_data.get("id"):
            self._result["participant_id"] = self._auth_data["id"]
        print(f"[Input] Data peserta: {self._result}")
        self.destroy()

    def get_result(self) -> Optional[dict]:
        return self._result


def show_input_window(server_client=None) -> Optional[dict]:
    win = InputWindow(server_client=server_client)
    win.mainloop()
    return win.get_result()
