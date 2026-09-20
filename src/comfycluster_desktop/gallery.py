from __future__ import annotations

import queue
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, QTimer, QUrl, Signal, Qt
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


class PreviewAssetWorker(QThread):
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, api: DesktopApi, asset_id: str) -> None:
        super().__init__()
        self.api = api
        self.asset_id = asset_id

    def run(self) -> None:
        try:
            path = self.api.download_preview(self.asset_id)
            self.ready.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))


class GalleryQueryWorker(QThread):
    ready = Signal(object, int)
    failed = Signal(str, int)

    def __init__(self, api: DesktopApi, filters: dict[str, Any], generation: int) -> None:
        super().__init__()
        self.api = api
        self.filters = filters
        self.generation = generation

    def run(self) -> None:
        try:
            self.ready.emit(self.api.query_asset_page(**self.filters), self.generation)
        except Exception as exc:
            self.failed.emit(str(exc), self.generation)


class AssetDetailWorker(QThread):
    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, api: DesktopApi, asset_id: str) -> None:
        super().__init__()
        self.api = api
        self.asset_id = asset_id

    def run(self) -> None:
        try:
            self.ready.emit(self.api.asset_detail(self.asset_id))
        except Exception as exc:
            self.failed.emit(str(exc))


def _duration_text(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return None
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class GalleryCard(QFrame):
    def __init__(self, asset: dict[str, Any], open_callback, preview_callback, details_callback) -> None:
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
        self.preview.setText(
            "IMAGE" if media.startswith("image/") else "VIDEO" if media.startswith("video/") else "FILE"
        )
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
        duration = _duration_text(metadata.get("duration_seconds"))
        details = []
        if models:
            details.append(Path(str(models[0])).name)
        if loras:
            details.append(f"{len(loras)} LoRA" + ("s" if len(loras) != 1 else ""))
        if width and height:
            details.append(f"{width}×{height}")
        if duration:
            details.append(duration)
        if metadata.get("video_codec"):
            details.append(str(metadata.get("video_codec")).upper())
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
        if media.startswith("video/"):
            preview_button = QPushButton("Preview")
            preview_button.clicked.connect(lambda: preview_callback(asset))
            actions.addWidget(preview_button)
        open_button = QPushButton("Open")
        open_button.clicked.connect(lambda: open_callback(asset))
        actions.addWidget(open_button)
        details_button = QPushButton("Details")
        details_button.clicked.connect(lambda: details_callback(asset))
        actions.addWidget(details_button)
        layout.addLayout(actions)


class GalleryPage(QWidget):
    PAGE_SIZE = 60

    def __init__(self, api: DesktopApi) -> None:
        super().__init__()
        self.api = api
        self.assets: list[dict[str, Any]] = []
        self.facets: dict[str, list[str]] = {}
        self.page: dict[str, Any] = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": self.PAGE_SIZE,
            "has_more": False,
            "sort_by": "created_at",
            "sort_order": "desc",
        }
        self.thumbnail_labels: dict[str, QLabel] = {}
        self.open_workers: set[OpenAssetWorker] = set()
        self.preview_workers: set[PreviewAssetWorker] = set()
        self.query_workers: set[GalleryQueryWorker] = set()
        self.detail_workers: set[AssetDetailWorker] = set()
        self.generation = 0
        self.initialized = False

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(12)
        title = QLabel("Outputs")
        title.setObjectName("title")
        root.addWidget(title)
        subtitle = QLabel(
            "Private paginated media library with Comfy provenance, model metadata, video previews, advanced filtering, and anonymous face groups."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search filenames, prompts, workflows, models, LoRAs, codecs, tags…")
        root.addWidget(self.search)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(lambda: self.refresh_page(reset=True))
        self.search.textChanged.connect(lambda _text: self.search_timer.start())

        filters = QHBoxLayout()
        self.model_filter = self._combo("All models")
        self.lora_filter = self._combo("All LoRAs")
        self.sampler_filter = self._combo("All samplers")
        self.media_filter = self._combo("All media")
        self.codec_filter = self._combo("All video codecs")
        self.group_filter = self._combo("All groups")
        self.face_filter = self._combo("All face groups")
        for combo in (
            self.model_filter,
            self.lora_filter,
            self.sampler_filter,
            self.media_filter,
            self.codec_filter,
            self.group_filter,
            self.face_filter,
        ):
            combo.currentIndexChanged.connect(lambda _index: self.refresh_page(reset=True))
            filters.addWidget(combo)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_filters)
        filters.addWidget(clear)
        root.addLayout(filters)

        navigation = QHBoxLayout()
        self.count_label = QLabel("0 outputs")
        self.count_label.setObjectName("muted")
        navigation.addWidget(self.count_label)
        navigation.addStretch(1)

        self.sort_filter = QComboBox()
        self.sort_filter.addItem("Newest", ("created_at", "desc"))
        self.sort_filter.addItem("Oldest", ("created_at", "asc"))
        self.sort_filter.addItem("Largest", ("size_bytes", "desc"))
        self.sort_filter.addItem("Smallest", ("size_bytes", "asc"))
        self.sort_filter.addItem("Longest video", ("duration_seconds", "desc"))
        self.sort_filter.addItem("Filename A–Z", ("filename", "asc"))
        self.sort_filter.currentIndexChanged.connect(lambda _index: self.refresh_page(reset=True))
        navigation.addWidget(self.sort_filter)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(lambda: self.refresh_page(reset=False))
        navigation.addWidget(refresh_button)
        self.previous_button = QPushButton("Previous")
        self.previous_button.clicked.connect(self.previous_page)
        navigation.addWidget(self.previous_button)
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.next_page)
        navigation.addWidget(self.next_button)
        root.addLayout(navigation)

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
        self._update_navigation()

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
        self.facets = snapshot.get("asset_facets") or {}
        models = sorted(
            set((self.facets.get("models") or []) + (self.facets.get("model_refs") or [])),
            key=str.casefold,
        )
        self._set_combo(self.model_filter, "All models", models)
        self._set_combo(self.lora_filter, "All LoRAs", self.facets.get("loras") or [])
        self._set_combo(self.sampler_filter, "All samplers", self.facets.get("samplers") or [])
        self._set_combo(self.media_filter, "All media", self.facets.get("media_families") or [])
        self._set_combo(self.codec_filter, "All video codecs", self.facets.get("video_codecs") or [])
        self._set_combo(self.group_filter, "All groups", self.facets.get("groups") or [])
        self._set_combo(self.face_filter, "All face groups", self.facets.get("face_clusters") or [])
        if not self.initialized:
            page = snapshot.get("asset_page") or {
                "items": snapshot.get("assets") or [],
                "total": len(snapshot.get("assets") or []),
                "offset": 0,
                "limit": self.PAGE_SIZE,
                "has_more": False,
                "sort_by": "created_at",
                "sort_order": "desc",
            }
            self._apply_page(page)
            self.initialized = True

    def clear_filters(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        for combo in (
            self.model_filter,
            self.lora_filter,
            self.sampler_filter,
            self.media_filter,
            self.codec_filter,
            self.group_filter,
            self.face_filter,
        ):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.sort_filter.blockSignals(True)
        self.sort_filter.setCurrentIndex(0)
        self.sort_filter.blockSignals(False)
        self.refresh_page(reset=True)

    def _query_filters(self, offset: int | None = None) -> dict[str, Any]:
        sort_by, sort_order = self.sort_filter.currentData() or ("created_at", "desc")
        return {
            "q": self.search.text().strip() or None,
            "model": self.model_filter.currentData(),
            "lora": self.lora_filter.currentData(),
            "sampler": self.sampler_filter.currentData(),
            "media_family": self.media_filter.currentData(),
            "video_codec": self.codec_filter.currentData(),
            "group_id": self.group_filter.currentData(),
            "face_cluster_id": self.face_filter.currentData(),
            "offset": self.page.get("offset", 0) if offset is None else offset,
            "limit": self.PAGE_SIZE,
            "sort_by": sort_by,
            "sort_order": sort_order,
        }

    def refresh_page(self, *, reset: bool) -> None:
        offset = 0 if reset else int(self.page.get("offset") or 0)
        self.generation += 1
        generation = self.generation
        self.count_label.setText("Searching…")
        worker = GalleryQueryWorker(self.api, self._query_filters(offset), generation)
        self.query_workers.add(worker)
        worker.ready.connect(self._query_ready)
        worker.failed.connect(self._query_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_query_worker(w))
        worker.start()

    def _query_ready(self, page: dict[str, Any], generation: int) -> None:
        if generation != self.generation:
            return
        self._apply_page(page)

    def _query_failed(self, message: str, generation: int) -> None:
        if generation != self.generation:
            return
        self.count_label.setText("Gallery query failed")
        QMessageBox.warning(self, "ComfyCluster gallery", message)

    def _cleanup_query_worker(self, worker: GalleryQueryWorker) -> None:
        self.query_workers.discard(worker)
        worker.deleteLater()

    def previous_page(self) -> None:
        offset = max(0, int(self.page.get("offset") or 0) - self.PAGE_SIZE)
        self._query_offset(offset)

    def next_page(self) -> None:
        if not self.page.get("has_more"):
            return
        offset = int(self.page.get("offset") or 0) + int(self.page.get("limit") or self.PAGE_SIZE)
        self._query_offset(offset)

    def _query_offset(self, offset: int) -> None:
        self.generation += 1
        generation = self.generation
        self.count_label.setText("Loading page…")
        worker = GalleryQueryWorker(self.api, self._query_filters(offset), generation)
        self.query_workers.add(worker)
        worker.ready.connect(self._query_ready)
        worker.failed.connect(self._query_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_query_worker(w))
        worker.start()

    def _apply_page(self, page: dict[str, Any]) -> None:
        self.page = page
        self.assets = list(page.get("items") or [])
        self.render()
        self._update_navigation()

    def _update_navigation(self) -> None:
        total = int(self.page.get("total") or 0)
        offset = int(self.page.get("offset") or 0)
        count = len(self.assets)
        if total and count:
            self.count_label.setText(f"Showing {offset + 1:,}–{offset + count:,} of {total:,} outputs")
        else:
            self.count_label.setText("0 outputs")
        self.previous_button.setEnabled(offset > 0)
        self.next_button.setEnabled(bool(self.page.get("has_more")))

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.thumbnail_labels.clear()

    def render(self) -> None:
        self._clear_grid()
        if not self.assets:
            empty = QLabel("No authorized outputs match these filters.")
            empty.setObjectName("muted")
            self.grid.addWidget(empty, 0, 0)
            return
        columns = 3
        for index, asset in enumerate(self.assets):
            card = GalleryCard(asset, self.open_asset, self.preview_asset, self.show_details)
            row, column = divmod(index, columns)
            self.grid.addWidget(card, row, column)
            asset_id = str(asset.get("asset_id") or "")
            media_type = str(asset.get("media_type") or "")
            if media_type.startswith("image/") or media_type.startswith("video/"):
                self.thumbnail_labels[asset_id] = card.preview
                self.thumbnail_worker.enqueue(asset_id)
        self.grid.setRowStretch((len(self.assets) + columns - 1) // columns, 1)

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

    def preview_asset(self, asset: dict[str, Any]) -> None:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id:
            return
        worker = PreviewAssetWorker(self.api, asset_id)
        self.preview_workers.add(worker)
        worker.ready.connect(lambda path: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        worker.failed.connect(
            lambda message: QMessageBox.warning(
                self,
                "Video preview unavailable",
                message + "\n\nThe full archived video can still be opened.",
            )
        )
        worker.finished.connect(lambda w=worker: self._cleanup_preview_worker(w))
        worker.start()

    def show_details(self, asset: dict[str, Any]) -> None:
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id:
            return
        worker = AssetDetailWorker(self.api, asset_id)
        self.detail_workers.add(worker)
        worker.ready.connect(self._show_detail_dialog)
        worker.failed.connect(lambda message: QMessageBox.warning(self, "Output metadata", message))
        worker.finished.connect(lambda w=worker: self._cleanup_detail_worker(w))
        worker.start()

    def _show_detail_dialog(self, asset: dict[str, Any]) -> None:
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
            f"Duration: {_duration_text(metadata.get('duration_seconds')) or '—'}",
            f"Frames: {metadata.get('frame_count') or '—'}",
            f"Frame rate: {metadata.get('frame_rate') or '—'} fps",
            f"Video codec: {metadata.get('video_codec') or '—'}",
            f"Audio codec: {metadata.get('audio_codec') or '—'}",
            f"Container: {metadata.get('container_format') or '—'}",
            f"Bit rate: {metadata.get('bit_rate_bps') or '—'} bps",
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

    def _cleanup_open_worker(self, worker: OpenAssetWorker) -> None:
        self.open_workers.discard(worker)
        worker.deleteLater()

    def _cleanup_preview_worker(self, worker: PreviewAssetWorker) -> None:
        self.preview_workers.discard(worker)
        worker.deleteLater()

    def _cleanup_detail_worker(self, worker: AssetDetailWorker) -> None:
        self.detail_workers.discard(worker)
        worker.deleteLater()

    def close(self) -> bool:
        self.thumbnail_worker.stop()
        self.thumbnail_worker.wait(2000)
        return super().close()
