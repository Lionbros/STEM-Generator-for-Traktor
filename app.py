import os
import threading
import datetime
import subprocess
import webbrowser
import shutil
import signal
import re
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Folders
MUSIC_FOLDER = os.path.expanduser("~/MusicToProcess")
OUTPUT_ROOT = os.path.join(MUSIC_FOLDER, "output")
ORIGINALS_DIR = os.path.join(MUSIC_FOLDER, "Original mp3s")  # move source here after completion

# In-memory state
# Each item: {title, status, progress, started_at, completed_at}
QUEUE = []
BATCH_RUNNING = False
CURRENT_BATCH_DIR = None  # absolute path (on host) of the timestamped output folder for this batch
CURRENT_PROC = None       # handle to running docker process (for skip/terminate)
PAUSE_EVENT = threading.Event()    # when set(), processing is paused
STOP_EVENT = threading.Event()     # when set(), terminate the worker early

# ---------- Helpers ----------

def scan_for_songs():
    """
    Return list of NEW .mp3 files found in MUSIC_FOLDER that are not already in the QUEUE.
    Return them alphabetically.
    """
    try:
        files = [f for f in os.listdir(MUSIC_FOLDER) if f.lower().endswith(".mp3")]
    except FileNotFoundError:
        os.makedirs(MUSIC_FOLDER, exist_ok=True)
        files = []

    queued = {item["title"] for item in QUEUE}
    new_files = [f for f in files if f not in queued]
    new_files.sort(key=lambda s: s.lower())
    return new_files


def create_batch_output_folder():
    """
    Create a timestamped output folder under ~/MusicToProcess/output.
    e.g. ~/MusicToProcess/output/stems 2025-08-13_14-45-10
    """
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder = os.path.join(OUTPUT_ROOT, f"stems {ts}")
    os.makedirs(folder, exist_ok=True)
    return folder


def container_path_for_host_path(host_path: str) -> str:
    """
    Convert a host path under MUSIC_FOLDER to the corresponding container path under /music.
    """
    rel = os.path.relpath(host_path, MUSIC_FOLDER)
    return "/music/" + rel.replace("\\", "/")


def move_original_to_archive(host_path: str):
    """
    After a song is successfully processed, move the original mp3 into ~/MusicToProcess/Original mp3s
    """
    try:
        os.makedirs(ORIGINALS_DIR, exist_ok=True)
        basename = os.path.basename(host_path)
        dest = os.path.join(ORIGINALS_DIR, basename)
        # If a file with same name exists, add a timestamp suffix
        if os.path.exists(dest):
            stem, ext = os.path.splitext(basename)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(ORIGINALS_DIR, f"{stem} ({ts}){ext}")
        shutil.move(host_path, dest)
    except Exception as e:
        # Non-fatal: just log to console
        print(f"[WARN] Could not move original '{host_path}' -> '{ORIGINALS_DIR}': {e}")


def _wait_if_paused():
    """
    Block here if PAUSE_EVENT is set (paused). Resume when cleared.
    """
    while PAUSE_EVENT.is_set() and not STOP_EVENT.is_set():
        # Sleep briefly to yield GIL and keep UI responsive
        threading.Event().wait(0.2)


def _kill_current_proc():
    """
    Kill the CURRENT_PROC docker process safely (used by skip/terminate).
    """
    global CURRENT_PROC
    proc = CURRENT_PROC
    if proc and proc.poll() is None:
        try:
            # Send SIGINT first for graceful shutdown, fall back to SIGKILL
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=4)
            except Exception:
                proc.kill()
        except Exception as e:
            print(f"[WARN] Failed to stop running process: {e}")
    CURRENT_PROC = None


# ---------- Worker ----------

def process_queue():
    """
    Background worker that processes QUEUE sequentially using stemgen in Docker.
    Writes all results for this run into CURRENT_BATCH_DIR.
    Supports pause/resume, skipping current, and terminate.
    """
    global BATCH_RUNNING, CURRENT_BATCH_DIR, CURRENT_PROC
    BATCH_RUNNING = True
    STOP_EVENT.clear()
    CURRENT_BATCH_DIR = create_batch_output_folder()

    # Process items in the order they currently appear
    for item in QUEUE:
        # Respect terminate request
        if STOP_EVENT.is_set():
            break

        # Skip already finished/failed/skipped
        if item["status"] in ("Completed", "Failed", "Skipped"):
            continue

        # If user removed it before we got here, skip
        if item["status"] == "Removed":
            continue

        # Pause gate before starting a new track
        _wait_if_paused()
        if STOP_EVENT.is_set():  # re-check after pause
            break

        # Mark processing
        item["status"] = "Processing"
        item["progress"] = 0
        item["started_at"] = datetime.datetime.now().strftime("%H:%M:%S")

        input_host = os.path.join(MUSIC_FOLDER, item["title"])
        output_host = CURRENT_BATCH_DIR

        # Convert host paths to container paths
        input_container = container_path_for_host_path(input_host)
        output_container = container_path_for_host_path(output_host)

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{MUSIC_FOLDER}:/music",
            "aclmb/stemgen:main",
            "generate",
            input_container,   # use container path here
            output_container,  # use container path here
            "--force",
            "--verbose",
        ]

        try:
            # Stream Docker output and parse % if present
            CURRENT_PROC = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )

            percent_re = re.compile(r"(\d{1,3})%")
            fallback_lines = 0
            for line in CURRENT_PROC.stdout:
                # Allow pause mid-track
                _wait_if_paused()
                if STOP_EVENT.is_set():
                    break

                # Progress via percentage if available
                m = percent_re.search(line)
                if m:
                    try:
                        pct = max(0, min(100, int(m.group(1))))
                        item["progress"] = pct
                    except Exception:
                        pass
                else:
                    # Fallback: inch forward slowly so the bar feels alive
                    fallback_lines += 1
                    if fallback_lines % 15 == 0 and item["progress"] < 95:
                        item["progress"] += 1

                # Print logs to terminal for visibility
                print(line, end="")

            CURRENT_PROC.wait()
            rc = CURRENT_PROC.returncode
            CURRENT_PROC = None

            if STOP_EVENT.is_set():
                # Terminate was requested; mark as Failed for clarity (not Completed)
                if item["status"] == "Processing":
                    item["status"] = "Failed"
                break

            if item["status"] == "Skipped":
                # Already marked by /skip while running; treat as handled
                item["completed_at"] = datetime.datetime.now().strftime("%H:%M:%S")
                continue

            if rc == 0:
                item["status"] = "Completed"
                item["progress"] = 100
                item["completed_at"] = datetime.datetime.now().strftime("%H:%M:%S")
                # Move original file to archive folder
                move_original_to_archive(input_host)
            else:
                item["status"] = "Failed"
                item["completed_at"] = datetime.datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            print(f"[ERROR] Processing '{item['title']}' failed: {e}")
            # If it was intentionally skipped, keep status
            if item["status"] != "Skipped":
                item["status"] = "Failed"
            item["completed_at"] = datetime.datetime.now().strftime("%H:%M:%S")
            CURRENT_PROC = None

        # Pause gate between tracks
        _wait_if_paused()
        if STOP_EVENT.is_set():
            break

    BATCH_RUNNING = False
    CURRENT_BATCH_DIR = None
    CURRENT_PROC = None


# ---------- Routes ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/queue", methods=["GET"])
def get_queue():
    # Compute overall progress: Completed / total
    total = len(QUEUE)
    completed = sum(1 for i in QUEUE if i["status"] == "Completed")
    overall_pct = int(round((completed / total) * 100)) if total else 0

    return jsonify({
        "items": QUEUE,
        "total": total,
        "completed": completed,
        "overall_progress": overall_pct,
        "paused": PAUSE_EVENT.is_set(),
        "running": BATCH_RUNNING
    })


@app.route("/add_batch", methods=["POST"])
def add_batch():
    new_files = scan_for_songs()

    # Add alphabetically
    for f in new_files:
        QUEUE.append({
            "title": f,
            "status": "Queued",
            "progress": 0,
            "started_at": None,
            "completed_at": None,
        })

    # Also keep the whole queue alphabetic for queued items (do not reorder active/finished rows)
    # We'll stable-sort by a key that puts Processing at top, then Queued by title, then others.
    def sort_key(item):
        # Keep Processing at the very top, then Queued by title, then Completed/Failed/Skipped by title.
        priority = {
            "Processing": 0,
            "Queued": 1,
            "Completed": 2,
            "Failed": 2,
            "Skipped": 2
        }.get(item["status"], 2)
        return (priority, item["title"].lower())

    QUEUE.sort(key=sort_key)

    # Start processor if not already running and if there's work
    if not BATCH_RUNNING and any(item["status"] == "Queued" for item in QUEUE):
        t = threading.Thread(target=process_queue, daemon=True)
        t.start()

    return jsonify({"added": new_files})


@app.route("/pause", methods=["POST"])
def pause():
    PAUSE_EVENT.set()
    return jsonify({"paused": True})


@app.route("/resume", methods=["POST"])
def resume():
    PAUSE_EVENT.clear()
    return jsonify({"paused": False})


@app.route("/terminate", methods=["POST"])
def terminate():
    # Stop the worker and any running docker process
    STOP_EVENT.set()
    PAUSE_EVENT.clear()
    _kill_current_proc()
    return jsonify({"terminated": True})


@app.route("/skip", methods=["POST"])
def skip():
    """
    Skip a song by title. If it's currently processing, kill the docker proc and mark Skipped.
    If it's queued, mark Skipped immediately.
    """
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title")
    if not title:
        return jsonify({"ok": False, "error": "title missing"}), 400

    # Find the item
    target = None
    for item in QUEUE:
        if item["title"] == title and item["status"] in ("Queued", "Processing"):
            target = item
            break

    if not target:
        return jsonify({"ok": False, "error": "title not found or not skippable"}), 404

    # Mark as skipped
    target["status"] = "Skipped"
    target["completed_at"] = datetime.datetime.now().strftime("%H:%M:%S")
    target["progress"] = 0 if target["progress"] is None else target["progress"]

    # If it is the currently running track, stop docker
    _kill_current_proc()

    return jsonify({"ok": True})


# ---------- Main ----------

if __name__ == "__main__":
    # Ensure base folders exist
    os.makedirs(MUSIC_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    os.makedirs(ORIGINALS_DIR, exist_ok=True)

    # Auto-open browser
    url = "http://127.0.0.1:7860"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host="0.0.0.0", port=7860, debug=True)
