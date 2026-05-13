"""
Entry point: config + flow.

Flow:
  1. Input Window  → participant data
  2. Mode Screen   → Solo / Multiplayer
     2a. Solo → GameWindow directly
     2b. Multiplayer → Room Lobby → GameWindow with room_id
  3. GameWindow    → play
  4. On retry     → back to step 1 (Input Window)
"""
import os
import platform
from dotenv import load_dotenv

from src.ui.input_window import show_input_window
from src.ui.game_window import GameWindow
from src.ui.room_window import show_room_screen, RoomClient
from src.api_client import ServerClient


def main():
    load_dotenv()

    SOLO_MODE = os.getenv("SOLO_MODE", "false").lower() == "true"
    BACKEND_OFFLINE = os.getenv("BACKEND_API_URL", "") == "offline"
    _SKIP_SERVER = SOLO_MODE or BACKEND_OFFLINE

    server = None if _SKIP_SERVER else ServerClient()

    from src.ui.game_window import _start_preload
    _start_preload()

    while True:
        user_data = show_input_window(server_client=server)
        if not user_data:
            break  # user closed input window

        room_id = None
        if not _SKIP_SERVER:
            # Build RoomClient with participant name from input
            player_name = user_data.get("name", "Player")
            rc = RoomClient(server, player_name)
            room_id, rc = show_room_screen(rc)
            # show_room_screen returns (room_id, room_client) or (None, None)
            # If solo, room_id is None and rc is None
            # If multiplayer, rc is the RoomClient
            if room_id:
                # multiplayer — WS match client already created inside RoomClient
                user_data["room_client"] = rc
        elif user_data.get("room_code"):
            room_id = user_data["room_code"]

        app = GameWindow(
            user_data=user_data,
            server_client=server,
            room_id=room_id,
        )

        def maximize_window():
            try:
                if platform.system() == "Windows":
                    app.state("zoomed")
                else:
                    app.attributes("-zoomed", True)
            except Exception:
                pass

        app.after(0, maximize_window)
        app.mainloop()
        # GameWindow was destroyed — retry loop → back to Input Window


if __name__ == "__main__":
    main()
