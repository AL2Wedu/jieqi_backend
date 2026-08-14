"""WebSocket 连接管理与定向推送(按玩家)。"""
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.players: dict[str, set[WebSocket]] = {}

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


manager = ConnectionManager()
