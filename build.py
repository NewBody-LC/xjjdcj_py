"""PyInstaller 打包脚本

将 CanvasGameAutoBot 打包为单个可执行文件 .exe

使用方法:
  python build.py

输出:
  dist/CanvasGameAutoBot.exe (单文件)

注意:
  - 首次打包需要下载 QtWebEngine 相关资源，可能较慢
  - 请确保路径中不含中文/特殊字符
  - UPX 可选：安装 UPX 后可进一步压缩体积
"""

import os
import sys
import subprocess
import shutil


def check_pyinstaller():
    """检查 PyInstaller 是否已安装"""
    try:
        import PyInstaller
        print(f"[Build] PyInstaller 版本: {PyInstaller.__version__}")
        return True
    except ImportError:
        print("[Build] 未检测到 PyInstaller，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=5.0"])
        return True


def build():
    """执行打包"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 检查必要资源
    templates_dir = os.path.join(base_dir, "templates")
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
        print(f"[Build] 已创建 templates 目录: {templates_dir}")
        print(f"[Build] 请将模板图片放入该目录后重新打包")

    # PyInstaller 参数
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=CanvasGameAutoBot",
        "--onefile",           # 打包为单个 exe
        "--windowed",          # 无控制台窗口
        f"--paths={base_dir}", # 搜索路径
        # 关键：包含 PyQt5 WebEngine 资源
        "--collect-all", "PyQt5",
        "--collect-all", "PyQtWebEngine",
        # 数据文件：模板目录和示例配置
        f"--add-data={templates_dir};templates",
        f"--add-data={os.path.join(base_dir,'config.example.json')};.",
        # 排除不需要的模块以减小体积
        "--exclude-module", "matplotlib",
        "--exclude-module", "pandas",
        "--exclude-module", "scipy",
        # 图标（可选）
        # f"--icon={os.path.join(base_dir,'assets','icon.ico')}",
        # 主入口
        os.path.join(base_dir, "main.py"),
    ]

    # 可选：UPX 压缩（需要系统已安装 upx.exe）
    upx_path = shutil.which("upx")
    if upx_path:
        cmd.extend(["--upx-dir", os.path.dirname(upx_path)])
        print(f"[Build] 检测到 UPX: {upx_path}，将启用压缩")
    else:
        print("[Build] 未检测到 UPX，跳过压缩（可选：安装 UPX 以减小体积）")

    print("\n" + "=" * 50)
    print("开始打包 CanvasGameAutoBot...")
    print("=" * 50 + "\n")
    print("命令:", " ".join(cmd))
    print()

    result = subprocess.call(cmd)

    if result == 0:
        exe_path = os.path.join(base_dir, "dist", "CanvasGameAutoBot.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print("\n" + "=" * 50)
            print(f"打包成功！")
            print(f"输出文件: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
            print("=" * 50)
            print("\n使用说明:")
            print(f"1. 将 {exe_path} 复制到任意目录")
            print("2. 在同目录下创建 'templates' 文件夹并放入模板图片")
            print("3. 运行 exe 即可使用")
    else:
        print(f"\n[Build] 打包失败，返回码: {result}")
        print("[Build] 常见问题排查:")
        print("  - 确保路径不含中文或空格")
        print("  - 确保 pip install 了 requirements.txt 中所有依赖")
        print("  - 首次打包可能需要较长时间下载 WebEngine 资源")


if __name__ == "__main__":
    if not check_pyinstaller():
        sys.exit(1)
    build()
