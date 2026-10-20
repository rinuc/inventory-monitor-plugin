"""Configurable choice lists for the decommissioning record (R4).

The lists live in PLUGINS_CONFIG, not in model ``choices=``: a value removed
from the configuration must stay valid on records that already carry it, which
``choices=`` would forbid on every full_clean(). These tests cover the runtime
helpers and the startup check; the "value removed from configuration" behaviour
of forms, filters and tables is tested in test_asset_type_decommissioning.py and
test_decommissioning_views.py, that of the API with the serializers.
"""

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from inventory_monitor import NetBoxInventoryMonitorConfig
from inventory_monitor.settings import (
    DECOMMISSIONING_REQUIREMENTS_CHOICES,
    DEFAULT_DECOMMISSIONING_CHOICES,
    SANITIZATION_METHOD_CHOICES,
    choice_display,
    choice_label,
    get_choices,
    get_choices_including,
    get_decommissioning_requirements_choices,
    get_sanitization_method_choices,
    is_configured,
    validate_choice_settings,
)

CHOICE_KEYS = (DECOMMISSIONING_REQUIREMENTS_CHOICES, SANITIZATION_METHOD_CHOICES)

EXPECTED_DEFAULTS = [
    ("clear", "Clear (overwrite / shred)"),
    ("purge", "Purge (ATA Secure Erase / NVMe Sanitize)"),
    ("crypto_erase", "Cryptographic erase (Pure Drive Erase)"),
    ("zeroize", "Zeroize (Juniper)"),
    ("factory_reset", "Factory reset"),
    ("destroy", "Physical destruction"),
    ("delegated_vendor", "Delegated to vendor"),
    ("not_applicable", "Not applicable"),
]

CUSTOM = [("wipe", "Wipe"), ("shred", "Shred")]


def plugins_config(**plugin_settings):
    return {"inventory_monitor": plugin_settings}


class DefaultChoicesTest(SimpleTestCase):
    def test_default_settings_declare_both_lists(self):
        for key in CHOICE_KEYS:
            with self.subTest(key=key):
                self.assertEqual(
                    [tuple(c) for c in NetBoxInventoryMonitorConfig.default_settings[key]], EXPECTED_DEFAULTS
                )

    def test_default_constant_matches(self):
        self.assertEqual([tuple(c) for c in DEFAULT_DECOMMISSIONING_CHOICES], EXPECTED_DEFAULTS)

    @override_settings(PLUGINS_CONFIG=plugins_config())
    def test_helpers_fall_back_to_defaults_when_key_missing(self):
        self.assertEqual(get_sanitization_method_choices(), EXPECTED_DEFAULTS)
        self.assertEqual(get_decommissioning_requirements_choices(), EXPECTED_DEFAULTS)

    @override_settings(PLUGINS_CONFIG={})
    def test_helpers_fall_back_to_defaults_without_plugin_config(self):
        self.assertEqual(get_sanitization_method_choices(), EXPECTED_DEFAULTS)

    def test_running_config_has_defaults_applied(self):
        # NetBox runs PluginConfig.validate() at startup, which fills in default_settings
        self.assertEqual(get_sanitization_method_choices(), EXPECTED_DEFAULTS)
        self.assertEqual(get_decommissioning_requirements_choices(), EXPECTED_DEFAULTS)


class OverrideChoicesTest(SimpleTestCase):
    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_override_replaces_the_default_list(self):
        self.assertEqual(get_sanitization_method_choices(), CUSTOM)
        self.assertFalse(is_configured(SANITIZATION_METHOD_CHOICES, "zeroize"))
        # The other list is independent
        self.assertEqual(get_decommissioning_requirements_choices(), EXPECTED_DEFAULTS)

    @override_settings(PLUGINS_CONFIG=plugins_config(decommissioning_requirements_choices=[["wipe", "Wipe"]]))
    def test_lists_of_lists_are_returned_as_tuples(self):
        self.assertEqual(get_decommissioning_requirements_choices(), [("wipe", "Wipe")])

    @override_settings(PLUGINS_CONFIG=plugins_config(decommissioning_requirements_choices=[]))
    def test_empty_requirements_list(self):
        self.assertEqual(get_decommissioning_requirements_choices(), [])
        self.assertFalse(is_configured(DECOMMISSIONING_REQUIREMENTS_CHOICES, "clear"))


class ConfiguredValueTest(SimpleTestCase):
    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_is_configured(self):
        self.assertTrue(is_configured(SANITIZATION_METHOD_CHOICES, "wipe"))
        self.assertFalse(is_configured(SANITIZATION_METHOD_CHOICES, "zeroize"))
        self.assertFalse(is_configured(SANITIZATION_METHOD_CHOICES, ""))
        self.assertFalse(is_configured(SANITIZATION_METHOD_CHOICES, None))

    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_choice_label(self):
        self.assertEqual(choice_label(SANITIZATION_METHOD_CHOICES, "shred"), "Shred")
        # A value no longer configured is shown as is, never dropped
        self.assertEqual(choice_label(SANITIZATION_METHOD_CHOICES, "zeroize"), "zeroize")
        self.assertEqual(choice_label(SANITIZATION_METHOD_CHOICES, ""), "")

    def test_value_back_in_configuration_is_normal_again(self):
        with self.settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM)):
            self.assertFalse(is_configured(SANITIZATION_METHOD_CHOICES, "zeroize"))
        with self.settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM + [("zeroize", "Z")])):
            self.assertTrue(is_configured(SANITIZATION_METHOD_CHOICES, "zeroize"))
            self.assertEqual(choice_label(SANITIZATION_METHOD_CHOICES, "zeroize"), "Z")

    def test_unknown_key_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            is_configured("currencies", "EUR")


class ChoiceDisplayTest(SimpleTestCase):
    """What forms and tables show for a stored value (R4)."""

    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_get_choices(self):
        self.assertEqual(get_choices(SANITIZATION_METHOD_CHOICES), CUSTOM)
        self.assertEqual(get_choices(DECOMMISSIONING_REQUIREMENTS_CHOICES), EXPECTED_DEFAULTS)

    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_choice_display(self):
        self.assertEqual(choice_display(SANITIZATION_METHOD_CHOICES, "wipe"), "Wipe")
        self.assertEqual(choice_display(SANITIZATION_METHOD_CHOICES, "zeroize"), "zeroize (not in configuration)")
        self.assertEqual(choice_display(SANITIZATION_METHOD_CHOICES, ""), "")

    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_choices_including_a_removed_value(self):
        self.assertEqual(
            get_choices_including(SANITIZATION_METHOD_CHOICES, "zeroize"),
            CUSTOM + [("zeroize", "zeroize (not in configuration)")],
        )

    @override_settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=CUSTOM))
    def test_choices_including_a_configured_or_empty_value(self):
        self.assertEqual(get_choices_including(SANITIZATION_METHOD_CHOICES, "wipe"), CUSTOM)
        self.assertEqual(get_choices_including(SANITIZATION_METHOD_CHOICES, ""), CUSTOM)
        self.assertEqual(get_choices_including(SANITIZATION_METHOD_CHOICES, None), CUSTOM)

    def test_choices_including_does_not_alter_the_configuration(self):
        with self.settings(PLUGINS_CONFIG=plugins_config(sanitization_method_choices=list(CUSTOM))):
            get_choices_including(SANITIZATION_METHOD_CHOICES, "zeroize")
            self.assertEqual(get_choices(SANITIZATION_METHOD_CHOICES), CUSTOM)


class ValidateChoiceSettingsTest(SimpleTestCase):
    def assertInvalid(self, key, value, *fragments):
        with self.assertRaises(ImproperlyConfigured) as cm:
            validate_choice_settings({key: value})
        message = str(cm.exception)
        self.assertIn(key, message)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def test_defaults_are_valid(self):
        validate_choice_settings({})
        validate_choice_settings({key: DEFAULT_DECOMMISSIONING_CHOICES for key in CHOICE_KEYS})

    def test_custom_lists_are_valid(self):
        validate_choice_settings({key: CUSTOM for key in CHOICE_KEYS})
        validate_choice_settings({key: [list(c) for c in CUSTOM] for key in CHOICE_KEYS})

    def test_value_of_exactly_50_characters_is_valid(self):
        validate_choice_settings({SANITIZATION_METHOD_CHOICES: [("x" * 50, "Fifty")]})

    def test_duplicate_values(self):
        for key in CHOICE_KEYS:
            with self.subTest(key=key):
                self.assertInvalid(key, [("wipe", "Wipe"), ("wipe", "Wipe again")], "'wipe'", "duplicate")

    def test_empty_value(self):
        for key in CHOICE_KEYS:
            for value in ("", "   "):
                with self.subTest(key=key, value=value):
                    self.assertInvalid(key, [(value, "Empty")], "empty")

    def test_value_longer_than_50(self):
        for key in CHOICE_KEYS:
            with self.subTest(key=key):
                self.assertInvalid(key, [("x" * 51, "Too long")], "x" * 51, "50")

    def test_value_not_a_string(self):
        self.assertInvalid(SANITIZATION_METHOD_CHOICES, [(1, "One")], "1")

    def test_empty_or_missing_label(self):
        self.assertInvalid(SANITIZATION_METHOD_CHOICES, [("wipe", "")], "'wipe'", "label")
        self.assertInvalid(SANITIZATION_METHOD_CHOICES, [("wipe", None)], "'wipe'", "label")

    def test_entry_not_a_pair(self):
        for entry in (("wipe",), ("wipe", "Wipe", "red"), "wipe", {"wipe": "Wipe"}):
            with self.subTest(entry=entry):
                self.assertInvalid(SANITIZATION_METHOD_CHOICES, [entry], "pair")

    def test_list_not_a_sequence(self):
        for value in ("wipe", {"wipe": "Wipe"}, None, 3):
            with self.subTest(value=value):
                self.assertInvalid(SANITIZATION_METHOD_CHOICES, value, "list")

    def test_empty_sanitization_list_is_rejected(self):
        # With no method configured no record could ever carry a sanitization date (V3 + V4)
        self.assertInvalid(SANITIZATION_METHOD_CHOICES, [], "empty")

    def test_empty_requirements_list_is_allowed(self):
        validate_choice_settings({DECOMMISSIONING_REQUIREMENTS_CHOICES: []})


class PluginConfigValidateTest(SimpleTestCase):
    """The check runs at NetBox startup through PluginConfig.validate()."""

    netbox_version = NetBoxInventoryMonitorConfig.min_version

    def test_defaults_are_applied_and_valid(self):
        user_config = {}
        NetBoxInventoryMonitorConfig.validate(user_config, self.netbox_version)
        for key in CHOICE_KEYS:
            with self.subTest(key=key):
                self.assertEqual([tuple(c) for c in user_config[key]], EXPECTED_DEFAULTS)

    def test_invalid_configuration_stops_startup(self):
        user_config = {SANITIZATION_METHOD_CHOICES: [("wipe", "Wipe"), ("wipe", "Again")]}
        with self.assertRaises(ImproperlyConfigured):
            NetBoxInventoryMonitorConfig.validate(user_config, self.netbox_version)
