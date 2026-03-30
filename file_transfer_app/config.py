from pathlib import Path

APP_NAME = "PulseSend"
BASE_DIR = Path(__file__).resolve().parent.parent
CONTACTS_FILE = BASE_DIR / "contacts.json"
STYLE_PATH = BASE_DIR / "style.qss"

DEFAULT_PORT = 5001
DEFAULT_CHUNK_LABEL = "Auto"
WINDOW_WIDTH = 1040
WINDOW_HEIGHT = 760
MIN_WIDTH = 960
MIN_HEIGHT = 700
DISCOVERY_SERVICE_TYPE = "_pulsesend._tcp.local."

NEW_CONTACT_LABEL = "Nouveau contact"
MANUAL_TARGET_LABEL = "Saisie manuelle"

CHUNK_PRESETS: dict[str, int] = {
    "Auto": 0,
    "4 KB": 4_096,
    "16 KB": 16_384,
    "64 KB": 65_536,
    "256 KB": 262_144,
    "1 MB": 1_048_576,
    "4 MB": 4_194_304,
    "8 MB": 8_388_608,
    "16 MB": 16_777_216,
}
