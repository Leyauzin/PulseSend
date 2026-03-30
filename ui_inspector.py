# ui_inspector.py
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QTableWidget,
    QLineEdit, QComboBox, QCheckBox, QTabWidget,
    QScrollArea, QFrame, QProgressBar, QSlider,
)
from PySide6.QtCore import QObject


def _node_label(obj: QObject) -> str:
    cls = type(obj).__name__
    name = obj.objectName() if hasattr(obj, 'objectName') else ""

    if isinstance(obj, QLabel):
        return f"QLabel  '{obj.text()}'" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QPushButton):
        return f"QPushButton  '{obj.text()}'" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QTableWidget):
        return f"QTableWidget  {obj.rowCount()}×{obj.columnCount()}" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QLineEdit):
        return f"QLineEdit  placeholder='{obj.placeholderText()}'" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QComboBox):
        return f"QComboBox  {obj.count()} options" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QCheckBox):
        return f"QCheckBox  '{obj.text()}'" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QTabWidget):
        tabs = [obj.tabText(i) for i in range(obj.count())]
        return f"QTabWidget  {tabs}" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QScrollArea):
        return f"QScrollArea" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QProgressBar):
        return f"QProgressBar  {obj.value()}/{obj.maximum()}" + (f"  [#{name}]" if name else "")
    if isinstance(obj, QSlider):
        return f"QSlider  {obj.value()}" + (f"  [#{name}]" if name else "")

    return f"{cls}" + (f"  [#{name}]" if name else "")


def _visual_children(obj: QObject) -> list[QObject]:
    children = [c for c in obj.children() if isinstance(c, QWidget)]
    if isinstance(obj, QWidget) and obj.layout() is not None:
        layout = obj.layout()
        ordered, seen = [], set()
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() and item.widget() in children:
                ordered.append(item.widget())
                seen.add(item.widget())
        ordered += [c for c in children if c not in seen]
        return ordered
    return children


def _walk(obj: QObject, prefix: str, is_last: bool, lines: list[str]) -> None:
    connector = "└─ " if is_last else "├─ "
    lines.append(prefix + connector + _node_label(obj))
    children = _visual_children(obj)
    child_prefix = prefix + ("   " if is_last else "│  ")
    for i, child in enumerate(children):
        _walk(child, child_prefix, i == len(children) - 1, lines)


def get_tree(root: QWidget) -> str:
    lines = [_node_label(root)]
    children = _visual_children(root)
    for i, child in enumerate(children):
        _walk(child, "", i == len(children) - 1, lines)
    return "\n".join(lines)


def print_tree(root: QWidget) -> None:
    print(get_tree(root))


def save_tree(root: QWidget, path: str = "ui_tree.txt") -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(get_tree(root))
    print(f"Arborescence sauvegardée → {path}")


# ------------------------------------------------------------------ #
#  Générateur de template QSS                                         #
# ------------------------------------------------------------------ #

# Widgets qui méritent un bloc QSS, avec leur template de base
_QSS_TEMPLATES: dict[type, str] = {
    QPushButton: "QPushButton {{\n    /* background-color: ;\n    color: ;\n    border-radius: px;\n    padding: px px; */\n}}\nQPushButton:hover {{\n    /* background-color: ; */\n}}\nQPushButton:pressed {{\n    /* background-color: ; */\n}}",
    QLabel:      "QLabel {{\n    /* color: ;\n    font-size: px;\n    font-weight: bold; */\n}}",
    QLineEdit:   "QLineEdit {{\n    /* background-color: ;\n    border: 1px solid ;\n    border-radius: px;\n    padding: px; */\n}}\nQLineEdit:focus {{\n    /* border-color: ; */\n}}",
    QComboBox:   "QComboBox {{\n    /* background-color: ;\n    border: 1px solid ;\n    border-radius: px; */\n}}",
    QCheckBox:   "QCheckBox {{\n    /* color: ;\n    spacing: px; */\n}}",
    QTabWidget:  "QTabWidget::pane {{\n    /* border: 1px solid ;\n    background-color: ; */\n}}\nQTabBar::tab {{\n    /* background-color: ;\n    padding: px px;\n    border-radius: px px 0 0; */\n}}\nQTabBar::tab:selected {{\n    /* background-color: ; */\n}}\nQTabBar::tab:hover {{\n    /* background-color: ; */\n}}",
    QScrollArea: "QScrollArea {{\n    /* border: none; */\n}}\nQScrollBar:vertical {{\n    /* width: px;\n    background: ; */\n}}\nQScrollBar::handle:vertical {{\n    /* background: ;\n    border-radius: px; */\n}}",
    QProgressBar:"QProgressBar {{\n    /* border: 1px solid ;\n    border-radius: px;\n    background-color: ; */\n}}\nQProgressBar::chunk {{\n    /* background-color: ;\n    border-radius: px; */\n}}",
    QSlider:     "QSlider::groove:horizontal {{\n    /* height: px;\n    background: ; */\n}}\nQSlider::handle:horizontal {{\n    /* width: px;\n    background: ;\n    border-radius: px; */\n}}",
    QFrame:      "QFrame {{\n    /* background-color: ;\n    border: 1px solid ; */\n}}",
}


def _collect_widgets(root: QWidget) -> list[QWidget]:
    """Collecte tous les widgets uniques de l'arbre."""
    result, seen = [], set()

    def walk(obj):
        if id(obj) in seen:
            return
        seen.add(id(obj))
        result.append(obj)
        for child in _visual_children(obj):
            walk(child)

    walk(root)
    return result


def generate_qss(root: QWidget, path: str = "style/style.qss") -> None:
    """
    Génère un fichier .qss commenté à partir de l'arbre de widgets.
    - Un bloc par type de widget trouvé dans l'arbre
    - Un bloc #objectName pour chaque widget nommé
    """
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)

    widgets = _collect_widgets(root)
    lines = ["/* ================================================================ */",
             "/* QSS généré automatiquement par ui_inspector                      */",
             "/* Décommentez et modifiez les propriétés que vous voulez utiliser  */",
             "/* ================================================================ */\n"]

    # Blocs par type — un seul bloc par type même s'il y en a plusieurs
    seen_types: set[type] = set()
    lines.append("/* ── Styles globaux par type de widget ── */\n")
    for widget in widgets:
        t = type(widget)
        if t in _QSS_TEMPLATES and t not in seen_types:
            seen_types.add(t)
            lines.append(_QSS_TEMPLATES[t].format())
            lines.append("")

    # Blocs par objectName — un bloc par widget nommé
    named = [(w, w.objectName()) for w in widgets if hasattr(w, 'objectName') and w.objectName()]
    if named:
        lines.append("\n/* ── Styles spécifiques par nom (#objectName) ── */\n")
        for widget, name in named:
            cls = type(widget).__name__
            lines.append(f"/* {cls} */")
            lines.append(f"#{name} {{")
            lines.append(f"    /* background-color: ; */")
            lines.append(f"    /* color: ; */")
            lines.append(f"}}")
            lines.append("")

    content = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Template QSS généré → {path}")