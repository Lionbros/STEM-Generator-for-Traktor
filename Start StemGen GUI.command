#!/usr/bin/env bash
set -e

# --------- SETTINGS ---------
APP_DIR="$HOME/stemgen_gui"
MUSIC_DIR="$HOME/MusicToProcess"
OUTPUT_DIR="$MUSIC_DIR/output"
CACHE_DIR="$HOME/.cache/torch/hub"
PORT=7860
LOG_FILE="$APP_DIR/gui.log"
URL="http://localhost:$PORT"
# ----------------------------

echo "== StemGen GUI Launcher =="

# 0) Basic checks
if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: Folder not found: $APP_DIR"
  echo "Move your app files (app.py, index.html, etc.) into $APP_DIR"
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is not installed. Install Docker Desktop for Mac first."
  exit 1
fi

# 1) Ensure required folders exist
mkdir -p "$MUSIC_DIR" "$OUTPUT_DIR" "$CACHE_DIR"

# 2) Start Docker Desktop if needed
if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker
  echo -n "Waiting for Docker to be ready"
  # Wait until the Docker daemon responds
  until docker info >/dev/null 2>&1; do
    echo -n "."
    sleep 2
  done
  echo " ready!"
fi

# 3) If port already in use, just open the browser to the running app
if lsof -i :$PORT >/dev/null 2>&1; then
  echo "GUI already running on port $PORT. Opening browser..."
  open "$URL"
  exit 0
fi

# 4) Launch Flask app
cd "$APP_DIR"
echo "Launching GUI from $APP_DIR ..."
# Start in background and log to file
nohup /usr/bin/env python3 app.py > "$LOG_FILE" 2>&1 & 
PID=$!

# 5) Wait for server to become reachable
echo -n "Starting web server"
for i in {1..40}; do
  if curl -sSf "$URL" >/dev/null 2>&1; then
    break
  fi
  echo -n "."
  sleep 0.5
done
echo

# 6) Open browser
echo "Opening $URL"
open "$URL"

echo "GUI is running (PID $PID). Logs: $LOG_FILE"
echo "Close this window or press Ctrl+C to stop watching the launcher output."
