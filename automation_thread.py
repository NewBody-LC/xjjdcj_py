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

                # 1. 请求主线程截图（关键：不在本线程调用 grab()）
                screenshot_cv2 = self._capture_screenshot_cross_thread()
                if screenshot_cv2 is None:
                    time.sleep(self.click_interval)
                    continue

                # 2. 初始化 Canvas 缩放比例（首次）
                if not self._scale_initialized:
                    self._init_canvas_scale()

                # 3. 批量模板匹配
                match_results = self._run_all_matching(screenshot_cv2)

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
                    self.state_changed.emit(new_state.name)

                # 5. 执行动作
                if action.action_type in (Action.CLICK_COORD, Action.CLICK_NEAREST_NODE):
                    x, y = action.position
                    self._click_at(x, y)

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
        """获取 Canvas 缩放比（JS 调用是线程安全的）"""
        js_code = """
        (function() {
            var c = document.querySelector('canvas');
            if (!c) return null;
            var r = c.getBoundingClientRect();
            return {cw: c.width, ch: h=c.height, rw: r.width, rh: r.height,
                    sx: c.width/r.width, sy: c.height/r.height};
        })()
        """

        try:
            page = self.web_view.page()

            result_container = [None]
            callback_fired = [False]

            def on_result(r):
                result_container[0] = r
                callback_fired[0] = True

            page.runJavaScript(js_code, on_result)

            for _ in range(20):  # 等 2 秒
                if callback_fired[0]:
                    break
                time.sleep(0.1)

            info = result_container[0]
            if isinstance(info, dict) and info:
                self._canvas_scale_x = float(info.get('sx', 1.0))
                self._canvas_scale_y = float(info.get('sy', 1.0))
                self._scale_initialized = True
                self._emit_log(
                    f"Canvas 缩放比: X={self._canvas_scale_x:.2f}, Y={self._canvas_scale_y:.2f} "
                    f"(内部{info.get('cw')}x{info.get('ch')}, 显示{info.get('rw')}x{info.get('rh')})"
                )
            else:
                self._scale_initialized = True
                self._emit_log("无法获取 Canvas 信息，使用默认缩放比 1.0")

        except Exception as e:
            self._emit_log(f"初始化 Canvas 缩放比失败: {e}")
            self._scale_initialized = True

    def _click_at(self, screen_x: int, screen_y: int):
        """在指定坐标点击"""
        canvas_x = int(screen_x * self._canvas_scale_x)
        canvas_y = int(screen_y * self._canvas_scale_y)
        self._emit_log(f"点击: 屏幕({screen_x},{screen_y}) → Canvas({canvas_x},{canvas_y})")
        self._click_via_js(canvas_x, canvas_y)

    def _click_via_js(self, canvas_x: int, canvas_y: int) -> bool:
        """通过 JS 注入鼠标事件"""
        sx, sy = self._canvas_scale_x, self._canvas_scale_y
        js_code = f"""(function(){{
            var c=document.querySelector('canvas');if(!c)return false;
            var r=c.getBoundingClientRect();
            function ev(t){{return new MouseEvent(t,{{bubbles:true,cancelable:true,
              clientX:r.left+{canvas_x}/{sx},clientY:r.top+{canvas_y}/{sy},
              button:0,buttons:t==='mousedown'?1:0}});}}
            c.dispatchEvent(ev('mousedown'));c.dispatchEvent(ev('mouseup'));c.dispatchEvent(ev('click'));
            return true;}})()"""
        try:
            self.web_view.page().runJavaScript(js_code)
            return True
        except Exception as e:
            self._emit_log(f"JS 点击注入失败: {e}")
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
