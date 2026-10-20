from netbox.plugins import PluginConfig

from .settings import (
    DECOMMISSIONING_REQUIREMENTS_CHOICES,
    DEFAULT_DECOMMISSIONING_CHOICES,
    SANITIZATION_METHOD_CHOICES,
    validate_choice_settings,
)
from .version import __version__


class NetBoxInventoryMonitorConfig(PluginConfig):
    name = "inventory_monitor"
    verbose_name = " Inventory Monitor"
    description = "Manage inventory discovered by SNMP"
    version = __version__
    base_url = "inventory-monitor"

    default_settings = {
        # Probe Status Settings
        "probe_recent_days": 7,
        # Currency Settings
        "currencies": [
            ("CZK", "Czech Koruna", "Kč"),
            ("EUR", "Euro", "€"),
            ("USD", "US Dollar", "$"),
            ("GBP", "British Pound", "£"),
            ("JPY", "Japanese Yen", "¥"),
        ],
        "default_currency": "EUR",
        "enable_netbox_attachments": False,
        # Decommissioning: (value, label) lists, replaced (not extended) by PLUGINS_CONFIG
        DECOMMISSIONING_REQUIREMENTS_CHOICES: list(DEFAULT_DECOMMISSIONING_CHOICES),
        SANITIZATION_METHOD_CHOICES: list(DEFAULT_DECOMMISSIONING_CHOICES),
    }
    required_settings = []
    min_version = "4.7.0"
    max_version = "4.7.99"

    @classmethod
    def validate(cls, user_config, netbox_version):
        # Runs at NetBox startup; super() fills in default_settings first
        super().validate(user_config, netbox_version)
        validate_choice_settings(user_config)


config = NetBoxInventoryMonitorConfig
