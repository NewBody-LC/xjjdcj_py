"""配置管理模块 - JSON 格式配置的加载、保存和默认值管理"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class GameConfig:
    """游戏自动化配置数据结构"""
    url: str = "https://example.com/game"
    threshold: float = 0.7
    click_interval: float = 0.5  # 截图间隔（秒）
    max_loops: int = 0  # 0 表示无限循环

    # 模板图片路径（相对于程序目录或绝对路径）
    templates: Dict[str, str] = field(default_factory=lambda: {
        "map_screen": "templates/map_screen.png",
        "in_battle": "templates/in_battle.png",
        "victory": "templates/victory.png",
        "defeat": "templates/defeat.png",
        "node_yellow": "templates/node_yellow.png",
        "node_red": "templates/node_red.png",
        "node_blue": "templates/node_blue.png",
        "node_green": "templates/node_green.png",
        "node_purple": "templates/node_purple.png",
    })

    # 固定点击坐标 [x, y]，基于 1280×720 窗口坐标系
    fixed_clicks: Dict[str, List[int]] = field(default_factory=lambda: {
        "auto_fight": [640, 500],
        "event_option0": [400, 550],
        "event_option1": [640, 550],
        "event_option2": [880, 550],
    })


class Config:
    """配置管理器：负责加载、保存配置到 JSON 文件"""

    DEFAULT_CONFIG_FILE = "config.json"

    def __init__(self, config_file: str = None):
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self.data = GameConfig()

    @property
    def base_dir(self) -> str:
        """返回配置文件所在目录（作为模板等资源的基准路径）"""
        return os.path.dirname(os.path.abspath(self.config_file))

    def resolve_path(self, path: str) -> str:
        """将相对路径转换为基于配置文件目录的绝对路径"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)

    def load(self) -> bool:
        """从 JSON 文件加载配置，成功返回 True，文件不存在返回 False（使用默认值）"""
        if not os.path.exists(self.config_file):
            return False
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self._apply_raw(raw)
            return True
        except (json.JSONDecodeError, IOError) as e:
            print(f"[Config] 加载配置失败: {e}")
            return False

    def save(self) -> bool:
        """将当前配置保存到 JSON 文件，成功返回 True"""
        try:
            raw = asdict(self.data)
            # 确保目录存在
            dir_name = os.path.dirname(os.path.abspath(self.config_file))
            os.makedirs(dir_name, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False, indent=4)
            return True
        except IOError as e:
            print(f"[Config] 保存配置失败: {e}")
            return False

    def _apply_raw(self, raw: dict):
        """将原始字典数据应用到 GameConfig"""
        for key, value in raw.items():
            if hasattr(self.data, key):
                setattr(self.data, key, value)

    def to_dict(self) -> dict:
        """导出为字典"""
        return asdict(self.data)

    def update_from_dict(self, raw: dict):
        """从字典更新配置"""
        self._apply_raw(raw)

    def reset_to_defaults(self):
        """重置为默认值"""
        self.data = GameConfig()
