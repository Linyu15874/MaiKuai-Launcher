@echo off
REM ============================================================
REM  麦块启动器 (PCL-Launcher) - Windows 一键打包脚本
REM  需要：Windows 10/11 x64 + Python 3.10+ (官网安装版)
REM  用法：双击本文件，或在命令行执行  build_exe.bat
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 3.10+ 并勾选 "Add to PATH"
    pause
    exit /b 1
)

echo [1/3] 安装依赖...
python -m pip install --upgrade pip
python -m pip install PySide6 requests pyinstaller msvc-runtime
if errorlevel 1 goto :fail

echo [2/3] 生成图标并收集运行库...
python tools\make_icon.py
python tools\fetch_vcredist.py

echo [3/3] 使用 PyInstaller 打包...
python -m PyInstaller --noconfirm --clean pcl-launcher.spec
if errorlevel 1 goto :fail

echo.
echo ============================================
echo  打包完成：dist\PCL-Launcher.exe
echo ============================================
pause
exit /b 0

:fail
echo [失败] 构建过程出错，请检查上方日志。
pause
exit /b 1
