# Otak Atik Merah Putih (OAMP) Game

Computer vision game for children. Players use hand gestures to match colored blocks displayed on screen. Block detection via YOLOv5, hand tracking via Mediapipe (optional).

## Architecture

```
main.py
  ├─ InputWindow        → participant registration
  ├─ RoomWindow         → solo / multiplayer lobby
  └─ GameWindow         → main game loop (camera + YOLO + hand tracking)
       ├─ BlockDetector  → YOLOv5 inference (torch.hub or ultralytics)
       ├─ HandTracker   → Mediapipe hands (lazy, optional)
       ├─ BlockEvaluator → math/visual validation
       ├─ AudioManager  → pygame SFX (lazy init)
       └─ GameEngine    → round/timer/scoring state machine
```

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SOLO_MODE` | `false` | Skip server auth, local participant |
| `BACKEND_API_URL` | `http://localhost:8000` | API server address |
| `MODEL_BANTAL` | `false` | Use `bantal.pt` (ultralytics YOLOv8) vs `best.pt` (torch.hub YOLOv5) |
| `HIDE_CAMERA` | `false` | Hide camera preview panel |
| `MEDIAPIPE_SKIP_FRAMES` | `2` | Skip Mediapipe inference every N frames |

Set `BACKEND_API_URL=offline` for fully offline solo play.

## Requirements

- Python 3.9+
- OpenCV, PyTorch, NumPy
- `mediapipe` + `ultralytics` — auto-skipped if unavailable (game still runs with reduced features)

## Project Structure

```
oamp-game/
├── main.py                  # Entry point + flow orchestration
├── src/
│   ├── api_client.py        # REST client (auth, lookup)
│   ├── core/
│   │   ├── audio_manager.py # pygame SFX, lazy init
│   │   └── game_engine.py   # round state machine
│   ├── multiplayer/
│   │   └── room_client.py   # WebSocket match client
│   ├── ui/
│   │   ├── game_window.py   # Main game UI (CTk)
│   │   ├── input_window.py  # Participant registration
│   │   ├── room_window.py   # Room lobby / solo select
│   │   └── components.py    # Shared CTk widgets
│   └── vision/
│       ├── block_detector.py  # YOLOv5 inference loop
│       ├── evaluator.py       # Block validation
│       └── hand_tracker.py    # Mediapipe hands (lazy)
├── models/
│   ├── weights/
│   │   ├── best.pt     # YOLOv5 custom weights
│   │   └── bantal.pt   # Ultralytics YOLOv8 format (optional)
│   └── yolov5/         # torch.hub local clone
└── assets/
    └── images/FILES/TEST_RANDOM_1500x1500/  # Level backgrounds
```