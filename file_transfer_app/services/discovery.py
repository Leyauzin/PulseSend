import socket
import threading
import uuid
from typing import Callable

from zeroconf import IPVersion, ServiceBrowser, ServiceInfo, ServiceListener, Zeroconf

from file_transfer_app.config import DEFAULT_PORT, DISCOVERY_SERVICE_TYPE
from file_transfer_app.models import DiscoveredPeer
from file_transfer_app.services.network import get_local_addresses, normalize_ip

PeersCallback = Callable[[list[DiscoveredPeer]], None] | None


class _PulseSendListener(ServiceListener):
    def __init__(self, manager: "PeerDiscoveryService"):
        self.manager = manager

    def add_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self.manager._upsert_service(zeroconf, service_type, name)

    def update_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self.manager._upsert_service(zeroconf, service_type, name)

    def remove_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        self.manager._remove_service(name)


class PeerDiscoveryService:
    def __init__(self, app_name: str, on_peers_changed: PeersCallback = None):
        self.app_name = app_name
        self.on_peers_changed = on_peers_changed
        self.instance_id = self._make_instance_id()
        self.device_name = socket.gethostname() or app_name
        self.transfer_port = DEFAULT_PORT

        self._lock = threading.Lock()
        self._peers: dict[str, DiscoveredPeer] = {}
        self._service_name_to_peer_id: dict[str, str] = {}
        self._zeroconf: Zeroconf | None = None
        self._browser: ServiceBrowser | None = None
        self._listener = _PulseSendListener(self)
        self._registered_info: ServiceInfo | None = None

    def start(self) -> None:
        if self._zeroconf is not None:
            return

        self.instance_id = self._make_instance_id()
        self._zeroconf = Zeroconf(ip_version=IPVersion.All)
        self._browser = ServiceBrowser(self._zeroconf, DISCOVERY_SERVICE_TYPE, self._listener)
        self._register_self()

    def stop(self) -> None:
        if self._browser is not None:
            self._browser.cancel()
            self._browser = None

        if self._zeroconf is not None and self._registered_info is not None:
            try:
                self._zeroconf.unregister_service(self._registered_info)
            except Exception:
                pass

        if self._zeroconf is not None:
            self._zeroconf.close()
            self._zeroconf = None

        self._registered_info = None
        with self._lock:
            self._peers.clear()
            self._service_name_to_peer_id.clear()
        self._emit_peers_changed()

    def refresh(self) -> None:
        if self._zeroconf is None:
            self.start()
            return

        with self._lock:
            self._peers.clear()
            self._service_name_to_peer_id.clear()
        self._emit_peers_changed()

        if self._browser is not None:
            self._browser.cancel()
        self._browser = ServiceBrowser(self._zeroconf, DISCOVERY_SERVICE_TYPE, self._listener)
        self._register_self()

    def set_transfer_port(self, port: int) -> None:
        self.transfer_port = port
        if self._zeroconf is not None:
            self._register_self()

    def peers(self) -> list[DiscoveredPeer]:
        with self._lock:
            return sorted(
                self._peers.values(),
                key=lambda peer: (peer.name.lower(), peer.preferred_ip(prefer_ipv6=True)),
            )

    def _register_self(self) -> None:
        if self._zeroconf is None:
            return

        ipv4_addresses, ipv6_addresses = self._split_addresses(get_local_addresses())
        addresses = self._service_addresses(ipv4_addresses, ipv6_addresses)
        service_name = f"{self.device_name}-{self.instance_id}.{DISCOVERY_SERVICE_TYPE}"
        info = ServiceInfo(
            DISCOVERY_SERVICE_TYPE,
            service_name,
            addresses=addresses,
            port=self.transfer_port,
            properties={
                b"instance_id": self.instance_id.encode("utf-8"),
                b"device_name": self.device_name.encode("utf-8"),
                b"ipv4": ",".join(ipv4_addresses).encode("utf-8"),
                b"ipv6": ",".join(ipv6_addresses).encode("utf-8"),
            },
        )

        if self._registered_info is not None:
            try:
                self._zeroconf.unregister_service(self._registered_info)
            except Exception:
                pass

        self._zeroconf.register_service(info, allow_name_change=True)
        self._registered_info = info

    def _upsert_service(self, zeroconf: Zeroconf, service_type: str, name: str) -> None:
        info = zeroconf.get_service_info(service_type, name, timeout=1500)
        if info is None:
            return

        properties = info.properties or {}
        instance_id = self._decode_property(properties.get(b"instance_id")) or name
        if instance_id == self.instance_id:
            return

        device_name = self._decode_property(properties.get(b"device_name")) or name.split(".")[0]
        ipv4_address, ipv6_address = self._extract_addresses(info)
        if not ipv4_address and not ipv6_address:
            return

        peer = DiscoveredPeer(
            instance_id=instance_id,
            name=device_name,
            ipv4=ipv4_address,
            ipv6=ipv6_address,
            port=self._safe_port(info.port),
        )

        with self._lock:
            self._peers[instance_id] = peer
            self._service_name_to_peer_id[name] = instance_id

        self._emit_peers_changed()

    def _remove_service(self, service_name: str) -> None:
        with self._lock:
            peer_id = self._service_name_to_peer_id.pop(service_name, None)
            if peer_id is None:
                return
            self._peers.pop(peer_id, None)

        self._emit_peers_changed()

    def _extract_addresses(self, info: ServiceInfo) -> tuple[str, str]:
        ipv4_addresses: list[str] = []
        ipv6_addresses: list[str] = []

        for parsed in info.parsed_scoped_addresses(IPVersion.All):
            self._append_address(normalize_ip(parsed), ipv4_addresses, ipv6_addresses)

        properties = info.properties or {}
        for raw_value in (
            properties.get(b"ipv4"),
            properties.get("ipv4"),
            properties.get(b"ipv6"),
            properties.get("ipv6"),
        ):
            for address in self._decode_address_list(raw_value):
                self._append_address(address, ipv4_addresses, ipv6_addresses)

        global_ipv6 = [address for address in ipv6_addresses if not address.startswith("fe80:")]
        chosen_ipv6 = global_ipv6[0] if global_ipv6 else (ipv6_addresses[0] if ipv6_addresses else "")
        chosen_ipv4 = ipv4_addresses[0] if ipv4_addresses else ""
        return chosen_ipv4, chosen_ipv6

    def _service_addresses(self, ipv4_addresses: list[str], ipv6_addresses: list[str]) -> list[bytes]:
        addresses = []
        for ip_address in [*ipv4_addresses, *ipv6_addresses]:
            try:
                if ":" in ip_address:
                    addresses.append(socket.inet_pton(socket.AF_INET6, ip_address.split("%", 1)[0]))
                else:
                    addresses.append(socket.inet_aton(ip_address))
            except OSError:
                continue

        if addresses:
            return addresses

        fallback_ip = socket.gethostbyname(socket.gethostname())
        return [socket.inet_aton(fallback_ip)]

    def _emit_peers_changed(self) -> None:
        if self.on_peers_changed is not None:
            self.on_peers_changed(self.peers())

    @staticmethod
    def _decode_property(value: bytes | None) -> str:
        if not value:
            return ""
        return value.decode("utf-8", errors="ignore").strip()

    @classmethod
    def _decode_address_list(cls, value) -> list[str]:
        if value is None:
            return []
        decoded = cls._decode_property(value if isinstance(value, bytes) else str(value).encode("utf-8"))
        if not decoded:
            return []
        return [item.strip() for item in decoded.split(",") if item.strip()]

    @staticmethod
    def _split_addresses(addresses: list[str]) -> tuple[list[str], list[str]]:
        ipv4_addresses: list[str] = []
        ipv6_addresses: list[str] = []
        for address in addresses:
            if ":" in address:
                ipv6_addresses.append(address)
            else:
                ipv4_addresses.append(address)
        return ipv4_addresses, ipv6_addresses

    @staticmethod
    def _append_address(address: str, ipv4_addresses: list[str], ipv6_addresses: list[str]) -> None:
        if not address:
            return
        target = ipv6_addresses if ":" in address else ipv4_addresses
        if address not in target:
            target.append(address)

    @staticmethod
    def _make_instance_id() -> str:
        return f"{socket.gethostname().lower()}-{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _safe_port(value: object) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            return DEFAULT_PORT

        return port if 1 <= port <= 65535 else DEFAULT_PORT
