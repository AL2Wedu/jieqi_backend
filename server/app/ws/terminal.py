"""管理终端桥:pywinpty(ConPTY)驱动 PowerShell。

单例共享会话(服务级):
- 一个 PowerShell 进程 + 一个读线程(读线程全局只启动一次)
- 所有活跃 WS 连接订阅同一数据流 → 多管理员看到同一终端(启停服务器操作可见)
- 非 Windows / 未装 pywinpty 时自动降级为"终端不可用"
"""
import asyncio
import threading
from pathlib import Path

try:
    import winpty

    HAS_PTY = True
except Exception:  # pragma: no cover
    HAS_PTY = False

SERVER_DIR = Path(__file__).resolve().parent.parent


class TerminalBridge:
    def __init__(self) -> None:
        self.proc = None
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._reader: threading.Thread | None = None

    def ensure_started(self) -> bool:
        if not HAS_PTY:
            return False
        with self._lock:
            if self.proc is None or not self.proc.isalive():
                self.proc = winpty.PtyProcess.spawn(
                    ["powershell.exe", "-NoLogo", "-NoExit"],
                    cwd=str(SERVER_DIR),
                    dimensions=(24, 110),
                )
            if self._reader is None or not self._reader.is_alive():
                self._reader = threading.Thread(target=self._read_loop, daemon=True)
                self._reader.start()
            return True

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append((loop, q))
        return q

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subs = [(loop, q) for loop, q in self._subs if q is not queue]

    def _read_loop(self) -> None:
        while True:
            try:
                chunk = self.proc.read()
                if not chunk:
                    break
                text = (
                    chunk.decode("utf-8", errors="replace")
                    if isinstance(chunk, bytes)
                    else chunk
                )
                self._broadcast(text)
            except Exception:
                break

    def _broadcast(self, text: str) -> None:
        for loop, q in list(self._subs):
            try:
                loop.call_soon_threadsafe(q.put_nowait, text)
            except Exception:
                pass

    def write(self, data: str) -> None:
        with self._lock:
            if self.proc and self.proc.isalive():
                self.proc.write(data)

    def resize(self, rows: int, cols: int) -> None:
        with self._lock:
            if self.proc and self.proc.isalive():
                try:
                    self.proc.setwinsize(rows, cols)
                except Exception:
                    pass

    def stop(self) -> None:
        with self._lock:
            if self.proc:
                try:
                    self.proc.terminate(force=True)
                except Exception:
                    pass
                self.proc = None


bridge = TerminalBridge()
