"""模板匹配引擎 - 基于 OpenCV 的模板匹配封装

负责加载模板图片、执行匹配、返回匹配结果（坐标+置信度）
"""

import os
import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class MatchResult:
    """单次模板匹配结果"""
    template_name: str
    found: bool
    confidence: float  # 0.0 ~ 1.0
    position: Optional[Tuple[int, int]] = None  # 匹配中心点 (x, y)
    top_left: Optional[Tuple[int, int]] = None   # 左上角 (x, y)
    all_positions: List[Tuple[int, int, float]] = None  # 所有匹配位置 [(x,y,conf), ...]


class TemplateMatcher:
    """模板匹配管理器"""

    # OpenCV 模板匹配方法
    MATCH_METHOD = cv2.TM_CCOEFF_NORMED

    def __init__(self, threshold: float = 0.7):
        """
        Args:
            threshold: 匹配置信度阈值，低于此值视为未匹配到 (默认 0.7)
        """
        self.threshold = threshold
        self._templates: Dict[str, np.ndarray] = {}  # name -> cv2 image (BGR)
        self._template_sizes: Dict[str, Tuple[int, int]] = {}  # name -> (w, h)

    def load_template(self, name: str, path: str) -> bool:
        """加载一张模板图片
        
        Args:
            name: 模板名称标识符
            path: 图片文件路径（绝对或相对路径）
            
        Returns:
            加载成功返回 True
        """
        if not os.path.exists(path):
            print(f"[TemplateMatcher] 模板文件不存在: {path}")
            return False
        try:
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None:
                print(f"[TemplateMatcher] 无法读取图片: {path}")
                return False
            self._templates[name] = img
            self._template_sizes[name] = (img.shape[1], img.shape[0])  # (w, h)
            print(f"[TemplateMatcher] 加载模板 '{name}': {img.shape[1]}x{img.shape[0]} from {path}")
            return True
        except Exception as e:
            print(f"[TemplateMatcher] 加载模板失败 '{name}': {e}")
            return False

    def load_templates(self, templates: Dict[str, str], base_dir: str = "") -> int:
        """批量加载模板图片
        
        Args:
            templates: {name: path} 映射字典
            base_dir: 基础目录，用于解析相对路径
            
        Returns:
            成功加载数量
        """
        count = 0
        for name, path in templates.items():
            full_path = path if os.path.isabs(path) else os.path.join(base_dir, path)
            if self.load_template(name, full_path):
                count += 1
        print(f"[TemplateMatcher] 共加载 {count}/{len(templates)} 个模板")
        return count

    def is_loaded(self, name: str) -> bool:
        """检查指定模板是否已加载"""
        return name in self._templates and self._templates[name] is not None

    def match(self, screenshot: np.ndarray, template_name: str,
              threshold: float = None) -> MatchResult:
        """对单张模板进行匹配
        
        Args:
            screenshot: 截图图像 (BGR 格式 numpy 数组)
            template_name: 要匹配的模板名称
            threshold: 本次匹配的阈值，None 则使用实例默认值
            
        Returns:
            MatchResult 对象
        """
        thresh = threshold or self.threshold

        if template_name not in self._templates:
            return MatchResult(template_name=template_name, found=False, confidence=0.0)

        tpl = self._templates[template_name]
        sh, sw = screenshot.shape[:2]
        th, tw = tpl.shape[:2]

        # 模板比截图大时无法匹配
        if th > sh or tw > sw:
            return MatchResult(template_name=template_name, found=False, confidence=0.0)

        result = cv2.matchTemplate(screenshot, tpl, self.MATCH_METHOD)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= thresh:
            center_x = max_loc[0] + tw // 2
            center_y = max_loc[1] + th // 2
            return MatchResult(
                template_name=template_name,
                found=True,
                confidence=float(max_val),
                position=(center_x, center_y),
                top_left=max_loc,
            )
        else:
            return MatchResult(
                template_name=template_name,
                found=False,
                confidence=float(max_val),
            )

    def match_all(self, screenshot: np.ndarray, template_name: str,
                  threshold: float = None) -> MatchResult:
        """对单张模板进行多位置匹配（找出所有超过阈值的位置）
        
        用于节点图标等可能在画面中出现多次的模板。
        
        Args:
            screenshot: 截图图像
            template_name: 模板名称
            threshold: 阈值
            
        Returns:
            MatchResult，all_positions 包含所有匹配位置
        """
        thresh = threshold or self.threshold

        if template_name not in self._templates:
            return MatchResult(template_name=template_name, found=False, confidence=0.0,
                               all_positions=[])

        tpl = self._templates[template_name]
        sh, sw = screenshot.shape[:2]
        th, tw = tpl.shape[:2]

        if th > sh or tw > sw:
            return MatchResult(template_name=template_name, found=False, confidence=0.0,
                               all_positions=[])

        result = cv2.matchTemplate(screenshot, tpl, self.MATCH_METHOD)

        # 找出所有超过阈值的匹配位置（使用非极大值抑制避免重叠）
        locations = np.where(result >= thresh)
        positions = []

        for pt in zip(*locations[::-1]):  # 切换为 (x, y) 顺序
            conf = result[pt[1], pt[0]]
            center_x = pt[0] + tw // 2
            center_y = pt[1] + th // 2
            positions.append((center_x, center_y, float(conf)))

        # 简单的非极大值抑制：过滤掉距离太近的重复匹配
        filtered = self._nms(positions, min_distance=max(tw, th) // 2)

        best_conf = max((p[2] for p in filtered), default=0.0)
        best_pos = filtered[0][:2] if filtered else None

        return MatchResult(
            template_name=template_name,
            found=len(filtered) > 0,
            confidence=best_conf,
            position=best_pos,
            all_positions=[(x, y, c) for x, y, c in filtered],
        )

    @staticmethod
    def _nms(positions: List[Tuple[int, int, float]],
             min_distance: int = 10) -> List[Tuple[int, int, float]]:
        """非极大值抑制：移除彼此距离过近的匹配点，保留置信度最高的"""
        if not positions:
            return []
        
        # 按置信度降序排列
        sorted_pos = sorted(positions, key=lambda p: p[2], reverse=True)
        keep = []
        
        for pos in sorted_pos:
            # 检查与已保留点的最小距离
            too_close = False
            for kept in keep:
                dist = ((pos[0] - kept[0]) ** 2 + (pos[1] - kept[1]) ** 2) ** 0.5
                if dist < min_distance:
                    too_close = True
                    break
            if not too_close:
                keep.append(pos)
        
        return keep

    def match_all_templates(self, screenshot: np.ndarray,
                            names: List[str] = None) -> Dict[str, MatchResult]:
        """对所有已加载模板（或指定列表）执行匹配
        
        Args:
            screenshot: 截图图像
            names: 要匹配的模板名列表，None 表示全部
            
        Returns:
            {template_name: MatchResult} 字典
        """
        target_names = names or list(self._templates.keys())
        results = {}
        for name in target_names:
            results[name] = self.match(screenshot, name)
        return results

    @property
    def loaded_templates(self) -> List[str]:
        """返回已成功加载的模板名称列表"""
        return [name for name, img in self._templates.items() if img is not None]

    def reload_all(self, templates: Dict[str, str], base_dir: str = "") -> int:
        """清除并重新加载所有模板"""
        self._templates.clear()
        self._template_sizes.clear()
        return self.load_templates(templates, base_dir)


def qimage_to_cv2(qimage) -> np.ndarray:
    """将 PyQt5 QImage/ QPixmap 转换为 OpenCV BGR numpy 数组
    
    Args:
        qimage: QImage 或 QPixmap 对象
        
    Returns:
        OpenCV BGR 格式的 numpy 数组
    """
    from PyQt5.QtGui import QImage, QPixmap
    
    if isinstance(qimage, QPixmap):
        qimage = qimage.toImage()
    
    w, h = qimage.width(), qimage.height()
    
    # 处理不同格式
    ptr = qimage.bits()
    ptr.setsize(h * w * 4)
    arr = np.array(ptr).reshape(h, w, 4)  # BGRA 格式
    
    # 转为 BGR（丢弃 alpha 通道）
    bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    return bgr


def pixmap_to_cv2(pixmap) -> np.ndarray:
    """PyQt5 QPixmap → OpenCV BGR 数组的快捷方法"""
    return qimage_to_cv2(pixmap)
