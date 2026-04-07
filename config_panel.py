"""配置面板模块 - PyQt5 配置界面控件

提供用户可配置的界面元素：
- 游戏 URL 输入
- 模板图片路径配置（每个模板一行）
- 匹配阈值滑块/输入
- 点击坐标配置（auto_fight, event_option0/1/2）
- 保存/加载配置按钮
- 日志输出文本框
"""

import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QDoubleSpinBox, QSpinBox,
    QLabel, QScrollArea, QGroupBox, QFileDialog,
    QTextEdit, QSplitter, QFrame, QGridLayout, QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont


class TemplatePathEditor(QWidget):
    """模板路径编辑器 - 显示所有模板名称和对应的文件路径"""

    # 英文名 → 中文显示名映射
    LABEL_MAP = {
        "map_screen": "地图画面标识",
        "in_battle": "战斗界面标识",
        "victory": "胜利结算图标",
        "defeat": "失败结算图标",
        "node_yellow": "黄色节点图标",
        "node_red": "红色节点图标",
        "node_blue": "蓝色节点图标",
        "node_green": "绿色节点图标",
        "node_purple": "紫色节点图标",
    }

    path_changed = pyqtSignal(str, str)  # template_name, new_path

    def __init__(self, templates: dict = None, parent=None):
        super().__init__(parent)
        self._edits = {}  # name -> QLineEdit
        self._setup_ui(templates or {})

    def _setup_ui(self, templates: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        for name, default_path in sorted(templates.items()):
            row_layout = QHBoxLayout()
            label = QLabel(self.LABEL_MAP.get(name, name))
            label.setMinimumWidth(100)
            edit = QLineEdit(default_path)
            edit.setMinimumWidth(150)
            browse_btn = QPushButton("...")
            browse_btn.setMaximumWidth(30)

            row_layout.addWidget(label)
            row_layout.addWidget(edit)
            row_layout.addWidget(browse_btn)
            layout.addLayout(row_layout)

            self._edits[name] = edit

            # 浏览按钮事件
            btn_name = name
            browse_btn.clicked.connect(
                lambda checked, n=btn_name, e=edit: self._browse_file(n, e)
            )
            edit.textChanged.connect(
                lambda text, n=btn_name: self.path_changed.emit(n, text)
            )

        layout.addStretch()

    def _browse_file(self, name: str, edit: QLineEdit):
        """打开文件选择对话框"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"选择 {name} 模板图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)"
        )
        if file_path:
            # 尝试转为相对路径
            base_dir = os.getcwd()
            try:
                rel_path = os.path.relpath(file_path, base_dir)
                if not rel_path.startswith('..'):
                    file_path = rel_path
            except ValueError:
                pass
            edit.setText(file_path)

    def get_paths(self) -> dict:
        """获取当前所有模板路径"""
        return {name: edit.text().strip() for name, edit in self._edits.items()}

    def set_paths(self, templates: dict):
        """设置所有模板路径"""
        for name, path in templates.items():
            if name in self._edits:
                self._edits[name].setText(path)


class CoordinateEditor(QWidget):
    """固定点击坐标编辑器"""

    coords_changed = pyqtSignal(str, list)  # coord_name, [x, y]

    # 坐标名称 → 中文标签映射
    LABEL_MAP = {
        "auto_fight": "自动战斗按钮",
        "event_option0": "事件选项 (左)",
        "event_option1": "事件选项 (中)",
        "event_option2": "事件选项 (右)",
    }

    DEFAULT_COORDS = {
        "auto_fight": [640, 500],
        "event_option0": [400, 550],
        "event_option1": [640, 550],
        "event_option2": [880, 550],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._x_edits = {}
        self._y_edits = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        for name, (default_x, default_y) in self.DEFAULT_COORDS.items():
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            x_edit = QSpinBox()
            x_edit.setRange(0, 1280)
            x_edit.setValue(default_x)
            x_edit.setPrefix("X:")

            y_edit = QSpinBox()
            y_edit.setRange(0, 720)
            y_edit.setValue(default_y)
            y_edit.setPrefix("Y:")

            row_layout.addWidget(x_edit)
            row_layout.addWidget(y_edit)

            layout.addRow(self.LABEL_MAP.get(name, name), row)

            self._x_edits[name] = x_edit
            self._y_edits[name] = y_edit

            x_edit.valueChanged.connect(
                lambda val, n=name: self.coords_changed.emit(n, [
                    val, self._y_edits[n].value()
                ])
            )
            y_edit.valueChanged.connect(
                lambda val, n=name: self.coords_changed.emit(n, [
                    self._x_edits[n].value(), val
                ])
            )

    def get_coords(self) -> dict:
        """获取当前所有坐标"""
        return {
            name: [self._x_edits[name].value(), self._y_edits[name].value()]
            for name in self.DEFAULT_COORDS
        }

    def set_coords(self, coords: dict):
        """设置坐标值"""
        for name, (x, y) in coords.items():
            if name in self._x_edits:
                self._x_edits[name].setValue(int(x))
                self._y_edits[name].setValue(int(y))


class LogViewer(QTextEdit):
    """日志显示区域"""

    MAX_LINES = 2000  # 最大保留行数，防止内存膨胀

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 9))
        self.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                border-radius: 3px;
            }
        """)
        self._line_count = 0

    def append_log(self, message: str):
        """追加日志消息"""
        self.append(message)
        self._line_count += 1
        
        # 超过最大行数时清理旧内容
        if self._line_count > self.MAX_LINES:
            # 保留后半部分
            text = self.toPlainText()
            lines = text.split('\n')
            keep_lines = lines[self.MAX_LINES // 2:]
            self.clear()
            self.append('\n'.join(keep_lines))
            self._line_count = len(keep_lines)

    def clear_log(self):
        """清空日志"""
        self.clear()
        self._line_count = 0


class ConfigPanel(QWidget):
    """
    完整的配置面板
    
    布局：
    - 顶部：游戏 URL 输入 + 加载按钮
    - Tab 切换：
      - Tab1 "基本设置"：阈值、循环次数、间隔时间
      - Tab2 "模板路径"：各模板图片路径编辑器 + 浏览按钮
      - Tab3 "点击坐标"：固定坐标编辑
    - 底部：保存/加载配置按钮 + 清空日志
    - 最下方：日志显示区（跨整个底部）
    
    信号:
        config_changed: 无参数 - 任何配置项变更时触发
        start_requested: 无参数 - 用户点击启动
        stop_requested: 无参数 - 用户点击停止  
        pause_requested: 无参数 - 用户点击暂停
        url_changed: str -> URL 变更时触发
    """

    config_changed = pyqtSignal()
    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    coord_pick_toggled = pyqtSignal(bool)  # 坐标拾取模式切换
    url_changed = pyqtSignal(str)  # URL 变更时触发

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # ---- 控制按钮行 ----
        control_row = QHBoxLayout()
        
        self.btn_start = QPushButton("▶ 启动")
        self.btn_start.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 6px;")
        
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold; padding: 6px;")
        self.btn_stop.setEnabled(False)

        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setEnabled(False)

        self.lbl_status = QLabel("状态: 就绪")
        self.lbl_status.setStyleSheet("font-weight: bold;")

        control_row.addWidget(self.btn_start)
        control_row.addWidget(self.btn_stop)
        control_row.addWidget(self.btn_pause)
        control_row.addStretch()
        control_row.addWidget(self.lbl_status)

        # 坐标拾取按钮
        self.btn_coord_pick = QPushButton("🎯 拾取坐标")
        self.btn_coord_pick.setCheckable(True)
        self.btn_coord_pick.setToolTip("开启后点击浏览器区域获取坐标，再次点击关闭")
        control_row.addWidget(self.btn_coord_pick)

        main_layout.addLayout(control_row)

        # ---- URL 行 ----
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("游戏 URL:"))
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("https://example.com/game")
        self.btn_load_url = QPushButton("加载页面")
        self.btn_load_url.setDefault(True)
        url_row.addWidget(self.edit_url)
        url_row.addWidget(self.btn_load_url)
        main_layout.addLayout(url_row)

        # ---- Tab 面板 ----
        tabs = QTabWidget()

        # Tab 1: 基本设置
        tab_basic = QWidget()
        basic_form = QFormLayout(tab_basic)
        
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.1, 1.0)
        self.spin_threshold.setSingleStep(0.05)
        self.spin_threshold.setValue(0.7)
        self.spin_threshold.setDecimals(2)
        basic_form.addRow("匹配阈值:", self.spin_threshold)

        self.spin_interval = QDoubleSpinBox()
        self.spin_interval.setRange(0.1, 10.0)
        self.spin_interval.setSingleStep(0.1)
        self.spin_interval.setValue(0.5)
        self.spin_interval.setSuffix(" 秒")
        basic_form.addRow("截图间隔:", self.spin_interval)

        self.spin_max_loops = QSpinBox()
        self.spin_max_loops.setRange(0, 99999)
        self.spin_max_loops.setValue(0)
        self.spin_max_loops.setSpecialValueText("无限循环")
        basic_form.addRow("最大循环:", self.spin_max_loops)

        tabs.addTab(tab_basic, "基本设置")

        # Tab 2: 模板路径
        self.template_editor = TemplatePathEditor(
            templates={
                "map_screen": "templates/map_screen.png",
                "in_battle": "templates/in_battle.png",
                "victory": "templates/victory.png",
                "defeat": "templates/defeat.png",
                "node_yellow": "templates/node_yellow.png",
                "node_red": "templates/node_red.png",
                "node_blue": "templates/node_blue.png",
                "node_green": "templates/node_green.png",
                "node_purple": "templates/node_purple.png",
            }
        )
        scroll_templates = QScrollArea()
        scroll_templates.setWidgetResizable(True)
        scroll_templates.setWidget(self.template_editor)
        tabs.addTab(scroll_templates, "模板路径")

        # Tab 3: 点击坐标
        self.coord_editor = CoordinateEditor()
        scroll_coords = QScrollArea()
        scroll_coords.setWidgetResizable(True)
        scroll_coords.setWidget(self.coord_editor)
        tabs.addTab(scroll_coords, "点击坐标")

        main_layout.addWidget(tabs, stretch=1)

        # ---- 操作按钮行 ----
        action_row = QHBoxLayout()
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_load_config = QPushButton("📂 加载配置")
        self.btn_clear_log = QPushButton("🗑 清空日志")
        action_row.addWidget(self.btn_save)
        action_row.addWidget(self.btn_load_config)
        action_row.addStretch()
        action_row.addWidget(self.btn_clear_log)
        main_layout.addLayout(action_row)

        # ---- 日志区域 ----
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_viewer = LogViewer()
        self.log_viewer.setMinimumHeight(120)
        log_layout.addWidget(self.log_viewer)
        main_layout.addWidget(log_group, stretch=1)

        # 设置面板最小宽度
        self.setMinimumWidth(320)
        self.setMaximumWidth(420)

    def _connect_signals(self):
        """连接内部信号"""
        # 启动/停止/暂停按钮
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_stop.clicked.connect(self.stop_requested.emit)
        self.btn_pause.clicked.connect(self.pause_requested.emit)

        # 配置变更信号聚合
        self.edit_url.textChanged.connect(self.config_changed.emit)
        self.spin_threshold.valueChanged.connect(lambda v: self.config_changed.emit())
        self.spin_interval.valueChanged.connect(lambda v: self.config_changed.emit())
        self.spin_max_loops.valueChanged.connect(lambda v: self.config_changed.emit())
        self.template_editor.path_changed.connect(lambda n, p: self.config_changed.emit())
        self.coord_editor.coords_changed.connect(lambda n, c: self.config_changed.emit())

        # 保存/加载/清空
        self.btn_save.clicked.connect(self._on_save)
        self.btn_load_config.clicked.connect(self._on_load)
        self.btn_clear_log.clicked.connect(self.log_viewer.clear_log)

        # 坐标拾取按钮
        self.btn_coord_pick.toggled.connect(self.coord_pick_toggled.emit)

        # URL 变更
        self.edit_url.textChanged.connect(self.url_changed.emit)

    def _on_save(self):
        """保存配置到文件"""
        from config import Config
        cfg = Config()
        data = self.get_config_data()
        cfg.update_from_dict(data)
        if cfg.save():
            self.log_viewer.append_log("[配置] 已保存到 config.json")
        else:
            self.log_viewer.append_log("[配置] 保存失败")

    def _on_load(self):
        """从文件加载配置"""
        from config import Config
        cfg = Config()
        if cfg.load():
            self.set_config_data(cfg.to_dict())
            self.log_viewer.append_log("[配置] 已从 config.json 加载")
        else:
            self.log_viewer.append_log("[配置] 未找到或加载失败配置文件")

    def get_config_data(self) -> dict:
        """从界面收集当前所有配置数据为字典"""
        return {
            "url": self.edit_url.text().strip(),
            "threshold": self.spin_threshold.value(),
            "click_interval": self.spin_interval.value(),
            "max_loops": int(self.spin_max_loops.value()),
            "templates": self.template_editor.get_paths(),
            "fixed_clicks": self.coord_editor.get_coords(),
        }

    def set_config_data(self, data: dict):
        """将配置字典填充到界面"""
        if 'url' in data:
            self.edit_url.setText(data['url'])
        if 'threshold' in data:
            self.spin_threshold.setValue(float(data['threshold']))
        if 'click_interval' in data:
            self.spin_interval.setValue(float(data['click_interval']))
        if 'max_loops' in data:
            self.spin_max_loops.setValue(int(data['max_loops']))
        if 'templates' in data:
            self.template_editor.set_paths(data['templates'])
        if 'fixed_clicks' in data:
            self.coord_editor.set_coords(data['fixed_clicks'])

    def get_url(self) -> str:
        """返回当前 URL"""
        return self.edit_url.text().strip()

    def set_status_text(self, text: str):
        """更新状态标签文字"""
        self.lbl_status.setText(f"状态: {text}")

    def set_running_state(self, running: bool):
        """根据运行状态更新按钮可用性"""
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_pause.setEnabled(running)

    def append_log(self, message: str):
        """向日志区追加消息"""
        self.log_viewer.append_log(message)
