from __future__ import annotations

import csv
import subprocess
from io import StringIO

from comfycluster_common.models import GPUInfo

_QUERY_FIELDS = [
    "index",
    "uuid",
    "name",
    "memory.total",
    "memory.used",
    "utilization.gpu",
    "temperature.gpu",
    "driver_version",
]


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return default


def discover_gpus(mock_count: int = 0) -> list[GPUInfo]:
    if mock_count:
        return [
            GPUInfo(
                index=i,
                uuid=f"MOCK-GPU-{i}",
                name="Mock NVIDIA GPU",
                memory_total_mb=32768,
                memory_used_mb=1024 + i * 256,
                utilization_percent=0,
                driver_version="mock",
            )
            for i in range(mock_count)
        ]

    command = [
        "nvidia-smi",
        f"--query-gpu={','.join(_QUERY_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    gpus: list[GPUInfo] = []
    for row in csv.reader(StringIO(completed.stdout)):
        if len(row) != len(_QUERY_FIELDS):
            continue
        gpus.append(
            GPUInfo(
                index=_to_int(row[0]),
                uuid=row[1].strip(),
                name=row[2].strip(),
                memory_total_mb=_to_int(row[3]),
                memory_used_mb=_to_int(row[4]),
                utilization_percent=_to_int(row[5]),
                temperature_c=_to_int(row[6]) if row[6].strip() not in {"", "N/A"} else None,
                driver_version=row[7].strip() or None,
            )
        )
    return gpus
