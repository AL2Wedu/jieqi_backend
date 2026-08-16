"""pytest 全局配置:测试环境关闭登录/注册限速,并把 TestClient 视为可信反代。

- RATE_LIMIT_ENABLED=false:测试套件高频注册/登录不触发 429(生产默认 true)
- TRUSTED_PROXIES=testclient:TestClient 的 client.host 为 "testclient",
  允许测试用 X-Forwarded-For 模拟真实 IP(生产默认空 = 不信任任何 XFF)
"""
import os

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("TRUSTED_PROXIES", "testclient")
