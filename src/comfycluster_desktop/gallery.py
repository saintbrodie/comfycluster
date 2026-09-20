from __future__ import annotations

import queue
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .api import DesktopApi


class ThumbnailWorker(QThread):
    ready = Signal(str, str)

    def __init__(self, api: DesktopApi) -> None:
        super().__init__()
        self.api = api
        self.tasks: queue.Queue[str | None] = queue.Queue()
        self.queued: set[str] = set()

    def enqueue(self, asset_id: str) -> None:
        if not asset_id or asset_id in self.queued:
            return
        self.queued.add(asset_id)
        self.tasks.put(asset_id)

    def run(self) -> None:
        while True:
            asset_id = self.tasks.get()
            if asset_id is None:
                return
            try:
                path = self.api.download_thumbnail(asset_id, 360)
                self.ready.emit(asset_id, str(path))
            except Exception:
                pass
            finally:
                self.queued.discard(asset_id)

    def stop(self) -> None:
        self.tasks.put(None)


class OpenAssetWorker(QThread):
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, api: DesktopApi, asset: dict[str, Any]) -> None:
        super().__init__()
        self.api = api
        self.asset = asset

    def run(self) -> None:
        try:
            path = self.api.download_asset(
                str(self.asset.get("asset_id") or ""),
                str(self.asset.get("filename") or "output.bin"),
            )
            self.ready.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))


class GalleryCard(QFrame):
    def __init__(self, asset: dict[str, Any], open_callback, details_callback) -> None:
        super().__init__()
        self.asset = asset
        self.setObjectName("card")
        self.setMinimumWidth(225)
        self.setMaximumWidth(290)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        self.preview = QLabel()
        self.preview.setFixedHeight(165)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "background:#0d0f12;border:1px solid #292d33;border-radius:7px;color:#727985;"
        )
        media = str(asset.get("media_type") or "application/octet-stream")
        self.preview.setText("IMAGE" if media.startswith("image/") else "VIDEO" if media.startswith("video/") else "FILE")
        layout.addWidget(self.preview)

        filename = QLabel(str(asset.get("filename") or "output"))
        filename.setStyleSheet("font-weight:650;")
        filename.setWordWrap(True)
        layout.addWidget(filename)

        metadata = asset.get("metadata") or {}
        models = metadata.get("models") or metadata.get("model_refs") or []
        loras = metadata.get("loras") or []
        width = metadata.get("width")
        height = metadata.get("height")
        sampler = (metadata.get("samplers") or [None])[0]
        seed = (metadata.get("seeds") or [None])[0]
        details = []
        if models:
            details.append(Path(str(models[0])).name)
        if loras:
            details.append(f"{len(loras)} LoRA" + ("s" if len(loras) != 1 else ""))
        if width and height:
            details.append(f"{width}×{height}")
        if sampler:
            details.append(str(sampler))
        if seed is not None:
            details.append(f"seed {seed}")
        summary = QLabel(" · ".join(details) or str(asset.get("media_type") or "file"))
        summary.setObjectName("muted")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        face_clusters = metadata.get("face_cluster_ids") or []
        if face_clusters:
            faces = QLabel(
                f"{metadata.get('face_count', len(face_clusters))} face(s) · "
                f"{len(face_clusters)} anonymous group(s)"
            )
            faces.setObjectName("muted")
            layout.addWidget(faces)

        footer = QLabel(
            f"{asset.get('group_id') or 'Private'} · "
            f"{str(asset.get('created_at') or '').replace('T', ' ')[:16]}"
        )
        footer.setObjectName("muted")
        layout.addWidget(footer)

        actions = QHBoxLayout()
        open_button = QPushButton("Open")
        open_button.clicked.connect(lambda: open_callback(asset))
        actions.addWidget(open_button)
        details_button = QPushButton("Details")
        details_button.clicked.connect(lambda: details_callback(asset))
        actions.addWidget(details_button)
        layout.addLayout(actions)


class GalleryPage(QWidget):
    def __init__(self, api: DesktopApi) -> None:
        super().__init__()
        self.api = api
        self.assets: list[dict[str, Any]] = []
        self.facets: dict[str, list[str]] = {}
        self.thumbnail_labels: dict[str, QLabel] = {}
        self.open_workers: set[OpenAssetWorker] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(12)
        title = QLabel("Outputs")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(
            "Private media library with Comfy provenance, model metadata, advanced filtering, and anonymous face groups."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search filenames, prompts, workflows, models, LoRAs, tags…")
        self.search.textChanged.connect(self.render)
        root.addWidget(self.search)

        filters = QHBoxLayout()
        self.model_filter = self._combo("All models")
        self.lora_filter = self._combo("All LoRAs")
        self.sampler_filter = self._combo("All samplers")
        self.media_filter = self._combo("All media")
        self.group_filter = self._combo("All groups")
        self.face_filter = self._combo("All face groups")
        for combo in (
            self.model_filter,
            self.lora_filter,
            self.sampler_filter,
            self.media_filter,
            self.group_filter,
            self.face_filter,
        ):
            combo.currentIndexChanged.connect(self.render)
            filters.addWidget(combo)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_filters)
        filters.addWidget(clear)
        root.addLayout(filters)

        self.count_label = QLabel("0 outputs")
        self.count_label.setObjectName("muted")
        root.addWidget(self.count_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        scroll.setWidget(self.body)
        root.addWidget(scroll, 1)

        self.thumbnail_worker = ThumbnailWorker(api)
        self.thumbnail_worker.ready.connect(self._thumbnail_ready)
        self.thumbnail_worker.start()

    @staticmethod
    def _combo(default: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem(default, None)
        combo.setMinimumWidth(115)
        return combo

    @staticmethod
    def _set_combo(combo: QComboBox, default: str, values: list[str]) -> None:
        selected = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(default, None)
        for value in values:
            combo.addItem(Path(value).name if "/" in value or "\\" in value else value, value)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.assets = list(snapshot.get("assets") or [])
        self.facets = snapshot.get("asset_facets") or {}
        models = sorted(
            set((self.facets.get("models") or []) + (self.facets.get("model_refs") or [])),
            key=str.casefold,
        )
        self._set_combo(self.model_filter, "All models", models)
        self._set_combo(self.lora_filter, "All LoRAs", self.facets.get("loras") or [])
        self._set_combo(self.sampler_filter, "All samplers", self.facets.get("samplers") or [])
        self._set_combo(self.media_filter, "All media", self.facets.get("media_families") or [])
        self._set_combo(self.group_filter, "All groups", self.facets.get("groups") or [])
        self._set_combo(self.face_filter, "All face groups", self.facets.get("face_clusters") or [])
        self.render()

    def clear_filters(self) -> None:
        self.search.clear()
        for combo in (
            self.model_filter,
            self.lora_filter,
            self.sampler_filter,
            self.media_filter,
            self.group_filter,
            self.face_filter,
        ):
            combo.setCurrentIndex(0)
        self.render()

    def _matches(self, asset: dict[str, Any]) -> bool:
        metadata = asset.get("metadata") or {}
        model = self.model_filter.currentData()
        lora = self.lora_filter.currentData()
        sampler = self.sampler_filter.currentData()
        media = self.media_filter.currentData()
        group = self.group_filter.currentData()
        face = self.face_filter.currentData()
        if model and model not in (metadata.get("models") or []) + (metadata.get("model_refs") or []):
            return False
        if lora and lora not in (metadata.get("loras") or []):
            return False
        if sampler and sampler not in (metadata.get("samplers") or []):
            return False
        if media and not str(asset.get("media_type") or "").startswith(str(media) + "/"):
            return False
        if group and asset.get("group_id") != group:
            return False
        if face and face not in (metadata.get("face_cluster_ids") or []):
            return False
        q = self.search.text().strip().casefold()
        if q:
            searchable = [
                str(asset.get("filename") or ""),
                str(metadata.get("workflow_name") or ""),
                *(str(value) for value in metadata.get("tags") or []),
                *(str(value) for value in metadata.get("models") or []),
                *(str(value) for value in metadata.get("model_refs") or []),
                *(str(value) for value in metadata.get("loras") or []),
                *(str(value) for value in metadata.get("prompts") or []),
            ]
            if not any(q in value.casefold() for value in searchable):
                return False
        return True

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.thumbnail_labels.clear()

    def render(self) -> None:
        self._clear_grid()
        filtered = [asset for asset in self.assets if self._matches(asset)][:300]
        self.count_label.setText(f"{len(filtered)} output{'s' if len(filtered) != 1 else ''}")
        if not filtered:
            empty = QLabel("No authorized outputs match these filters.")
            empty.setObjectName("muted")
            self.grid.addWidget(empty, 0, 0)
            return
        columns = 3
        for index, asset in enumerate(filtered):
            card = GalleryCard(asset, self.open_asset, self.show_details)
            row, column = divmod(index, columns)
            self.grid.addWidget(card, row, column)
            asset_id = str(asset.get("asset_id") or "")
            if str(asset.get("media_type") or "").startswith("image/"):
                self.thumbnail_labels[asset_id] = card.preview
                self.thumbnail_worker.enqueue(asset_id)
        self.grid.setRowStretch((len(filtered) + columns - 1) // columns, 1)

    def _thumbnail_ready(self, asset_id: str, path: str) -> None:
        label = self.thumbnail_labels.get(asset_id)
        if label is None:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        label.setPixmap(
            pixmap.scaled(
                label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def open_asset(self, asset: dict[str, Any]) -> None:
        worker = OpenAssetWorker(self.api, asset)
        self.open_workers.add(worker)
        worker.ready.connect(lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        worker.failed.connect(lambda message: QMessageBox.warning(self, "ComfyCluster", message))
        worker.finished.connect(lambda w=worker: self._cleanup_open_worker(w))
        worker.start()

    def _cleanup_open_worker(self, worker: OpenAssetWorker) -> None:
        self.open_workers.discard(worker)
        worker.deleteLater()

    def show_details(self, asset: dict[str, Any]) -> None:
        metadata = asset.get("metadata") or {}
        lines = [
            str(asset.get("filename") or "output"),
            f"Group: {asset.get('group_id') or 'Private'}",
            f"Media: {asset.get('media_type') or 'unknown'}",
            f"Size: {asset.get('size_bytes') or 0:,} bytes",
            f"Workflow: {metadata.get('workflow_name') or 'Unnamed'}",
            f"Models: {', '.join(metadata.get('models') or metadata.get('model_refs') or []) or '—'}",
            f"LoRAs: {', '.join(metadata.get('loras') or []) or '—'}",
            f"Sampler: {', '.join(metadata.get('samplers') or []) or '—'}",
            f"Scheduler: {', '.join(metadata.get('schedulers') or []) or '—'}",
            f"Seed: {', '.join(str(v) for v in metadata.get('seeds') or []) or '—'}",
            f"Steps: {', '.join(str(v) for v in metadata.get('steps') or []) or '—'}",
            f"CFG: {', '.join(str(v) for v in metadata.get('cfg_scales') or []) or '—'}",
            f"Dimensions: {metadata.get('width') or '?'} × {metadata.get('height') or '?'}",
            f"GPU: {metadata.get('gpu_name') or '—'}",
            f"Runtime: {metadata.get('runtime_seconds') or '—'} s",
            f"Faces: {metadata.get('face_count', 0)}",
            f"Face groups: {', '.join(metadata.get('face_cluster_ids') or []) or '—'}",
            f"Tags: {', '.join(metadata.get('tags') or []) or '—'}",
        ]
        prompts = metadata.get("prompts") or []
        if prompts:
            lines.append("\nPrompt metadata:\n" + "\n\n".join(str(value)[:3000] for value in prompts[:4]))
        QMessageBox.information(self, "Output metadata", "\n".join(lines))

    def close(self) -> bool:
        self.thumbnail_worker.stop()
        self.thumbnail_worker.wait(2000)
        return super().close()
