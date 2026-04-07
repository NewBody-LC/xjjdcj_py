"""Canvas 游戏自动挂机程序 - 入口文件

使用方法：
  python main.py

依赖安装：
  pip install -r requirements.txt
"""

import sys
import os


def main():
    """程序主入口"""
    # 确保工作目录为脚本所在目录（方便相对路径的模板/配置文件）
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的环境
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    os.chdir(base_dir)

    # 高 DPI 支持 + QtWebEngine 必需的 OpenGL 共享上下文
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # QtWebEngine 要求：必须在创建 QApplication 之前设置
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    # QtWebEngine 要求：必须在创建 QCoreApplication 之前导入
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    app = QApplication(sys.argv)
    app.setApplicationName("CanvasGameAutoBot")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("AutoBot")

    # 创建并显示主窗口
    from main_window import MainWindow
    window = MainWindow()
    window.show()

    ret = app.exec_()
    print("程序退出，返回码:", ret)
    return ret


if __name__ == "__main__":
    sys.exit(main() or 0)
