"""主窗口模块 - 应用程序主窗口

组装 QWebEngineView（内嵌浏览器，固定 1280×720）和 ConfigPanel（配置面板）
提供启动/停止/暂停自动化线程的控制接口
"""

import os
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QStatusBar, QMessageBox, QSizePolicy,
    QFrame, QLabel
)
from PyQt5.QtCore import Qt, QSize, QTimer, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineScript

from config import Config
from config_panel import ConfigPanel
from automation_thread import AutomationThread


class MainWindow(QMainWindow):
    """
    Canvas 游戏自动挂机程序主窗口
    
    布局：
    ┌──────────────────────────────────────────────┐
    │  标题栏: Canvas Game Auto-Bot                │
    ├───────────────┬──────────────────────────────┤
    │               │                              │
    │  配置面板      │  浏览器区域 (1280×720)        │
    │  (ConfigPanel)│  (QWebEngineView)            │
    │               │                              │
    ├───────────────┴──────────────────────────────┤
    │  运行日志 (LogViewer)                          │
    └──────────────────────────────────────────────┘
    """

    def __init__(self):
        super().__init__()
        self._auto_thread = None  # AutomationThread 实例
        self._config = Config()   # 配置管理器

        self.config_panel: ConfigPanel = None
        self.web_view = None

        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._load_initial_config()

    # ---------- 初始化 ----------

    def _setup_window(self):
        """设置窗口属性"""
        self.setWindowTitle("Canvas Game Auto-Bot")
        self.resize(1720, 900)

    def _build_ui(self):
        """构建界面"""
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # 上半部分：水平分割器 [配置面板 | 浏览器]
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

        # ---- 配置 WebEngine 页面属性 ----
        page = self.web_view.page()

        # 1. User-Agent 伪装为 Chrome
        chrome_ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
        page.profile().setHttpUserAgent(chrome_ua)

        # 2. 启用 Web 功能
        from PyQt5.QtWebEngineWidgets import QWebEngineSettings
        settings = page.settings()
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.XSSAuditingEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        settings.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)

        # 3. 持久化存储路径
        profile = page.profile()
        storage_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webengine_data")
        os.makedirs(storage_path, exist_ok=True)
        profile.setPersistentStoragePath(storage_path)
        profile.setCachePath(storage_path)
        profile.setHttpCacheType(profile.DiskHttpCache)

        # 4. 注入 OPFS Polyfill（在页面 JS 执行前）
        self._inject_opfs_polyfill(profile)

        # 4b. 页面加载完成后二次确认注入（SPA 框架可能动态覆盖 navigator）
        def _reinject_on_load(ok):
            self._reinforce_polyfill(page)
            # 延迟多次注入，等待 SPA 框架（single-spa）逐步初始化
            from PyQt5.QtCore import QTimer
            for delay in [1000, 3000, 6000, 10000]:
                QTimer.singleShot(delay, lambda d=delay: (
                    self.config_panel.append_log(f"[Polyfill] 第 {d//1000}s 注入"),
                    self._reinforce_polyfill(page)
                ))
        page.loadFinished.connect(_reinject_on_load)

        # 5. 页面加载事件
        page.loadFinished.connect(self._on_page_load_finished)

        browser_layout.addWidget(self.web_view, alignment=Qt.AlignCenter)

        # 浏览器下方状态标签
        self.lbl_browser_status = QLabel("浏览器: 未加载")
        self.lbl_browser_status.setStyleSheet("color: #888; font-size: 11px; padding: 2px;")
        browser_layout.addWidget(self.lbl_browser_status)

        top_splitter.addWidget(browser_container)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([390, 1290])

        root_layout.addWidget(top_splitter, stretch=6)

        # 状态栏
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

    def _load_initial_config(self):
        """程序启动时加载已有配置"""
        if self._config.load() and self.config_panel:
            self.config_panel.set_config_data(self._config.to_dict())

            url = self._config.data.url
            if url and "example.com" not in url:
                self.web_view.load(QUrl(url))
                self.lbl_browser_status.setText(f"浏览器: {url}")

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

        self._auto_thread = AutomationThread(self.web_view)
        self._auto_thread.configure(config_data, templates_base_dir)

        self._auto_thread.log_signal.connect(self.config_panel.append_log)
        self._auto_thread.state_changed.connect(self._on_state_changed)
        self._auto_thread.error_signal.connect(self._on_error)

        self.config_panel.set_running_state(True)
        self.config_panel.set_status_text("运行中")

        self._auto_thread.start()
        self.statusBar().showMessage("自动化运行中...")

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
        """状态机状态变化"""
        self.statusBar().showMessage(f"状态: {state_name}")
        self.lbl_browser_status.setText(f"状态: {state_name}")

    def _on_error(self, error_msg: str):
        """错误信息"""
        self.config_panel.append_log(f"[ERROR] {error_msg}")

    # ---------- URL 加载 ----------

    def _load_url(self):
        """加载 URL 到内嵌浏览器"""
        url = self.config_panel.get_url().strip()
        if not url:
            return

        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.config_panel.edit_url.setText(url)

        qurl = QUrl(url)
        if not qurl.isValid():
            QMessageBox.warning(self, "URL 无效", f"无法解析: {url}")
            return

        self.web_view.load(qurl)
        self.config_panel.append_log(f"[加载] {url}")
        self.lbl_browser_status.setText("浏览器: 加载中...")

        def on_load_ok(ok):
            if ok:
                self.lbl_browser_status.setText(f"浏览器: 已就绪 ({url})")
            else:
                self.config_panel.append_log(f"[加载] 页面加载可能失败")
                self.lbl_browser_status.setText("浏览器: 加载异常")

        self.web_view.loadFinished.connect(on_load_ok)

    # ---------- OPFS Polyfill ----------

    def _inject_opfs_polyfill(self, profile):
        """
        使用 QWebEngineScript + DocumentCreation 注入点，确保在页面任何 JS 执行之前注入。
        
        关键区别：
        - runJavaScript(): 页面加载完成后才执行 → 太晚，游戏已报错
        - QWebEngineScript(DocumentCreation): 文档创建时就注入 → 在所有脚本之前执行
        """
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
        """
        通过 runJavaScript 注入/确认 polyfill（由外部调用方控制时机）
        """
        reinforce_js = R"""(function(){
if(typeof navigator.storage.getDirectory !== 'function'){
  var S={};
  class H{constructor(n,d,m){this.name=n;this.kind='file';this._d=d||new ArrayBuffer(0);this._m=m||'application/octet-stream'}async getFile(){return new File([this._d],this.name,{type:this._m})}async createWritable(){var s=this;return{write:function(d){if(d instanceof ArrayBuffer)s._d=d;else if(typeof d==='string')s._d=new TextEncoder().encode(d).buffer;else if(d&&d.buffer)s._d=d.buffer;S[s.name]={d:s._d,m:s._m};return Promise.resolve()},close:function(){return Promise.resolve()}}}}
  class D{constructor(){this.name='/';this.kind='directory'}async getFileHandle(n,o){var e=S[n];if(!e||!e.d){if(o&&o.create){e={d:new ArrayBuffer(0),m:'application/octet-stream'};S[n]=e}else{throw new DOMException('NotFound','NotFoundError')}}return new H(n,e.d,e.m)}async getDirectoryHandle(n,o){return this}}
  navigator.storage=navigator.storage||{};
  navigator.storage.getDirectory=function(){console.log('[OPFS-REINFORCE] getDirectory');return Promise.resolve(new D())};
  navigator.storage.estimate=async()=>({quota:10737418240,usage:0});
  console.log('[OPFS-REINFORCE] OK');
} else {
  console.log('[OPFS-REINFORCE] skip - already exists');
}
})();"""
        page.runJavaScript(reinforce_js)

    # ---------- 事件回调 ----------

    def _on_page_load_finished(self, ok: bool):
        """页面加载完成的回调"""
        current_url = self.web_view.url().toString()
        if ok:
            self.config_panel.append_log(f"[页面] 加载完成: {current_url}")
            self.lbl_browser_status.setText("浏览器: 已就绪")
        else:
            self.config_panel.append_log(f"[页面] 加载可能未完全成功: {current_url}")

    # ---------- 窗口事件 ----------

    def closeEvent(self, event):
        """关闭窗口时停止线程、保存必要数据"""
        if self._auto_thread and self._auto_thread.is_running:
            self._auto_thread.stop()
            self._auto_thread.wait(5000)
        event.accept()
