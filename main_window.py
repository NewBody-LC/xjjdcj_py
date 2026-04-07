"""主窗口模块 - 应用程序主窗口

组装 QWebEngineView（内嵌浏览器，固定 1280×720）和 ConfigPanel（配置面板）
提供启动/停止/暂停自动化线程的控制接口、坐标拾取功能
"""

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QMessageBox, QSizePolicy,
    QFrame, QLabel, QLineEdit, QApplication
)
from PyQt5.QtCore import Qt, QSize, QTimer, QUrl, QPoint, QEvent
from PyQt5.QtGui import QPixmap, QMouseEvent
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript

from config import Config
from config_panel import ConfigPanel
from automation_thread import AutomationThread


class MainWindow(QMainWindow):
    """
    Canvas 游戏自动挂机程序主窗口
    
    功能：
    - 内嵌浏览器（1280x720）加载游戏页面
    - 配置面板：URL、模板路径、点击坐标、日志
    - 自动化线程控制：启动/停止/暂停
    - 坐标拾取：点击浏览器区域显示坐标
    - 跨线程截图：响应 AutomationThread 的请求在主线程执行 grab()
    """

    def __init__(self):
        super().__init__()
        self._auto_thread = None
        self._config = Config()
        self.config_panel: ConfigPanel = None
        self.web_view = None

        # 坐标拾取模式开关
        self._coord_pick_mode = False

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._setup_coord_picker()

        # 延迟初始化配置和加载（等 UI 完全就绪）
        QTimer.singleShot(500, self._load_initial_config)

    # ---------- 初始化 ----------

    def _setup_window(self):
        self.setWindowTitle("Canvas Game Auto-Bot")
        self.resize(1720, 900)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        top_splitter = QSplitter(Qt.Horizontal)

        # --- 左侧：配置面板 ---
        self.config_panel = ConfigPanel()
        top_splitter.addWidget(self.config_panel)

        # --- 右侧：浏览器容器 ---
        browser_container = QWidget()
        browser_layout = QVBoxLayout(browser_container)
        browser_layout.setContentsMargins(2, 2, 2, 2)
        browser_layout.setSpacing(2)

        self.web_view = QWebEngineView()
        self.web_view.setFixedSize(1280, 720)

        # ---- WebEngine 配置 ----
        page = self.web_view.page()

        # 1. User-Agent
        chrome_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        page.profile().setHttpUserAgent(chrome_ua)

        # 2. 启用 Web 功能
        from PyQt5.QtWebEngineWidgets import QWebEngineSettings
        s = page.settings()
        s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        s.setAttribute(QWebEngineSettings.XSSAuditingEnabled, False)
        s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)

        # 3. 持久化存储
        profile = page.profile()
        storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webengine_data")
        os.makedirs(storage_path, exist_ok=True)
        profile.setPersistentStoragePath(storage_path)
        profile.setCachePath(storage_path)
        profile.setHttpCacheType(profile.DiskHttpCache)

        # 4. 注入 OPFS Polyfill
        self._inject_opfs_polyfill(profile)

        # 5. 页面加载后多次注入 polyfill（SPA 框架兼容）
        def _reinject(ok):
            self._reinforce_polyfill(page)
            for delay in [1000, 3000, 6000]:
                QTimer.singleShot(delay, lambda d=delay: self._reinforce_polyfill(page))
        page.loadFinished.connect(_reinject)

        page.loadFinished.connect(self._on_page_load_finished)

        browser_layout.addWidget(self.web_view, alignment=Qt.AlignCenter)

        # 坐标拾取覆盖层（透明，仅在拾取模式下显示并拦截点击）
        self._coord_overlay = QLabel(self.web_view)
        self._coord_overlay.setFixedSize(1280, 720)
        self._coord_overlay.setStyleSheet(
            "background: transparent; border: 2px dashed #e6a700;"
        )
        self._coord_overlay.hide()
        self._coord_overlay.setCursor(Qt.CrossCursor)

        # 浏览器状态栏（含坐标拾取提示）
        status_row = QHBoxLayout()
        self.lbl_browser_status = QLabel("浏览器: 未加载")
        self.lbl_browser_status.setStyleSheet("color: #888; font-size: 11px; padding: 2px;")
        self.lbl_coords = QLabel("")
        self.lbl_coords.setStyleSheet("color: #e6a700; font-size: 11px; font-weight: bold; padding: 2px;")
        status_row.addWidget(self.lbl_browser_status, stretch=1)
        status_row.addWidget(self.lbl_coords)
        browser_layout.addLayout(status_row)

        top_splitter.addWidget(browser_container)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([390, 1290])

        root_layout.addWidget(top_splitter, stretch=6)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        status_bar.showMessage("就绪")

    def _connect_signals(self):
        """连接信号槽"""
        if not self.config_panel:
            return

        self.config_panel.start_requested.connect(self._on_start)
        self.config_panel.stop_requested.connect(self._on_stop)
        self.config_panel.pause_requested.connect(self._on_pause)

        if hasattr(self.config_panel, 'btn_load_url'):
            self.config_panel.btn_load_url.clicked.connect(self._load_url)

        # 坐标拾取模式
        if hasattr(self.config_panel, 'coord_pick_toggled'):
            self.config_panel.coord_pick_toggled.connect(self.set_coord_pick_mode)

    def _setup_coord_picker(self):
        """设置坐标拾取 - 使用覆盖层 + JS 注入双保险"""
        # 覆盖层鼠标事件
        self._coord_overlay.mouseMoveEvent = self._coord_mouse_move
        self._coord_overlay.mousePressEvent = self._coord_mouse_press
        self._coord_overlay.leaveEvent = self._coord_mouse_leave

    def _coord_mouse_move(self, event):
        if not self._coord_pick_mode:
            return
        x, y = event.x(), event.y()
        self.lbl_coords.setText(f"[坐标拾取] ({x}, {y})")

    def _coord_mouse_press(self, event):
        if not self._coord_pick_mode:
            return
        if event.button() == Qt.LeftButton:
            x, y = event.x(), event.y()
            self.lbl_coords.setText(f"已选择: ({x}, {y})")
            self.config_panel.append_log(f"[坐标] 点击位置: ({x}, {y})")
            
            # 尝试填入聚焦的输入框
            focused = QApplication.focusWidget()
            if isinstance(focused, QLineEdit):
                focused.setText(str(x))
                next_w = focused.nextInFocusChain()
                if isinstance(next_w, QLineEdit):
                    next_w.setFocus()
                    next_w.setText(str(y))
                    self.config_panel.append_log(f"[坐标] 已自动填入: X={x}, Y={y}")

    def _coord_mouse_leave(self, event):
        if self._coord_pick_mode:
            pass  # 保持最后显示的坐标

    # 保留 eventFilter 作为 JS 坐标拾取的补充（当覆盖层不适用时）
    def eventFilter(self, obj, event):
        """事件过滤器 - 用于坐标拾取"""
        if self._coord_pick_mode and obj is self.web_view:
            if event.type() == QEvent.MouseMove:
                pos = event.pos()
                self.lbl_coords.setText(f"[坐标拾取] ({pos.x()}, {pos.y()})")
            elif event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    pos = event.pos()
                    x, y = pos.x(), pos.y()
                    self.lbl_coords.setText(f"已选择: ({x}, {y})")
                    self.config_panel.append_log(f"[坐标] 点击位置: ({x}, {y})")

                    # 将坐标填入最近聚焦的输入框（如果有）
                    focused = QApplication.focusWidget()
                    if isinstance(focused, (QLineEdit)):
                        focused.setText(str(x))
                        # 跳到下一个（Y 坐标）
                        next_widget = focused.nextInFocusChain()
                        if isinstance(next_widget, QLineEdit):
                            next_widget.setFocus()
                            next_widget.setText(str(y))
                            self.config_panel.append_log(f"[坐标] 已填入: X={x}, Y={y}")

                    return False  # 不阻止事件继续传播
        return super().eventFilter(obj, event)

    def set_coord_pick_mode(self, enabled: bool):
        """切换坐标拾取模式"""
        self._coord_pick_mode = enabled
        if enabled:
            # 显示透明覆盖层（拦截鼠标事件）
            self._coord_overlay.show()
            self._coord_overlay.raise_()
            self.lbl_browser_status.setText("[坐标拾取模式] 点击浏览器区域获取坐标")
            
            # 同时注入 JS 监听器作为补充
            self.web_view.page().runJavaScript(R"""(function(){
                window.__coordPickHandler = function(e) {
                    var x = Math.round(e.offsetX || e.layerX);
                    var y = Math.round(e.offsetY || e.layerY);
                    // 通过 title 传递给 Qt
                    document.title = 'COORD:' + x + ',' + y;
                };
                if (!window.__coordPickInstalled) {
                    document.addEventListener('mousemove', window.__coordPickHandler);
                    document.addEventListener('click', function(e) {
                        var x = Math.round(e.offsetX || e.layerX);
                        var y = Math.round(e.offsetY || e.layerY);
                        document.title = 'COORD_CLICK:' + x + ',' + y;
                    });
                    window.__coordPickInstalled = true;
                }
            })()""")
        else:
            self._coord_overlay.hide()
            self.lbl_browser_status.setText("浏览器: 就绪")
            self.lbl_coords.setText("")
            # 移除 JS 监听器
            self.web_view.page().runJavaScript("""(function(){
                if (window.__coordPickHandler) {
                    document.removeEventListener('mousemove', window.__coordPickHandler);
                    window.__coordPickInstalled = false;
                }
            })()""")

    def _load_initial_config(self):
        """程序启动时加载配置并自动加载游戏 URL"""
        if self._config.load() and self.config_panel:
            self.config_panel.set_config_data(self._config.to_dict())

            url = self._config.data.url
            if url and "example.com" not in url:
                # 延迟 1 秒后加载，确保 UI 和 polyfill 都就绪
                QTimer.singleShot(1000, lambda u=url: self._do_load_url(u))
                self.config_panel.append_log(f"[启动] 将自动加载: {url}")
                self.lbl_browser_status.setText("浏览器: 准备加载...")

    # ---------- 控制回调 ----------

    def _on_start(self):
        """用户点击【启动】"""
        if self._auto_thread and self._auto_thread.is_running:
            QMessageBox.warning(self, "提示", "自动化已在运行中")
            return

        url = self.config_panel.get_url()
        if not url or not url.strip():
            QMessageBox.warning(self, "提示", "请先输入游戏 URL 并加载页面")
            return

        config_data = self.config_panel.get_config_data()
        templates_base_dir = self._config.base_dir

        # 创建并配置自动化线程
        self._auto_thread = AutomationThread(self.web_view)
        self._auto_thread.configure(config_data, templates_base_dir)

        # 关键连接：截图请求信号 -> 主线程执行 grab() -> 返回结果给线程
        self._auto_thread.request_screenshot.connect(self._on_screenshot_request)

        # 日志/状态/错误信号
        self._auto_thread.log_signal.connect(self.config_panel.append_log)
        self._auto_thread.state_changed.connect(self._on_state_changed)
        self._auto_thread.error_signal.connect(self._on_error)

        self.config_panel.set_running_state(True)
        self.config_panel.set_status_text("运行中")

        self._auto_thread.start()
        self.statusBar().showMessage("自动化运行中...")
        self.config_panel.append_log("[主窗口] 自动化线程已启动")

    def _on_screenshot_request(self):
        """
        主线程处理截图请求（由 AutomationThread 发出 signal 触发）
        
        这是修复跨线程 OpenGL 崩溃的关键：
        - AutomationThread 在后台线程发出 request_screenshot 信号
        - 此槽函数在主线程中被调用（Qt 信号跨线程自动排队）
        - 在主线程调用 grab()，OpenGL 上下文正确
        - 调用 on_screenshot_ready() 将结果返回给线程
        """
        try:
            pixmap = self.web_view.grab()
            if self._auto_thread:
                self._auto_thread.on_screenshot_ready(pixmap)
        except Exception as e:
            self.config_panel.append_log(f"[ERROR] 主线程截图失败: {e}")
            if self._auto_thread:
                self._auto_thread.on_screenshot_ready(None)

    def _on_stop(self):
        """用户点击【停止】"""
        if self._auto_thread:
            self._auto_thread.stop()
            if self._auto_thread.isRunning():
                self._auto_thread.wait(3000)
            self._auto_thread = None

        self.config_panel.set_running_state(False)
        self.config_panel.set_status_text("已停止")
        self.statusBar().showMessage("已停止")

    def _on_pause(self):
        """用户点击【暂停/恢复】"""
        if not self._auto_thread:
            return

        if self._auto_thread.is_paused:
            self._auto_thread.resume()
            self.config_panel.btn_pause.setText("\u23f8 暂停")
            self.config_panel.set_status_text("运行中")
        else:
            self._auto_thread.pause()
            self.config_panel.btn_pause.setText("\u25b6 恢复")
            self.config_panel.set_status_text("已暂停")

    def _on_state_changed(self, state_name: str):
        self.statusBar().showMessage(f"状态: {state_name}")
        self.lbl_browser_status.setText(f"状态: {state_name}")

    def _on_error(self, error_msg: str):
        self.config_panel.append_log(f"[ERROR] {error_msg}")

    # ---------- URL 加载 ----------

    def _do_load_url(self, url: str):
        """内部方法：实际执行 URL 加载"""
        qurl = QUrl(url)
        if not qurl.isValid():
            self.config_panel.append_log(f"[加载] 无效的 URL: {url}")
            return

        self.web_view.load(qurl)
        self.config_panel.append_log(f"[加载] {url}")
        self.lbl_browser_status.setText("浏览器: 加载中...")

    def _load_url(self):
        """用户点击【加载页面】按钮"""
        url = self.config_panel.get_url().strip()
        if not url:
            return

        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.config_panel.edit_url.setText(url)

        self._do_load_url(url)

    # ---------- OPFS Polyfill ----------

    def _inject_opfs_polyfill(self, profile):
        """使用 QWebEngineScript 在页面创建前注入 OPFS Polyfill"""
        script = QWebEngineScript()
        script.setName("opfs_polyfill")
        script.setSourceCode(R"""(function(){
if(navigator.storage&&typeof navigator.storage.getDirectory==='function')return;
var S={};
class H{constructor(n,d,m){this.name=n;this.kind='file';this._d=d||new ArrayBuffer(0);this._m=m||'application/octet-stream'}async getFile(){return new File([this._d],this.name,{type:this._m})}async createWritable(){var s=this;return{write:function(d){if(d instanceof ArrayBuffer)s._d=d;else if(typeof d==='string')s._d=new TextEncoder().encode(d).buffer;else if(d&&d.buffer)s._d=d.buffer;S[s.name]={d:s._d,m:s._m};return Promise.resolve()},close:function(){return Promise.resolve()}}}}
class D{constructor(){this.name='/';this.kind='directory'}async getFileHandle(n,o){var e=S[n];if(!e||!e.d){if(o&&o.create){e={d:new ArrayBuffer(0),m:'application/octet-stream'};S[n]=e}else{throw new DOMException('NotFound','NotFoundError')}}return new H(n,e.d,e.m)}async getDirectoryHandle(n,o){return this}}
navigator.storage=navigator.storage||{};
navigator.storage.getDirectory=function(){console.log('[OPFS-Polyfill] getDirectory');return Promise.resolve(new D())};
navigator.storage.estimate=async()=>({quota:10737418240,usage:0});
console.log('[OPFS-Polyfill] OK');
});""")
        script.setInjectionPoint(QWebEngineScript.DocumentCreation)
        script.setRunsOnSubFrames(True)
        script.setWorldId(QWebEngineScript.MainWorld)
        profile.scripts().insert(script)

    def _reinforce_polyfill(self, page):
        """延迟补充注入 polyfill（防止 SPA 覆盖）"""
        js = R"""(function(){
if(typeof navigator.storage.getDirectory !== 'function'){
  var S={};
  class H{constructor(n,d,m){this.name=n;this.kind='file';this._d=d||new ArrayBuffer(0);this._m=m||'application/octet-stream'}async getFile(){return new File([this._d],this.name,{type:this._m})}async createWritable(){var s=this;return{write:function(d){if(d instanceof ArrayBuffer)s._d=d;else if(typeof d==='string')s._d=new TextEncoder().encode(d).buffer;else if(d&&d.buffer)s._d=d.buffer;S[s.name]={d:s._d,m:s._m};return Promise.resolve()},close:function(){return Promise.resolve()}}}}
  class D{constructor(){this.name='/';this.kind='directory'}async getFileHandle(n,o){var e=S[n];if(!e||!e.d){if(o&&o.create){e={d:new ArrayBuffer(0),m:'application/octet-stream'};S[n]=e}else{throw new DOMException('NotFound','NotFoundError')}}return new H(n,e.d,e.m)}async getDirectoryHandle(n,o){return this}}
  navigator.storage=navigator.storage||{};
  navigator.storage.getDirectory=function(){console.log('[OPFS-REINFORCE] OK');return Promise.resolve(new D())};
}
})();"""
        page.runJavaScript(js)

    def _on_page_load_finished(self, ok: bool):
        current_url = self.web_view.url().toString()
        if ok:
            self.config_panel.append_log(f"[页面] 加载完成: {current_url}")
            self.lbl_browser_status.setText("浏览器: 已就绪")
        else:
            self.config_panel.append_log(f"[页面] 加载可能未完全成功")

    # ---------- 窗口事件 ----------

    def closeEvent(self, event):
        if self._auto_thread and self._auto_thread.is_running:
            self._auto_thread.stop()
            self._auto_thread.wait(5000)
        event.accept()
