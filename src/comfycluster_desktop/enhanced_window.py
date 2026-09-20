from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .gallery import GalleryPage
from .settings import DesktopSettings
from .window import APP_STYLE, MainWindow


class EnhancedMainWindow(MainWindow):
    """Desktop shell with the richer tenant-scoped media library."""

    def __init__(self, settings: DesktopSettings) -> None:
        super().__init__(settings)
        old_outputs_page = self.stack.widget(4)
        self.outputs_gallery = GalleryPage(self.api)
        self.stack.removeWidget(old_outputs_page)
        old_outputs_page.deleteLater()
        self.stack.insertWidget(4, self.outputs_gallery)
        if self.stack.currentIndex() == 4:
            self.stack.setCurrentIndex(4)

    def _render_outputs(self) -> None:
        if hasattr(self, "outputs_gallery"):
            self.outputs_gallery.apply_snapshot(self.snapshot)

    def closeEvent(self, event) -> None:  # noqa: N802
        if hasattr(self, "outputs_gallery"):
            self.outputs_gallery.thumbnail_worker.stop()
            self.outputs_gallery.thumbnail_worker.wait(2000)
        super().closeEvent(event)


def run_desktop(settings: DesktopSettings | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("ComfyCluster")
    app.setOrganizationName("ComfyCluster")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = EnhancedMainWindow(settings or DesktopSettings())
    window.show()
    return app.exec()
