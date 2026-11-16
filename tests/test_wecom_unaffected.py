"""WeCom auto layout preserves business and customer-selection settings."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def raw_cfg():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def test_wecom_auto_profile_preserves_business_settings(raw_cfg):
    """Geometry can change; customer scope and reply policy must not."""
    from wxbot.profile import apply_to_config, load_profile
    out = apply_to_config(raw_cfg, load_profile("wecom"))
    assert out["layout"]["auto_detect"] is True
    assert out["wecom"]["window_class"] == "WeWorkWindow"
    assert out["rag"] == raw_cfg["rag"]
    assert out.get("customers") == raw_cfg.get("customers")


def test_wecom_preserves_explicit_customer_scope(raw_cfg):
    """A local test whitelist must survive applying the built-in profile."""
    from wxbot.profile import apply_to_config, load_profile
    from wxbot.scan_policy import parse_whitelist
    out = apply_to_config(raw_cfg, load_profile("wecom"))
    assert parse_whitelist(out.get("customers", {})) == parse_whitelist(raw_cfg.get("customers", {}))
    assert out.get("detection", {}).get("red_dot", {}).get("enabled", True) is True
    assert out["rag"]["allow_auto_send"] is True
    assert out["fallback"] == raw_cfg["fallback"]


def test_no_customer_match_override_for_wecom(raw_cfg):
    """`customer_match` 只能由微信 profile 设置；企微继续用 @微信 后缀。"""
    from wxbot.profile import apply_to_config, load_profile
    out = apply_to_config(raw_cfg, load_profile("wecom"))
    assert "customer_match" not in out["ocr"]


def test_profile_apply_does_not_mutate_original(raw_cfg):
    from wxbot.profile import apply_to_config, load_profile
    snapshot = json.dumps(raw_cfg, ensure_ascii=False, sort_keys=True)
    apply_to_config(raw_cfg, load_profile("wecom"))
    assert json.dumps(raw_cfg, ensure_ascii=False, sort_keys=True) == snapshot


def test_main_impl_defines_gates_before_use():
    """whitelist / use_red_dot 必须在 _main_impl 里定义，两个后台函数共用。"""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert src.count("whitelist = parse_whitelist(") == 1
    assert src.count("use_red_dot = bool(") == 1
    # 定义位置在 _run_scan / _scan_fallback 之前
    d_wl = src.index("whitelist = parse_whitelist(")
    assert d_wl < src.index("def _run_scan")
    assert d_wl < src.index("def _scan_fallback")
