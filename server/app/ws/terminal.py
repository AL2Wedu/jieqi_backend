"""管理终端桥:pywinpty(ConPTY)驱动 PowerShell。

- 单例共享会话(服务级),管理员可看到同一终端的输出(启动/停止服务器操作可见)。
- 不依赖 PTY 时(非 Windows / 未装 pywinpty)自动降级为"终端不可用"。
"""
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
            return True

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
