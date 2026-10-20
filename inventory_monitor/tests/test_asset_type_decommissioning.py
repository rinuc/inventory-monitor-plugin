"""AssetType.decommissioning_requirements in forms, filters and table (R2, R4).

The values come from ``decommissioning_requirements_choices`` at runtime. A value
removed from the configuration stays on the asset types that carry it and stays
selectable in their edit form only. The API is tested with the serializers.
"""

from django.test import TestCase, override_settings

from inventory_monitor.filtersets import AssetTypeFilterSet
from inventory_monitor.forms import (
    AssetTypeBulkEditForm,
    AssetTypeBulkImportForm,
    AssetTypeFilterForm,
    AssetTypeForm,
)
from inventory_monitor.models import AssetType
from inventory_monitor.tables import AssetTypeTable

# decommissioning_requirements_choices without "zeroize", which the "switch" type keeps
WITHOUT_ZEROIZE = {"inventory_monitor": {"decommissioning_requirements_choices": [("clear", "Clear")]}}


def choice_values(field):
    """Values offered by a form field; the blank choice of add_blank_choice() is None, NetBox filters add "null"."""
    return [value for value, _label in field.choices if value not in (None, "null")]


def import_form(record, instance=None):
    """AssetTypeBulkImportForm as BulkImportView builds it: on update, only the CSV columns."""
    form = AssetTypeBulkImportForm(data=record, instance=instance)
    if instance is not None:
        for name in [f for f in form.fields if f not in record]:
            del form.fields[name]
    return form


class AssetTypeDecommissioningTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.switch = AssetType.objects.create(name="Switch", slug="switch", decommissioning_requirements="zeroize")
        cls.server = AssetType.objects.create(name="Server", slug="server", decommissioning_requirements="purge")
        cls.cable = AssetType.objects.create(name="Cable", slug="cable")


class AssetTypeFormTest(AssetTypeDecommissioningTestCase):
    def form_data(self, **kwargs):
        return {"name": "Router", "slug": "router", **kwargs}

    def test_configured_value_accepted(self):
        form = AssetTypeForm(data=self.form_data(decommissioning_requirements="crypto_erase"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().decommissioning_requirements, "crypto_erase")

    def test_empty_value_accepted(self):
        form = AssetTypeForm(data=self.form_data(decommissioning_requirements=""))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().decommissioning_requirements, "")

    def test_unconfigured_value_rejected(self):
        form = AssetTypeForm(data=self.form_data(decommissioning_requirements="burn"))
        self.assertFalse(form.is_valid())
        self.assertIn("decommissioning_requirements", form.errors)

    def test_choices_are_the_configured_list(self):
        form = AssetTypeForm()
        self.assertEqual(
            choice_values(form.fields["decommissioning_requirements"]),
            [
                "clear",
                "purge",
                "crypto_erase",
                "zeroize",
                "factory_reset",
                "destroy",
                "delegated_vendor",
                "not_applicable",
            ],
        )

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_value_selectable_only_for_its_instance(self):
        edit = AssetTypeForm(instance=self.switch)
        self.assertEqual(choice_values(edit.fields["decommissioning_requirements"]), ["clear", "zeroize"])
        self.assertIn(
            ("zeroize", "zeroize (not in configuration)"), edit.fields["decommissioning_requirements"].choices
        )
        self.assertEqual(choice_values(AssetTypeForm().fields["decommissioning_requirements"]), ["clear"])
        self.assertEqual(
            choice_values(AssetTypeForm(instance=self.server).fields["decommissioning_requirements"]),
            ["clear", "purge"],
        )

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_value_preserved_when_editing_another_field(self):
        form = AssetTypeForm(
            data={
                "name": "Switch",
                "slug": "switch",
                "description": "L2/L3",
                "decommissioning_requirements": "zeroize",
            },
            instance=self.switch,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.decommissioning_requirements, "zeroize")
        self.assertEqual(self.switch.description, "L2/L3")

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_value_rejected_on_another_instance(self):
        form = AssetTypeForm(data=self.form_data(decommissioning_requirements="zeroize"))
        self.assertFalse(form.is_valid())
        self.assertIn("decommissioning_requirements", form.errors)


class AssetTypeBulkEditFormTest(AssetTypeDecommissioningTestCase):
    def test_field_offers_configured_values_and_is_nullable(self):
        form = AssetTypeBulkEditForm()
        self.assertEqual(choice_values(form.fields["decommissioning_requirements"])[:2], ["clear", "purge"])
        self.assertIn("decommissioning_requirements", AssetTypeBulkEditForm.nullable_fields)

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_value_not_offered(self):
        self.assertEqual(choice_values(AssetTypeBulkEditForm().fields["decommissioning_requirements"]), ["clear"])


class AssetTypeBulkImportFormTest(AssetTypeDecommissioningTestCase):
    def test_configured_value_accepted(self):
        form = import_form({"name": "Router", "slug": "router", "decommissioning_requirements": "destroy"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().decommissioning_requirements, "destroy")

    def test_unconfigured_value_rejected(self):
        form = import_form({"name": "Router", "slug": "router", "decommissioning_requirements": "burn"})
        self.assertFalse(form.is_valid())
        self.assertIn("decommissioning_requirements", form.errors)

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_update_preserves_removed_value(self):
        form = import_form({"description": "L2/L3"}, instance=self.switch)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.decommissioning_requirements, "zeroize")

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_update_to_removed_value_rejected(self):
        form = import_form({"decommissioning_requirements": "zeroize"}, instance=self.server)
        self.assertFalse(form.is_valid())


class AssetTypeFilterTest(AssetTypeDecommissioningTestCase):
    def filter(self, **params):
        return AssetTypeFilterSet(params, AssetType.objects.all()).qs

    def test_filter_by_value(self):
        self.assertCountEqual(self.filter(decommissioning_requirements=["zeroize"]), [self.switch])
        self.assertCountEqual(
            self.filter(decommissioning_requirements=["zeroize", "purge"]), [self.switch, self.server]
        )

    def test_filter_configured(self):
        self.assertCountEqual(self.filter(decommissioning_requirements_configured="true"), [self.switch, self.server])
        self.assertCountEqual(self.filter(decommissioning_requirements_configured="false"), [])

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_filter_not_configured_finds_removed_value(self):
        """An empty value is not "not configured": there is nothing to fix."""
        self.assertCountEqual(self.filter(decommissioning_requirements_configured="false"), [self.switch, self.server])
        self.assertCountEqual(self.filter(decommissioning_requirements_configured="true"), [])

    def test_value_filter_offers_configured_values(self):
        filterset = AssetTypeFilterSet({}, AssetType.objects.all())
        self.assertIn("zeroize", choice_values(filterset.filters["decommissioning_requirements"].field))
        form = AssetTypeFilterForm()
        self.assertIn("zeroize", choice_values(form.fields["decommissioning_requirements"]))
        self.assertIn("decommissioning_requirements_configured", form.fields)

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_value_filter_follows_configuration(self):
        filterset = AssetTypeFilterSet({}, AssetType.objects.all())
        self.assertEqual(choice_values(filterset.filters["decommissioning_requirements"].field), ["clear"])
        self.assertEqual(choice_values(AssetTypeFilterForm().fields["decommissioning_requirements"]), ["clear"])


class AssetTypeTableTest(AssetTypeDecommissioningTestCase):
    def cell(self, asset_type):
        table = AssetTypeTable(AssetType.objects.filter(pk=asset_type.pk))
        return str(table.rows[0].get_cell("decommissioning_requirements"))

    def test_column_is_optional(self):
        self.assertIn("decommissioning_requirements", AssetTypeTable.Meta.fields)
        self.assertNotIn("decommissioning_requirements", AssetTypeTable.Meta.default_columns)

    def test_column_shows_configured_label(self):
        cell = self.cell(self.switch)
        self.assertIn("Zeroize (Juniper)", cell)
        self.assertNotIn("text-bg-warning", cell)

    def test_column_empty_value(self):
        self.assertNotIn("not in configuration", self.cell(self.cable))

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_column_badge_for_removed_value(self):
        cell = self.cell(self.switch)
        self.assertIn("text-bg-warning", cell)
        self.assertIn("zeroize (not in configuration)", cell)

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_export_value_for_removed_value(self):
        table = AssetTypeTable(AssetType.objects.filter(pk=self.switch.pk))
        self.assertEqual(table.rows[0].get_cell_value("decommissioning_requirements"), "zeroize (not in configuration)")
