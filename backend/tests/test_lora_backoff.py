"""
LoRa Backoff 退避算法测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import math
from services.lora_ingest.backoff import LoRaBackoff


class TestLoRaBackoff:

    def test_init_defaults(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        assert backoff.node_id == 1
        assert backoff.current_window_ms == 200.0
        assert backoff.retry_max == 3

    def test_spreading_factor_assignment(self):
        """按 node_id 分配 SF, 不同节点 SF 不同 (正交信道)"""
        sf_list = [7, 8, 9, 10, 11, 12]
        config = {
            "spreading_factors": sf_list,
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        }

        backoffs = [LoRaBackoff(node_id=i, config=config) for i in range(1, 7)]
        sfs = [b.spreading_factor for b in backoffs]

        # 6 个节点分到不同 SF
        assert len(set(sfs)) == 6
        assert all(sf in sf_list for sf in sfs)

    def test_acquire_channel_returns_positive_delay(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        delay = backoff.acquire_channel()
        assert delay >= 0
        assert delay <= 8.0  # 不超过最大窗口 (秒)

    def test_acquire_channel_with_congestion(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        # 拥堵时延迟更大 (统计上)
        delays_low = [backoff.acquire_channel(0.0) for _ in range(100)]
        delays_high = [backoff.acquire_channel(1.0) for _ in range(100)]
        assert sum(delays_high) > sum(delays_low) * 1.5

    def test_backoff_increases_on_failure(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        initial_window = backoff.current_window_ms

        backoff.report_result(False)
        assert backoff.current_window_ms == initial_window * 2

        backoff.report_result(False)
        assert backoff.current_window_ms == initial_window * 4

    def test_backoff_decreases_on_success(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        # 先失败几次让窗口变大
        backoff.report_result(False)
        backoff.report_result(False)
        big_window = backoff.current_window_ms

        # 成功后窗口减半
        backoff.report_result(True)
        assert backoff.current_window_ms == big_window * 0.5

    def test_backoff_capped_at_max(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        # 连续失败很多次
        for _ in range(20):
            backoff.report_result(False)
        assert backoff.current_window_ms <= 8000.0

    def test_backoff_floor_at_init(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        # 连续成功很多次, 窗口不会低于初始值
        for _ in range(20):
            backoff.report_result(True)
        assert backoff.current_window_ms == pytest.approx(200.0, rel=0.01)

    def test_collision_probability_increases_with_nodes(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        })
        p_low = backoff.simulate_collision_probability(3)
        p_high = backoff.simulate_collision_probability(20)
        assert p_high > p_low
        assert 0 <= p_low <= 1
        assert 0 <= p_high <= 1

    def test_send_with_backoff_sync_success(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 10,  # 小值让测试快
            "backoff_max_ms": 100,
            "retry_max": 3,
        })
        # 先失败一次让窗口变大到 20ms
        backoff.report_result(False)
        assert backoff.current_window_ms == pytest.approx(20.0)

        # 成功后窗口减半
        result = backoff.send_with_backoff_sync(lambda: True)
        assert result is True
        # 成功后从 20ms 减半到 10ms (刚好是初始值/floor)
        assert backoff.current_window_ms == pytest.approx(10.0, rel=0.01)

    def test_send_with_backoff_sync_all_fail(self):
        backoff = LoRaBackoff(node_id=1, config={
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 10,
            "backoff_max_ms": 100,
            "retry_max": 3,
        })
        result = backoff.send_with_backoff_sync(lambda: False)
        assert result is False
        # 失败 3 次, 窗口变大
        assert backoff.current_window_ms > 10.0

    def test_deterministic_with_seed(self):
        """相同种子产生相同退避序列 (可复现性)"""
        config = {
            "spreading_factors": [7, 8, 9, 10, 11, 12],
            "backoff_init_ms": 200,
            "backoff_max_ms": 8000,
            "retry_max": 3,
        }
        b1 = LoRaBackoff(node_id=1, seed=42, config=config)
        b2 = LoRaBackoff(node_id=1, seed=42, config=config)

        delays1 = [b1.acquire_channel() for _ in range(10)]
        delays2 = [b2.acquire_channel() for _ in range(10)]

        assert delays1 == delays2
