from typing import Callable, Literal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QLayout, QLineEdit, QMainWindow, QPushButton,
    QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QTimer
from PySide6.QtCore import Qt

_NOTIF_STYLES = {
    "success": "background-color: #2d6a2d; color: white; border-radius: 6px; padding: 8px 14px;",
    "error":   "background-color: #8b0000; color: white; border-radius: 6px; padding: 8px 14px;",
    "warning": "background-color: #7a5c00; color: white; border-radius: 6px; padding: 8px 14px;",
    "info":    "background-color: #1a3a6b; color: white; border-radius: 6px; padding: 8px 14px;",
}

Callback = Callable[..., None]
Align = Literal["top", "bottom", "center", "left", "right"] | None

_SIDEBAR_CFG: dict[str, tuple] = {
    "up":    (QHBoxLayout, lambda self, w: self._outer_layout.insertWidget(0, w)),
    "down":  (QHBoxLayout, lambda self, w: self._outer_layout.addWidget(w)),
    "left":  (QVBoxLayout, lambda self, w: self._middle_layout.insertWidget(0, w)),
    "right": (QVBoxLayout, lambda self, w: self._middle_layout.addWidget(w)),
}

# (spacer_avant, spacer_après)
_MAIN_AXIS: dict[str, tuple[bool, bool]] = {
    "top":    (False, True),
    "left":   (False, True),
    "bottom": (True,  False),
    "right":  (True,  False),
    "center": (True,  True),
}

_CROSS_FLAGS_HORIZONTAL = {
    "top":    Qt.AlignmentFlag.AlignTop,
    "bottom": Qt.AlignmentFlag.AlignBottom,
    "center": Qt.AlignmentFlag.AlignVCenter,
}
_CROSS_FLAGS_VERTICAL = {
    "left":   Qt.AlignmentFlag.AlignLeft,
    "right":  Qt.AlignmentFlag.AlignRight,
    "center": Qt.AlignmentFlag.AlignHCenter,
}

class _NotificationBanner(QLabel):
    """Label flottant positionné en bas de la fenêtre parente."""

    def __init__(self, parent: QWidget, text: str, kind: str, duration: int):
        super().__init__(text, parent)
        self.setStyleSheet(_NOTIF_STYLES.get(kind, _NOTIF_STYLES["info"]))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()

        # Positionne en bas au centre
        pw, ph = parent.width(), parent.height()
        w = max(self.width() + 40, 300)
        self.setFixedWidth(w)
        self.move((pw - w) // 2, ph - self.height() - 20)
        self.show()
        self.raise_()

        QTimer.singleShot(duration, self.deleteLater)

class Section:
    def __init__(
        self,
        layout: QLayout,
        parent: "Section | None" = None,
        stretches: list[int] | None = None,
        align: Align = None,
        cross_flag: Qt.AlignmentFlag | None = None,
    ):
        self._layout = layout
        self._parent = parent
        self._stretches = list(stretches) if stretches else []
        self._stretch_idx = 0
        self._align = align
        self._sealed = False
        self._sub_sections: list["Section"] = []
        self._named_widgets: dict[str, QWidget] = {}  # 3. références nommées

        before, _ = _MAIN_AXIS.get(align, (False, False))
        if before:
            self._layout.addStretch(1)

        if cross_flag is not None:
            self._layout.setAlignment(cross_flag)

    def add_tabs(
            self,
            tabs: list[str],
            stretch: int = 1,
            name: str | None = None,
    ) -> dict[str, "Section"]:
        from PySide6.QtWidgets import QTabWidget
        tabs_widget = self._register(name, QTabWidget())
        self._layout.addWidget(tabs_widget, self._next_stretch(stretch))

        sections: dict[str, Section] = {}
        for tab_name in tabs:
            container = QWidget()
            layout = QVBoxLayout(container)
            tabs_widget.addTab(container, tab_name)
            child = Section(layout, parent=self)
            self._sub_sections.append(child)
            sections[tab_name] = child

        return sections

    def _seal(self) -> None:
        if self._sealed:
            return
        self._sealed = True
        _, after = _MAIN_AXIS.get(self._align, (False, False))
        if after:
            self._layout.addStretch(1)
        for child in self._sub_sections:
            child._seal()

    def _next_stretch(self, explicit: int | None = None) -> int:
        if explicit is not None:
            return explicit
        if self._stretch_idx < len(self._stretches):
            s = self._stretches[self._stretch_idx]
            self._stretch_idx += 1
            return s
        return 0

    def _register(self, name: str | None, widget: QWidget) -> QWidget:
        if name:
            widget.setObjectName(name)
            self._named_widgets[name] = widget
        return widget

    def get(self, name: str) -> QWidget | None:
        """Retourne un widget enregistré par son nom (récursif)."""
        if name in self._named_widgets:
            return self._named_widgets[name]
        for child in self._sub_sections:
            result = child.get(name)
            if result is not None:
                return result
        return None

    def clear(self) -> "Section":
        """Vide tous les widgets de la section."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._named_widgets.clear()
        self._sub_sections.clear()
        self._stretch_idx = 0
        self._sealed = False
        return self

    def add_label(
        self,
        text: str,
        stretch: int | None = None,
        name: str | None = None,
    ) -> "Section":
        widget = self._register(name, QLabel(text))
        self._layout.addWidget(widget, self._next_stretch(stretch))
        return self

    def add_button(
        self,
        text: str,
        callback: Callback,
        stretch: int | None = None,
        gap: int = 0,
        name: str | None = None,
    ) -> "Section":
        btn = self._register(name, QPushButton(text))
        btn.clicked.connect(callback)
        self._layout.addWidget(btn, self._next_stretch(stretch))
        if gap > 0:
            self._layout.addSpacing(gap)
        return self

    # ------------------------------------------------------------------ #
    #  1. Inputs / formulaires                                             #
    # ------------------------------------------------------------------ #

    def add_input(
        self,
        placeholder: str = "",
        callback: Callback | None = None,
        stretch: int | None = None,
        name: str | None = None,
    ) -> "Section":
        """Champ texte — callback appelé à chaque frappe."""
        widget = self._register(name, QLineEdit())
        widget.setPlaceholderText(placeholder)
        if callback:
            widget.textChanged.connect(callback)
        self._layout.addWidget(widget, self._next_stretch(stretch))
        return self

    def add_dropdown(
        self,
        options: list[str],
        callback: Callback | None = None,
        stretch: int | None = None,
        name: str | None = None,
    ) -> "Section":
        """Liste déroulante — callback reçoit la valeur sélectionnée."""
        widget = self._register(name, QComboBox())
        widget.addItems(options)
        if callback:
            widget.currentTextChanged.connect(callback)
        self._layout.addWidget(widget, self._next_stretch(stretch))
        return self

    def add_checkbox(
        self,
        text: str,
        callback: Callback | None = None,
        checked: bool = False,
        stretch: int | None = None,
        name: str | None = None,
    ) -> "Section":
        """Case à cocher — callback reçoit l'état booléen."""
        widget = self._register(name, QCheckBox(text))
        widget.setChecked(checked)
        if callback:
            widget.toggled.connect(callback)
        self._layout.addWidget(widget, self._next_stretch(stretch))
        return self

    def add_separator(self, stretch: int | None = None) -> "Section":
        """Ligne de séparation horizontale ou verticale selon le layout."""
        line = QFrame()
        if isinstance(self._layout, QVBoxLayout):
            line.setFrameShape(QFrame.Shape.HLine)
        else:
            line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self._layout.addWidget(line, self._next_stretch(stretch))
        return self

    # ------------------------------------------------------------------ #
    #  Espacement                                                          #
    # ------------------------------------------------------------------ #

    def add_spacer(self, stretch: int = 1) -> "Section":
        self._layout.addStretch(stretch)
        return self

    def add_spacing(self, px: int) -> "Section":
        self._layout.addSpacing(px)
        return self

    def set_spacing(self, px: int) -> "Section":
        """Espacement global entre tous les éléments de la section."""
        self._layout.setSpacing(px)
        return self

    def set_margins(self, top: int = 0, right: int = 0, bottom: int = 0, left: int = 0) -> "Section":
        self._layout.setContentsMargins(left, top, right, bottom)
        return self

    # ------------------------------------------------------------------ #
    #  2. Styling                                                          #
    # ------------------------------------------------------------------ #

    def set_style(self, css: str) -> "Section":
        """Applique du CSS Qt sur le widget conteneur de cette section."""
        widget = self._layout.parentWidget()
        if widget:
            widget.setStyleSheet(css)
        return self

    # ------------------------------------------------------------------ #
    #  Sous-sections                                                       #
    # ------------------------------------------------------------------ #

    def add_row(self, stretches=None, stretch=None, align=None, cross_align=None, name=None) -> "Section":
        cross_flag = _CROSS_FLAGS_HORIZONTAL.get(cross_align) if cross_align else None
        return self._make_sub(QHBoxLayout, stretches, stretch, align, cross_flag, name)

    def add_column(self, stretches=None, stretch=None, align=None, cross_align=None, name=None) -> "Section":
        cross_flag = _CROSS_FLAGS_VERTICAL.get(cross_align) if cross_align else None
        return self._make_sub(QVBoxLayout, stretches, stretch, align, cross_flag, name)

    def _make_sub(self, layout_cls, stretches, stretch, align, cross_flag, name=None) -> "Section":
        container = QFrame()
        if name:
            container.setObjectName(name)  # ← ciblable en QSS via #content
        layout = layout_cls(container)
        self._layout.addWidget(container, self._next_stretch(stretch))
        child = Section(layout, parent=self, stretches=stretches, align=align, cross_flag=cross_flag)
        self._sub_sections.append(child)
        return child

    # ------------------------------------------------------------------ #
    #  4. Scroll                                                           #
    # ------------------------------------------------------------------ #

    def add_scroll(
        self,
        stretch: int | None = None,
        horizontal: bool = False,
    ) -> "Section":
        """Crée une zone scrollable — retourne la Section intérieure."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        scroll.setWidget(inner)
        self._layout.addWidget(scroll, self._next_stretch(stretch))
        child = Section(inner_layout, parent=self)
        self._sub_sections.append(child)
        return child

    def add_table(self, columns: list[str], rows: int = 0, stretch: int | None = None) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        if rows > 0:
            table.setRowCount(rows)
        self._layout.addWidget(table, self._next_stretch(stretch))
        return table

    def add_table_row(self, table: QTableWidget, values: list[str]) -> "Section":
        row_idx = table.rowCount()
        table.insertRow(row_idx)
        for col_idx, value in enumerate(values):
            if col_idx >= table.columnCount():
                break
            table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))
        return self

    def end(self) -> "Section":
        return self._parent if self._parent is not None else self


class UIWrapper:
    def __init__(self, title: str = "", width: int = 800, height: int = 600, padding: int = 0):
        self.app = QApplication.instance() or QApplication([])
        self.window = QMainWindow()
        self.window.setWindowTitle(title)
        self.window.resize(width, height)

        central = QWidget()
        self.window.setCentralWidget(central)

        self._outer_layout = QVBoxLayout(central)
        self._outer_layout.setContentsMargins(padding, padding, padding, padding)
        self._outer_layout.setSpacing(0)

        self._middle_widget = QWidget()
        self._middle_widget.setObjectName("middle")
        self._middle_layout = QHBoxLayout(self._middle_widget)
        self._middle_layout.setContentsMargins(0, 0, 0, 0)
        self._middle_layout.setSpacing(0)
        self._outer_layout.addWidget(self._middle_widget, 1)

        content_widget = QWidget()
        content_widget.setObjectName("content")
        self._content_layout = QVBoxLayout(content_widget)
        self._middle_layout.addWidget(content_widget, 1)
        self._root_section = Section(self._content_layout)

        self._sidebars: dict[str, Section] = {}

    def __getattr__(self, name: str):
        return getattr(self._root_section, name)

    def set_icon(self, path: str) -> "UIWrapper":
        """Icône de la barre de titre / taskbar."""
        from PySide6.QtGui import QIcon
        self.window.setWindowIcon(QIcon(path))
        return self

    def set_resizable(self, resizable: bool) -> "UIWrapper":
        """Bloque ou autorise le redimensionnement."""
        if not resizable:
            self.window.setFixedSize(self.window.size())
        else:
            self.window.setMinimumSize(0, 0)
            self.window.setMaximumSize(16777215, 16777215)
        return self

    def set_min_size(self, width: int, height: int) -> "UIWrapper":
        self.window.setMinimumSize(width, height)
        return self

    def set_max_size(self, width: int, height: int) -> "UIWrapper":
        self.window.setMaximumSize(width, height)
        return self

    def set_opacity(self, value: float) -> "UIWrapper":
        """Transparence de la fenêtre — 0.0 invisible, 1.0 opaque."""
        self.window.setWindowOpacity(value)
        return self

    def set_on_close(self, callback: Callback) -> "UIWrapper":
        """Callback appelé quand l'utilisateur ferme la fenêtre."""
        self.window.closeEvent = lambda event: (callback(), event.accept())
        return self

    def center(self) -> "UIWrapper":
        """Centre la fenêtre sur l'écran."""
        screen = self.app.primaryScreen().geometry()
        w, h = self.window.width(), self.window.height()
        self.window.move((screen.width() - w) // 2, (screen.height() - h) // 2)
        return self

    def load_style(self, path: str) -> "UIWrapper":
        """Charge un fichier .qss et l'applique à la fenêtre."""
        from pathlib import Path
        qss = Path(path).read_text(encoding="utf-8")
        self.window.setStyleSheet(qss)
        return self

    def notify(
            self,
            text: str,
            kind: str = "info",  # "success" | "error" | "warning" | "info"
            duration: int = 3000,  # ms avant disparition
    ) -> "UIWrapper":
        """Affiche une notification flottante en bas de la fenêtre."""
        central = self.window.centralWidget()
        _NotificationBanner(central, text, kind, duration)
        return self

    def open_window(
            self,
            title: str = "",
            width: int = 400,
            height: int = 300,
            padding: int = 0,
    ) -> "UIWrapper":
        """Ouvre une fenêtre secondaire avec toute l'API UIWrapper."""
        child = UIWrapper(title=title, width=width, height=height, padding=padding)
        child.window.show()
        return child

    def _make_sidebar(
        self,
        side: str,
        stretches: list[int] | None = None,
        align: Align = None,
        cross_align: Align = None,
        size: int | None = None,
    ) -> Section:
        if side not in _SIDEBAR_CFG:
            raise ValueError(f"Sidebar inconnue : '{side}'. Valeurs valides : {list(_SIDEBAR_CFG)}")
        layout_cls, insert_fn = _SIDEBAR_CFG[side]
        widget = QWidget()
        widget.setObjectName(f"sidebar-{side}")
        if size is not None:
            widget.setFixedWidth(size) if side in ("left", "right") else widget.setFixedHeight(size)
        layout = layout_cls(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        insert_fn(self, widget)
        cross_flags = _CROSS_FLAGS_HORIZONTAL if side in ("up", "down") else _CROSS_FLAGS_VERTICAL
        resolved_cross = cross_flags.get(cross_align) if cross_align else None
        return Section(layout, stretches=stretches, align=align, cross_flag=resolved_cross)

    def sidebar(
        self,
        side: str = "left",
        stretches: list[int] | None = None,
        align: Align = None,
        cross_align: Align = None,
        size: int | None = None,
    ) -> Section:
        side = side.lower()
        if side not in self._sidebars:
            self._sidebars[side] = self._make_sidebar(side, stretches, align, cross_align, size)
        return self._sidebars[side]

    def run(self) -> int:
        for section in self._sidebars.values():
            section._seal()
        self._root_section._seal()
        self.window.show()
        return self.app.exec()
