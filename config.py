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
    # 界面状态模板（单次匹配，按优先级排列）
    templates: Dict[str, str] = field(default_factory=lambda: {
        "next_level":       "templates/next_level.png",      # 下一关（最高优先）
        "node_challenge":   "templates/node_challenge.png",  # 节点挑战状态
        "shop_popup":       "templates/shop_popup.png",      # 商城弹窗状态
        "event_select":     "templates/event_select.png",    # 事件选择状态
        "captain_select":   "templates/captain_select.png",  # 队长选择状态
        "equipment_select": "templates/equipment_select.png",# 装备选择状态
        "map_screen":       "templates/map_screen.png",      # 地图界面
        "in_battle":        "templates/in_battle.png",       # 战斗中界面
        "victory":          "templates/victory.png",         # 胜利结算
        "defeat":           "templates/defeat.png",          # 失败结算
        # 节点颜色模板（多次匹配）
        "node_yellow":      "templates/node_yellow.png",
        "node_red":         "templates/node_red.png",
        "node_blue":        "templates/node_blue.png",
        "node_green":       "templates/node_green.png",
        "node_purple":      "templates/node_purple.png",
    })

    # 固定点击坐标 [x, y]，基于 1280×720 窗口坐标系
    fixed_clicks: Dict[str, List[int]] = field(default_factory=lambda: {
        # 功能按钮坐标
        "next_level":     [640, 400],    # 下一关按钮
        "challenge_btn":  [640, 400],    # 挑战按钮（节点挑战时点击）
        "shop_close":     [1200, 50],    # 商城关闭按钮
        "battle_result":  [640, 500],    # 战斗结算确认（胜利/失败通用）
        "captain_pos":    [640, 400],    # 队长选择位置
        "equipment_pos":  [640, 400],    # 装备选择位置
        # 事件选项（三选一）
        "event_option0":  [400, 550],    # 事件选项左
        "event_option1":  [640, 550],    # 事件选项中
        "event_option2":  [880, 550],    # 事件选项右
        # 已弃用（保留兼容性）
        "auto_fight":     [640, 500],    # 自动战斗（已弃用，战斗不再点击）
    })


class Config:
    """配置管理器：负责加载、保存配置到 JSON 文件"""

    DEFAULT_CONFIG_FILE = "config.json"

    def __init__(self, config_file: str = None):
        self.config_file = config_file or self.DEFAULT_CONFIG_FILE
        self.data = GameConfig()

    @property
    def base_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.config_file))

    def resolve_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)

    def load(self) -> bool:
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
        try:
            raw = asdict(self.data)
            dir_name = os.path.dirname(os.path.abspath(self.config_file))
            os.makedirs(dir_name, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False, indent=4)
            return True
        except IOError as e:
            print(f"[Config] 保存配置失败: {e}")
            return False

    def _apply_raw(self, raw: dict):
        for key, value in raw.items():
            if hasattr(self.data, key):
                setattr(self.data, key, value)

    def to_dict(self) -> dict:
        return asdict(self.data)

    def update_from_dict(self, raw: dict):
        self._apply_raw(raw)

    def reset_to_defaults(self):
        self.data = GameConfig()
