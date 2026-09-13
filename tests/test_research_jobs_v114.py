from backend import database
from backend import research_jobs


def test_cache_hash_and_cancel(monkeypatch,tmp_path):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"db.sqlite3");database.init_db()
    key=research_jobs.cache_key("x",{"a":1},"d","f","m")
    research_jobs.cache_put(key,"d","f","m",{"answer":42})
    assert research_jobs.cache_get(key)=={"answer":42}
    job=research_jobs.create("x",{"a":1})
    assert research_jobs.get(job["job_id"])["status"]=="QUEUED"
    assert research_jobs.cancel(job["job_id"]) is True and research_jobs.cancelled(job["job_id"])
