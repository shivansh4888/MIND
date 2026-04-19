import time
import threading
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from backend.utils.config import config


class _CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, on_change_cb):
        super().__init__()
        self._cb = on_change_cb
        self._debounce: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        self._handle(event)

    def on_created(self, event):
        self._handle(event)

    def _handle(self, event):
        if event.is_directory:
            return
        path = event.src_path
        ext = Path(path).suffix.lower()
        if ext not in config.SUPPORTED_EXTENSIONS:
            return
        if any(part in config.IGNORE_DIRS for part in Path(path).parts):
            return

        now = time.time()
        with self._lock:
            last = self._debounce.get(path, 0)
            if now - last < 2.0:          # debounce: ignore events within 2s
                return
            self._debounce[path] = now

        threading.Thread(target=self._cb, args=(path,), daemon=True).start()


class FileWatcher:
    def __init__(self, root_path: str, on_change_cb):
        self._root = root_path
        self._handler = _CodeChangeHandler(on_change_cb)
        self._observer = Observer()

    def start(self):
        self._observer.schedule(self._handler, self._root, recursive=True)
        self._observer.start()
        print(f"[watcher] Watching {self._root}")

    def stop(self):
        self._observer.stop()
        self._observer.join()