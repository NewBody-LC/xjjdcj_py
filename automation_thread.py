"""自动化线程 - 在后台线程中执行模板匹配、状态判断和点击操作

关键设计：截图必须在主线程执行（OpenGL 上下文绑定），通过信号槽机制
将截图请求发送到主线程，主线程完成截图后返回结果。
"""

import time
import math
from PyQt5.QtCore import (
    QThread, pyqtSignal, QObject, QTimer,
    QMetaObject, Qt as QtCoreQt
)
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPixmap
from typing import Optional, Dict, Any

from template_matcher import TemplateMatcher, pixmap_to_cv2
from state_machine import GameStateMachine, Action


class AutomationThread(QThread):
    """自动化执行线程
    
    运行在独立线程中，周期性执行：
    1. 通过信号请求主线程截取 QWebEngineView 画面（避免跨线程 OpenGL 问题）
    2. 转换为 OpenCV 格式
    3. 批量模板匹配
    4. 调用状态机 update() 获取动作
    5. 执行点击动作
    
    与 MainWindow 的通信协议：
    - AutomationThread -> MainWindow: request_screenshot 信号（请求截图）
    - MainWindow -> AutomationThread: on_screenshot_ready 槽（接收截图结果）
    
    信号:
        log_signal: str -> 日志消息
        state_changed: str -> 当前状态名称变更
        error_signal: str -> 错误信息
        request_screenshot: 无参数 -> 请求主线程截图
    """

    # --- 发给主窗口的信号 ---
    log_signal = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    # 关键信号：向主线程请求截图
    request_screenshot = pyqtSignal()

    def __init__(self, web_view: QWidget, parent=None):
        super().__init__(parent)
        self.web_view = web_view

        # 在主线程中缓存窗口句柄（避免后台线程访问 Qt GUI 对象导致跨线程崩溃）
        self._webview_hwnd = int(web_view.winId()) if web_view else 0

        # 核心组件
        self.matcher = TemplateMatcher()
        self.state_machine = GameStateMachine()

        # 控制标志
        self._running = False
        self._paused = False
        self._requested_stop = False

        # 配置参数
        self.config: Dict[str, Any] = {}
        self.click_interval: float = 0.5
        self.max_loops: int = 0

        # Canvas 坐标转换缓存
        self._canvas_scale_x: float = 1.0
        self._canvas_scale_y: float = 1.0
        self._scale_initialized = False

        # 截图结果容器（主线程写入，本线程读取）
        self._screenshot_result = None
        self._screenshot_ready = False

        self.state_machine.set_log_callback(self._emit_log)

    def configure(self, config_data: dict, templates_base_dir: str = ""):
        """配置自动化线程"""
        self.config = config_data
        self.click_interval = config_data.get('click_interval', 0.5)
        self.max_loops = config_data.get('max_loops', 0)

        threshold = config_data.get('threshold', 0.7)
        self.matcher.threshold = threshold

        templates = config_data.get('templates', {})
        if templates:
            count = self.matcher.load_templates(templates, templates_base_dir)
            self._emit_log(f"已加载 {count} 个模板")

    def _emit_log(self, message: str):
        """发送日志信号"""
        self.log_signal.emit(message)

    # ---------- 主窗口调用的方法 ----------

    def on_screenshot_ready(self, pixmap):
        """
        主线程调用此方法，传入截图结果。
        
        这是跨线程通信的关键：
        1. AutomationThread 发出 request_screenshot 信号
        2. MainWindow 在主线程中执行 web_view.grab()
        3. MainWindow 调用此方法传入 QPixmap
        4. AutomationThread 的 run() 循环继续执行
        
        Args:
            pixmap: 主线程截取的 QPixmap 对象
        """
        self._screenshot_result = pixmap
        self._screenshot_ready = True

    # ---------- 线程主循环 ----------

    def run(self):
        """线程主循环"""
        self._running = True
        self._paused = False
        self._requested_stop = False
        self.state_machine.start()

        while self._running:
            try:
                if self._requested_stop:
                    break

                if self._paused:
                    time.sleep(0.2)
                    continue

                if self.max_loops > 0 and self.state_machine.loop_count > self.max_loops:
                    self._emit_log(f"已达到最大循环次数 ({self.max_loops})，自动停止")
                    break

                # ---- 核心流程 ----

                # 初始化诊断计数器（确保在循环开始前存在）
                if not hasattr(self, '_screenshot_warn_count'):
                    self._screenshot_warn_count = 0
                if not hasattr(self, '_diag_counter'):
                    self._diag_counter = 0

                # 1. 请求主线程截图（关键：不在本线程调用 grab()）
                screenshot_cv2 = self._capture_screenshot_cross_thread()
                if screenshot_cv2 is None:
                    self._screenshot_warn_count += 1
                    if self._screenshot_warn_count <= 3:
                        self._emit_log(f"截图未就绪，等待中... ({self._screenshot_warn_count})")
                    time.sleep(self.click_interval)
                    continue

                if self._screenshot_warn_count > 0:
                    self._emit_log("截图已恢复正常")
                    self._screenshot_warn_count = 0

                # 2. 初始化 Canvas 缩放比例（首次）
                if not self._scale_initialized:
                    self._init_canvas_scale()

                # 3. 批量模板匹配
                match_results = self._run_all_matching(screenshot_cv2)

                # 3b. 诊断输出：每 10 次循环输出一次匹配摘要
                self._diag_counter += 1
                if self._diag_counter % 10 == 1:
                    found_list = [f"[{k}]({v.confidence:.0%})" 
                                  for k, v in match_results.items() if v and v.found]
                    not_found = [k for k, v in match_results.items() if v and not v.found]
                    summary = f"[诊断] 已匹配: {', '.join(found_list) if found_list else '无'}"
                    if not_found:
                        summary += f" | 未匹配: {', '.join(not_found)}"
                    self._emit_log(summary)

                # 4. 状态机决策
                config_for_sm = {
                    'threshold': self.matcher.threshold,
                    'fixed_clicks': self.config.get('fixed_clicks', {}),
                }
                new_state, action = self.state_machine.update(
                    screenshot=screenshot_cv2,
                    match_results=match_results,
                    config=config_for_sm
                )

                old_name = self.state_machine.previous_state.name if self.state_machine.previous_state else ""
                if new_state.name != old_name:
                    self.state_changed.emit(new_state.value)

                # 5. 执行动作
                if action.action_type in (Action.CLICK_COORD, Action.CLICK_NEAREST_NODE):
                    x, y = action.position
                    self._click_at(x, y)

                if self._diag_counter % 10 == 1 and action and hasattr(action, 'description') and action.description:
                    self._emit_log(f"[动作] {action.description}")

                time.sleep(self.click_interval)

            except Exception as e:
                self.error_signal.emit(f"自动化循环异常: {e}")
                time.sleep(1.0)

        self._running = False
        self.state_machine.stop()
        self.state_changed.emit("STOPPED")
        self._emit_log("=== 自动化线程已结束 ===")

    # ---------- 截图（跨线程安全）----------

    def _capture_screenshot_cross_thread(self):
        """
        跨线程安全的截图方法
        
        原理：
        1. 重置结果容器
        2. 发出 request_screenshot 信号（连接到主线程的槽）
        3. 等待主线程完成截图并回调 on_screenshot_ready
        4. 读取结果并转换格式
        
        Returns:
            OpenCV BGR numpy 数组，失败返回 None
        """
        try:
            # 重置状态
            self._screenshot_result = None
            self._screenshot_ready = False

            # 发送截图请求到主线程
            self.request_screenshot.emit()

            # 等待主线程完成（最多等待 3 秒）
            timeout = 30  # 3秒 * 10次/100ms
            for _ in range(timeout):
                if self._screenshot_ready or self._requested_stop:
                    break
                time.sleep(0.1)

            if not self._screenshot_ready or self._screenshot_result is None:
                return None

            pixmap = self._screenshot_result
            if isinstance(pixmap, QPixmap) and not pixmap.isNull():
                if pixmap.width() > 0 and pixmap.height() > 0:
                    return pixmap_to_cv2(pixmap)

            return None

        except Exception as e:
            self._emit_log(f"截图过程出错: {e}")
            return None

    # ---------- 模板匹配 ----------

    def _run_all_matching(self, screenshot_cv2) -> Dict[str, Any]:
        """对所有模板批量执行匹配"""
        results = {}

        single_match_templates = [
            "map_screen", "in_battle", "victory", "defeat"
        ]
        for name in single_match_templates:
            if self.matcher.is_loaded(name):
                results[name] = self.matcher.match(screenshot_cv2, name)

        multi_match_templates = [
            "node_yellow", "node_red", "node_blue", "node_green", "node_purple"
        ]
        for name in multi_match_templates:
            if self.matcher.is_loaded(name):
                results[name] = self.matcher.match_all(screenshot_cv2, name)

        return results

    # ---------- 点击操作 ----------

    def _init_canvas_scale(self):
        """获取 Canvas 缩放比（使用默认值 1.0）
        
        1280x720 固定窗口不需要动态计算缩放比，
        且从后台线程调用 page.runJavaScript 不够可靠。
        """
        self._scale_initialized = True
        self._canvas_scale_x = 1.0
        self._canvas_scale_y = 1.0
        self._emit_log("Canvas 缩放比: 使用默认值 1.0 (1280x720 固定窗口)")

    def _click_at(self, screen_x: int, screen_y: int):
        """在指定坐标点击（优先用 Win32 API，JS 作为补充）"""
        # 直接使用屏幕坐标（1280x720 窗口坐标），不转换 Canvas 内部坐标
        self._emit_log(f"点击: 屏幕({screen_x},{screen_y})")
        
        # 方式1：Win32 API 物理点击（最可靠）
        success = self._click_via_win32(screen_x, screen_y)
        if success:
            return

        # 方式2：JS 注入点击事件（备选）
        self._click_via_js(screen_x, screen_y)

    def _click_via_win32(self, x: int, y: int) -> bool:
        """使用 Win32 API 模拟物理鼠标点击（纯 Win32，不触碰 Qt GUI 对象）"""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = self._webview_hwnd

            if hwnd == 0:
                self._emit_log("Win32 点击失败：无效的窗口句柄")
                return False

            # 纯 Win32 API 获取窗口屏幕坐标
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            abs_x = rect.left + x
            abs_y = rect.top + y

            # 设置鼠标位置并点击
            user32.SetCursorPos(abs_x, abs_y)
            time.sleep(0.03)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.03)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP

            return True

        except ImportError:
            self._emit_log("Win32 API 不可用（非 Windows 平台）")
            return False
        except Exception as e:
            self._emit_log(f"Win32 点击异常: {e}")
            return False

    def _click_via_js(self, x: int, y: int) -> bool:
        """通过 JS 注入鼠标事件到 Canvas（已禁用 - 避免跨线程访问 Qt GUI 对象）"""
        self._emit_log("JS 点击注入已禁用（避免跨线程问题），请确保 Win32 API 可用")
        return False

    # ---------- 控制方法 ----------

    def pause(self):
        self._paused = True
        self.state_machine.pause()

    def resume(self):
        self._paused = False
        self.state_machine.resume()

    def stop(self):
        self._requested_stop = True
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running and not self._requested_stop

    @property
    def is_paused(self) -> bool:
        return self._paused
