"""WebSocket 连接管理与定向推送(按玩家)。"""
import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.players: dict[str, set[WebSocket]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None  # lifespan 里注入主事件循环

    def connect(self, ws: WebSocket, player_id: str) -> None:
        """注册连接(accept 由调用方完成,避免重复 accept)。"""
        self.players.setdefault(player_id, set()).add(ws)

    def disconnect(self, ws: WebSocket, player_id: str) -> None:
        conns = self.players.get(player_id)
        if conns and ws in conns:
            conns.remove(ws)
            if not conns:
                self.players.pop(player_id, None)

    async def send_to_player(self, player_id: str, message: dict) -> None:
        """定向推送(该玩家的所有连接),清理死连接。"""
        conns = self.players.get(player_id)
        if not conns:
            return
        dead: list[WebSocket] = []
        for ws in list(conns):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, player_id)


    def push_sync(self, player_id: str, message: dict) -> None:
        """线程安全定向推送:供同步 handler(管理后台改数值等)调用。

        玩家不在线(无连接)时静默无操作;推送到主事件循环,失败忽略。
        """
        if not self.players.get(player_id) or self.loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.send_to_player(player_id, message), self.loop
            )
        except Exception:
            pass


manager = ConnectionManager()
