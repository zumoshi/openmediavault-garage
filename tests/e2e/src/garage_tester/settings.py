"""Settings for the garage tester, from environment variables.

Required:
    OMV_HOST            http host of the OMV box, e.g. omv-test.lan
    OMV_SSH             ssh target for root access, e.g. root@omv-test.lan
                        (anything your ssh config understands)
    OMV_ADMIN_PASSWORD  workbench password of the admin user
    OMV_DISK            substring of the devicefile new shares are created
                        on, e.g. "sda" or "loop"
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    ssh_target: str
    admin_password: str
    disk: str
    admin_user: str = "admin"

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [k for k in ("OMV_HOST", "OMV_SSH", "OMV_ADMIN_PASSWORD", "OMV_DISK")
                   if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"missing environment variables: {', '.join(missing)}")
        return cls(
            host=os.environ["OMV_HOST"],
            ssh_target=os.environ["OMV_SSH"],
            admin_password=os.environ["OMV_ADMIN_PASSWORD"],
            disk=os.environ["OMV_DISK"],
        )
