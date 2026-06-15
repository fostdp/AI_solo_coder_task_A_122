"""
CSMA-CA 退避管理器 - 每个 LoRa 节点 (网关) 一个实例
防止消息碰撞: 按 tent_id 分配 SF + 随机退避 + 相位抖动
"""
import math
import random
import time
from typing import Optional

from shared.config_loader import get_lora_config


class LoRaBackoff:
    """
    LoRa CSMA/CA + BEB (Binary Exponential Backoff) 退避管理器

    - 按节点 ID 分配扩频因子 (SF7~SF12), 正交信道无冲突
    - 发送前随机退避 (Uniform[0, window])
    - 失败退避窗口 ×2, 成功 ×0.5 恢复
    - 相位抖动: 打散周期上报的时间重合点
    """

    def __init__(
        self,
        node_id: int,
        seed: Optional[int] = None,
        config: Optional[dict] = None,
    ):
        cfg = config or get_lora_config()
        self.node_id = node_id
        self.sf_list = cfg.get("spreading_factors", [7, 8, 9, 10, 11, 12])
        self.backoff_init_ms = cfg.get("backoff_init_ms", 200)
        self.backoff_max_ms = cfg.get("backoff_max_ms", 8000)
        self.retry_max = cfg.get("retry_max", 3)

        self.spreading_factor = self.sf_list[(node_id - 1) % len(self.sf_list)]
        self.current_window_ms = float(self.backoff_init_ms)

        # 独立随机数生成器, 不影响全局 random, 且可复现
        self._rng = random.Random(seed if seed is not None else node_id * 1000)

    def _phase_jitter_seconds(self) -> float:
        """按节点 ID 计算相位抖动 (固定偏移), 打散周期上报重合点"""
        phase = (self.node_id * 37.0) % 360.0
        return (phase / 360.0) * (self.backoff_init_ms / 2) / 1000.0

    def acquire_channel(self, congestion_level: float = 0.0) -> float:
        """
        模拟信道接入, 返回需要等待的秒数
        congestion_level: 0~1, 1 表示极度拥堵, 自动扩大退避窗口
        """
        window = self.current_window_ms * (1.0 + congestion_level * 3.0)
        window = min(window, self.backoff_max_ms)
        backoff_ms = self._rng.uniform(0, window)
        jitter = self._phase_jitter_seconds()
        return backoff_ms / 1000.0 + jitter

    def report_result(self, success: bool):
        """BEB: 成功窗口减半, 失败加倍"""
        if success:
            self.current_window_ms = max(
                float(self.backoff_init_ms),
                self.current_window_ms * 0.5,
            )
        else:
            self.current_window_ms = min(
                float(self.backoff_max_ms),
                self.current_window_ms * 2.0,
            )

    def simulate_collision_probability(self, concurrent_nodes: int) -> float:
        """
        估算碰撞概率 (纯 ALOHA + SF 正交化)
        P(collision) ≈ 1 - e^(-2G), 其中 G = 每信道归一化负载
        """
        channels = len(self.sf_list)
        per_channel_load = concurrent_nodes / channels
        if per_channel_load <= 0:
            return 0.0
        per_channel_success = math.exp(-2 * per_channel_load)
        return 1.0 - max(0.0, min(1.0, per_channel_success))

    # === 便捷方法: 执行带退避 + 重试的发送 ===
    async def send_with_backoff(self, send_fn, congestion: float = 0.0) -> bool:
        """
        带退避重试的发送
        send_fn: async function, 返回 True/False
        """
        for attempt in range(self.retry_max):
            delay = self.acquire_channel(congestion + attempt * 0.2)
            await self._async_sleep(delay)
            ok = await send_fn()
            self.report_result(ok)
            if ok:
                return True
        return False

    @staticmethod
    async def _async_sleep(seconds: float):
        import asyncio
        await asyncio.sleep(seconds)

    def send_with_backoff_sync(self, send_fn, congestion: float = 0.0) -> bool:
        """同步版本 (用于测试)"""
        for attempt in range(self.retry_max):
            delay = self.acquire_channel(congestion + attempt * 0.2)
            time.sleep(delay)
            ok = send_fn()
            self.report_result(ok)
            if ok:
                return True
        return False
