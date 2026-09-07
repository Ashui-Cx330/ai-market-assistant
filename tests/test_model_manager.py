from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import joblib

from backend.model_manager import ModelManager


def test_windows_cross_volume_replace_falls_back_to_copy(tmp_path, monkeypatch):
    manager=ModelManager(tmp_path);real_replace=os.replace
    def cross_volume(source,target):
        error=OSError(18,"cross-volume");error.winerror=17;raise error
    monkeypatch.setattr(os,"replace",cross_volume)
    target=manager.save("BTC","1h","1H",{"fingerprint":"one","version":"4.0"})
    assert joblib.load(target)["fingerprint"]=="one"
    assert not list(target.parent.glob("*.tmp"))
    monkeypatch.setattr(os,"replace",real_replace)


def test_concurrent_saves_use_unique_temporary_files(tmp_path):
    manager=ModelManager(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        targets=list(pool.map(lambda index:manager.save("BTC","1h","1H",{"fingerprint":str(index),"version":"4.0"}),range(8)))
    assert all(target==targets[0] for target in targets)
    assert joblib.load(targets[0])["fingerprint"] in {str(index) for index in range(8)}
    assert not list(targets[0].parent.glob("*.tmp"))
