"""Which provisioning settings are missing, by name (KAN-248).

A store stays PROVISIONING when its QStash job cannot be published, delivered, verified
or run. Most of those causes are production configuration, so ``/health/ready`` reports
the missing variable NAMES (never a value) and the app logs them at start. Local and test
runs are relaxed: nothing is enqueued and the local provider is expected.
"""

from dataclasses import dataclass

from app.core.config import Settings

SIGNING_KEY_NAME = "QSTASH_CURRENT_SIGNING_KEY"
NEON_NAMES = ("NEON_API_KEY", "NEON_PROJECT_ID", "NEON_BRANCH_ID", "NEON_ROLE_NAME")


@dataclass(frozen=True)
class ProvisioningReadiness:
    ready: bool
    missing: tuple[str, ...]


def _is_set(value: object) -> bool:
    if value is None:
        return False
    secret = getattr(value, "get_secret_value", None)
    return bool(secret() if secret else value)


def check_provisioning_settings(settings: Settings) -> ProvisioningReadiness:
    """Names of the settings store provisioning needs here and does not have."""
    if settings.relaxed_environment:
        return ProvisioningReadiness(True, ())
    required: list[str] = []
    if not _is_set(settings.QSTASH_TOKEN):
        required.append("QSTASH_TOKEN")
    if not _is_set(settings.PROVISIONING_BASE_URL):
        required.append("PROVISIONING_BASE_URL")
    if not settings.qstash_signing_keys:
        required.append(SIGNING_KEY_NAME)
    if not _is_set(settings.STORE_DB_ENCRYPTION_KEY):
        required.append("STORE_DB_ENCRYPTION_KEY")
    if settings.STORE_DB_PROVIDER != "neon":
        # "local" is development only and refuses to provision elsewhere.
        required.append("STORE_DB_PROVIDER")
    else:
        required.extend(n for n in NEON_NAMES if not _is_set(getattr(settings, n)))
    missing = tuple(required)
    return ProvisioningReadiness(not missing, missing)
