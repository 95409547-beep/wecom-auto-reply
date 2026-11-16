"""Incomplete downloads must not be reported as a usable local model."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from safetensors.numpy import save_file

from scripts import prepare_model


def write_model(target):
    for name in prepare_model.MODEL_FILES:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name == "model.safetensors":
            save_file({"test": np.zeros(1, dtype=np.float32)}, str(path))
        elif path.suffix == ".json":
            path.write_text("{}", encoding="utf-8")
        else:
            path.write_text("test", encoding="utf-8")


@pytest.fixture
def model_setup(tmp_path, monkeypatch):
    target = tmp_path / "model"
    monkeypatch.setattr(prepare_model, "TARGET", target)
    monkeypatch.setattr(sys, "argv", ["prepare_model.py", "--official"])
    download = Mock(side_effect=lambda *args, **kwargs: write_model(target))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    return target, download


def test_complete_model_does_not_download(model_setup):
    target, download = model_setup
    write_model(target)
    assert prepare_model.main() == 0
    download.assert_not_called()


def test_weights_alone_are_not_a_complete_model(model_setup):
    target, download = model_setup
    target.mkdir()
    save_file({"test": np.zeros(1, dtype=np.float32)}, str(target / "model.safetensors"))
    assert prepare_model.main() == 0
    assert download.call_count == 1
    assert download.call_args.kwargs["force_download"] is False
    assert "pytorch_model.bin" not in download.call_args.kwargs["allow_patterns"]


@pytest.mark.parametrize("broken_file", ["config.json", "model.safetensors"])
def test_corrupt_files_force_download_even_with_cached_metadata(model_setup, broken_file):
    target, download = model_setup
    write_model(target)
    (target / broken_file).write_bytes(b"incomplete download")
    assert prepare_model.main() == 0
    assert download.call_args.kwargs["force_download"] is True
    assert prepare_model.model_problems(target) == {}


def test_failed_download_returns_failure(model_setup):
    target, download = model_setup
    download.side_effect = OSError("offline")
    assert prepare_model.main() == 1
    assert not target.exists()


def test_download_success_still_requires_complete_files(model_setup):
    target, download = model_setup
    download.side_effect = None
    assert prepare_model.main() == 1
    assert prepare_model.model_problems(target)
