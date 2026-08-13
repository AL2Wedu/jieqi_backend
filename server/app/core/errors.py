"""统一错误与响应信封。"""


class AppError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        http_status: int = 400,
        code: int = 20000,
    ):
        self.error_code = error_code
        self.message = message
        self.http_status = http_status
        self.code = code
        super().__init__(message)


def ok(data=None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
