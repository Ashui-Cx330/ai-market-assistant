from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import joblib


class ModelManager:
    _locks: dict[str, threading.RLock] = {}
    _locks_guard = threading.Lock()

    def __init__(self, root: str | Path | None = None) -> None:
        data_root = Path(root or os.environ.get("TRADING_AI_DATA_DIR") or Path.home() / ".ai-market-assistant")
        self.root = data_root / "models"

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", value)

    def path(self, symbol: str, interval: str, horizon: str) -> Path:
        return self.root / self._safe(symbol) / self._safe(interval) / self._safe(horizon) / "ensemble.joblib"

    @classmethod
    def _target_lock(cls, target: Path) -> threading.RLock:
        key = str(target.resolve()).lower()
        with cls._locks_guard:
            return cls._locks.setdefault(key, threading.RLock())

    @staticmethod
    def _replace_cross_volume_safe(source: Path, target: Path) -> None:
        error: OSError | None = None
        for attempt in range(6):
            try:
                os.replace(source, target)
                return
            except PermissionError as exc:
                # Windows Search/Defender and a just-closed model reader can
                # retain a very short sharing lock. The source is still intact,
                # so bounded retry is safe and remains atomic when it succeeds.
                error=exc
                if attempt < 5:
                    time.sleep(.025 * (attempt + 1))
                    continue
                raise
            except OSError as exc:
                error=exc
                break
        if error is not None:
            exc=error
            # Some Windows roaming-profile/reparse configurations report
            # ERROR_NOT_SAME_DEVICE even for visually identical AppData paths.
            # Copying remains valid across volumes; the existing .previous
            # backup keeps this fallback recoverable.
            if getattr(exc, "winerror", None) != 17 and exc.errno != 18:
                raise
            shutil.copy2(source, target)
            source.unlink(missing_ok=True)

    def load(self, symbol: str, interval: str, horizon: str, fingerprint: str):
        target = self.path(symbol, interval, horizon)
        try:
            artifact = joblib.load(target)
            return artifact if artifact.get("fingerprint") == fingerprint else None
        except Exception:
            return None

    def current(self, symbol: str, interval: str, horizon: str):
        try:return joblib.load(self.path(symbol,interval,horizon))
        except Exception:return None

    def promote_if_better(self, symbol: str, interval: str, horizon: str, candidate: dict) -> tuple[dict,str]:
        """Replace a V4 model only after an untouched-test improvement."""
        existing=self.current(symbol,interval,horizon)
        if not existing or existing.get("version")!="4.0":
            self.save(symbol,interval,horizon,candidate);return candidate,"INITIAL_OR_SCHEMA_UPGRADE"
        old=existing.get("ensemble_metrics",{});new=candidate.get("ensemble_metrics",{})
        accuracy_gain=float(new.get("accuracy",0))-float(old.get("accuracy",0))
        brier_gain=float(old.get("brier_score",1))-float(new.get("brier_score",1))
        if accuracy_gain>=.01 or (brier_gain>=.02 and accuracy_gain>=-.005):
            self.save(symbol,interval,horizon,candidate);return candidate,"PROMOTED_AFTER_HOLDOUT_IMPROVEMENT"
        existing["fingerprint"]=candidate["fingerprint"]
        existing["last_candidate_trained_at"]=candidate.get("trained_at")
        self.save(symbol,interval,horizon,existing)
        return existing,"RETAINED_PREVIOUS_MODEL_NO_SIGNIFICANT_IMPROVEMENT"

    def save(self, symbol: str, interval: str, horizon: str, artifact: dict) -> Path:
        target = self.path(symbol, interval, horizon)
        with self._target_lock(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                joblib.dump(artifact, temporary)
                if target.exists():
                    shutil.copy2(target, target.with_suffix(".previous.joblib"))
                self._replace_cross_volume_safe(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return target

    def rollback(self, symbol: str, interval: str, horizon: str) -> bool:
        target = self.path(symbol, interval, horizon)
        previous = target.with_suffix(".previous.joblib")
        with self._target_lock(target):
            if not previous.exists():
                return False
            self._replace_cross_volume_safe(previous, target)
            return True
