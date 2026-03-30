import threading
from pathlib import Path

from file_transfer_app.config import (
    APP_NAME,
    CHUNK_PRESETS,
    CONTACTS_FILE,
    DEFAULT_CHUNK_LABEL,
    DEFAULT_PORT,
    MANUAL_TARGET_LABEL,
    NEW_CONTACT_LABEL,
)
from file_transfer_app.models import Contact, DiscoveredPeer, ReceiveRequest, SendRequest
from file_transfer_app.services.contacts import ContactStore
from file_transfer_app.services.discovery import PeerDiscoveryService
from file_transfer_app.services.network import canonical_ip, get_local_addresses
from file_transfer_app.services.transfer import TransferService
from file_transfer_app.ui.main_window import MainWindowView


class FileTransferController:
    def __init__(self):
        self.contact_store = ContactStore(CONTACTS_FILE)
        self.transfer_service = TransferService()
        self.discovery_service = PeerDiscoveryService(APP_NAME, on_peers_changed=self._on_peers_changed)
        self.view = MainWindowView()
        self.selected_path: Path | None = None
        self.receive_directory = Path.cwd()
        self.peers_by_label: dict[str, DiscoveredPeer] = {}
        self.loaded_contact_name: str | None = None
        self.receive_cancel_event: threading.Event | None = None

        self._bind_events()
        self._hydrate_view()

    def run(self) -> int:
        return self.view.run()

    def shutdown(self) -> None:
        self.discovery_service.stop()

    def _bind_events(self) -> None:
        for widget_name, callback in (
            ("refresh_peers_btn", self._refresh_peers),
            ("save_contact_btn", self._save_contact),
            ("apply_contact_btn", self._apply_contact_to_destination),
            ("delete_contact_btn", self._delete_contact),
            ("pick_file_btn", self._pick_file),
            ("pick_folder_btn", self._pick_folder),
            ("pick_save_dir_btn", self._pick_receive_directory),
            ("send_btn", self._start_send),
            ("recv_btn", self._start_receive),
            ("cancel_recv_btn", self._cancel_receive),
        ):
            self.view.connect(widget_name, callback)

        self.view.connect_text_changed("contact_dd", self._on_contact_selected)
        self.view.connect_text_changed("peer_dd", self._on_peer_selected)
        self.view.connect_text_changed("ip_ver_dd", self._on_send_ip_version_changed)
        self.view.connect_input_changed("recv_port_input", self._sync_discovery_port)
        self.view.set_on_close(self.shutdown)

    def _hydrate_view(self) -> None:
        self.view.set_receive_directory(self.receive_directory)
        self.view.set_status("Pret. L'interface et les services reseau sont initialises.")
        self._refresh_contacts()
        self._refresh_network_badge()
        self._refresh_device_dropdown([])
        self._sync_discovery_port(self.view.text("recv_port_input"))

        try:
            self.discovery_service.start()
        except Exception as error:
            self.view.set_peer_details("Decouverte reseau indisponible sur cette machine.")
            self.view.notify(str(error), "warning")

    def _refresh_contacts(self, selected: str | None = None) -> None:
        names = [NEW_CONTACT_LABEL, *self.contact_store.list_names()]
        current = selected or self.view.current_text("contact_dd") or NEW_CONTACT_LABEL
        self.view.populate_contacts(names, selected=current)
        self.view.set_badge_text("contacts_badge", f"{len(names) - 1} contact(s)")

    def _refresh_network_badge(self) -> None:
        addresses = get_local_addresses()
        network_text = " / ".join(addresses[:2]) if addresses else "Aucune IP detectee"
        self.view.set_badge_text("network_badge", f"Reseau local: {network_text}")

    def _refresh_device_dropdown(
        self,
        peers: list[DiscoveredPeer],
        selected_label: str | None = None,
    ) -> None:
        self.peers_by_label = {peer.label: peer for peer in peers}
        labels = [MANUAL_TARGET_LABEL, *self.peers_by_label]
        current = selected_label or self.view.current_text("peer_dd") or MANUAL_TARGET_LABEL
        self.view.populate_devices(labels, selected=current)
        self.view.set_badge_text("devices_badge", f"{len(peers)} appareil(s) detecte(s)")

        active_label = current if current in self.peers_by_label else MANUAL_TARGET_LABEL
        if active_label == MANUAL_TARGET_LABEL:
            if peers:
                self.view.set_peer_details("Selectionnez un appareil detecte ou gardez la saisie manuelle.")
            else:
                self.view.set_peer_details("Aucune autre instance PulseSend detectee pour le moment.")
        else:
            peer = self.peers_by_label[active_label]
            self.view.set_peer_details(peer.details)

    def _refresh_peers(self) -> None:
        self.view.set_status("Rafraichissement des appareils detectes...")
        try:
            self.discovery_service.refresh()
        except Exception as error:
            self.view.notify(str(error), "error")

    def _on_peers_changed(self, peers: list[DiscoveredPeer]) -> None:
        self.view.call_in_ui(lambda discovered=peers: self._refresh_device_dropdown(discovered))

    def _on_peer_selected(self, label: str) -> None:
        peer = self.peers_by_label.get(label)
        if peer is None:
            self.view.set_peer_details("Saisie manuelle active. Vous pouvez entrer l'IP a la main.")
            return

        target_ip, version = self._peer_target(peer)
        self.view.set_host(target_ip)
        self.view.set_send_port(str(peer.port))
        self.view.set_ip_version(version)
        self.view.set_peer_details(peer.details)
        self.view.set_status("Destination reseau detectee et pre-remplie.")

    def _on_send_ip_version_changed(self, _: str) -> None:
        selected_label = self.view.current_text("peer_dd")
        peer = self.peers_by_label.get(selected_label)
        if peer is None:
            return

        target_ip, version = self._peer_target(peer)
        if target_ip:
            self.view.set_host(target_ip)
            self.view.set_ip_version(version)

    def _on_contact_selected(self, name: str) -> None:
        if not name or name == NEW_CONTACT_LABEL:
            self.loaded_contact_name = None
            self.view.clear_contact_form()
            self.view.set_status("Edition d'un nouveau contact.")
            return

        contact = self.contact_store.get_contact(name)
        if contact is None:
            return

        self.loaded_contact_name = contact.name
        self.view.set_contact_form(
            name=contact.name,
            ip=contact.ip,
            port=str(contact.port),
            ip_version="IPv6" if contact.ipv6 else "IPv4",
        )
        self.view.set_status("Contact charge dans le carnet d'adresses.")

    def _save_contact(self) -> None:
        name = self.view.text("contact_name_input")
        ip_value = self.view.text("contact_ip_input")
        if not name:
            self.view.notify("Entrez un nom pour le contact.", "warning")
            return
        if not ip_value:
            self.view.notify("Entrez une adresse IP pour le contact.", "warning")
            return

        try:
            normalized_ip = canonical_ip(ip_value)
            port = self._parse_port(self.view.text("contact_port_input"))
        except ValueError as error:
            self.view.notify(str(error), "error")
            return

        contact = Contact(
            name=name,
            ip=normalized_ip,
            port=port,
            ipv6=":" in normalized_ip,
        )
        previous_name = self.loaded_contact_name
        self.contact_store.save_contact(contact)
        if previous_name and previous_name != contact.name:
            self.contact_store.delete_contact(previous_name)

        self.loaded_contact_name = contact.name
        self.view.set_contact_form(
            name=contact.name,
            ip=contact.ip,
            port=str(contact.port),
            ip_version="IPv6" if contact.ipv6 else "IPv4",
        )
        self._refresh_contacts(selected=contact.name)
        self.view.notify(f'Contact "{contact.name}" sauvegarde.', "success")

    def _apply_contact_to_destination(self) -> None:
        ip_value = self.view.text("contact_ip_input")
        if not ip_value:
            self.view.notify("Aucun contact pret a appliquer.", "warning")
            return

        try:
            normalized_ip = canonical_ip(ip_value)
            port = self._parse_port(self.view.text("contact_port_input"))
        except ValueError as error:
            self.view.notify(str(error), "error")
            return

        self.view.set_host(normalized_ip)
        self.view.set_send_port(str(port))
        self.view.set_ip_version("IPv6" if ":" in normalized_ip else "IPv4")
        self.view.set_status("Destination chargee depuis le carnet d'adresses.")

    def _delete_contact(self) -> None:
        name = self.loaded_contact_name or self.view.current_text("contact_dd")
        if not name or name == NEW_CONTACT_LABEL:
            self.view.notify("Selectionnez un contact a supprimer.", "warning")
            return

        removed = self.contact_store.delete_contact(name)
        if removed:
            self.loaded_contact_name = None
            self.view.clear_contact_form()
            self._refresh_contacts(selected=NEW_CONTACT_LABEL)
            self.view.notify(f'Contact "{name}" supprime.', "info")

    def _pick_file(self) -> None:
        selected = self.view.choose_file()
        if selected is None:
            return

        self.selected_path = selected
        self.view.set_selected_path(selected)
        self.view.set_status("Fichier pret pour l'envoi.")

    def _pick_folder(self) -> None:
        selected = self.view.choose_directory("Choisir un dossier")
        if selected is None:
            return

        self.selected_path = selected
        self.view.set_selected_path(selected)
        self.view.set_status("Dossier pret pour l'envoi.")

    def _pick_receive_directory(self) -> None:
        selected = self.view.choose_directory("Choisir le dossier de reception")
        if selected is None:
            return

        self.receive_directory = selected
        self.view.set_receive_directory(selected)
        self.view.set_status("Dossier de reception mis a jour.")

    def _sync_discovery_port(self, raw_value: str) -> None:
        self.discovery_service.set_transfer_port(self._parse_port_or_default(raw_value))

    def _start_send(self) -> None:
        try:
            request = self._build_send_request()
        except ValueError as error:
            self.view.notify(str(error), "error")
            return

        self.view.set_action_enabled("send_btn", False)
        self.view.set_progress(0)
        self.view.set_status("Preparation de l'envoi...")

        threading.Thread(
            target=self._run_send,
            args=(request,),
            daemon=True,
        ).start()

    def _run_send(self, request: SendRequest) -> None:
        try:
            self.transfer_service.send(
                request,
                progress_cb=lambda value: self.view.call_in_ui(
                    lambda progress=value: self.view.set_progress(progress)
                ),
                status_cb=lambda message: self.view.call_in_ui(
                    lambda status=message: self.view.set_status(status)
                ),
            )
            self.view.call_in_ui(
                lambda: self.view.notify("Transfert termine avec succes.", "success")
            )
        except Exception as error:
            self.view.call_in_ui(
                lambda message=str(error): self.view.notify(message, "error")
            )
        finally:
            self.view.call_in_ui(lambda: self.view.set_action_enabled("send_btn", True))

    def _start_receive(self) -> None:
        try:
            request = self._build_receive_request()
        except ValueError as error:
            self.view.notify(str(error), "error")
            return

        self.receive_cancel_event = threading.Event()
        request.cancel_event = self.receive_cancel_event
        self.view.set_action_enabled("recv_btn", False)
        self.view.set_action_enabled("cancel_recv_btn", True)
        self.view.set_progress(0)
        self.view.set_status("Initialisation de l'ecoute...")

        threading.Thread(
            target=self._run_receive,
            args=(request,),
            daemon=True,
        ).start()

    def _cancel_receive(self) -> None:
        if self.receive_cancel_event is None:
            return

        self.receive_cancel_event.set()
        self.view.set_action_enabled("cancel_recv_btn", False)
        self.view.set_status("Annulation de la reception...")

    def _run_receive(self, request: ReceiveRequest) -> None:
        try:
            final_path = self.transfer_service.receive(
                request,
                progress_cb=lambda value: self.view.call_in_ui(
                    lambda progress=value: self.view.set_progress(progress)
                ),
                status_cb=lambda message: self.view.call_in_ui(
                    lambda status=message: self.view.set_status(status)
                ),
            )
            self.view.call_in_ui(
                lambda path=final_path: self.view.notify(
                    f"Reception terminee: {path.name}",
                    "success",
                )
            )
        except InterruptedError:
            self.view.call_in_ui(
                lambda: self.view.notify("Reception annulee.", "info")
            )
            self.view.call_in_ui(
                lambda: self.view.set_status("Reception annulee.")
            )
        except Exception as error:
            self.view.call_in_ui(
                lambda message=str(error): self.view.notify(message, "error")
            )
        finally:
            self.receive_cancel_event = None
            self.view.call_in_ui(lambda: self.view.set_action_enabled("recv_btn", True))
            self.view.call_in_ui(lambda: self.view.set_action_enabled("cancel_recv_btn", False))

    def _build_send_request(self) -> SendRequest:
        if self.selected_path is None:
            raise ValueError("Selectionnez un fichier ou un dossier a envoyer.")

        host = self.view.text("host_input")
        if not host:
            raise ValueError("Entrez une adresse IP de destination.")

        return SendRequest(
            source_path=self.selected_path,
            host=host,
            port=self._parse_port(self.view.text("send_port_input")),
            ipv6=self.view.current_text("ip_ver_dd") == "IPv6",
            chunk_size=CHUNK_PRESETS.get(
                self.view.current_text("chunk_dd"),
                CHUNK_PRESETS[DEFAULT_CHUNK_LABEL],
            ),
            passphrase=self.view.text("send_pass_input"),
        )

    def _build_receive_request(self) -> ReceiveRequest:
        allowed_ip = self.view.text("allowed_ip_input")
        if allowed_ip:
            try:
                canonical_ip(allowed_ip)
            except ValueError as error:
                raise ValueError("Entrez une adresse IP source valide.") from error

        return ReceiveRequest(
            port=self._parse_port(self.view.text("recv_port_input")),
            allowed_ip=allowed_ip,
            passphrase=self.view.text("recv_pass_input"),
            save_directory=self.receive_directory,
        )

    def _peer_target(self, peer: DiscoveredPeer) -> tuple[str, str]:
        preferred_version = self.view.current_text("ip_ver_dd")
        prefer_ipv6 = preferred_version == "IPv6" or (preferred_version == "" and peer.has_ipv6)

        target_ip = peer.preferred_ip(prefer_ipv6=prefer_ipv6)
        version = "IPv6" if ":" in target_ip else "IPv4"
        return target_ip, version

    @staticmethod
    def _parse_port(raw_value: str) -> int:
        value = raw_value.strip() if raw_value else ""
        if not value:
            return DEFAULT_PORT

        try:
            port = int(value)
        except ValueError as error:
            raise ValueError("Le port doit etre un nombre valide.") from error

        if not 1 <= port <= 65535:
            raise ValueError("Le port doit etre compris entre 1 et 65535.")

        return port

    @staticmethod
    def _parse_port_or_default(raw_value: str) -> int:
        try:
            return FileTransferController._parse_port(raw_value)
        except ValueError:
            return DEFAULT_PORT
