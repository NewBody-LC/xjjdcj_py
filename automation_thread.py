"""自动化线程 - 在后台线程中执行截图、模板匹配、状态判断和点击操作

继承 QThread，避免阻塞 UI 线程。
通过信号与主窗口通信：日志输出、状态变化、错误报告。
"""

import time
import math
from PyQt5.QtCore import QThread, pyqtSignal, QObject, QTimer
from PyQt5.QtWidgets import QWidget
from typing import Optional, Dict, Any

from template_matcher import TemplateMatcher, pixmap_to_cv2
from state_machine import GameStateMachine, Action


class AutomationThread(QThread):
    """自动化执行线程
    
    运行在独立线程中，周期性执行：
    1. 截取 QWebEngineView 画面
    2. 转换为 OpenCV 格式
    3. 批量模板匹配
    4. 调用状态机 update() 获取动作
    5. 执行点击动作（通过 JavaScript 注入或坐标转换后点击）
    
    信号:
        log_signal: str -> 日志消息
        state_changed: str -> 状态名称变更
        error_signal: str -> 错误信息
        match_result_signal: dict -> 模板匹配结果（调试用）
    """

    # --- 信号定义 ---
    log_signal = pyqtSignal(str)           # 日志消息
    state_changed = pyqtSignal(str)         # 当前状态名称
    error_signal = pyqtSignal(str)          # 错误信息
    screenshot_signal = object              # 最新截图（用于调试显示）

    def __init__(self, web_view: QWidget, parent=None):
        """
        Args:
            web_view: QWebEngineView 实例，用于截图和注入点击事件
            parent: 父对象
        """
        super().__init__(parent)
        self.web_view = web_view

        # 核心组件
        self.matcher = TemplateMatcher()
        self.state_machine = GameStateMachine()

        # 控制标志
        self._running = False
        self._paused = False
        self._requested_stop = False

        # 配置参数（从 ConfigPanel 设置）
        self.config: Dict[str, Any] = {}
        self.click_interval: float = 0.5  # 截图/匹配间隔秒数
        self.max_loops: int = 0  # 0=无限循环

        # Canvas 坐标转换相关缓存
        self._canvas_scale_x: float = 1.0
        self._canvas_scale_y: float = 1.0
        self._scale_initialized = False

        # 绑定状态机日志回调
        self.state_machine.set_log_callback(self._emit_log)

    def configure(self, config_data: dict, templates_base_dir: str = ""):
        """配置自动化线程
        
        Args:
            config_data: 配置字典（来自 Config.data.to_dict()）
            templates_base_dir: 模板图片的基准目录路径
        """
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

    def run(self):
        """线程主循环 - 由 start() 触发调用"""
        self._running = True
        self._paused = False
        self._requested_stop = False
        self.state_machine.start()

        loop_counter = 0

        while self._running:
            try:
                # 检查停止请求
                if self._requested_stop:
                    break

                # 检查暂停
                if self._paused:
                    time.sleep(0.2)
                    continue

                # 检查最大循环次数
                if self.max_loops > 0 and self.state_machine.loop_count > self.max_loops:
                    self._emit_log(f"已达到最大循环次数 ({self.max_loops})，自动停止")
                    break

                # ---- 核心流程 ----
                
                # 1. 截图
                screenshot_cv2 = self._capture_screenshot()
                if screenshot_cv2 is None:
                    time.sleep(self.click_interval)
                    continue

                self.screenshot_signal.emit(screenshot_cv2)

                # 2. 初始化 Canvas 缩放比例（首次）
                if not self._scale_initialized:
                    self._init_canvas_scale()

                # 3. 对所有模板执行匹配
                match_results = self._run_all_matching(screenshot_cv2)

                # 4. 调用状态机获取动作
                config_for_sm = {
                    'threshold': self.matcher.threshold,
                    'fixed_clicks': self.config.get('fixed_clicks', {}),
                }
                new_state, action = self.state_machine.update(
                    screenshot=screenshot_cv2,
                    match_results=match_results,
                    config=config_for_sm
                )

                # 5. 发送状态变化信号
                old_name = self.state_machine.previous_state.name if self.state_machine.previous_state else ""
                if new_state.name != old_name:
                    self.state_changed.emit(new_state.name)

                # 6. 执行动作
                if action.action_type == Action.CLICK_COORD:
                    x, y = action.position
                    self._click_at(x, y)
                elif action.action_type == Action.CLICK_NEAREST_NODE:
                    x, y = action.position
                    self._click_at(x, y)
                elif action.action_type == Action.WAIT:
                    pass  # 不做操作，等待下个周期
                elif action.action_type == Action.NONE:
                    pass

                # 7. 等待间隔
                time.sleep(self.click_interval)

            except Exception as e:
                self.error_signal.emit(f"自动化循环异常: {e}")
                time.sleep(1.0)

        # 清理
        self._running = False
        self.state_machine.stop()
        self.state_changed.emit("STOPPED")
        self._emit_log("=== 自动化线程已结束 ===")

    # ---------- 截图 ----------

    def _capture_screenshot(self):
        """截取 QWebEngineView 的当前画面并转换为 OpenCV 格式
        
        Returns:
            OpenCV BGR numpy 数组，失败返回 None
        """
        try:
            from PyQt5.QtWidgets import QApplication
            
            # 在主线程中截图（QPixmap 操作需要在主线程）
            pixmap = None
            result_container = [None]

            def grab_in_main():
                result_container[0] = self.web_view.grab()

            # 通过 Qt 事件机制确保在主线程执行
            # 注意：grab() 需要在 GUI 线程调用
            from PyQt5.QtCore import QMetaObject, Qt
            done = [False]
            
            def do_grab():
                try:
                    result_container[0] = self.web_view.grab()
                except Exception as e:
                    print(f"[AutomationThread] 截图异常: {e}")
                finally:
                    done[0] = True

            QMetaObject.invokeMethod(self.web_view, "grab", Qt.QueuedConnection)
            
            # 备用方案：直接调用（大多数情况可以工作）
            try:
                pixmap = self.web_view.grab()
            except Exception as e:
                self._emit_log(f"截图失败: {e}")
                return None

            if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
                return None

            return pixmap_to_cv2(pixmap)

        except Exception as e:
            self._emit_log(f"截图过程出错: {e}")
            return None

    # ---------- 模板匹配 ----------

    def _run_all_matching(self, screenshot_cv2) -> Dict[str, Any]:
        """对所有模板批量执行匹配
        
        区分单次匹配模板（如 victory、map_screen）和多位置匹配模板（如节点图标）
        
        Returns:
            {template_name: MatchResult} 字典
        """
        results = {}

        # 单次匹配的模板（界面状态标识）
        single_match_templates = [
            "map_screen", "in_battle", "victory", "defeat"
        ]
        for name in single_match_templates:
            if self.matcher.is_loaded(name):
                results[name] = self.matcher.match(screenshot_cv2, name)

        # 多位置匹配的模板（节点图标）
        multi_match_templates = [
            "node_yellow", "node_red", "node_blue", "node_green", "node_purple"
        ]
        for name in multi_match_templates:
            if self.matcher.is_loaded(name):
                results[name] = self.matcher.match_all(screenshot_cv2, name)

        return results

    # ---------- 点击操作 ----------

    def _init_canvas_scale(self):
        """通过 JavaScript 获取 Canvas 的内部分辨率与 CSS 显示尺寸的比例
        
        Canvas 内部分辨率可能与显示尺寸不同（如 canvas.width=1920 但 CSS width=1280），
        点击时需要将屏幕坐标转换为 Canvas 内部坐标。
        """
        js_code = """
        (function() {
            var canvases = document.querySelectorAll('canvas');
            if (canvases.length === 0) return null;
            var c = canvases[0];
            var rect = c.getBoundingClientRect();
            return {
                canvasWidth: c.width,
                canvasHeight: c.height,
                cssWidth: rect.width,
                cssHeight: rect.height,
                scaleX: c.width / rect.width,
                scaleY: c.height / rect.height
            };
        })()
        """

        try:
            page = self.web_view.page()
            result_container = [None]

            def on_result(r):
                result_container[0] = r

            page.runJavaScript(js_code, lambda r: setattr(result_container, '__setitem__', (0, r)))

            # 同步等待结果（简单实现，实际可能需要改进）
            import time
            time.sleep(0.3)

            if isinstance(result_container[0], dict) and result_container[0]:
                info = result_container[0]
                self._canvas_scale_x = info.get('scaleX', 1.0)
                self._canvas_scale_y = info.get('scaleY', 1.0)
                self._scale_initialized = True
                self._emit_log(
                    f"Canvas 缩放比: X={self._canvas_scale_x:.2f}, Y={self._canvas_scale_y:.2f} "
                    f"(内部{info.get('canvasWidth')}x{info.get('canvasHeight')}, "
                    f"显示{info.get('cssWidth')}x{info.get('cssHeight')})"
                )
            else:
                self._canvas_scale_x = 1.0
                self._canvas_scale_y = 1.0
                self._scale_initialized = True  # 即使没拿到也标记为已初始化，避免重复尝试
                self._emit_log("无法获取 Canvas 信息，使用默认缩放比 1.0")

        except Exception as e:
            self._emit_log(f"初始化 Canvas 缩放比失败: {e}，使用默认值 1.0")
            self._canvas_scale_x = 1.0
            self._canvas_scale_y = 1.0
            self._scale_initialized = True

    def _click_at(self, screen_x: int, screen_y: int):
        """在指定屏幕坐标位置模拟点击
        
        先尝试通过 runJavaScript 注入鼠标事件到 Canvas，
        如果失败则使用 Win32 API 模拟物理鼠标点击。
        
        Args:
            screen_x: 基于 1280×720 窗口坐标系中的 X 坐标
            screen_y: 基于 1280×720 窗口坐标系中的 Y 坐标
        """
        # 转换为 Canvas 内部坐标
        canvas_x = int(screen_x * self._canvas_scale_x)
        canvas_y = int(screen_y * self._canvas_scale_y)

        self._emit_log(f"点击: 屏幕({screen_x},{screen_y}) → Canvas({canvas_x},{canvas_y})")

        # 方式1：通过 JavaScript 注入点击事件到 Canvas
        success = self._click_via_js(canvas_x, canvas_y)

        # 方式2（备选）：Win32 API 物理点击
        if not success:
            self._click_via_win32(screen_x, screen_y)

    def _click_via_js(self, canvas_x: int, canvas_y: int) -> bool:
        """通过 runJavaScript 向 Canvas 元素注入 mousedown + mouseup 事件
        
        Returns:
            成功返回 True
        """
        js_code = f"""
        (function() {{
            var canvas = document.querySelector('canvas');
            if (!canvas) return false;
            
            // 创建并分发鼠标事件
            function createMouseEvent(type, x, y) {{
                var evt = new MouseEvent(type, {{
                    bubbles: true,
                    cancelable: true,
                    clientX: canvas.getBoundingClientRect().left + x / ({self._canvas_scale_x}),
                    clientY: canvas.getBoundingClientRect().top + y / ({self._canvas_scale_y}),
                    button: 0,
                    buttons: type === 'mousedown' ? 1 : 0
                }});
                return evt;
            }}
            
            canvas.dispatchEvent(createMouseEvent('mousedown', {canvas_x}, {canvas_y}));
            canvas.dispatchEvent(createMouseEvent('mouseup', {canvas_x}, {canvas_y}));
            canvas.dispatchEvent(createMouseEvent('click', {canvas_x}, {canvas_y}));
            return true;
        }})()
        """

        try:
            page = self.web_view.page()
            page.runJavaScript(js_code)
            return True
        except Exception as e:
            self._emit_log(f"JS 点击注入失败: {e}")
            return False

    def _click_via_win32(self, x: int, y: int) -> bool:
        """使用 Win32 API 模拟鼠标物理点击（备选方案）
        
        将窗口内坐标转换为屏幕绝对坐标后点击。
        注意：此方式需要窗口可见且未被遮挡。
        
        Args:
            x: 窗口内相对坐标 X
            y: 窗口内相对坐标 Y
            
        Returns:
            成功返回 True
        """
        try:
            import ctypes
            from ctypes import wintypes

            # 获取窗口在屏幕上的绝对位置
            win_id = self.web_view.winId()
            from PyQt5.QtGui import QWindow
            from PyQt5.QtWidgets import QApplication

            qwindow = self.web_view.windowHandle()
            if qwindow:
                global_pos = qwindow.mapToGlobal(__import__('PyQt5.QtCore').QPoint(x, y))
                abs_x = global_pos.x()
                abs_y = global_pos.y()
            else:
                # 回退：使用 ctypes 获取窗口位置
                user32 = ctypes.windll.user32
                rect = wintypes.RECT()
                user32.GetWindowRect(win_id, ctypes.byref(rect))
                abs_x = rect.left + x
                abs_y = rect.top + y

            # 设置鼠标位置并点击
            user32 = ctypes.windll.user32
            user32.SetCursorPos(abs_x, abs_y)
            time.sleep(0.05)
            user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.05)
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP

            return True

        except ImportError:
            self._emit_log("Win32 API 不可用（非 Windows 平台）")
            return False
        except Exception as e:
            self._emit_log(f"Win32 点击失败: {e}")
            return False

    # ---------- 控制方法 ----------

    def pause(self):
        """暂停自动化"""
        self._paused = True
        self.state_machine.pause()

    def resume(self):
        """恢复自动化"""
        self._paused = False
        self.state_machine.resume()

    def stop(self):
        """请求停止自动化线程"""
        self._requested_stop = True
        self._running = False

    @property
    def is_running(self) -> bool:
        """线程是否正在运行"""
        return self._running and not self._requested_stop

    @property
    def is_paused(self) -> bool:
        """是否处于暂停状态"""
        return self._paused
