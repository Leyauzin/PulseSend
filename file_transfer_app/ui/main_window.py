from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QLabel, QLineEdit, QProgressBar, QWidget

from file_transfer_app.config import (
    APP_NAME,
    CHUNK_PRESETS,
    DEFAULT_CHUNK_LABEL,
    DEFAULT_PORT,
    MIN_HEIGHT,
    MIN_WIDTH,
    STYLE_PATH,
    WINDOW_HEIGHT,
    WINDOW_WIDTH,
)
from ui_tools import UIWrapper


class _UiDispatcher(QObject):
    invoke = Signal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(self._run)

    @Slot(object)
    def _run(self, callback) -> None:
        callback()


class MainWindowView:
    def __init__(self):
        self.ui = UIWrapper(APP_NAME, width=WINDOW_WIDTH, height=WINDOW_HEIGHT, padding=24)
        self.ui.set_min_size(MIN_WIDTH, MIN_HEIGHT).center()
        if STYLE_PATH.exists():
            self.ui.load_style(str(STYLE_PATH))

        self._widgets: dict[str, QWidget] = {}
        self._dispatcher = _UiDispatcher()
        self._build()

    def _build(self) -> None:
        root = self.ui
        root.set_spacing(18)

        hero = root.add_column(name="hero_card")
        hero.set_margins(24, 24, 24, 24).set_spacing(10)
        hero.add_label("PulseSend", name="hero_title")
        hero.add_label(
            "Transfert local avec decouverte reseau, carnet d'adresses et filtrage IP strict.",
            name="hero_subtitle",
        )
        badges = hero.add_row(name="hero_badges")
        badges.set_spacing(10)
        badges.add_label("0 contact", name="contacts_badge")
        badges.add_label("0 appareil detecte", name="devices_badge")
        badges.add_label("Reseau local: detection...", name="network_badge")

        tabs = root.add_tabs(["Envoyer", "Recevoir"], name="main_tabs")
        self._build_send_tab(tabs["Envoyer"])
        self._build_receive_tab(tabs["Recevoir"])

        footer = root.add_column(name="footer_card")
        footer.set_margins(20, 20, 20, 20).set_spacing(10)
        footer.add_label("Statut du transfert", name="footer_title")
        footer.add_label("Pret a lancer le premier transfert.", name="status_label")

        progress = QProgressBar()
        progress.setObjectName("transfer_progress")
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setFormat("%p%")
        footer._layout.addWidget(progress)
        self._widgets["transfer_progress"] = progress

        for label_name in (
            "peer_hint_label",
            "peer_info_label",
            "contact_hint_label",
            "path_value_label",
            "source_guard_note_label",
            "status_label",
        ):
            label = self.widget(label_name)
            if isinstance(label, QLabel):
                label.setWordWrap(True)

        save_dir_input = self.widget("save_dir_input")
        if isinstance(save_dir_input, QLineEdit):
            save_dir_input.setReadOnly(True)

        for widget_name in ("send_pass_input", "recv_pass_input"):
            widget = self.widget(widget_name)
            if isinstance(widget, QLineEdit):
                widget.setEchoMode(QLineEdit.EchoMode.Password)

        self.set_chunk(DEFAULT_CHUNK_LABEL)
        self.set_send_port(str(DEFAULT_PORT))
        self.set_receive_port(str(DEFAULT_PORT))
        self.clear_contact_form()
        self.set_action_enabled("cancel_recv_btn", False)

    def _build_send_tab(self, tab_section) -> None:
        send_scroll = tab_section.add_scroll()
        send_scroll.set_spacing(16)

        send_grid = send_scroll.add_row(stretches=[3, 2], cross_align="top")
        send_grid.set_spacing(16)
        left = send_grid.add_column()
        left.set_spacing(16)
        right = send_grid.add_column()
        right.set_spacing(16)

        peers = left.add_column(name="card")
        peers.set_margins(20, 20, 20, 20).set_spacing(10)
        peers.add_label("Appareils detectes")
        peers.add_label(
            "Les autres instances ouvertes sur le reseau local apparaissent ici.",
            name="peer_hint_label",
        )
        peer_row = peers.add_row(stretches=[4, 1])
        peer_row.set_spacing(10)
        peer_row.add_dropdown([], name="peer_dd")
        peer_row.add_button("Rafraichir", lambda: None, name="refresh_peers_btn")
        peers.add_label(
            "Selectionnez un appareil detecte ou gardez la saisie manuelle.",
            name="peer_info_label",
        )

        target = left.add_column(name="card")
        target.set_margins(20, 20, 20, 20).set_spacing(12)
        target.add_label("Destination d'envoi")
        host_row = target.add_row(stretches=[4, 1])
        host_row.set_spacing(10)
        host_row.add_input("Adresse IP cible", name="host_input")
        host_row.add_dropdown(["IPv4", "IPv6"], name="ip_ver_dd")
        tuning_row = target.add_row(stretches=[1, 2])
        tuning_row.set_spacing(12)
        port_column = tuning_row.add_column()
        port_column.set_spacing(6)
        port_column.add_label("Port")
        port_column.add_input(str(DEFAULT_PORT), name="send_port_input")
        chunk_column = tuning_row.add_column()
        chunk_column.set_spacing(6)
        chunk_column.add_label("Taille des paquets")
        chunk_column.add_dropdown(list(CHUNK_PRESETS), name="chunk_dd")

        payload = left.add_column(name="card")
        payload.set_margins(20, 20, 20, 20).set_spacing(12)
        payload.add_label("Contenu a envoyer")
        pick_row = payload.add_row()
        pick_row.set_spacing(10)
        pick_row.add_button("Choisir un fichier", lambda: None, stretch=1, name="pick_file_btn")
        pick_row.add_button("Choisir un dossier", lambda: None, stretch=1, name="pick_folder_btn")
        payload.add_label("Aucune selection pour le moment.", name="path_value_label")

        contacts = right.add_column(name="card")
        contacts.set_margins(20, 20, 20, 20).set_spacing(10)
        contacts.add_label("Carnet d'adresses")
        contacts.add_dropdown([], name="contact_dd")
        contacts.add_label("Nom du contact")
        contacts.add_input("Ex: Portable salon", name="contact_name_input")
        ip_row = contacts.add_row(stretches=[4, 1])
        ip_row.set_spacing(10)
        ip_row.add_input("Adresse IP du contact", name="contact_ip_input")
        ip_row.add_dropdown(["IPv4", "IPv6"], name="contact_ip_ver_dd")
        contacts.add_label("Port du contact")
        contacts.add_input(str(DEFAULT_PORT), name="contact_port_input")
        contact_actions = contacts.add_row(stretches=[1, 1, 1])
        contact_actions.set_spacing(10)
        contact_actions.add_button("Utiliser", lambda: None, name="apply_contact_btn")
        contact_actions.add_button("Sauvegarder", lambda: None, name="save_contact_btn")
        contact_actions.add_button("Supprimer", lambda: None, name="delete_contact_btn")
        contacts.add_label(
            "La destination d'envoi et les contacts sont separes: vous pouvez preparer ou modifier un contact sans toucher a la cible actuelle.",
            name="contact_hint_label",
        )

        security = right.add_column(name="card")
        security.set_margins(20, 20, 20, 20).set_spacing(10)
        security.add_label("Verification")
        security.add_input("Passphrase optionnelle", name="send_pass_input")
        security.add_button("Envoyer maintenant", lambda: None, name="send_btn")

    def _build_receive_tab(self, tab_section) -> None:
        recv_scroll = tab_section.add_scroll()
        recv_scroll.set_spacing(16)

        receive_grid = recv_scroll.add_row(stretches=[1, 1], cross_align="top")
        receive_grid.set_spacing(16)
        left = receive_grid.add_column()
        left.set_spacing(16)
        right = receive_grid.add_column()
        right.set_spacing(16)

        listening = left.add_column(name="card")
        listening.set_margins(20, 20, 20, 20).set_spacing(12)
        listening.add_label("Ecoute")
        listening.add_label("Le poste se met en attente sur le port choisi.", name="recv_description")
        listening.add_label("Port")
        listening.add_input(str(DEFAULT_PORT), name="recv_port_input")
        listening.add_label("Passphrase (optionnelle)")
        listening.add_input("Doit correspondre a celle de l'expediteur", name="recv_pass_input")
        recv_actions = listening.add_row(stretches=[1, 1])
        recv_actions.set_spacing(10)
        recv_actions.add_button("Demarrer l'ecoute", lambda: None, name="recv_btn")
        recv_actions.add_button("Annuler", lambda: None, name="cancel_recv_btn")

        guard = right.add_column(name="card")
        guard.set_margins(20, 20, 20, 20).set_spacing(12)
        guard.add_label("Filtre IP strict")
        guard.add_label("Adresse IP source attendue")
        guard.add_input("Ex: 192.168.1.50 ou 2001:db8::50", name="allowed_ip_input")
        guard.add_label(
            "Si ce champ est renseigne, l'IP reelle du socket entrant doit correspondre exactement a cette adresse IPv4 ou IPv6.",
            name="source_guard_note_label",
        )

        target = recv_scroll.add_column(name="card")
        target.set_margins(20, 20, 20, 20).set_spacing(12)
        target.add_label("Dossier de reception")
        save_row = target.add_row(stretches=[4, 1])
        save_row.set_spacing(10)
        save_row.add_input("", name="save_dir_input")
        save_row.add_button("Parcourir", lambda: None, name="pick_save_dir_btn")

    def widget(self, name: str) -> QWidget | None:
        if name in self._widgets:
            return self._widgets[name]
        return self.ui.get(name)

    def connect(self, name: str, callback) -> None:
        widget = self.widget(name)
        if widget is not None and hasattr(widget, "clicked"):
            widget.clicked.connect(callback)

    def connect_text_changed(self, name: str, callback) -> None:
        widget = self.widget(name)
        if widget is not None and hasattr(widget, "currentTextChanged"):
            widget.currentTextChanged.connect(callback)

    def connect_input_changed(self, name: str, callback) -> None:
        widget = self.widget(name)
        if widget is not None and hasattr(widget, "textChanged"):
            widget.textChanged.connect(callback)

    def populate_contacts(self, contacts: list[str], selected: str | None = None) -> None:
        self._populate_dropdown("contact_dd", contacts, selected)

    def populate_devices(self, devices: list[str], selected: str | None = None) -> None:
        self._populate_dropdown("peer_dd", devices, selected)

    def set_badge_text(self, name: str, value: str) -> None:
        label = self.widget(name)
        if isinstance(label, QLabel):
            label.setText(value)

    def set_status(self, message: str) -> None:
        label = self.widget("status_label")
        if isinstance(label, QLabel):
            label.setText(message)

    def set_peer_details(self, message: str) -> None:
        label = self.widget("peer_info_label")
        if isinstance(label, QLabel):
            label.setText(message)

    def set_progress(self, value: float) -> None:
        progress = self.widget("transfer_progress")
        if isinstance(progress, QProgressBar):
            progress.setValue(int(value))

    def set_selected_path(self, path: Path) -> None:
        label = self.widget("path_value_label")
        if isinstance(label, QLabel):
            label.setText(str(path))
            label.setToolTip(str(path))

    def set_receive_directory(self, path: Path) -> None:
        self.set_input_text("save_dir_input", str(path))

    def set_host(self, host: str) -> None:
        self.set_input_text("host_input", host)

    def set_send_port(self, port: str) -> None:
        self.set_input_text("send_port_input", port)

    def set_receive_port(self, port: str) -> None:
        self.set_input_text("recv_port_input", port)

    def set_ip_version(self, version: str) -> None:
        self.set_dropdown_text("ip_ver_dd", version)

    def set_chunk(self, label: str) -> None:
        self.set_dropdown_text("chunk_dd", label)

    def set_contact_form(
        self,
        name: str = "",
        ip: str = "",
        port: str = "",
        ip_version: str = "IPv4",
    ) -> None:
        self.set_input_text("contact_name_input", name)
        self.set_input_text("contact_ip_input", ip)
        self.set_input_text("contact_port_input", port or str(DEFAULT_PORT))
        self.set_dropdown_text("contact_ip_ver_dd", ip_version)

    def clear_contact_form(self) -> None:
        self.set_contact_form(port=str(DEFAULT_PORT))

    def set_input_text(self, name: str, value: str) -> None:
        widget = self.widget(name)
        if isinstance(widget, QLineEdit):
            widget.setText(value)

    def set_dropdown_text(self, name: str, value: str) -> None:
        widget = self.widget(name)
        if widget is not None and hasattr(widget, "setCurrentText"):
            widget.setCurrentText(value)

    def text(self, name: str) -> str:
        widget = self.widget(name)
        return widget.text().strip() if isinstance(widget, QLineEdit) else ""

    def current_text(self, name: str) -> str:
        widget = self.widget(name)
        if widget is not None and hasattr(widget, "currentText"):
            return widget.currentText().strip()
        return ""

    def set_action_enabled(self, name: str, enabled: bool) -> None:
        widget = self.widget(name)
        if widget is not None and hasattr(widget, "setEnabled"):
            widget.setEnabled(enabled)

    def notify(self, message: str, kind: str = "info") -> None:
        self.ui.notify(message, kind)

    def call_in_ui(self, callback) -> None:
        self._dispatcher.invoke.emit(callback)

    def choose_file(self) -> Path | None:
        file_path, _ = QFileDialog.getOpenFileName(self.ui.window, "Choisir un fichier")
        return Path(file_path) if file_path else None

    def choose_directory(self, title: str) -> Path | None:
        directory = QFileDialog.getExistingDirectory(self.ui.window, title)
        return Path(directory) if directory else None

    def set_on_close(self, callback) -> None:
        self.ui.set_on_close(callback)

    def run(self) -> int:
        return self.ui.run()

    def _populate_dropdown(self, widget_name: str, values: list[str], selected: str | None) -> None:
        dropdown = self.widget(widget_name)
        if dropdown is None:
            return

        dropdown.blockSignals(True)
        dropdown.clear()
        dropdown.addItems(values)
        if selected and dropdown.findText(selected) >= 0:
            dropdown.setCurrentText(selected)
        elif values:
            dropdown.setCurrentIndex(0)
        dropdown.blockSignals(False)
