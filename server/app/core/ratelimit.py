"""轻量内存限速器(滑动窗口,按 key 计数)。

用于登录/注册/管理端登录等入口的暴力破解防护。
单进程内存实现(模块化单体够用);多进程部署时建议换 Redis 或反代层限速。

用法:
    limiter = RateLimiter(max_hits=5, window_seconds=60)
    if not limiter.allow("login:1.2.3.4"):
        raise AppError("RATE_LIMITED", "操作过于频繁,请稍后再试", http_status=429, code=10003)
"""
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_hits: int = 5, window_seconds: int = 60):
        self.max_hits = max_hits
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """记录一次命中并判断是否放行;超限返回 False。"""
        now = time.monotonic()
        q = self._hits[key]
        # 清理窗口外的旧记录
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        if len(q) >= self.max_hits:
            return False
        q.append(now)
        return True

    def reset(self, key: str) -> None:
        """清除某 key 的计数(如登录成功后)。"""
        self._hits.pop(key, None)


# 全局实例:登录/注册/管理端登录共用
login_limiter = RateLimiter(max_hits=10, window_seconds=60)
register_limiter = RateLimiter(max_hits=5, window_seconds=60)
admin_login_limiter = RateLimiter(max_hits=5, window_seconds=60)
