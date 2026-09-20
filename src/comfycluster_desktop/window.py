from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, QUrl, Signal, Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .api import DesktopApi
from .settings import DesktopSettings

APP_STYLE = """
QMainWindow, QWidget { background: #101114; color: #eceff3; }
QLabel { background: transparent; }
QFrame#sidebar { background: #14161a; border-right: 1px solid #292d33; }
QFrame#card { background: #191c21; border: 1px solid #2c3138; border-radius: 12px; }
QLabel#muted { color: #9299a3; }
QLabel#title { font-size: 24px; font-weight: 700; }
QLabel#sectionTitle { font-size: 16px; font-weight: 650; }
QLabel#metricValue { font-size: 25px; font-weight: 700; }
QPushButton { background: #24282e; border: 1px solid #3a4048; border-radius: 7px; padding: 8px 12px; color: #eef1f5; }
QPushButton:hover { background: #2d323a; }
QPushButton:pressed { background: #1e2227; }
QPushButton#primary { background: #e87522; border-color: #f58a35; color: white; font-weight: 650; }
QPushButton#primary:hover { background: #f07e29; }
QPushButton#nav { text-align: left; border: 0; border-radius: 7px; padding: 10px 12px; background: transparent; color: #aab0b8; }
QPushButton#nav:hover { background: #202329; color: white; }
QPushButton#nav:checked { background: #29231f; color: #ff9a4e; }
QTableWidget { background: #17191d; border: 1px solid #2c3138; border-radius: 10px; gridline-color: #292d33; selection-background-color: #363b43; }
QHeaderView::section { background: #202329; color: #cdd2d9; border: 0; border-bottom: 1px solid #343941; padding: 8px; }
QScrollArea { border: 0; }
"""


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


def fmt_size(size: int | None) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return "0 B"


def badge(text: str, tone: str = "neutral") -> QLabel:
    palette = {
        "good": ("#173b2d", "#83e6b6"),
        "warn": ("#493914", "#ffd46e"),
        "bad": ("#481f24", "#ff9ca7"),
        "accent": ("#3d2b1d", "#ffad6d"),
        "neutral": ("#292d33", "#c5cad1"),
    }
    background, foreground = palette.get(tone, palette["neutral"])
    label = QLabel(text)
    label.setStyleSheet(
        f"background:{background};color:{foreground};border-radius:9px;padding:3px 8px;font-size:11px;"
    )
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return label


class Card(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(9)


class SnapshotPoller(QThread):
    snapshot_ready = Signal(object)

    def __init__(self, api: DesktopApi, interval_seconds: float) -> None:
        super().__init__()
        self.api = api
        self.interval = max(1.0, interval_seconds)
        self._stop_event = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.snapshot_ready.emit(self.api.snapshot())
            self._wake.wait(self.interval)
            self._wake.clear()

    def refresh_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()


class ActionRunner(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, action: Callable[[], Any]) -> None:
        super().__init__()
        self.action = action

    def run(self) -> None:
        try:
            self.succeeded.emit(self.action())
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, settings: DesktopSettings) -> None:
        super().__init__()
        self.settings = settings
        self.api = DesktopApi(settings)
        self.snapshot: dict[str, Any] = {}
        self.runners: set[ActionRunner] = set()
        self.setWindowTitle("ComfyCluster")
        self.resize(1280, 820)
        self.setMinimumSize(980, 650)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 18, 14, 14)
        side.setSpacing(5)
        logo = QLabel("ComfyCluster")
        logo.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        side.addWidget(logo)
        subtitle = QLabel("ComfyUI fleet manager")
        subtitle.setObjectName("muted")
        side.addWidget(subtitle)
        side.addSpacing(18)

        self.stack = QStackedWidget()
        self.home_layout = self._scroll_page("Home", "This workstation and its ComfyUI workers.")
        self.comfy_layout = self._scroll_page(
            "Comfy Environments", "Managed ComfyUI runtimes on this workstation."
        )
        self.models_table = self._table_page(
            "Models",
            "Cluster model inventory and availability.",
            ["Model", "Type", "Size", "This PC", "Cluster"],
        )
        self.nodes_table = self._table_page(
            "Custom Nodes",
            "Custom-node packages visible across the fleet.",
            ["Node", "This PC Commit", "Hosts", "Status"],
        )
        self.outputs_table = self._table_page(
            "Outputs",
            "Archived files authorized for your account and private groups. Double-click to open.",
            ["File", "Type", "Size", "Group", "Created", "Job"],
        )
        self.outputs_table.cellDoubleClicked.connect(self.open_output_asset)
        self.cluster_layout = self._scroll_page(
            "Cluster", "Windows hosts and GPU workers visible to your account."
        )
        self.settings_layout = self._scroll_page(
            "Settings", "Desktop connection and local agent information."
        )

        labels = ["Home", "Comfy", "Models", "Custom Nodes", "Outputs", "Cluster", "Settings"]
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(labels):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self.set_page(i))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addStretch(1)
        self.connection_badge = badge("Starting...", "neutral")
        side.addWidget(self.connection_badge)
        self.identity_label = QLabel("Not signed in")
        self.identity_label.setObjectName("muted")
        self.identity_label.setWordWrap(True)
        side.addWidget(self.identity_label)

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        self.set_page(0)

        self.poller = SnapshotPoller(self.api, settings.desktop_refresh_seconds)
        self.poller.snapshot_ready.connect(self.apply_snapshot)
        self.poller.start()

    def _page_header(self, page: QWidget, title: str, subtitle: str) -> QVBoxLayout:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(14)
        title_label = QLabel(title)
        title_label.setObjectName("title")
        layout.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("muted")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
        return layout

    def _scroll_page(self, title: str, subtitle: str) -> QVBoxLayout:
        page = QWidget()
        root = self._page_header(page, title, subtitle)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self.stack.addWidget(page)
        return body_layout

    def _table_page(self, title: str, subtitle: str, columns: list[str]) -> QTableWidget:
        page = QWidget()
        root = self._page_header(page, title, subtitle)
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        root.addWidget(table, 1)
        self.stack.addWidget(page)
        return table

    def set_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for nav_index, button in enumerate(self.nav_buttons):
            button.setChecked(nav_index == index)

    def apply_snapshot(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        local = snapshot.get("local") or {}
        if local and local.get("controller_connected") and not snapshot.get("controller_error"):
            text, tone = "Cluster connected", "good"
        elif local and not snapshot.get("local_error"):
            text, tone = "Local mode", "warn"
        else:
            text, tone = "Agent offline", "bad"
        styled = badge(text, tone)
        self.connection_badge.setText(text)
        self.connection_badge.setStyleSheet(styled.styleSheet())
        styled.deleteLater()
        me = snapshot.get("me") or {}
        self.identity_label.setText(str(me.get("display_name") or "Not signed in"))
        self._render_home()
        self._render_comfy()
        self._render_models()
        self._render_nodes()
        self._render_outputs()
        self._render_cluster()
        self._render_settings()

    def _registration(self) -> dict:
        return (self.snapshot.get("local") or {}).get("registration") or {}

    def _is_admin(self) -> bool:
        return bool((self.snapshot.get("me") or {}).get("platform_admin"))

    def _render_identity_and_queue(self) -> None:
        me = self.snapshot.get("me") or {}
        queue = self.snapshot.get("queue_summary") or {}
        if not me:
            if self.snapshot.get("controller_error"):
                card = Card()
                title = QLabel("Cluster sign-in required")
                title.setObjectName("sectionTitle")
                card.body.addWidget(title)
                detail = QLabel(
                    "Local Comfy controls still work. Ask a ComfyCluster administrator for a user token "
                    "to access private group jobs and cluster services."
                )
                detail.setObjectName("muted")
                detail.setWordWrap(True)
                card.body.addWidget(detail)
                self.home_layout.addWidget(card)
            return

        card = Card()
        top = QHBoxLayout()
        identity = QVBoxLayout()
        name = QLabel(str(me.get("display_name") or me.get("user_id") or "User"))
        name.setObjectName("sectionTitle")
        identity.addWidget(name)
        groups = me.get("group_ids") or []
        group_text = ", ".join(str(item) for item in groups) if groups else "No private group assigned"
        group_label = QLabel(group_text)
        group_label.setObjectName("muted")
        identity.addWidget(group_label)
        top.addLayout(identity, 1)
        top.addWidget(badge("PLATFORM ADMIN" if me.get("platform_admin") else "PRIVATE GROUPS", "accent"))
        card.body.addLayout(top)

        user_queue = queue.get("user") or {}
        own = QLabel(
            f"Your queue: {user_queue.get('running', 0)} running  |  "
            f"{user_queue.get('queued', 0)} waiting"
        )
        own.setObjectName("muted")
        card.body.addWidget(own)

        for group in queue.get("groups") or []:
            policy = group.get("policy") or {}
            row = QHBoxLayout()
            row.addWidget(QLabel(str(group.get("name") or group.get("group_id") or "Group")), 1)
            row.addWidget(
                QLabel(
                    f"{group.get('running', 0)} / {policy.get('max_running_jobs', '?')} running"
                )
            )
            row.addWidget(
                QLabel(f"{group.get('queued', 0)} / {policy.get('max_queued_jobs', '?')} queued")
            )
            row.addWidget(badge(f"weight {policy.get('weight', 1)}", "neutral"))
            card.body.addLayout(row)
        self.home_layout.addWidget(card)

    def _render_home(self) -> None:
        clear_layout(self.home_layout)
        registration = self._registration()
        gpus = registration.get("gpus") or []
        workers = registration.get("workers") or []
        total_vram = sum(int(gpu.get("memory_total_mb") or 0) for gpu in gpus)
        running = sum(
            1 for worker in workers if worker.get("state") not in {"stopped", "offline"}
        )
        connected = bool((self.snapshot.get("local") or {}).get("controller_connected"))

        metrics = QHBoxLayout()
        for label, value in (
            ("GPUs", str(len(gpus))),
            ("VRAM", f"{total_vram / 1024:.0f} GB" if total_vram else "0 GB"),
            ("Workers", f"{running} / {len(workers)}"),
            ("Cluster", "Connected" if connected else "Offline"),
        ):
            card = Card()
            caption = QLabel(label)
            caption.setObjectName("muted")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            card.body.addWidget(caption)
            card.body.addWidget(value_label)
            metrics.addWidget(card)
        self.home_layout.addLayout(metrics)
        self._render_identity_and_queue()

        env = Card()
        comfy = registration.get("comfy") or {}
        top = QHBoxLayout()
        name_box = QVBoxLayout()
        title = QLabel("Production Comfy")
        title.setObjectName("sectionTitle")
        name_box.addWidget(title)
        path = QLabel(comfy.get("path") or "ComfyUI installation not detected")
        path.setObjectName("muted")
        path.setWordWrap(True)
        name_box.addWidget(path)
        top.addLayout(name_box, 1)
        host = self.snapshot.get("local_host") or {}
        if not registration:
            top.addWidget(badge("Agent unavailable", "bad"))
        elif host.get("draining"):
            top.addWidget(badge("Draining", "warn"))
        elif connected:
            top.addWidget(badge("Cluster ready", "good"))
        else:
            top.addWidget(badge("Local only", "warn"))
        env.body.addLayout(top)
        detail = QLabel(
            f"Comfy {comfy.get('version') or 'unversioned'}  |  "
            f"{len(registration.get('nodes') or [])} node packages  |  "
            f"{len(registration.get('models') or [])} model files"
        )
        detail.setObjectName("muted")
        env.body.addWidget(detail)
        actions = QHBoxLayout()
        open_button = QPushButton("Open ComfyUI")
        open_button.setObjectName("primary")
        open_button.clicked.connect(self.open_local_comfy)
        actions.addWidget(open_button)
        for label, operation in (("Start All", "start"), ("Stop All", "stop")):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, op=operation: self.local_fleet_action(op)
            )
            actions.addWidget(button)
        restart = QPushButton("Restart All")
        restart.clicked.connect(self.restart_all_workers)
        actions.addWidget(restart)
        if host and self._is_admin():
            operation = "resume" if host.get("draining") else "drain"
            drain = QPushButton("Resume Host" if host.get("draining") else "Drain Host")
            drain.clicked.connect(lambda _checked=False, op=operation: self.host_mode(op))
            actions.addWidget(drain)
        actions.addStretch(1)
        env.body.addLayout(actions)
        self.home_layout.addWidget(env)

        workers_title = QLabel("GPU Workers")
        workers_title.setObjectName("sectionTitle")
        self.home_layout.addWidget(workers_title)
        if not workers:
            empty = QLabel("No local GPU workers discovered yet.")
            empty.setObjectName("muted")
            self.home_layout.addWidget(empty)
        for worker in workers:
            gpu = next((item for item in gpus if item.get("uuid") == worker.get("gpu_uuid")), {})
            card = Card()
            row = QHBoxLayout()
            info = QVBoxLayout()
            name = QLabel(gpu.get("name") or worker.get("worker_id") or "GPU Worker")
            name.setObjectName("sectionTitle")
            info.addWidget(name)
            details = QLabel(
                f"GPU {worker.get('gpu_index')}  |  port {worker.get('port')}  |  "
                f"VRAM {gpu.get('memory_used_mb', 0)} / {gpu.get('memory_total_mb', 0)} MB  |  "
                f"utilization {gpu.get('utilization_percent', 0)}%"
            )
            details.setObjectName("muted")
            info.addWidget(details)
            row.addLayout(info, 1)
            state = str(worker.get("state") or "unknown")
            tone = "good" if state == "idle" else "warn" if state in {"busy", "starting"} else "bad"
            row.addWidget(badge(state.upper(), tone))
            for label, operation in (("Start", "start"), ("Restart", "restart"), ("Stop", "stop")):
                button = QPushButton(label)
                worker_id = str(worker.get("worker_id"))
                button.clicked.connect(
                    lambda _checked=False, wid=worker_id, op=operation: self.local_worker_action(wid, op)
                )
                row.addWidget(button)
            card.body.addLayout(row)
            self.home_layout.addWidget(card)
        self.home_layout.addStretch(1)

    def _render_comfy(self) -> None:
        clear_layout(self.comfy_layout)
        registration = self._registration()
        comfy = registration.get("comfy") or {}
        desired = self.snapshot.get("desired_release") or {}
        plan = self.snapshot.get("release_plan") or {}
        host_id = self.snapshot.get("host_id")
        host_plan = next(
            (item for item in plan.get("hosts", []) if item.get("host_id") == host_id), {}
        )
        card = Card()
        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Production")
        title.setObjectName("sectionTitle")
        title_box.addWidget(title)
        path = QLabel(comfy.get("path") or "No ComfyUI installation detected")
        path.setObjectName("muted")
        path.setWordWrap(True)
        title_box.addWidget(path)
        top.addLayout(title_box, 1)
        if host_plan:
            top.addWidget(
                badge(
                    "IN SYNC" if host_plan.get("in_sync") else "DRIFT",
                    "good" if host_plan.get("in_sync") else "warn",
                )
            )
        card.body.addLayout(top)
        for key, value in (
            ("Comfy version", comfy.get("version") or "Unknown"),
            ("Git commit", comfy.get("git_commit") or "Unknown"),
            ("Python", comfy.get("python_executable") or "Unknown"),
            ("Fleet release", desired.get("name") or "Not configured"),
            ("Custom nodes", str(len(registration.get("nodes") or []))),
            ("Models", str(len(registration.get("models") or []))),
        ):
            row = QHBoxLayout()
            label = QLabel(key)
            label.setObjectName("muted")
            row.addWidget(label)
            row.addStretch(1)
            row.addWidget(QLabel(str(value)))
            card.body.addLayout(row)
        if host_plan.get("drift"):
            drift = QLabel(
                "Drift: " + ", ".join(item.get("kind", "unknown") for item in host_plan["drift"])
            )
            drift.setStyleSheet("color:#ffd46e;")
            drift.setWordWrap(True)
            card.body.addWidget(drift)
        buttons = QHBoxLayout()
        open_button = QPushButton("Open ComfyUI")
        open_button.setObjectName("primary")
        open_button.clicked.connect(self.open_local_comfy)
        buttons.addWidget(open_button)
        refresh = QPushButton("Refresh Inventory")
        refresh.clicked.connect(self.refresh_inventory)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        self.comfy_layout.addWidget(card)
        self.comfy_layout.addStretch(1)

    @staticmethod
    def _set_table(table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                table.setItem(row_index, column_index, QTableWidgetItem(value))

    def _render_models(self) -> None:
        registration = self._registration()
        local_keys = {
            (str(item.get("category", "")).casefold(), str(item.get("name", "")).casefold())
            for item in registration.get("models") or []
        }
        host_count = max(1, len(self.snapshot.get("hosts") or []))
        rows = []
        for item in self.snapshot.get("models") or []:
            key = (
                str(item.get("category", "")).casefold(),
                str(item.get("name", "")).casefold(),
            )
            rows.append(
                [
                    str(item.get("name") or ""),
                    str(item.get("category") or ""),
                    fmt_size(item.get("size_bytes")),
                    "Yes" if key in local_keys else "No",
                    f"{item.get('host_count', 0)} / {host_count}",
                ]
            )
        self._set_table(self.models_table, rows)

    def _render_nodes(self) -> None:
        host_id = self.snapshot.get("host_id")
        host_count = max(1, len(self.snapshot.get("hosts") or []))
        rows = []
        for item in self.snapshot.get("nodes") or []:
            hosts = item.get("hosts") or {}
            local = hosts.get(host_id) or {}
            commits = {
                str(value.get("git_commit"))
                for value in hosts.values()
                if value.get("git_commit")
            }
            status = "Consistent" if len(commits) <= 1 and len(hosts) == host_count else "Check fleet"
            rows.append(
                [
                    str(item.get("name") or ""),
                    str(local.get("git_commit") or "Not installed"),
                    f"{len(hosts)} / {host_count}",
                    status,
                ]
            )
        self._set_table(self.nodes_table, rows)

    def _render_outputs(self) -> None:
        assets = (self.snapshot.get("assets") or [])[:250]
        self.outputs_table.setRowCount(len(assets))
        for row_index, asset in enumerate(assets):
            media_type = str(asset.get("media_type") or "application/octet-stream")
            media_family = media_type.split("/", 1)[0].title() if "/" in media_type else media_type
            values = [
                str(asset.get("filename") or "output"),
                media_family,
                fmt_size(asset.get("size_bytes")),
                str(asset.get("group_id") or "Private"),
                str(asset.get("created_at") or "").replace("T", " ")[:19],
                str(asset.get("job_id") or "")[:12],
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column_index == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        {
                            "asset_id": str(asset.get("asset_id") or ""),
                            "filename": str(asset.get("filename") or "output.bin"),
                        },
                    )
                self.outputs_table.setItem(row_index, column_index, item)

    def _render_cluster(self) -> None:
        clear_layout(self.cluster_layout)
        hosts = self.snapshot.get("hosts") or []
        if not hosts:
            empty = QLabel("Controller has no registered hosts yet.")
            empty.setObjectName("muted")
            self.cluster_layout.addWidget(empty)
        for host in hosts:
            card = Card()
            top = QHBoxLayout()
            name_box = QVBoxLayout()
            name = QLabel(str(host.get("hostname") or host.get("host_id") or "Host"))
            name.setObjectName("sectionTitle")
            name_box.addWidget(name)
            summary = QLabel(
                f"{len(host.get('gpus') or [])} GPUs  |  {len(host.get('models') or [])} models  |  "
                f"{len(host.get('nodes') or [])} nodes"
            )
            summary.setObjectName("muted")
            name_box.addWidget(summary)
            top.addLayout(name_box, 1)
            if host.get("draining"):
                top.addWidget(badge("DRAINING", "warn"))
            top.addWidget(
                badge(
                    "ONLINE" if host.get("connected") else "OFFLINE",
                    "good" if host.get("connected") else "bad",
                )
            )
            if self._is_admin():
                host_id = str(host.get("host_id"))
                operation = "resume" if host.get("draining") else "drain"
                button = QPushButton("Resume" if host.get("draining") else "Drain")
                button.clicked.connect(
                    lambda _checked=False, hid=host_id, op=operation: self.host_mode(op, hid)
                )
                top.addWidget(button)
            card.body.addLayout(top)
            for worker in host.get("workers") or []:
                gpu = next(
                    (
                        item
                        for item in host.get("gpus") or []
                        if item.get("uuid") == worker.get("gpu_uuid")
                    ),
                    {},
                )
                row = QHBoxLayout()
                row.addWidget(QLabel(str(gpu.get("name") or worker.get("worker_id"))), 1)
                row.addWidget(QLabel(f"GPU {worker.get('gpu_index')}  :{worker.get('port')}"))
                row.addWidget(badge(str(worker.get("state") or "unknown").upper()))
                card.body.addLayout(row)
            self.cluster_layout.addWidget(card)
        self.cluster_layout.addStretch(1)

    def _render_settings(self) -> None:
        clear_layout(self.settings_layout)
        card = Card()
        me = self.snapshot.get("me") or {}
        local = self.snapshot.get("local") or {}
        for key, value in (
            ("Signed in as", me.get("display_name") or "Not signed in"),
            ("Controller", self.snapshot.get("controller_base") or ""),
            ("Local agent API", self.settings.local_api_url),
            ("Host ID", self.snapshot.get("host_id") or self.settings.host_id),
            ("Central output archive", "Enabled" if local.get("archive_outputs", True) else "Disabled"),
            (
                "Delete local after archive",
                "Enabled" if local.get("delete_local_outputs_after_archive") else "Disabled",
            ),
            ("Refresh interval", f"{self.settings.desktop_refresh_seconds:.1f} seconds"),
        ):
            row = QHBoxLayout()
            label = QLabel(key)
            label.setObjectName("muted")
            row.addWidget(label)
            row.addStretch(1)
            value_label = QLabel(str(value))
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(value_label)
            card.body.addLayout(row)
        buttons = QHBoxLayout()
        if self._is_admin():
            admin = QPushButton("Open Controller Admin")
            admin.clicked.connect(self.open_controller)
            buttons.addWidget(admin)
        refresh = QPushButton("Refresh Now")
        refresh.clicked.connect(self.refresh_now)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        card.body.addLayout(buttons)
        self.settings_layout.addWidget(card)
        self.settings_layout.addStretch(1)

    def _run_action(self, action: Callable[[], Any]) -> None:
        runner = ActionRunner(action)
        self.runners.add(runner)
        runner.succeeded.connect(lambda _result: self.refresh_now())
        runner.failed.connect(self._show_action_error)
        runner.finished.connect(lambda r=runner: self._cleanup_runner(r))
        runner.start()

    def _cleanup_runner(self, runner: ActionRunner) -> None:
        self.runners.discard(runner)
        runner.deleteLater()

    def _show_action_error(self, message: str) -> None:
        QMessageBox.warning(self, "ComfyCluster", message)

    def refresh_now(self) -> None:
        self.poller.refresh_now()

    def local_worker_action(self, worker_id: str, operation: str) -> None:
        self._run_action(lambda: self.api.local_worker_action(worker_id, operation))

    def local_fleet_action(self, operation: str) -> None:
        self._run_action(lambda: self.api.local_fleet_action(operation))

    def restart_all_workers(self) -> None:
        workers = self._registration().get("workers") or []

        def action():
            return [
                self.api.local_worker_action(str(worker.get("worker_id")), "restart")
                for worker in workers
            ]

        self._run_action(action)

    def refresh_inventory(self) -> None:
        self._run_action(self.api.refresh_local_inventory)

    def host_mode(self, operation: str, host_id: str | None = None) -> None:
        target = host_id or self.snapshot.get("host_id")
        if not target:
            self._show_action_error("Local host is not registered with the controller yet.")
            return
        self._run_action(lambda: self.api.host_mode(str(target), operation))

    def open_output_asset(self, row: int, _column: int) -> None:
        item = self.outputs_table.item(row, 0)
        payload = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(payload, dict):
            return
        asset_id = str(payload.get("asset_id") or "")
        filename = str(payload.get("filename") or "output.bin")
        if not asset_id:
            return

        runner = ActionRunner(lambda: self.api.download_asset(asset_id, filename))
        self.runners.add(runner)
        runner.succeeded.connect(self._open_downloaded_asset)
        runner.failed.connect(self._show_action_error)
        runner.finished.connect(lambda r=runner: self._cleanup_runner(r))
        runner.start()

    def _open_downloaded_asset(self, path: object) -> None:
        local_path = Path(str(path))
        if not local_path.is_file():
            self._show_action_error("The downloaded output is no longer available.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(local_path)))

    def open_local_comfy(self) -> None:
        workers = self._registration().get("workers") or []
        worker = next((item for item in workers if item.get("comfy_url")), None)
        if not worker:
            self._show_action_error("No local ComfyUI worker is available to open.")
            return
        QDesktopServices.openUrl(QUrl(str(worker.get("comfy_url"))))

    def open_controller(self) -> None:
        QDesktopServices.openUrl(QUrl(self.api.controller_base))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.poller.stop()
        self.poller.wait(3000)
        event.accept()


def run_desktop(settings: DesktopSettings | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComfyCluster")
    app.setOrganizationName("ComfyCluster")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = MainWindow(settings or DesktopSettings())
    window.show()
    return app.exec()
