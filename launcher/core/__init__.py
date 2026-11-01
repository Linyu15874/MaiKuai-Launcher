"""核心层：路径 / 配置 / 网络 / 认证 / 安装 / 启动。

本层不依赖 Qt，可单独命令行调用，便于测试与二次开发。
"""

from . import auth, config, installer, java, launch, net, paths, version  # noqa: F401
