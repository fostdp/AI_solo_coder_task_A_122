"""
LoRa 消息去重器测试
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import time
from services.lora_ingest.deduplicator import MessageDeduplicator


class TestMessageDeduplicator:

    def test_init(self):
        dedup = MessageDeduplicator(window_seconds=60)
        assert dedup.window_seconds == 60
        stats = dedup.stats
        assert stats["total"] == 0
        assert stats["duplicates"] == 0

    def test_first_message_not_duplicate(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()
        is_dup = dedup.is_duplicate(
            tent_id=1, sensor_type="temperature", sensor_id=1, timestamp=now
        )
        assert is_dup is False
        assert dedup.stats["total"] == 1
        assert dedup.stats["duplicates"] == 0

    def test_same_message_is_duplicate(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        dedup.is_duplicate(1, "temperature", 1, now)
        is_dup = dedup.is_duplicate(1, "temperature", 1, now)

        assert is_dup is True
        assert dedup.stats["duplicates"] == 1

    def test_different_sensor_not_duplicate(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        dedup.is_duplicate(1, "temperature", 1, now)
        is_dup = dedup.is_duplicate(1, "temperature", 2, now)

        assert is_dup is False

    def test_different_tent_not_duplicate(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        dedup.is_duplicate(1, "temperature", 1, now)
        is_dup = dedup.is_duplicate(2, "temperature", 1, now)

        assert is_dup is False

    def test_different_type_not_duplicate(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        dedup.is_duplicate(1, "temperature", 1, now)
        is_dup = dedup.is_duplicate(1, "humidity", 1, now)

        assert is_dup is False

    def test_same_minute_aligned(self):
        """同一分钟内的消息被认为重复 (30min 粒度上报)"""
        dedup = MessageDeduplicator(window_seconds=60)
        t1 = 1_700_000_000.0  # 整秒
        t2 = 1_700_000_010.0  # 10 秒后, 同一分钟内

        dedup.is_duplicate(1, "temperature", 1, t1)
        is_dup = dedup.is_duplicate(1, "temperature", 1, t2)

        assert is_dup is True

    def test_different_minute_not_duplicate(self):
        """不同分钟的消息不被去重"""
        dedup = MessageDeduplicator(window_seconds=60)
        t1 = 1_700_000_000.0
        t2 = 1_700_000_100.0  # 100 秒后, 不同分钟

        dedup.is_duplicate(1, "temperature", 1, t1)
        is_dup = dedup.is_duplicate(1, "temperature", 1, t2)

        assert is_dup is False

    def test_aw_deduplication(self):
        """水分活度数据去重"""
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        dedup.is_aw_duplicate(1, "当归", 1, now)
        is_dup = dedup.is_aw_duplicate(1, "当归", 1, now)

        assert is_dup is True

    def test_aw_different_drug_not_duplicate(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        dedup.is_aw_duplicate(1, "当归", 1, now)
        is_dup = dedup.is_aw_duplicate(1, "大黄", 1, now)

        assert is_dup is False

    def test_expired_message_not_duplicate(self):
        """超过窗口时间的老消息不被视为重复"""
        dedup = MessageDeduplicator(window_seconds=1)  # 1 秒窗口
        now = time.time()

        # 手动插入一条"过期"消息: expire_ts 在过去
        old_key = "1:temperature:1:1700000000"
        dedup._buckets[old_key] = now - 10
        dedup._timeline.append((now - 5, old_key))  # 5 秒前就过期了

        # 清理
        dedup._cleanup(now)

        # 新消息 (同一 tent/sensor/type, 但已过期不影响)
        is_dup = dedup.is_duplicate(1, "temperature", 1, now)

        assert is_dup is False
        assert old_key not in dedup._buckets

    def test_reset(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        for i in range(10):
            dedup.is_duplicate(1, "temperature", i, now)

        assert dedup.stats["total"] == 10
        dedup.reset()
        assert dedup.stats["total"] == 0
        assert dedup.stats["duplicates"] == 0

    def test_stats_tracking(self):
        dedup = MessageDeduplicator(window_seconds=60)
        now = time.time()

        # 插入 5 条唯一消息
        for i in range(5):
            dedup.is_duplicate(1, "temperature", i, now)

        # 重复插入 2 条
        dedup.is_duplicate(1, "temperature", 0, now)
        dedup.is_duplicate(1, "temperature", 1, now)

        stats = dedup.stats
        assert stats["total"] == 7
        assert stats["duplicates"] == 2
