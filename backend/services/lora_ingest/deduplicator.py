"""
消息去重器 - 防止 LoRa 重传导致重复数据入库
基于 sliding window + set 的轻量去重, 窗口时间可配置
"""
import time
from collections import defaultdict, deque
from typing import Optional

from shared.config_loader import get_lora_config


class MessageDeduplicator:
    """
    滑动窗口去重器
    - key: tent_id + sensor_type + sensor_id + timestamp (30min 粒度)
    - window: 配置的 dedup_window_seconds
    - 自动清理过期条目
    """

    def __init__(self, window_seconds: Optional[int] = None):
        cfg = get_lora_config()
        self.window_seconds = window_seconds or cfg.get("dedup_window_seconds", 60)

        # 按 tent_id 分桶, 加速清理
        self._buckets: dict[str, float] = {}  # key -> first_seen_ts
        self._timeline: deque[tuple] = deque()  # (expire_ts, key) 用于过期清理
        self._stats = {"total": 0, "duplicates": 0, "dropped": 0}

    @staticmethod
    def _make_key(tent_id: int, sensor_type: str, sensor_id: int, timestamp: float) -> str:
        # timestamp 按整分钟对齐, 避免毫秒级差异导致重复
        ts_aligned = int(timestamp // 60) * 60
        return f"{tent_id}:{sensor_type}:{sensor_id}:{ts_aligned}"

    def is_duplicate(
        self,
        tent_id: int,
        sensor_type: str,
        sensor_id: int,
        timestamp: float,
    ) -> bool:
        """
        检查是否重复消息
        返回 True = 重复 (应丢弃)
        返回 False = 新消息 (应处理)
        """
        key = self._make_key(tent_id, sensor_type, sensor_id, timestamp)
        now = time.time()
        self._stats["total"] += 1
        self._cleanup(now)

        if key in self._buckets:
            self._stats["duplicates"] += 1
            return True

        self._buckets[key] = now
        expire_ts = now + self.window_seconds
        self._timeline.append((expire_ts, key))
        return False

    def is_aw_duplicate(
        self,
        tent_id: int,
        drug_name: str,
        meter_id: int,
        timestamp: float,
    ) -> bool:
        """水分活度数据去重"""
        return self.is_duplicate(tent_id, f"aw:{drug_name}", meter_id, timestamp)

    def _cleanup(self, now: float):
        """清理过期条目"""
        while self._timeline and self._timeline[0][0] <= now:
            expire_ts, key = self._timeline.popleft()
            if key in self._buckets:
                del self._buckets[key]
                self._stats["dropped"] += 1

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def reset(self):
        self._buckets.clear()
        self._timeline.clear()
        self._stats = {"total": 0, "duplicates": 0, "dropped": 0}
