from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import RLock


_EVENTS: deque[dict] = deque(maxlen=500)
_LOCK = RLock()


def record(path: str, method: str, status: int, duration_ms: float) -> None:
    event={"event":"api_end","path":path,"method":method,"status":status,
           "duration_ms":round(duration_ms,2),"timestamp":datetime.now(timezone.utc).isoformat()}
    with _LOCK: _EVENTS.append(event)


def snapshot(limit: int = 100) -> dict:
    with _LOCK: rows=list(_EVENTS)[-limit:]
    grouped={}
    for row in rows:
        item=grouped.setdefault(row["path"],[]);item.append(row["duration_ms"])
    summary=[]
    for path,values in grouped.items():
        ordered=sorted(values);p95=ordered[min(len(ordered)-1,int(len(ordered)*.95))]
        summary.append({"path":path,"calls":len(values),"average_ms":round(sum(values)/len(values),2),
                        "p95_ms":p95,"max_ms":max(values)})
    summary.sort(key=lambda row:row["max_ms"],reverse=True)
    return {"events":rows,"summary":summary,"clock":"server monotonic duration",
            "notice":"Provider等待时间包含在对应API总耗时内；浏览器渲染耗时由Performance API记录。"}
