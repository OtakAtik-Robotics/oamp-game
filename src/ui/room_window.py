"""
App_Mode — Solo / Multiplayer selection screen.
App_Room — Room lobby (create / join / ready) using RoomClient + WS spectator.
"""
import os
import threading
from typing import Optional

import customtkinter as ctk

from src.multiplayer.room_client import RoomClient

# ── Palette ───────────────────────────────────────────────────────────────────
CLR_BG     = "#f5f5f5"
CLR_CARD   = "#ffffff"
CLR_ACCENT = "#FF1744"
CLR_ACCENT2= "#B71C1C"
CLR_SUCCESS= "#00BFA5"
CLR_MUTED  = "#757575"
CLR_TEXT   = "#1a1a1a"
CLR_DANGER = "#F44336"
CLR_BORDER = "#e0e0e0"


# ─────────────────────────────────────────────────────────────────────────────
# App_Mode  — Solo / Multiplayer select
# ─────────────────────────────────────────────────────────────────────────────

class App_Mode(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OAMP — Pilih Mode")
        self.geometry("440x260+580+180")
        self.configure(fg_color=CLR_BG)
        self.resizable(False, False)
        self.mode: Optional[str] = None  # "solo" | "multiplayer"

        self._build_ui()
        self.bind("<Escape>", lambda _: self.destroy())

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color=CLR_CARD, corner_radius=0, height=58)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Pilih Mode Permainan",
            font=("Helvetica", 20, "bold"), text_color=CLR_TEXT,
        ).grid(row=0, column=0, padx=20, pady=16, sticky="w")

        body = ctk.CTkFrame(self, fg_color=CLR_BG)
        body.grid(row=1, column=0, padx=28, pady=24, sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            body, text="Solo",
            command=self._solo,
            font=("Helvetica", 17, "bold"),
            fg_color=CLR_ACCENT, hover_color=CLR_ACCENT2,
            corner_radius=12, height=76,
        ).grid(row=0, column=0, padx=(0, 10), sticky="ew")

        ctk.CTkButton(
            body, text="Multiplayer",
            command=self._multi,
            font=("Helvetica", 17, "bold"),
            fg_color=CLR_SUCCESS, hover_color="#0d9266",
            corner_radius=12, height=76,
        ).grid(row=0, column=1, padx=(10, 0), sticky="ew")

        ctk.CTkLabel(
            body,
            text="Solo: tes mandiri\nMultiplayer: duel real-time",
            font=("Helvetica", 12), text_color=CLR_MUTED, justify="center",
        ).grid(row=1, column=0, columnspan=2, pady=(18, 0))

    def _solo(self):
        self.mode = "solo"
        self.destroy()

    def _multi(self):
        self.mode = "multiplayer"
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# App_Room  — Lobby (create / join / ready), WS-driven
# ─────────────────────────────────────────────────────────────────────────────

class App_Room(ctk.CTk):
    def __init__(self, room_client: RoomClient):
        super().__init__()
        self.title("OAMP — Lobby")
        self.geometry("580x500+340+90")
        self.configure(fg_color=CLR_BG)
        self.resizable(False, False)

        self._rc = room_client
        self._room_ready = False
        self._i_am_ready = False
        self._spectator_running = False

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color=CLR_CARD, corner_radius=0, height=52)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Multiplayer Lobby",
            font=("Helvetica", 19, "bold"), text_color=CLR_TEXT,
        ).grid(row=0, column=0, padx=20, pady=13, sticky="w")

        # ── Find panel ──
        self.find_frame = ctk.CTkFrame(self, fg_color=CLR_BG)
        self.find_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)
        self.find_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            self.find_frame, text="Buat Room Baru",
            command=self._create_room,
            font=("Helvetica", 15, "bold"),
            fg_color=CLR_ACCENT, hover_color=CLR_ACCENT2,
            corner_radius=10, height=48,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ctk.CTkLabel(
            self.find_frame, text="─── atau masukkan kode room ───",
            font=("Helvetica", 11), text_color=CLR_MUTED,
        ).grid(row=1, column=0, columnspan=2, pady=(0, 8))

        code_row = ctk.CTkFrame(self.find_frame, fg_color="transparent")
        code_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        code_row.grid_columnconfigure(0, weight=1)

        self.code_entry = ctk.CTkEntry(
            code_row, placeholder_text="Kode Room (4 huruf)",
            font=("Helvetica", 17, "bold"), height=42,
        )
        self.code_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkButton(
            code_row, text="JOIN",
            command=self._join_by_code,
            font=("Helvetica", 13, "bold"),
            fg_color=CLR_SUCCESS, hover_color="#0d9266",
            corner_radius=10, height=42, width=80,
        ).grid(row=0, column=1)

        list_hdr = ctk.CTkFrame(self.find_frame, fg_color="transparent")
        list_hdr.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        list_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            list_hdr, text="Room Tersedia",
            font=("Helvetica", 12, "bold"), text_color=CLR_MUTED,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            list_hdr, text="Refresh",
            command=self._refresh_rooms,
            font=("Helvetica", 11),
            fg_color=CLR_BORDER, hover_color=CLR_CARD,
            corner_radius=6, height=26, width=80,
        ).grid(row=0, column=1)

        self.room_list_frame = ctk.CTkScrollableFrame(
            self.find_frame, fg_color=CLR_CARD, corner_radius=8, height=150,
        )
        self.room_list_frame.grid(row=4, column=0, columnspan=2, sticky="ew")
        self.room_list_frame.grid_columnconfigure(0, weight=1)

        self._rooms_placeholder = ctk.CTkLabel(
            self.room_list_frame, text="Memuat...",
            font=("Helvetica", 12), text_color=CLR_MUTED,
        )
        self._rooms_placeholder.grid(row=0, column=0, pady=20)

        # ── Lobby panel ──
        self.lobby_frame = ctk.CTkFrame(self, fg_color=CLR_BG)
        self.lobby_frame.grid_columnconfigure(0, weight=1)

        code_card = ctk.CTkFrame(self.lobby_frame, fg_color=CLR_CARD, corner_radius=12)
        code_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        code_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(code_card, text="KODE ROOM", font=("Helvetica", 10), text_color=CLR_MUTED).grid(row=0, column=0, pady=(12, 0))
        self.code_display = ctk.CTkLabel(code_card, text="----", font=("Helvetica", 52, "bold"), text_color=CLR_ACCENT)
        self.code_display.grid(row=1, column=0, pady=(0, 4))
        ctk.CTkButton(
            code_card, text="Salin Kode",
            command=self._copy_code,
            font=("Helvetica", 11),
            fg_color=CLR_BORDER, hover_color=CLR_BG,
            corner_radius=6, height=26, width=110,
        ).grid(row=2, column=0, pady=(0, 12))

        players_row = ctk.CTkFrame(self.lobby_frame, fg_color="transparent")
        players_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        players_row.grid_columnconfigure((0, 1), weight=1)

        def _pc(parent, col):
            card = ctk.CTkFrame(parent, fg_color=CLR_CARD, corner_radius=10)
            card.grid(row=0, column=col, padx=(0, 6) if col == 0 else (6, 0), sticky="nsew")
            card.grid_columnconfigure(0, weight=1)
            return card

        p1 = _pc(players_row, 0)
        ctk.CTkLabel(p1, text="PLAYER 1", font=("Helvetica", 10), text_color=CLR_MUTED).grid(row=0, column=0, pady=(10, 2))
        self.p1_name = ctk.CTkLabel(p1, text="...", font=("Helvetica", 13, "bold"), text_color=CLR_TEXT)
        self.p1_name.grid(row=1, column=0, pady=(0, 2))
        self.p1_status = ctk.CTkLabel(p1, text="⏳", font=("Helvetica", 11), text_color=CLR_MUTED)
        self.p1_status.grid(row=2, column=0, pady=(0, 10))

        p2 = _pc(players_row, 1)
        ctk.CTkLabel(p2, text="PLAYER 2", font=("Helvetica", 10), text_color=CLR_MUTED).grid(row=0, column=0, pady=(10, 2))
        self.p2_name = ctk.CTkLabel(p2, text="Menunggu...", font=("Helvetica", 13, "bold"), text_color=CLR_MUTED)
        self.p2_name.grid(row=1, column=0, pady=(0, 2))
        self.p2_status = ctk.CTkLabel(p2, text="", font=("Helvetica", 11), text_color=CLR_MUTED)
        self.p2_status.grid(row=2, column=0, pady=(0, 10))

        self.lobby_msg = ctk.CTkLabel(self.lobby_frame, text="", font=("Helvetica", 12), text_color=CLR_MUTED)
        self.lobby_msg.grid(row=2, column=0, pady=(0, 8))

        btn_row = ctk.CTkFrame(self.lobby_frame, fg_color="transparent")
        btn_row.grid(row=3, column=0, sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)

        self.ready_btn = ctk.CTkButton(
            btn_row, text="SIAP",
            command=self._mark_ready,
            font=("Helvetica", 15, "bold"),
            fg_color=CLR_SUCCESS, hover_color="#0d9266",
            corner_radius=10, height=48,
        )
        self.ready_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        ctk.CTkButton(
            btn_row, text="Keluar",
            command=self._leave_room,
            font=("Helvetica", 13),
            fg_color=CLR_DANGER, hover_color="#b91c1c",
            corner_radius=10, height=48, width=110,
        ).grid(row=0, column=1)

    # ── Panel switching ────────────────────────────────────────────────────────

    def _show_find(self):
        self.lobby_frame.grid_remove()
        self.find_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)

    def _show_lobby(self, room: dict):
        self.find_frame.grid_remove()
        self.lobby_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)
        self._i_am_ready = False
        self.ready_btn.configure(text="SIAP", fg_color=CLR_SUCCESS, state="normal")
        self._update_lobby(room)
        # Start WS spectator for room broadcasts
        rid = room.get("id")
        if rid:
            self._rc.start_ws_spectator(rid, self._on_ws_broadcast)

    # ── Room list ─────────────────────────────────────────────────────────────

    def _refresh_rooms(self):
        def _fetch():
            return self._rc.get_rooms()
        threading.Thread(target=_fetch, daemon=True).start()

    def _update_room_list(self, rooms: list):
        for w in self.room_list_frame.winfo_children():
            w.destroy()
        if not rooms:
            ctk.CTkLabel(
                self.room_list_frame, text="Belum ada room",
                font=("Helvetica", 12), text_color=CLR_MUTED,
            ).grid(row=0, column=0, pady=20)
            return
        for i, r in enumerate(rooms):
            row = ctk.CTkFrame(self.room_list_frame, fg_color=CLR_BG, corner_radius=8)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=4)
            row.grid_columnconfigure(1, weight=1)
            code = r.get("id", "?")
            ctk.CTkLabel(row, text=code, font=("Helvetica", 20, "bold"), text_color=CLR_ACCENT, width=72).grid(row=0, column=0, padx=(12, 8), pady=8)
            ctk.CTkLabel(row, text=r.get("player1_name", "—"), font=("Helvetica", 12), text_color=CLR_TEXT).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(row, text="1/2", font=("Helvetica", 11), text_color=CLR_MUTED, width=32).grid(row=0, column=2)
            ctk.CTkButton(
                row, text="JOIN",
                command=lambda c=code: self._join_by_id(c),
                font=("Helvetica", 12, "bold"),
                fg_color=CLR_ACCENT, hover_color=CLR_ACCENT2,
                corner_radius=6, height=30, width=60,
            ).grid(row=0, column=3, padx=(8, 12), pady=8)

    # ── Create / Join ─────────────────────────────────────────────────────────

    def _create_room(self):
        rid = self._rc.create_room()
        if rid:
            room = {"id": rid}
            self._show_lobby(room)
        else:
            self._show_err("Gagal membuat room. Server offline?")

    def _join_by_code(self):
        code = self.code_entry.get().strip().upper()
        if len(code) != 4:
            self._show_err("Kode room harus 4 karakter")
            return
        self._join_by_id(code)

    def _join_by_id(self, code: str):
        rid = self._rc.join_room(code)
        if rid:
            room = {"id": rid}
            self._show_lobby(room)
        else:
            self._show_err(f"Room '{code}' tidak ditemukan atau sudah penuh")

    # ── Lobby actions ─────────────────────────────────────────────────────────

    def _mark_ready(self):
        if self._i_am_ready:
            return
        ok = self._rc.mark_ready()
        if ok:
            self._i_am_ready = True
            self.ready_btn.configure(text="SIAP!", fg_color=CLR_BORDER, state="disabled")
        else:
            self._show_err("Gagal mengirim ready. Coba lagi.")

    def _leave_room(self):
        self._rc.stop_ws()
        self._rc.leave_room()
        self._show_find()

    def _copy_code(self):
        rid = self._rc.room_id
        if rid:
            self.clipboard_clear()
            self.clipboard_append(rid)

    # ── Lobby UI update ──────────────────────────────────────────────────────

    def _update_lobby(self, room: dict):
        self.code_display.configure(text=room.get("id", "----"))
        p1 = room.get("player1_name") or "—"
        p2 = room.get("player2_name")
        r1 = room.get("player1_ready", False)
        r2 = room.get("player2_ready", False)
        st = room.get("status", "waiting")

        self.p1_name.configure(text=p1)
        self.p1_status.configure(
            text="SIAP" if r1 else "Belum siap",
            text_color=CLR_SUCCESS if r1 else CLR_MUTED,
        )
        if p2:
            self.p2_name.configure(text=p2, text_color=CLR_TEXT)
            self.p2_status.configure(
                text="SIAP" if r2 else "Belum siap",
                text_color=CLR_SUCCESS if r2 else CLR_MUTED,
            )
        else:
            self.p2_name.configure(text="Menunggu pemain...", text_color=CLR_MUTED)
            self.p2_status.configure(text="")

        if st == "playing":
            self.lobby_msg.configure(text="Game dimulai!")
            self.after(500, lambda: self._on_game_start())
        elif st == "ready" and r1 and not r2:
            self.lobby_msg.configure(text="Menunggu Player 2 tekan SIAP...")
        elif st == "ready" and not r1 and r2:
            self.lobby_msg.configure(text="Menunggu Player 1 tekan SIAP...")
        else:
            self.lobby_msg.configure(text="Tekan SIAP jika sudah siap")

    def _on_ws_broadcast(self, data: dict):
        """Handle WS broadcast messages from Go backend for room state."""
        msg_type = data.get("type", "")
        if msg_type in ("join", "score_update", "GAME_OVER", "leave"):
            # Merge into existing room state
            updated = dict(data)
            # Update p1/p2 name if join/leave
            if msg_type == "join":
                pid = data.get("player_id", "")
                # update player2 name if this is player2
                self.p2_name.configure(text=pid, text_color=CLR_TEXT)
                self.lobby_msg.configure(text="Player 2 bergabung!")
            elif msg_type == "leave":
                self.p2_name.configure(text="Menunggu pemain...", text_color=CLR_MUTED)
                self.p2_status.configure(text="")
                self.lobby_msg.configure(text="Player 2 keluar...")
            elif msg_type == "GAME_OVER":
                self.lobby_msg.configure(text=f"Game Over! Player {data.get('player_id')} selesai")
            elif msg_type == "score_update":
                # show opponent score briefly
                pid = data.get("player_id", "?")
                score = data.get("game_score", 0)
                self.lobby_msg.configure(text=f"Player {pid}: score={score}")
            # Poll HTTP for full room state update
            self.after(100, self._poll_http)
        elif msg_type == "status" and data.get("status"):
            # Server pushes full room state
            self.after(0, lambda: self._update_lobby(data))

    def _poll_http(self):
        rid = self._rc.room_id
        if not rid:
            return
        # Fetch room state via HTTP
        import requests as _r
        def _worker():
            try:
                base = os.getenv("BACKEND_API_URL", "http://localhost:8080/api/v1").rstrip("/")
                resp = _r.get(f"{base}/rooms/{rid}", timeout=3)
                if resp.status_code == 200:
                    body = resp.json()
                    if body.get("status") == "success":
                        self.after(0, lambda r=body.get("data", {}): self._update_lobby(r))
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _on_game_start(self):
        """Both players ready — room status = playing."""
        self._room_ready = True
        self.destroy()

    def _show_err(self, msg: str):
        import tkinter.messagebox as mb
        mb.showerror("Error", msg, parent=self)

    def _on_close(self):
        self._rc.stop_ws()
        self._rc.leave_room()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# show_room_screen  — modal entry point
# Returns (room_id, room_client) on success, (None, None) on cancel
# ─────────────────────────────────────────────────────────────────────────────

def show_room_screen(room_client: RoomClient) -> tuple:
    """
    Show App_Mode → App_Room flow.
    Returns (room_id, room_client) if multiplayer-ready, (None, None) if solo/cancelled.
    """
    mode_win = App_Mode()
    mode_win.focus()
    mode_win.wait_window()
    mode = mode_win.mode

    if mode == "multiplayer":
        room_win = App_Room(room_client)
        room_win.focus()
        room_win.wait_window()
        if room_win._room_ready and room_client.room_id:
            return room_client.room_id, room_client
        return None, None

    # Solo
    return None, None
