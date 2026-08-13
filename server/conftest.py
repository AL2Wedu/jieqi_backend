"""pytest 全局配置:统一测试数据库与管理员凭据(在 app 导入前生效)。"""
import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["ADMIN_ENABLED"] = "true"

# 每个测试进程启动前清空旧库(引擎尚未连接,可安全删除)
if os.path.exists("test.db"):
    os.remove("test.db")
