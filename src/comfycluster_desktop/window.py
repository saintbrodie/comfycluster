from __future__ import annotations

import threading
from collections.abc import Callable
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
        widget = item.widget()
        child = item.layout()
        if widget:
            widget.deleteLater()
        elif child:
            clear_layout(child)


def fmt_size(size: int | None) -> str:
    value = float(size or 0)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def badge(text: str, tone: str = "neutral") -> QLabel:
    colors = {
        "good": ("#173b2d", "#83e6b6"),
        "warn": ("#493914", "#ffd46e"),
        "bad": ("#481f24", "#ff9ca7"),
        "accent": ("#3d2b1d", "#ffad6d"),
        "neutral": ("#292d33", "#c5cad1"),
    }
    background, foreground = colors.get(tone, colors["neutral"])
    label = QLabel(text)
    label.setStyleSheet(
        f"background:{background};color:{foreground};border-radius:9px;padding:3px 8px;font-size:11px;"
    )
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return label


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 14)
        self.layout.setSpacing(9)


class SnapshotPoller(QThread):
    snapshot_ready = Signal(object)

    def __init__(self, api: DesktopApi, interval_seconds: float) -> None:
        super().__init__()
        self.api = api
        self.interval = max(1.0, interval_seconds)
        self._stop = threading.Event()
        self._wake = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            self.snapshot_ready.emit(self.api.snapshot())
            self._wake.wait(self.interval)
            self._wake.clear()

    def refresh_now(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
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
        except Exception as exc:  # GUI boundary: surface action failures to the operator.
            self.failed.emit(str(exc))


class Page(QWidget):
    def __init__(self, shell: "MainWindow", title: str, subtitle: str) -> None:
        super().__init__()
        self.shell = shell
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(26, 24, 26, 24)
        self.root.setSpacing(14)
        title_label = QLabel(title)
        title_label.setObjectName("title")
        self.root.addWidget(title_label)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("muted")
        subtitle_label.setWordWrap(True)
        self.root.addWidget(subtitle_label)

    def update_snapshot(self, snapshot: dict) -> None:
        raise NotImplementedError


class HomePage(Page):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Home", "This workstation and its ComfyUI workers.")
        self.metrics = QHBoxLayout()
        self.root.addLayout(self.metrics)
        self.environment = Card()
        self.root.addWidget(self.environment)
        section = QLabel("GPU Workers")
        section.setObjectName("sectionTitle")
        self.root.addWidget(section)
        self.worker_scroll = QScrollArea()
        self.worker_scroll.setWidgetResizable(True)
        self.worker_body = QWidget()
        self.worker_layout = QVBoxLayout(self.worker_body)
        self.worker_layout.setContentsMargins(0, 0, 0, 0)
        self.worker_layout.setSpacing(10)
        self.worker_scroll.setWidget(self.worker_body)
        self.root.addWidget(self.worker_scroll, 1)

    def _metric(self, label: str, value: str) -> Card:
        card = Card()
        caption = QLabel(label)
        caption.setObjectName("muted")
        number = QLabel(value)
        number.setObjectName("metricValue")
        card.layout.addWidget(caption)
        card.layout.addWidget(number)
        return card

    def update_snapshot(self, snapshot: dict) -> None:
        clear_layout(self.metrics)
        local = snapshot.get("local") or {}
        registration = local.get("registration") or {}
        gpus = registration.get("gpus") or []
        workers = registration.get("workers") or []
        total_vram = sum(int(gpu.get("memory_total_mb") or 0) for gpu in gpus)
        running = sum(1 for worker in workers if worker.get("state") not in {"stopped", "offline"})
        controller_connected = bool(local.get("controller_connected"))
        self.metrics.addWidget(self._metric("GPUs", str(len(gpus))))
        self.metrics.addWidget(self._metric("VRAM", f"{total_vram / 1024:.0f} GB" if total_vram else "0 GB"))
        self.metrics.addWidget(self._metric("Workers", f"{running} / {len(workers)}"))
        self.metrics.addWidget(self._metric("Cluster", "Connected" if controller_connected else "Offline"))

        clear_layout(self.environment.layout)
        top = QHBoxLayout()
        comfy = registration.get("comfy") or {}
        name_box = QVBoxLayout()
        env_title = QLabel("Production Comfy")
        env_title.setObjectName("sectionTitle")
        name_box.addWidget(env_title)
        path = comfy.get("path") or "ComfyUI installation not detected"
        path_label = QLabel(path)
        path_label.setObjectName("muted")
        path_label.setWordWrap(True)
        name_box.addWidget(path_label)
        top.addLayout(name_box, 1)
        host = snapshot.get("local_host") or {}
        if not local:
            top.addWidget(badge("Agent unavailable", "bad"))
        elif host.get("draining"):
            top.addWidget(badge("Draining", "warn"))
        elif controller_connected:
            top.addWidget(badge("Cluster ready", "good"))
        else:
            top.addWidget(badge("Local only", "warn"))
        self.environment.layout.addLayout(top)

        detail = QLabel(
            f"Comfy {comfy.get('version') or 'unversioned'}  |  "
            f"{len(registration.get('nodes') or [])} node packages  |  "
            f"{len(registration.get('models') or [])} model files"
        )
        detail.setObjectName("muted")
        self.environment.layout.addWidget(detail)
        buttons = QHBoxLayout()
        open_button = QPushButton("Open ComfyUI")
        open_button.setObjectName("primary")
        open_button.clicked.connect(shell.open_local_comfy)
        buttons.addWidget(open_button)
        for label, operation in (("Start All", "start"), ("Stop All", "stop")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, op=operation: shell.local_fleet_action(op))
            buttons.addWidget(button)
        restart = QPushButton("Restart All")
        restart.clicked.connect(shell.restart_all_workers)
        buttons.addWidget(restart)
        if host:
            drain = QPushButton("Resume Host" if host.get("draining") else "Drain Host")
            drain.clicked.connect(
                lambda: shell.host_mode("resume" if host.get("draining") else "drain")
            )
            buttons.addWidget(drain)
        buttons.addStretch(1)
        self.environment.layout.addLayout(buttons)

        clear_layout(self.worker_layout)
        if not workers:
            empty = QLabel("No local GPU workers discovered yet.")
            empty.setObjectName("muted")
            self.worker_layout.addWidget(empty)
        for worker in workers:
            gpu = next((item for item in gpus if item.get("uuid") == worker.get("gpu_uuid")), {})
            card = Card()
            row = QHBoxLayout()
            info = QVBoxLayout()
            title = QLabel(gpu.get("name") or worker.get("worker_id") or "GPU Worker")
            title.setObjectName("sectionTitle")
            info.addWidget(title)
            info.addWidget(
                QLabel(
                    f"GPU {worker.get('gpu_index')}  |  port {worker.get('port')}  |  "
                    f"VRAM {gpu.get('memory_used_mb', 0)} / {gpu.get('memory_total_mb', 0)} MB  |  "
                    f"utilization {gpu.get('utilization_percent', 0)}%"
                )
            )
            info.itemAt(1).widget().setObjectName("muted")
            row.addLayout(info, 1)
            state = str(worker.get("state") or "unknown")
            row.addWidget(
                badge(
                    state.upper(),
                    "good" if state == "idle" else "warn" if state in {"busy", "starting"} else "bad",
                )
            )
            for label, operation in (("Start", "start"), ("Restart", "restart"), ("Stop", "stop")):
                button = QPushButton(label)
                worker_id = str(worker.get("worker_id"))
                button.clicked.connect(
                    lambda _=False, wid=worker_id, op=operation: shell.local_worker_action(wid, op)
                )
                row.addWidget(button)
            card.layout.addLayout(row)
            self.worker_layout.addWidget(card)
        self.worker_layout.addStretch(1)


class EnvironmentPage(Page):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Comfy Environments", "Managed ComfyUI runtimes on this workstation.")
        self.card = Card()
        self.root.addWidget(self.card)
        self.root.addStretch(1)

    def update_snapshot(self, snapshot: dict) -> None:
        clear_layout(self.card.layout)
        local = snapshot.get("local") or {}
        registration = local.get("registration") or {}
        comfy = registration.get("comfy") or {}
        desired = snapshot.get("desired_release") or {}
        plan = snapshot.get("release_plan") or {}
        host_id = snapshot.get("host_id")
        host_plan = next((item for item in plan.get("hosts", []) if item.get("host_id") == host_id), {})

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Production")
        title.setObjectName("sectionTitle")
        title_box.addWidget(title)
        subtitle = QLabel(comfy.get("path") or "No ComfyUI installation detected")
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(subtitle)
        top.addLayout(title_box, 1)
        if host_plan:
            top.addWidget(badge("IN SYNC" if host_plan.get("in_sync") else "DRIFT", "good" if host_plan.get("in_sync") else "warn"))
        self.card.layout.addLayout(top)

        rows = [
            ("Comfy version", comfy.get("version") or "Unknown"),
            ("Git commit", comfy.get("git_commit") or "Unknown"),
            ("Python", comfy.get("python_executable") or "Unknown"),
            ("Fleet release", desired.get("name") or "Not configured"),
            ("Custom nodes", str(len(registration.get("nodes") or []))),
            ("Models", str(len(registration.get("models") or []))),
        ]
        for key, value in rows:
            row = QHBoxLayout()
            key_label = QLabel(key)
            key_label.setObjectName("muted")
            row.addWidget(key_label)
            row.addStretch(1)
            row.addWidget(QLabel(value))
            self.card.layout.addLayout(row)

        if host_plan.get("drift"):
            drift = QLabel(
                "Drift: " + ", ".join(item.get("kind", "unknown") for item in host_plan["drift"])
            )
            drift.setStyleSheet("color:#ffd46e;")
            drift.setWordWrap(True)
            self.card.layout.addWidget(drift)

        buttons = QHBoxLayout()
        open_button = QPushButton("Open ComfyUI")
        open_button.setObjectName("primary")
        open_button.clicked.connect(shell.open_local_comfy)
        buttons.addWidget(open_button)
        refresh = QPushButton("Refresh Inventory")
        refresh.clicked.connect(shell.refresh_inventory)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        self.card.layout.addLayout(buttons)


class TablePage(Page):
    def __init__(self, shell: "MainWindow", title: str, subtitle: str, columns: list[str]) -> None:
        super().__init__(shell, title, subtitle)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.root.addWidget(self.table, 1)

    def set_rows(self, rows: list[list[str]]) -> None:
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.table.setItem(row_index, column_index, QTableWidgetItem(value))


class ModelsPage(TablePage):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Models", "Cluster model inventory and availability.", ["Model", "Type", "Size", "This PC", "Cluster"])

    def update_snapshot(self, snapshot: dict) -> None:
        local = snapshot.get("local") or {}
        registration = local.get("registration") or {}
        local_keys = {
            (str(item.get("category", "")).casefold(), str(item.get("name", "")).casefold())
            for item in registration.get("models") or []
        }
        host_count = max(1, len(snapshot.get("hosts") or []))
        rows = []
        for item in snapshot.get("models") or []:
            key = (str(item.get("category", "")).casefold(), str(item.get("name", "")).casefold())
            rows.append(
                [
                    str(item.get("name") or ""),
                    str(item.get("category") or ""),
                    fmt_size(item.get("size_bytes")),
                    "Yes" if key in local_keys else "No",
                    f"{item.get('host_count', 0)} / {host_count}",
                ]
            )
        self.set_rows(rows)


class NodesPage(TablePage):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Custom Nodes", "Custom-node packages visible across the fleet.", ["Node", "This PC Commit", "Hosts", "Status"])

    def update_snapshot(self, snapshot: dict) -> None:
        host_id = snapshot.get("host_id")
        host_count = max(1, len(snapshot.get("hosts") or []))
        rows = []
        for item in snapshot.get("nodes") or []:
            hosts = item.get("hosts") or {}
            local = hosts.get(host_id) or {}
            commits = {str(value.get("git_commit")) for value in hosts.values() if value.get("git_commit")}
            status = "Consistent" if len(commits) <= 1 and len(hosts) == host_count else "Check fleet"
            rows.append(
                [
                    str(item.get("name") or ""),
                    str(local.get("git_commit") or "Not installed"),
                    f"{len(hosts)} / {host_count}",
                    status,
                ]
            )
        self.set_rows(rows)


class OutputsPage(TablePage):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Outputs", "Recent ComfyCluster jobs and their generated outputs.", ["State", "Created", "Host", "Worker", "Outputs", "Job"])

    def update_snapshot(self, snapshot: dict) -> None:
        rows = []
        for job in (snapshot.get("jobs") or [])[:100]:
            outputs = job.get("outputs") or {}
            output_count = sum(len(value) if isinstance(value, dict) else 1 for value in outputs.values())
            rows.append(
                [
                    str(job.get("state") or ""),
                    str(job.get("created_at") or "").replace("T", " ")[:19],
                    str(job.get("assigned_host_id") or ""),
                    str(job.get("assigned_worker_id") or ""),
                    str(output_count),
                    str(job.get("job_id") or "")[:12],
                ]
            )
        self.set_rows(rows)


class ClusterPage(Page):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Cluster", "All Windows hosts and GPU workers known to the controller.")
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.body = QWidget()
        self.cards = QVBoxLayout(self.body)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(10)
        self.scroll.setWidget(self.body)
        self.root.addWidget(self.scroll, 1)

    def update_snapshot(self, snapshot: dict) -> None:
        clear_layout(self.cards)
        hosts = snapshot.get("hosts") or []
        if not hosts:
            empty = QLabel("Controller has no registered hosts yet.")
            empty.setObjectName("muted")
            self.cards.addWidget(empty)
        for host in hosts:
            card = Card()
            top = QHBoxLayout()
            name_box = QVBoxLayout()
            name = QLabel(str(host.get("hostname") or host.get("host_id") or "Host"))
            name.setObjectName("sectionTitle")
            name_box.addWidget(name)
            name_box.addWidget(QLabel(f"{len(host.get('gpus') or [])} GPUs  |  {len(host.get('models') or [])} models  |  {len(host.get('nodes') or [])} nodes"))
            name_box.itemAt(1).widget().setObjectName("muted")
            top.addLayout(name_box, 1)
            if host.get("draining"):
                top.addWidget(badge("DRAINING", "warn"))
            top.addWidget(badge("ONLINE" if host.get("connected") else "OFFLINE", "good" if host.get("connected") else "bad"))
            mode = QPushButton("Resume" if host.get("draining") else "Drain")
            host_id = str(host.get("host_id"))
            operation = "resume" if host.get("draining") else "drain"
            mode.clicked.connect(lambda _=False, hid=host_id, op=operation: shell.host_mode(op, hid))
            top.addWidget(mode)
            card.layout.addLayout(top)
            for worker in host.get("workers") or []:
                gpu = next((g for g in host.get("gpus") or [] if g.get("uuid") == worker.get("gpu_uuid")), {})
                row = QHBoxLayout()
                row.addWidget(QLabel(str(gpu.get("name") or worker.get("worker_id"))), 1)
                row.addWidget(QLabel(f"GPU {worker.get('gpu_index')}  :{worker.get('port')}"))
                row.addWidget(badge(str(worker.get("state") or "unknown").upper()))
                card.layout.addLayout(row)
            self.cards.addWidget(card)
        self.cards.addStretch(1)


class SettingsPage(Page):
    def __init__(self, shell: "MainWindow") -> None:
        super().__init__(shell, "Settings", "Desktop connection and local agent information.")
        self.card = Card()
        self.root.addWidget(self.card)
        self.root.addStretch(1)

    def update_snapshot(self, snapshot: dict) -> None:
        clear_layout(self.card.layout)
        rows = [
            ("Controller", snapshot.get("controller_base") or ""),
            ("Local agent API", self.shell.settings.local_api_url),
            ("Host ID", snapshot.get("host_id") or self.shell.settings.host_id),
            ("Refresh interval", f"{self.shell.settings.desktop_refresh_seconds:.1f} seconds"),
        ]
        for key, value in rows:
            row = QHBoxLayout()
            key_label = QLabel(key)
            key_label.setObjectName("muted")
            row.addWidget(key_label)
            row.addStretch(1)
            value_label = QLabel(str(value))
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(value_label)
            self.card.layout.addLayout(row)
        buttons = QHBoxLayout()
        admin = QPushButton("Open Controller Admin")
        admin.clicked.connect(self.shell.open_controller)
        buttons.addWidget(admin)
        refresh = QPushButton("Refresh Now")
        refresh.clicked.connect(self.shell.refresh_now)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        self.card.layout.addLayout(buttons)


class MainWindow(QMainWindow):
    def __init__(self, settings: DesktopSettings) -> None:
        super().__init__()
        self.settings = settings
        self.api = DesktopApi(settings)
        self.snapshot: dict = {}
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
        tagline = QLabel("ComfyUI fleet manager")
        tagline.setObjectName("muted")
        side.addWidget(tagline)
        side.addSpacing(18)

        self.stack = QStackedWidget()
        self.pages: list[Page] = [
            HomePage(self),
            EnvironmentPage(self),
            ModelsPage(self),
            NodesPage(self),
            OutputsPage(self),
            ClusterPage(self),
            SettingsPage(self),
        ]
        labels = ["Home", "Comfy", "Models", "Custom Nodes", "Outputs", "Cluster", "Settings"]
        self.nav_buttons: list[QPushButton] = []
        for index, (label, page) in enumerate(zip(labels, self.pages, strict=True)):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, i=index: self.set_page(i))
            self.nav_buttons.append(button)
            side.addWidget(button)
            self.stack.addWidget(page)
        side.addStretch(1)
        self.connection_badge = badge("Starting...", "neutral")
        side.addWidget(self.connection_badge)
        version = QLabel("Windows desktop preview")
        version.setObjectName("muted")
        side.addWidget(version)
        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        self.set_page(0)

        self.poller = SnapshotPoller(self.api, settings.desktop_refresh_seconds)
        self.poller.snapshot_ready.connect(self.apply_snapshot)
        self.poller.start()

    def set_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for nav_index, button in enumerate(self.nav_buttons):
            button.setChecked(nav_index == index)

    def apply_snapshot(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        local = snapshot.get("local") or {}
        controller_error = snapshot.get("controller_error")
        local_error = snapshot.get("local_error")
        if local and local.get("controller_connected") and not controller_error:
            text, tone = "Cluster connected", "good"
        elif local and not local_error:
            text, tone = "Local mode", "warn"
        else:
            text, tone = "Agent offline", "bad"
        self.connection_badge.setText(text)
        replacement = badge(text, tone)
        self.connection_badge.setStyleSheet(replacement.styleSheet())
        replacement.deleteLater()
        for page in self.pages:
            page.update_snapshot(snapshot)

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
        local = self.snapshot.get("local") or {}
        workers = (local.get("registration") or {}).get("workers") or []

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

    def open_local_comfy(self) -> None:
        local = self.snapshot.get("local") or {}
        workers = (local.get("registration") or {}).get("workers") or []
        worker = next((item for item in workers if item.get("comfy_url")), None)
        if not worker:
            self._show_action_error("No local ComfyUI worker is available to open.")
            return
        QDesktopServices.openUrl(QUrl(str(worker.get("comfy_url"))))

    def open_controller(self) -> None:
        QDesktopServices.openUrl(QUrl(self.api.controller_base))

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming convention
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
