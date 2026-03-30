from .controller import FileTransferController


def run() -> int:
    return FileTransferController().run()


__all__ = ["FileTransferController", "run"]
