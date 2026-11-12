"""Celery application and task dispatch.

Run a worker with:  celery -A app.worker.celery_app worker --loglevel=info --concurrency=4
With TASK_BACKEND=inline (dev/tests only) jobs run in a background thread of the API process.
"""
from __future__ import annotations

import logging
import threading

from celery import Celery

from app.config import get_settings

log = logging.getLogger(__name__)
settings = get_settings()

celery_app = Celery("seo_metadata", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
)


@celery_app.task(name="crawl.run")
def crawl_task(job_id: int) -> None:
    from app.crawler.engine import run_crawl_job

    run_crawl_job(job_id)


@celery_app.task(name="ai.run")
def ai_task(job_id: int) -> None:
    from app.ai.pipeline import run_ai_job

    run_ai_job(job_id)


_TASKS = {"crawl": crawl_task, "ai": ai_task}


def dispatch(kind: str, job_id: int) -> str | None:
    task = _TASKS[kind]
    if get_settings().task_backend == "inline":
        t = threading.Thread(target=task.run, args=(job_id,), daemon=True, name=f"{kind}-{job_id}")
        t.start()
        return None
    res = task.delay(job_id)
    return res.id
