"""统一错误与响应信封。"""


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        http_status: int = 400,
        code: int = 20000,
        extra: dict | None = None,
    ):
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.code = code
        self.extra = extra  # 附加数据（如 GUEST_BUSY 携带 session_id 供客户端恢复会话）
        super().__init__(message)


def ok(data=None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
