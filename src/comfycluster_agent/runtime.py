from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx

from comfycluster_common.models import ComfyInstallation, GPUInfo, WorkerSnapshot, WorkerState


@dataclass(slots=True)
class ManagedProcess:
    worker: WorkerSnapshot
    process: subprocess.Popen | None = None
    log_handle: object | None = None
    current_prompt_id: str | None = None


class NativeWindowsRuntime:
    def __init__(
        self,
        comfy: ComfyInstallation | None,
        gpus: list[GPUInfo],
        base_port: int = 8188,
        runtime_dir: Path | None = None,
    ) -> None:
        self.comfy = comfy
        self.gpus = gpus
        self.base_port = base_port
        self.runtime_dir = runtime_dir or Path("runtime")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._workers: dict[str, ManagedProcess] = {}
        for offset, gpu in enumerate(gpus):
            worker_id = self.worker_id(gpu)
            port = base_port + offset
            self._workers[worker_id] = ManagedProcess(
                worker=WorkerSnapshot(
                    worker_id=worker_id,
                    gpu_uuid=gpu.uuid,
                    gpu_index=gpu.index,
                    port=port,
                    state=WorkerState.STOPPED,
                    comfy_url=f"http://127.0.0.1:{port}",
                )
            )

    @staticmethod
    def worker_id(gpu: GPUInfo) -> str:
        safe_uuid = gpu.uuid.replace("GPU-", "").replace(" ", "-")
        return f"gpu-{gpu.index}-{safe_uuid[:12]}"

    def snapshots(self) -> list[WorkerSnapshot]:
        self._refresh_process_state()
        return [managed.worker.model_copy(deep=True) for managed in self._workers.values()]

    def _refresh_process_state(self) -> None:
        for managed in self._workers.values():
            if managed.process is None:
                continue
            return_code = managed.process.poll()
            if return_code is None:
                if managed.worker.state not in {WorkerState.STARTING, WorkerState.BUSY, WorkerState.DRAINING}:
                    managed.worker.state = WorkerState.IDLE
                managed.worker.pid = managed.process.pid
            else:
                managed.worker.pid = None
                managed.worker.state = WorkerState.ERROR if return_code else WorkerState.STOPPED
                managed.process = None
                if managed.log_handle:
                    managed.log_handle.close()
                    managed.log_handle = None

    def start(self, worker_id: str) -> WorkerSnapshot:
        managed = self._workers[worker_id]
        if managed.process and managed.process.poll() is None:
            return managed.worker.model_copy(deep=True)
        if self.comfy is None:
            raise RuntimeError("ComfyUI installation not found")

        log_path = self.runtime_dir / f"{worker_id}.log"
        log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
        args = [
            self.comfy.python_executable,
            self.comfy.main_py,
            "--listen",
            "127.0.0.1",
            "--port",
            str(managed.worker.port),
            "--cuda-device",
            str(managed.worker.gpu_index),
            "--disable-auto-launch",
        ]
        managed.worker.state = WorkerState.STARTING
        try:
            managed.process = subprocess.Popen(
                args,
                cwd=self.comfy.path,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except Exception:
            log_handle.close()
            managed.worker.state = WorkerState.ERROR
            raise
        managed.log_handle = log_handle
        managed.worker.pid = managed.process.pid
        return managed.worker.model_copy(deep=True)

    def stop(self, worker_id: str, timeout: float = 10.0) -> WorkerSnapshot:
        managed = self._workers[worker_id]
        process = managed.process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        managed.process = None
        managed.worker.pid = None
        managed.worker.current_job_id = None
        managed.current_prompt_id = None
        managed.worker.state = WorkerState.STOPPED
        if managed.log_handle:
            managed.log_handle.close()
            managed.log_handle = None
        return managed.worker.model_copy(deep=True)

    def restart(self, worker_id: str) -> WorkerSnapshot:
        self.stop(worker_id)
        return self.start(worker_id)

    def start_all(self) -> list[WorkerSnapshot]:
        return [self.start(worker_id) for worker_id in self._workers]

    def stop_all(self) -> list[WorkerSnapshot]:
        return [self.stop(worker_id) for worker_id in self._workers]

    async def submit_job(
        self,
        worker_id: str,
        job_id: UUID,
        workflow: dict,
        client_id: str | None = None,
    ) -> str:
        managed = self._workers[worker_id]
        if managed.worker.state not in {WorkerState.IDLE, WorkerState.STARTING}:
            raise RuntimeError(f"worker {worker_id} is not idle")
        payload: dict = {"prompt": workflow}
        if client_id:
            payload["client_id"] = client_id
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{managed.worker.comfy_url}/prompt", json=payload)
            response.raise_for_status()
            body = response.json()
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI accepted request without returning prompt_id")
        managed.worker.state = WorkerState.BUSY
        managed.worker.current_job_id = job_id
        managed.current_prompt_id = str(prompt_id)
        return str(prompt_id)

    async def poll_jobs(self) -> list[dict]:
        """Return terminal job events observed in Comfy history."""
        completed: list[dict] = []
        async with httpx.AsyncClient(timeout=2.0) as client:
            for managed in self._workers.values():
                job_id = managed.worker.current_job_id
                prompt_id = managed.current_prompt_id
                if managed.worker.state is not WorkerState.BUSY or not job_id or not prompt_id:
                    continue
                try:
                    response = await client.get(f"{managed.worker.comfy_url}/history/{prompt_id}")
                    if not response.is_success:
                        continue
                    body = response.json()
                except (httpx.HTTPError, ValueError):
                    continue
                history = body.get(prompt_id) if isinstance(body, dict) else None
                if not history:
                    continue
                status = history.get("status", {}) if isinstance(history, dict) else {}
                status_str = str(status.get("status_str", "success")).lower()
                event = "job.failed" if status_str in {"error", "failed"} else "job.completed"
                completed.append(
                    {
                        "event": event,
                        "job_id": job_id,
                        "prompt_id": prompt_id,
                        "status": status_str,
                    }
                )
                managed.worker.state = WorkerState.IDLE
                managed.worker.current_job_id = None
                managed.current_prompt_id = None
        return completed

    async def probe_workers(self) -> None:
        self._refresh_process_state()
        async with httpx.AsyncClient(timeout=1.5) as client:
            for managed in self._workers.values():
                if not managed.process or managed.process.poll() is not None:
                    continue
                try:
                    response = await client.get(f"{managed.worker.comfy_url}/system_stats")
                    if response.is_success and managed.worker.state is WorkerState.STARTING:
                        managed.worker.state = WorkerState.IDLE
                except httpx.HTTPError:
                    pass
