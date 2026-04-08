"""游戏状态机 - 管理自动化循环中的状态转换和动作决策

状态流程:
  IDLE → DETECTING_MAP (检测当前界面)
    → NEXT_LEVEL (下一关)     ← 最高优先，所有节点点完时触发
    → NODE_CHALLENGE (节点挑战)  ← 点击挑战按钮位置
    → SHOP_POPUP (商城弹窗)      ← 点击关闭按钮
    → EVENT_SELECT (事件选择)    ← 选择事件选项
    → CAPTAIN_SELECT (队长选择)   ← 点击队长坐标
    → EQUIPMENT_SELECT (装备选择) ← 点击装备坐标
    → ON_MAP (在地图上)          ← 选择节点
    → IN_BATTLE (战斗中)         ← 不点击，只等待结算
    → BATTLE_RESULT (结算界面)   ← 点击结算确认
"""

import math
import time
from enum import Enum, auto
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass


class State(Enum):
    """游戏自动化状态枚举（中文名称用于日志显示）"""
    IDLE = "空闲"               # 空闲/未启动
    DETECTING_MAP = "检测地图"      # 正在检测当前界面状态（每帧都重新判断）
    ON_MAP = "在地图上"             # 在地图上，需要选择节点
    NEXT_LEVEL = "下一关"           # 所有节点已探索完，点击下一关进入新关卡
    NODE_CHALLENGE = "节点挑战"     # 节点挑战界面（点击挑战按钮位置）
    SHOP_POPUP = "商城弹窗"         # 商城弹出窗口（点击关闭按钮）
    EVENT_SELECT = "事件选择"       # 事件选择界面（选选项）
    CAPTAIN_SELECT = "队长选择"     # 队长选择界面（点击队长坐标）
    EQUIPMENT_SELECT = "装备选择"   # 装备选择界面（点击装备坐标）
    IN_BATTLE = "战斗中"           # 战斗中（不点击，只等待结算）
    BATTLE_RESULT = "结算界面"     # 战斗结算（胜利/失败），点击结算确认
    PAUSED = "已暂停"             # 已暂停
    STOPPED = "已停止"            # 已停止


@dataclass
class Action:
    """状态机输出的动作指令"""
    action_type: str  # 动作类型
    target: Optional[str] = None   # 目标（坐标名、模板名等）
    position: Optional[Tuple[int, int]] = None  # 点击位置 (x, y)
    positions: Optional[List[Tuple[int, int]]] = None  # 多个候选位置
    description: str = ""          # 人类可读描述

    # 动作类型常量
    CLICK_COORD = "click_coord"        # 按固定坐标点击
    CLICK_TEMPLATE = "click_template"  # 点击模板匹配到的位置
    CLICK_NEAREST_NODE = "click_nearest_node"  # 点击最近节点
    WAIT = "wait"                      # 等待（不做操作）
    NONE = "none"                      # 无动作


# 检测优先级（从高到低）：每轮循环先检查高优先级的状态
DETECTION_PRIORITY = [
    ("next_level",       State.NEXT_LEVEL),        # 下一关 — 最高优先
    ("node_challenge",   State.NODE_CHALLENGE),    # 节点挑战
    ("shop_popup",       State.SHOP_POPUP),        # 商城弹窗
    ("event_select",     State.EVENT_SELECT),      # 事件选择
    ("captain_select",   State.CAPTAIN_SELECT),    # 队长选择
    ("equipment_select", State.EQUIPMENT_SELECT),  # 装备选择
    ("map_screen",       State.ON_MAP),            # 在地图上
    ("in_battle",        State.IN_BATTLE),         # 战斗中（不点击）
    ("victory",          State.BATTLE_RESULT),     # 胜利结算
    ("defeat",           State.BATTLE_RESULT),     # 失败结算
]


class GameStateMachine:
    """
    基于有限状态机的游戏自动化控制器
    
    通过 update(screenshot_cv2) 方法驱动：
    1. 接收当前截图
    2. 用模板匹配判断当前画面内容
    3. 根据当前状态 + 匹配结果决定下一步动作
    4. 返回 (next_state, action) 元组
    
    检测策略：每帧按优先级依次检查所有状态模板，
    匹配到最高优先级的状态即执行对应处理。
    """

    def __init__(self):
        self.current_state = State.IDLE
        self.previous_state: Optional[State] = None
        self.last_click_pos: Optional[Tuple[int, int]] = None
        self._clicked_positions = set()  # 本轮已点击过的位置集合
        self.loop_count: int = 0
        self._state_entry_time: float = 0
        self._log_callback = None

    def set_log_callback(self, callback):
        """设置日志回调函数 callback(message: str)"""
        self._log_callback = callback

    def _log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {msg}"
        print(full_msg)
        if self._log_callback:
            self._log_callback(full_msg)

    def reset(self):
        self.current_state = State.IDLE
        self.previous_state = None
        self.last_click_pos = None
        self._clicked_positions.clear()
        self.loop_count = 0
        self._log("状态机已重置")

    def start(self):
        self.reset()
        self._transition_to(State.DETECTING_MAP)
        self._log("=== 自动化已启动 ===")

    def pause(self):
        if self.current_state not in (State.PAUSED, State.STOPPED, State.IDLE):
            self._transition_to(State.PAUSED)
            self._log("=== 自动化已暂停 ===")

    def resume(self):
        if self.current_state == State.PAUSED:
            self._transition_to(State.DETECTING_MAP)
            self._log("=== 自动化已恢复 ===")

    def stop(self):
        self._transition_to(State.STOPPED)
        self._log("=== 自动化已停止 ===")

    def _transition_to(self, new_state: State):
        old_state = self.current_state
        self.previous_state = old_state
        self.current_state = new_state
        self._state_entry_time = time.time()
        if old_state != new_state:
            self._log(f"状态: {old_state.value} → {new_state.value}")

    def update(self,
               screenshot=None,
               match_results: Dict[str, Any] = None,
               config: Dict[str, Any] = None) -> Tuple[State, Action]:
        cfg = config or {}
        threshold = cfg.get('threshold', 0.7)
        fixed_clicks = cfg.get('fixed_clicks', {})

        handler = {
            State.DETECTING_MAP: self._handle_detecting_map,
            State.ON_MAP: self._handle_on_map,
            State.NEXT_LEVEL: self._handle_next_level,
            State.NODE_CHALLENGE: self._handle_node_challenge,
            State.SHOP_POPUP: self._handle_shop_popup,
            State.EVENT_SELECT: self._handle_event_select,
            State.CAPTAIN_SELECT: self._handle_captain_select,
            State.EQUIPMENT_SELECT: self._handle_equipment_select,
            State.IN_BATTLE: self._handle_in_battle,
            State.BATTLE_RESULT: self._handle_battle_result,
            State.PAUSED: self._handle_paused,
            State.IDLE: self._handle_idle,
            State.STOPPED: self._handle_stopped,
        }.get(self.current_state, self._handle_idle)

        return handler(match_results or {}, fixed_clicks, threshold)

    # ---------- 核心检测逻辑（带优先级）----------

    def _detect_current_state(self, match_results, threshold):
        """
        按优先级检测当前匹配到的最高优先级状态
        
        Returns:
            (state_name, result) 或 (None, None) 如果没有匹配到任何状态
        """
        for template_key, target_state in DETECTION_PRIORITY:
            result = match_results.get(template_key)
            if result and result.found:
                return target_state, result
        return None, None

    # ---------- 各状态处理函数 ----------

    def _handle_detecting_map(self, match_results, fixed_clicks, threshold):
        """核心检测入口：每帧按优先级检测所有状态"""
        detected_state, result = self._detect_current_state(match_results, threshold)

        if detected_state is None:
            return self.current_state, Action(Action.WAIT, description="未检测到任何已知状态")

        # 根据检测结果跳转到对应处理
        if detected_state == State.ON_MAP:
            # 进入地图时计数一轮新循环
            if self.current_state != State.ON_MAP:
                self.loop_count += 1
                self._log(f"=== 第 {self.loop_count} 轮循环 ===")
                self._clicked_positions.clear()
            self._transition_to(State.ON_MAP)
            return self._handle_on_map(match_results, fixed_clicks, threshold)

        # 其他状态直接转换并处理
        self._transition_to(detected_state)
        handler = {
            State.NEXT_LEVEL: self._handle_next_level,
            State.NODE_CHALLENGE: self._handle_node_challenge,
            State.SHOP_POPUP: self._handle_shop_popup,
            State.EVENT_SELECT: self._handle_event_select,
            State.CAPTAIN_SELECT: self._handle_captain_select,
            State.EQUIPMENT_SELECT: self._handle_equipment_select,
            State.IN_BATTLE: self._handle_in_battle,
            State.BATTLE_RESULT: self._handle_battle_result,
        }.get(detected_state, lambda *a: (detected_state, Action(Action.NONE)))

        return handler(match_results, fixed_clicks, threshold)

    def _handle_on_map(self, match_results, fixed_clicks, threshold):
        """在地图上：查找并点击可探索节点（X升序优先，Y升序次之）"""
        node_colors = ["node_yellow", "node_red", "node_blue", "node_green", "node_purple"]

        all_candidates = []
        for color in node_colors:
            result = match_results.get(color)
            if result and result.found and result.all_positions and len(result.all_positions) > 0:
                for pos in result.all_positions:
                    x, y, conf = pos
                    all_candidates.append((color, x, y, conf))

        if not all_candidates:
            # 地图上没有节点了，回到检测状态（可能需要点下一关）
            self._transition_to(State.DETECTING_MAP)
            return State.DETECTING_MAP, Action(Action.WAIT, description="地图上无节点，等待检测...")

        # 排序：X 升序（从左到右），X 相同则 Y 升序（从上到下）
        all_candidates.sort(key=lambda item: (item[1], item[2]))

        # 选第一个未点击的节点
        best_color, best_x, best_y, best_conf = None, None, None, None
        for candidate in all_candidates:
            color, x, y, conf = candidate
            pos_key = (x // 20, y // 20)
            if pos_key not in self._clicked_positions:
                best_color, best_x, best_y, best_conf = color, x, y, conf
                break

        if best_x is None:
            # 所有节点都点过了，清空记录让系统去检测下一关
            self._clicked_positions.clear()
            self._transition_to(State.DETECTING_MAP)
            return State.DETECTING_MAP, Action(Action.WAIT, description="所有节点已点过，检测下一关...")

        self.last_click_pos = (best_x, best_y)
        self._clicked_positions.add((best_x // 20, best_y // 20))

        action = Action(
            Action.CLICK_NEAREST_NODE,
            target=best_color,
            position=(best_x, best_y),
            description=f"点击 [{best_color}] 节点 ({best_x},{best_y}) 置信度={best_conf:.0%}"
        )
        self._log(action.description)
        return self.current_state, action

    def _handle_next_level(self, match_results, fixed_clicks, threshold):
        """下一关：点击下一关按钮/坐标"""
        pos = fixed_clicks.get("next_level", [640, 400])
        action = Action(
            Action.CLICK_COORD,
            target="next_level",
            position=tuple(pos),
            description=f"点击 [下一关] ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_node_challenge(self, match_results, fixed_clicks, threshold):
        """节点挑战：点击挑战按钮位置"""
        pos = fixed_clicks.get("challenge_btn", [640, 400])
        action = Action(
            Action.CLICK_COORD,
            target="challenge_btn",
            position=tuple(pos),
            description=f"点击 [挑战按钮] ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_shop_popup(self, match_results, fixed_clicks, threshold):
        """商城弹窗：点击关闭按钮"""
        pos = fixed_clicks.get("shop_close", [1200, 50])
        action = Action(
            Action.CLICK_COORD,
            target="shop_close",
            position=tuple(pos),
            description=f"点击 [关闭商城] ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_event_select(self, match_results, fixed_clicks, threshold):
        """事件选择：默认选中间选项"""
        option_key = "event_option1"
        pos = fixed_clicks.get(option_key, [640, 550])
        action = Action(
            Action.CLICK_COORD,
            target=option_key,
            position=tuple(pos),
            description=f"点击 [事件选项] ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_captain_select(self, match_results, fixed_clicks, threshold):
        """队长选择：点击队长坐标"""
        pos = fixed_clicks.get("captain_pos", [640, 400])
        action = Action(
            Action.CLICK_COORD,
            target="captain_pos",
            position=tuple(pos),
            description=f"点击 [队长选择] ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_equipment_select(self, match_results, fixed_clicks, threshold):
        """装备选择：点击装备坐标"""
        pos = fixed_clicks.get("equipment_pos", [640, 400])
        action = Action(
            Action.CLICK_COORD,
            target="equipment_pos",
            position=tuple(pos),
            description=f"点击 [装备选择] ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_in_battle(self, match_results, fixed_clicks, threshold):
        """战斗中：不点击任何按钮，只等待结算出现"""
        victory = match_results.get("victory")
        defeat = match_results.get("defeat")
        if (victory and victory.found) or (defeat and defeat.found):
            self._transition_to(State.BATTLE_RESULT)
            return self._handle_battle_result(match_results, fixed_clicks, threshold)

        return self.current_state, Action(Action.WAIT, description="战斗中，等待结算...")

    def _handle_battle_result(self, match_results, fixed_clicks, threshold):
        """战斗结算：点击结算确认坐标（胜利/失败通用）"""
        victory = match_results.get("victory")
        defeat = match_results.get("defeat")
        result_type = "胜利" if (victory and victory.found) else (
            "失败" if (defeat and defeat.found) else "未知"
        )

        pos = fixed_clicks.get("battle_result", [640, 500])
        action = Action(
            Action.CLICK_COORD,
            target="battle_result",
            position=tuple(pos),
            description=f"战斗{result_type} - 确认结算 ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_paused(self, match_results, fixed_clicks, threshold):
        return State.PAUSED, Action(Action.NONE, description="已暂停")

    def _handle_idle(self, match_results, fixed_clicks, threshold):
        return State.IDLE, Action(Action.NONE, description="空闲")

    def _handle_stopped(self, match_results, fixed_clicks, threshold):
        return State.STOPPED, Action(Action.NONE, description="已停止")

    @property
    def state_name(self) -> str:
        return self.current_state.name if self.current_state else "UNKNOWN"

    @property
    def is_running(self) -> bool:
        return self.current_state in (
            State.DETECTING_MAP, State.ON_MAP,
            State.NEXT_LEVEL, State.NODE_CHALLENGE,
            State.SHOP_POPUP, State.EVENT_SELECT,
            State.CAPTAIN_SELECT, State.EQUIPMENT_SELECT,
            State.IN_BATTLE, State.BATTLE_RESULT
        )
