"""
共享配置加载器 - 从 config/config.yaml 读取所有配置
所有服务通过此模块统一获取配置, 避免硬编码
"""
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List

_CONFIG_CACHE: Dict[str, Any] = {}


def _default_config_path() -> Path:
    """默认配置路径: backend/config/config.yaml"""
    # 从当前文件向上找 config 目录
    here = Path(__file__).resolve().parent
    return here.parent / "config" / "config.yaml"


def load_config(config_path: str | Path | None = None, force_reload: bool = False) -> dict:
    """加载并缓存 YAML 配置"""
    global _CONFIG_CACHE
    cache_key = str(config_path or "default")

    if not force_reload and cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    path = Path(config_path) if config_path else _default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    _CONFIG_CACHE[cache_key] = cfg
    return cfg


# --- 便捷访问函数 ---

def get_tents() -> List[dict]:
    cfg = load_config()
    return cfg["tents"]


def get_tent(tent_id: int) -> dict | None:
    for t in get_tents():
        if t["id"] == tent_id:
            return t
    return None


def get_drug_params(drug_name: str) -> dict | None:
    cfg = load_config()
    return cfg["drugs"].get(drug_name)


def get_drug_list() -> List[str]:
    cfg = load_config()
    return list(cfg["drugs"].keys())


def get_clickhouse_config() -> dict:
    return load_config()["clickhouse"]


def get_redis_config() -> dict:
    return load_config()["redis"]


def get_alert_config() -> dict:
    return load_config()["alerts"]


def get_lora_config() -> dict:
    return load_config()["lora"]


def get_microbial_config() -> dict:
    return load_config()["microbial"]


def get_priority_model_config() -> dict:
    return load_config()["priority_model"]
