# 麦块启动器 (MaiKuai Launcher / PCL-Launcher)

> 一款致敬 [PCL2](https://github.com/PCL-Community/PCL2) 与 [HMCL](https://github.com/HMCL-dev/HMCL) 的开源 Minecraft 启动器。
> 采用卡片式界面与多加载器设计，使用 Python + PySide6 独立实现（非源码复刻，仅作二次创作灵感参考）。

## 特性

- **多版本 / 多加载器**：原版（Vanilla）、Fabric、Quilt、Forge、NeoForge
- **多账号体系**：离线、微软（OAuth2 设备码）、第三方 Yggdrasil 外置登录
- **实例隔离**：每个游戏版本独立存档目录，互不干扰
- **智能 Java 管理**：系统扫描、自动选版本、内置 Temurin 下载
- **镜像加速**：官方源 / BMCLAPI，多线程断点续传 + SHA1 校验
- **Mod 下载**：集成 Modrinth 搜索与依赖解析
- **精美 UI**：浅色 / 深色主题，自绘矢量图标，无外部素材依赖
- **崩溃分析**：启动控制台自动识别常见崩溃原因

## 下载

- 已打包好的 Windows 可执行文件见 **[Releases](../../releases)**（`PCL-Launcher.exe`，单文件绿色版，内置 VC++ 运行库）。
- 直接双击运行，无需安装 Python。

## 快速使用

1. 首次启动会引导设置：游戏目录、下载源（国内推荐 BMCLAPI）、内存
2. 「下载」页安装所需的 Minecraft 版本与加载器
3. 「启动」页登录账号（离线 / 微软 / 外置登录）后点击「启动游戏」
4. 数据默认位于 `%APPDATA%/pcl-launcher`；在 exe 同目录放一个空 `portable.txt` 即切换为便携模式

## 从源码运行

```bash
pip install -r requirements.txt
python main.py
```

## 自己打包成 exe（Windows）

```bat
build_exe.bat
```

脚本会自动安装依赖、生成图标、收集 VC++ 运行库，并用 PyInstaller 产出 `dist/PCL-Launcher.exe`。

## 目录结构

```
launcher/
  core/        核心逻辑：路径、网络、账号、版本解析、安装、启动、实例、Modrinth
  ui/          PySide6 界面：主题、图标、窗口、各页面、对话框
  resources/   图标资源
  vcredist/    打包所需的 VC++ 运行库 DLL
tools/        图标生成、冒烟测试、构建辅助
pcl-launcher.spec   PyInstaller 打包配置
```

## 免责声明

本仓库代码为独立编写的实现，仅借鉴 PCL2 / HMCL 的交互与设计理念，不包含其源码。
Minecraft 是 Mojang Studios 的商标，本启动器不附带游戏本体，需用户自行下载。
