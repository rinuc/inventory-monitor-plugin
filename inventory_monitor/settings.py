"""
Plugin Settings Helper Module for Inventory Monitor Plugin.

This module provides centralized access to plugin configuration settings
and helper functions for commonly used settings.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

# Warning thresholds applied when ``warning_days`` does not mention an
# attribute at all. Setting the key explicitly to None disables colour
# indicators for that attribute.
DEFAULT_WARNING_DAYS = {
    "service": 60,
    "warranty": 60,
    "invoicing": 30,
}

# Configurable (value, label) lists for decommissioning. They are applied at
# runtime by forms, serializers, filters and clean(), never as model choices=:
# with choices= full_clean() would reject a value removed from the
# configuration on every save of a record that still carries it.
DECOMMISSIONING_REQUIREMENTS_CHOICES = "decommissioning_requirements_choices"
SANITIZATION_METHOD_CHOICES = "sanitization_method_choices"
CHOICE_SETTINGS = (DECOMMISSIONING_REQUIREMENTS_CHOICES, SANITIZATION_METHOD_CHOICES)
# Lists that must not be empty: with no sanitization method configured no
# record could carry a sanitization date.
NON_EMPTY_CHOICE_SETTINGS = (SANITIZATION_METHOD_CHOICES,)
# max_length of the model fields storing these values
CHOICE_VALUE_MAX_LENGTH = 50

DEFAULT_DECOMMISSIONING_CHOICES = [
    ("clear", "Clear (overwrite / shred)"),
    ("purge", "Purge (ATA Secure Erase / NVMe Sanitize)"),
    ("crypto_erase", "Cryptographic erase (Pure Drive Erase)"),
    ("zeroize", "Zeroize (Juniper)"),
    ("factory_reset", "Factory reset"),
    ("destroy", "Physical destruction"),
    ("delegated_vendor", "Delegated to vendor"),
    ("not_applicable", "Not applicable"),
]


def get_plugin_settings():
    """
    Get all plugin configuration settings.

    Returns:
        dict: Plugin configuration settings dictionary
    """
    return settings.PLUGINS_CONFIG.get("inventory_monitor", {})


def get_probe_recent_days():
    """
    Get the number of days to consider a probe "recent".

    Returns:
        int: Number of days (default: 7)
    """
    return get_plugin_settings().get("probe_recent_days", 7)


def get_external_inventory_status_config():
    """
    Get the external inventory status configuration.
    Returns empty dict if not configured.

    Returns:
        dict: Status configuration with codes, labels, and colors
    """
    return get_plugin_settings().get("external_inventory_status_config", {})


def get_external_inventory_status_config_safe():
    """
    Safely get external inventory status configuration with validation.
    Checks if configuration exists and is not empty.

    Returns:
        tuple: (config_dict, is_configured)
            - config_dict: Status configuration dictionary
            - is_configured: Boolean indicating if valid configuration exists
    """
    plugin_settings = get_plugin_settings()

    # Check if config key exists
    if "external_inventory_status_config" not in plugin_settings:
        return {}, False

    # Get the configuration
    status_config = plugin_settings.get("external_inventory_status_config", {})

    # Check if configuration is not empty
    if not status_config:
        return {}, False

    return status_config, True


def get_external_inventory_tooltip_template():
    """
    Get the configurable tooltip template for external inventory status.

    Returns:
        str: Template string for the tooltip content
    """
    default_template = "<span class='badge text-bg-{color}'>{code}</span> {label}"
    return get_plugin_settings().get("external_inventory_tooltip_template", default_template)


def get_warning_days(attribute):
    """
    Get the warning days threshold for a specific attribute.

    An attribute that is not mentioned in ``warning_days`` falls back to
    DEFAULT_WARNING_DAYS, so color indicators work without configuration.
    To turn them off, set the key explicitly to None.

    Args:
        attribute: The attribute key (e.g., "service", "warranty")

    Returns:
        int or None: Number of warning days, or None if explicitly disabled
                     (which means no color indicators should be shown)
    """
    warning_days = get_plugin_settings().get("warning_days", {})
    if not isinstance(warning_days, dict):
        # e.g. "warning_days": None — the natural way to disable every indicator.
        return None
    if attribute in warning_days:
        # An explicit value wins, including None which disables indicators.
        return warning_days[attribute]
    return DEFAULT_WARNING_DAYS.get(attribute)


def _get_choices(key):
    if key not in CHOICE_SETTINGS:
        raise ValueError(f"{key!r} is not a configurable choice list")
    choices = get_plugin_settings().get(key)
    if choices is None:
        # PluginConfig.validate() fills in the default at startup; it is missing
        # only when PLUGINS_CONFIG is replaced afterwards (e.g. override_settings).
        choices = DEFAULT_DECOMMISSIONING_CHOICES
    return [(value, label) for value, label in choices]


def get_choices(key):
    """
    Get a configurable choice list by its key.

    Args:
        key: One of CHOICE_SETTINGS

    Returns:
        list: (value, label) tuples
    """
    return _get_choices(key)


def get_decommissioning_requirements_choices():
    """
    Get the configured AssetType decommissioning requirements.

    Returns:
        list: (value, label) tuples
    """
    return _get_choices(DECOMMISSIONING_REQUIREMENTS_CHOICES)


def get_sanitization_method_choices():
    """
    Get the configured decommissioning record sanitization methods.

    Returns:
        list: (value, label) tuples
    """
    return _get_choices(SANITIZATION_METHOD_CHOICES)


def is_configured(key, value):
    """
    Check whether a value is in a configurable choice list.

    Args:
        key: One of CHOICE_SETTINGS
        value: The stored value; an empty value is never configured

    Returns:
        bool: True if the value is currently configured
    """
    return bool(value) and value in dict(_get_choices(key))


def choice_label(key, value):
    """
    Get the label of a value in a configurable choice list.

    Returns:
        str: The configured label, or the value itself if it is not configured
    """
    return dict(_get_choices(key)).get(value, value)


def not_configured_label(value):
    """
    Get the label shown for a stored value that is no longer configured.

    Returns:
        str: The value followed by "(not in configuration)"
    """
    return _("{value} (not in configuration)").format(value=value)


def choice_display(key, value):
    """
    Get the text shown for a value of a configurable choice list.

    Returns:
        str: The configured label, not_configured_label() for a removed value, or "" if empty
    """
    if not value:
        return ""
    if is_configured(key, value):
        return choice_label(key, value)
    return not_configured_label(value)


def get_choices_including(key, value):
    """
    Get a configurable choice list, plus ``value`` if it is no longer configured.

    Edit forms pass the value of the object being edited: the object can keep a
    value removed from the configuration, which no other object is offered.

    Returns:
        list: (value, label) tuples
    """
    choices = _get_choices(key)
    if value and value not in dict(choices):
        choices.append((value, not_configured_label(value)))
    return choices


def validate_choice_settings(plugin_config):
    """
    Validate the configurable choice lists of a plugin configuration.

    Each list must be a sequence of (value, label) pairs with unique, non-empty
    string values of at most CHOICE_VALUE_MAX_LENGTH characters and non-empty
    string labels. A missing key falls back to the default list.

    Raises:
        ImproperlyConfigured: naming the offending key and value
    """
    for key in CHOICE_SETTINGS:
        choices = plugin_config.get(key, DEFAULT_DECOMMISSIONING_CHOICES)
        prefix = f"PLUGINS_CONFIG['inventory_monitor'][{key!r}]"

        if not isinstance(choices, (list, tuple)):
            raise ImproperlyConfigured(f"{prefix} must be a list of (value, label) pairs, got {choices!r}.")
        if not choices and key in NON_EMPTY_CHOICE_SETTINGS:
            raise ImproperlyConfigured(f"{prefix} must not be empty.")

        seen = set()
        for entry in choices:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ImproperlyConfigured(f"{prefix}: {entry!r} is not a (value, label) pair.")
            value, label = entry
            if not isinstance(value, str):
                raise ImproperlyConfigured(f"{prefix}: value {value!r} must be a string.")
            if not value.strip():
                raise ImproperlyConfigured(f"{prefix}: value {value!r} must not be empty.")
            if len(value) > CHOICE_VALUE_MAX_LENGTH:
                raise ImproperlyConfigured(
                    f"{prefix}: value {value!r} is longer than {CHOICE_VALUE_MAX_LENGTH} characters."
                )
            if value in seen:
                raise ImproperlyConfigured(f"{prefix}: duplicate value {value!r}.")
            if not isinstance(label, str) or not label.strip():
                raise ImproperlyConfigured(f"{prefix}: label of value {value!r} must be a non-empty string.")
            seen.add(value)
