from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import joblib


class ModelManager:
    def __init__(self, root: str | Path | None = None) -> None:
        data_root = Path(root or os.environ.get("TRADING_AI_DATA_DIR") or Path.home() / ".ai-market-assistant")
        self.root = data_root / "models"

    @staticmethod
    def _safe(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", value)

    def path(self, symbol: str, interval: str, horizon: str) -> Path:
        return self.root / self._safe(symbol) / self._safe(interval) / self._safe(horizon) / "ensemble.joblib"

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
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        joblib.dump(artifact, temporary)
        if target.exists():
            shutil.copy2(target, target.with_suffix(".previous.joblib"))
        os.replace(temporary, target)
        return target

    def rollback(self, symbol: str, interval: str, horizon: str) -> bool:
        target = self.path(symbol, interval, horizon)
        previous = target.with_suffix(".previous.joblib")
        if not previous.exists():
            return False
        os.replace(previous, target)
        return True
