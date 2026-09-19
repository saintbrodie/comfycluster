from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from comfycluster_common.models import HostView, JobRecord, JobState, WorkerState
from comfycluster_common.releases import ReleaseManifest

from .store import FleetStore


class SQLiteFleetStore(FleetStore):
    """Durable FleetStore using only the Python standard-library sqlite3 driver."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hosts (
                host_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );
            """
        )
        self._db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '1')"
        )
        self._db.commit()
        self._load()

    def _load(self) -> None:
        for (raw,) in self._db.execute("SELECT data FROM hosts"):
            host = HostView.model_validate_json(raw)
            host.connected = False
            for worker in host.workers:
                worker.state = WorkerState.OFFLINE
                worker.current_job_id = None
            self._hosts[host.host_id] = host

        dirty_jobs: list[JobRecord] = []
        for (raw,) in self._db.execute("SELECT data FROM jobs"):
            job = JobRecord.model_validate_json(raw)
            if job.state in {JobState.DISPATCHING, JobState.RUNNING}:
                job.state = JobState.FAILED
                job.error = "controller restarted while job was active; terminal state is unknown"
                dirty_jobs.append(job)
            self._jobs[job.job_id] = job
        for job in dirty_jobs:
            self._persist_job(job)

        row = self._db.execute("SELECT value FROM meta WHERE key='desired_release'").fetchone()
        if row:
            self._desired_release = ReleaseManifest.model_validate_json(row[0])

    def _persist_host(self, host: HostView) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO hosts(host_id, data) VALUES(?, ?)",
            (host.host_id, host.model_dump_json()),
        )
        self._db.commit()

    def _persist_job(self, job: JobRecord) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO jobs(job_id, data) VALUES(?, ?)",
            (str(job.job_id), job.model_dump_json()),
        )
        self._db.commit()

    def _persist_desired_release(self, manifest: ReleaseManifest) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('desired_release', ?)",
            (manifest.model_dump_json(),),
        )
        self._db.commit()

    async def register_host(self, registration):
        host = await super().register_host(registration)
        self._persist_host(host)
        return host

    async def heartbeat(self, heartbeat):
        host = await super().heartbeat(heartbeat)
        if host:
            self._persist_host(host)
        return host

    async def mark_disconnected(self, host_id: str) -> None:
        await super().mark_disconnected(host_id)
        host = await super().get_host(host_id)
        if host:
            self._persist_host(host)

    async def set_host_draining(self, host_id: str, draining: bool):
        host = await super().set_host_draining(host_id, draining)
        if host:
            self._persist_host(host)
        return host

    async def update_worker(
        self,
        host_id: str,
        worker_id: str,
        *,
        state: WorkerState | None = None,
        current_job_id: UUID | None = None,
    ):
        worker = await super().update_worker(
            host_id,
            worker_id,
            state=state,
            current_job_id=current_job_id,
        )
        host = await super().get_host(host_id)
        if host:
            self._persist_host(host)
        return worker

    async def create_job(self, job: JobRecord) -> JobRecord:
        created = await super().create_job(job)
        self._persist_job(created)
        return created

    async def update_job(self, job_id: UUID, **changes: object):
        job = await super().update_job(job_id, **changes)
        if job:
            self._persist_job(job)
        return job

    async def set_desired_release(self, manifest: ReleaseManifest) -> ReleaseManifest:
        stored = await super().set_desired_release(manifest)
        self._persist_desired_release(stored)
        return stored

    async def seed_hosts(self, hosts) -> None:
        await super().seed_hosts(hosts)
        for host in await super().list_hosts():
            self._persist_host(host)

    def close(self) -> None:
        self._db.close()
