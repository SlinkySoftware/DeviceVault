from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

BackupCallable = Callable[[str, Dict], str]


@dataclass
class BackupPlugin:
    """Metadata and entrypoint for a backup method plugin."""
    key: str
    friendly_name: str
    description: str
    entrypoint: BackupCallable

    def run(self, ip_address: str, credentials: Dict) -> str:
        """Invoke the plugin entrypoint with normalized arguments."""
        return self.entrypoint(ip_address, credentials)
