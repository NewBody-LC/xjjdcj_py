"""游戏状态机 - 管理自动化循环中的状态转换和动作决策

状态流程:
  IDLE → DETECTING_MAP → ON_MAP → IN_BATTLE → BATTLE_RESULT → ON_MAP (循环)
"""

import math
import time
from enum import Enum, auto
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass


class State(Enum):
    """游戏自动化状态枚举（中文名称用于日志显示）"""
    IDLE = "空闲"               # 空闲/未启动
    DETECTING_MAP = "检测地图"      # 正在检测是否进入地图界面
    ON_MAP = "在地图上"             # 在地图上，需要选择节点
    IN_BATTLE = "战斗中"           # 战斗中，需点击自动战斗
    BATTLE_RESULT = "结算界面"     # 战斗结算（胜利/失败），需选择选项
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


class GameStateMachine:
    """
    基于有限状态机的游戏自动化控制器
    
    通过 update(screenshot_cv2) 方法驱动：
    1. 接收当前截图
    2. 用模板匹配判断当前画面内容
    3. 根据当前状态 + 匹配结果决定下一步动作
    4. 返回 (next_state, action) 元组
    """

    def __init__(self):
        self.current_state = State.IDLE
        self.previous_state: Optional[State] = None
        self.last_click_pos: Optional[Tuple[int, int]] = None  # 上次点击位置，用于计算最近节点
        self._clicked_positions = set()  # 本轮已点击过的位置集合，避免重复点击
        self.loop_count: int = 0  # 完成的循环次数
        self._state_entry_time: float = 0  # 进入当前状态的时间
        self._log_callback = None  # 日志回调函数

    def set_log_callback(self, callback):
        """设置日志回调函数 callback(message: str)"""
        self._log_callback = callback

    def _log(self, msg: str):
        """内部日志方法"""
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {msg}"
        print(full_msg)
        if self._log_callback:
            self._log_callback(full_msg)

    def reset(self):
        """重置状态机到初始状态"""
        self.current_state = State.IDLE
        self.previous_state = None
        self.last_click_pos = None
        self._clicked_positions.clear()
        self.loop_count = 0
        self._log("状态机已重置")

    def start(self):
        """启动状态机"""
        self.reset()
        self._transition_to(State.DETECTING_MAP)
        self._log("=== 自动化已启动 ===")

    def pause(self):
        """暂停状态机"""
        if self.current_state not in (State.PAUSED, State.STOPPED, State.IDLE):
            self._transition_to(State.PAUSED)
            self._log("=== 自动化已暂停 ===")

    def resume(self):
        """恢复状态机"""
        if self.current_state == State.PAUSED:
            self._transition_to(State.DETECTING_MAP)
            self._log("=== 自动化已恢复 ===")

    def stop(self):
        """停止状态机"""
        self._transition_to(State.STOPPED)
        self._log("=== 自动化已停止 ===")

    def _transition_to(self, new_state: State):
        """执行状态转换"""
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
        """
        状态机主更新方法
        
        Args:
            screenshot: 当前截图 (OpenCV BGR numpy array)，可选（未来扩展用）
            match_results: 预先完成的模板匹配结果字典 {name: MatchResult}
            config: 配置信息（阈值、坐标等）
            
        Returns:
            (new_state, action) 元组
        """
        cfg = config or {}
        threshold = cfg.get('threshold', 0.7)
        fixed_clicks = cfg.get('fixed_clicks', {})

        # 根据当前状态分发处理
        handler = {
            State.DETECTING_MAP: self._handle_detecting_map,
            State.ON_MAP: self._handle_on_map,
            State.IN_BATTLE: self._handle_in_battle,
            State.BATTLE_RESULT: self._handle_battle_result,
            State.PAUSED: self._handle_paused,
            State.IDLE: self._handle_idle,
            State.STOPPED: self._handle_stopped,
        }.get(self.current_state, self._handle_idle)

        return handler(match_results or {}, fixed_clicks, threshold)

    # ---------- 各状态处理函数 ----------

    def _handle_detecting_map(self, match_results, fixed_clicks, threshold):
        """等待进入地图界面"""
        map_result = match_results.get("map_screen")
        
        if map_result and map_result.found:
            self.loop_count += 1
            self._log(f"=== 第 {self.loop_count} 轮循环 ===")
            self._clicked_positions.clear()  # 新一轮循环，清空已点击记录
            self._transition_to(State.ON_MAP)
            return self._handle_on_map(match_results, fixed_clicks, threshold)
        
        return self.current_state, Action(Action.WAIT, description="等待进入地图界面...")

    def _handle_on_map(self, match_results, fixed_clicks, threshold):
        """在地图上：查找并点击可探索节点
        
        节点选择策略：
        1. 先按 X 坐标升序（从左到右）
        2. X 相同则按 Y 坐标升序（从上到下）
        3. 每次只点击一个节点，下次循环继续下一个
        4. 已点击过的节点不会重复点击
        """
        # 所有节点颜色
        node_colors = ["node_yellow", "node_red", "node_blue", "node_green", "node_purple"]

        # 收集所有找到的节点
        all_candidates = []  # [(color_name, x, y, confidence), ...]

        for color in node_colors:
            result = match_results.get(color)
            if result and result.found and result.all_positions and len(result.all_positions) > 0:
                for pos in result.all_positions:  # pos = (x, y, conf)
                    x, y, conf = pos
                    all_candidates.append((color, x, y, conf))

        if not all_candidates:
            # 没有找到任何节点，检查是否已进入战斗/结算
            battle = match_results.get("in_battle")
            if battle and battle.found:
                self._transition_to(State.IN_BATTLE)
                return self._handle_in_battle(match_results, fixed_clicks, threshold)

            victory = match_results.get("victory")
            defeat = match_results.get("defeat")
            if (victory and victory.found) or (defeat and defeat.found):
                self._transition_to(State.BATTLE_RESULT)
                return self._handle_battle_result(match_results, fixed_clicks, threshold)

            return self.current_state, Action(Action.WAIT, description="在地图上，未找到可点击节点")

        # 排序：X 升序（从左到右）优先，X 相同则 Y 升序（从上到下）
        def sort_key(item):
            _, x, y, _ = item
            return (x, y)

        all_candidates.sort(key=sort_key)

        # 选择排序后的第一个节点（跳过已点击的位置）
        best_color, best_x, best_y, best_conf = None, None, None, None
        for candidate in all_candidates:
            color, x, y, conf = candidate
            pos_key = (x // 20, y // 20)  # 粗粒度去重（允许一定误差）
            if pos_key not in self._clicked_positions:
                best_color, best_x, best_y, best_conf = color, x, y, conf
                break

        if best_x is None:
            # 所有节点都已点击过，重置并重新开始
            self._clicked_positions.clear()
            self._log("所有已知节点已点击，重置节点列表")
            return self.current_state, Action(Action.WAIT, description="等待新周期...")
        
        self.last_click_pos = (best_x, best_y)
        # 记录已点击位置（粗粒度去重）
        self._clicked_positions.add((best_x // 20, best_y // 20))

        # 检查是否同时匹配到了战斗界面
        battle_result = match_results.get("in_battle")
        if battle_result and battle_result.found:
            self._transition_to(State.IN_BATTLE)

        action = Action(
            Action.CLICK_NEAREST_NODE,
            target=best_color,
            position=(best_x, best_y),
            description=f"点击 [{best_color}] 节点 ({best_x},{best_y}) 置信度={best_conf:.0%}"
        )
        self._log(action.description)
        return self.current_state, action

    def _handle_in_battle(self, match_results, fixed_clicks, threshold):
        """战斗中：点击自动战斗按钮，然后等待结算"""
        # 先检查是否已经出现结算画面（可能战斗很快结束）
        victory = match_results.get("victory")
        defeat = match_results.get("defeat")
        if (victory and victory.found) or (defeat and defeat.found):
            self._transition_to(State.BATTLE_RESULT)
            return self._handle_battle_result(match_results, fixed_clicks, threshold)

        # 还在战斗中，点击自动战斗按钮
        pos = fixed_clicks.get("auto_fight", [640, 500])
        action = Action(
            Action.CLICK_COORD,
            target="auto_fight",
            position=tuple(pos),
            description=f"点击 [自动战斗] 按钮 ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)
        return self.current_state, action

    def _handle_battle_result(self, match_results, fixed_clicks, threshold):
        """战斗结算：选择一个选项（三选一）"""
        victory = match_results.get("victory")
        defeat = match_results.get("defeat")

        result_type = "胜利" if (victory and victory.found) else (
            "失败" if (defeat and defeat.found) else "未知"
        )

        # 默认选择中间选项 option1
        option_key = "event_option1"
        pos = fixed_clicks.get(option_key, [640, 550])

        action = Action(
            Action.CLICK_COORD,
            target=option_key,
            position=tuple(pos),
            description=f"战斗{result_type} - 选择选项 ({pos[0]}, {pos[1]})"
        )
        self._log(action.description)

        # 选择后回到地图检测状态
        self._transition_to(State.DETECTING_MAP)
        return State.DETECTING_MAP, action

    def _handle_paused(self, match_results, fixed_clicks, threshold):
        """暂停状态：不做任何操作"""
        return State.PAUSED, Action(Action.NONE, description="已暂停")

    def _handle_idle(self, match_results, fixed_clicks, threshold):
        """空闲状态"""
        return State.IDLE, Action(Action.NONE, description="空闲")

    def _handle_stopped(self, match_results, fixed_clicks, threshold):
        """停止状态"""
        return State.STOPPED, Action(Action.NONE, description="已停止")

    # ---------- 辅助方法 ----------

    @staticmethod
    def _find_nearest_position(positions: List[Tuple[int, int, float]],
                               reference: Optional[Tuple[int, int]]) -> Optional[Tuple[int, int, float]]:
        """
        从多个候选位置中找出距离参考点最近的一个
        
        Args:
            positions: 候选位置列表 [(x, y, confidence), ...]
            reference: 参考点 (x, y)，None 则使用画面中心
            
        Returns:
            最近的位置元组 (x, y, confidence)，无候选返回 None
        """
        if not positions:
            return None

        if reference is None:
            # 没有参考点时选择置信度最高的
            return max(positions, key=lambda p: p[2])

        min_dist = float('inf')
        nearest = None
        for pos in positions:
            dist = math.sqrt((pos[0] - reference[0]) ** 2 + (pos[1] - reference[1]) ** 2)
            if dist < min_dist:
                min_dist = dist
                nearest = pos

        return nearest

    @property
    def state_name(self) -> str:
        """返回当前状态的字符串名称"""
        return self.current_state.name if self.current_state else "UNKNOWN"

    @property
    def is_running(self) -> bool:
        """状态机是否正在运行（非停止/暂停/空闲）"""
        return self.current_state in (
            State.DETECTING_MAP, State.ON_MAP,
            State.IN_BATTLE, State.BATTLE_RESULT
        )
