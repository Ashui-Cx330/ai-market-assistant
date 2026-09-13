"""SQLite-backed cancellable research jobs and hash-keyed cache."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .database import connection


def _now():return datetime.now(timezone.utc).isoformat()


def cache_key(job_type: str, request: dict, dataset_hash: str, feature_hash: str, model_hash: str) -> str:
    raw=json.dumps([job_type,request,dataset_hash,feature_hash,model_hash],sort_keys=True,ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def cache_get(key: str) -> dict | None:
    with connection() as conn:
        row=conn.execute("SELECT payload_json FROM research_cache WHERE cache_key=?",(key,)).fetchone()
        if row:conn.execute("UPDATE research_cache SET last_accessed_at=? WHERE cache_key=?",(_now(),key))
    return json.loads(row[0]) if row else None


def cache_put(key: str, dataset_hash: str, feature_hash: str, model_hash: str, payload: dict) -> None:
    now=_now()
    with connection() as conn:conn.execute("""INSERT OR REPLACE INTO research_cache
      (cache_key,dataset_hash,feature_hash,model_hash,payload_json,created_at,last_accessed_at) VALUES(?,?,?,?,?,?,?)""",
      (key,dataset_hash,feature_hash,model_hash,json.dumps(payload,ensure_ascii=False,default=str),now,now))


def create(job_type: str, request: dict) -> dict:
    job={"job_id":uuid.uuid4().hex,"job_type":job_type,"status":"QUEUED","progress":0.0,"created_at":_now()}
    with connection() as conn:conn.execute("INSERT INTO research_jobs(job_id,job_type,status,request_json,progress,created_at) VALUES(?,?,?,?,?,?)",
      (job["job_id"],job_type,"QUEUED",json.dumps(request,ensure_ascii=False),0,job["created_at"]))
    return job


def get(job_id: str) -> dict | None:
    with connection() as conn:row=conn.execute("SELECT * FROM research_jobs WHERE job_id=?",(job_id,)).fetchone()
    if not row:return None
    item=dict(row);item["request"]=json.loads(item.pop("request_json"));item["result"]=json.loads(item.pop("result_json")) if item.get("result_json") else None
    return item


def update(job_id: str, status: str, progress: float, result: dict | None=None, error: str | None=None) -> None:
    now=_now();started=now if status=="RUNNING" else None;completed=now if status in {"COMPLETED","FAILED","CANCELLED"} else None
    with connection() as conn:conn.execute("""UPDATE research_jobs SET status=?,progress=?,result_json=COALESCE(?,result_json),error=?,
      started_at=COALESCE(started_at,?),completed_at=COALESCE(?,completed_at) WHERE job_id=?""",
      (status,progress,json.dumps(result,ensure_ascii=False,default=str) if result is not None else None,error,started,completed,job_id))


def cancel(job_id: str) -> bool:
    with connection() as conn:
        cursor=conn.execute("UPDATE research_jobs SET cancel_requested=1 WHERE job_id=? AND status IN ('QUEUED','RUNNING')",(job_id,))
    return cursor.rowcount==1


def cancelled(job_id: str) -> bool:
    with connection() as conn:row=conn.execute("SELECT cancel_requested FROM research_jobs WHERE job_id=?",(job_id,)).fetchone()
    return bool(row and row[0])
