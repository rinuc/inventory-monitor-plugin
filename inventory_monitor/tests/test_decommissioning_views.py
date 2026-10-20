"""User interface of the decommissioning record (R3, R4, D3, D4, V0, V6).

Forms, CSV import, filters and tables of the record, plus the new fields, filter
and columns on Asset. The rules themselves live in Model.clean() and are tested
in test_decommissioning_record.py; here they are checked through each channel.
"""

import datetime
from unittest import mock

from django.test import TestCase, override_settings
from tenancy.models import Contact

from inventory_monitor.filtersets import AssetFilterSet, DecommissioningRecordFilterSet
from inventory_monitor.forms import (
    AssetBulkImportForm,
    AssetFilterForm,
    AssetForm,
    DecommissioningRecordBulkEditForm,
    DecommissioningRecordBulkImportForm,
    DecommissioningRecordFilterForm,
    DecommissioningRecordForm,
)
from inventory_monitor.models import Asset, AssetType, DecommissioningRecord, LifecycleStatusChoices
from inventory_monitor.tables import AssetTable, DecommissioningRecordTable

TODAY = datetime.date(2026, 10, 20)
YESTERDAY = TODAY - datetime.timedelta(days=1)
LAST_WEEK = TODAY - datetime.timedelta(days=7)

RETIRED = LifecycleStatusChoices.RETIRED
DISPOSED = LifecycleStatusChoices.DISPOSED
IN_USE = LifecycleStatusChoices.IN_USE

# sanitization_method_choices without "zeroize", which the records below keep
WITHOUT_ZEROIZE = {"inventory_monitor": {"sanitization_method_choices": [("clear", "Clear")]}}


def choice_values(field):
    """Values offered by a form field; the blank choice of add_blank_choice() is None, NetBox filters add "null"."""
    return [value for value, _label in field.choices if value not in (None, "null")]


def error_codes(form):
    return {field: [e.code for e in errors] for field, errors in form.errors.as_data().items()}


def import_form(record, instance=None):
    """A bulk import form as BulkImportView builds it: on update, only the CSV columns."""
    form = DecommissioningRecordBulkImportForm(data=record, instance=instance)
    if instance is not None:
        for name in [f for f in form.fields if f not in record]:
            del form.fields[name]
    return form


def asset_import_form(record, instance):
    form = AssetBulkImportForm(data=record, instance=instance)
    for name in [f for f in form.fields if f not in record]:
        del form.fields[name]
    return form


class DecommissioningUITestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.switch = AssetType.objects.create(name="Switch", slug="switch", decommissioning_requirements="zeroize")
        cls.mario = Contact.objects.create(name="Mario Rossi")
        cls.anna = Contact.objects.create(name="Anna Bianchi")

        cls.retired = Asset.objects.create(
            serial="SN-RET", partnumber="PN-1", type=cls.switch, lifecycle_status=RETIRED
        )
        cls.disposed = Asset.objects.create(serial="SN-DIS", lifecycle_status=DISPOSED)
        cls.in_use = Asset.objects.create(serial="SN-USE", lifecycle_status=IN_USE)

    def setUp(self):
        now = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)
        patcher = mock.patch("django.utils.timezone.now", return_value=now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_record(self, asset, **kwargs):
        return DecommissioningRecord.objects.create(asset=asset, **kwargs)


class DecommissioningRecordFormTest(DecommissioningUITestCase):
    def test_create(self):
        form = DecommissioningRecordForm(
            data={
                "asset": self.retired.pk,
                "technical_decommission_date": "2026-10-19",
                "technical_decommission_operator": self.mario.pk,
                "sanitization_date": "2026-10-20",
                "sanitization_method": "zeroize",
                "sanitization_operator": self.anna.pk,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        record = form.save()
        self.assertEqual(record.asset, self.retired)
        self.assertEqual(record.technical_decommission_date, YESTERDAY)
        self.assertEqual(record.technical_decommission_operator, self.mario)
        self.assertEqual(record.sanitization_method, "zeroize")
        self.assertEqual(record.sanitization_operator, self.anna)

    def test_model_rules_reported_on_fields(self):
        form = DecommissioningRecordForm(
            data={
                "asset": self.in_use.pk,
                "technical_decommission_date": "2026-10-20",
                "sanitization_date": "2026-10-19",
            }
        )
        self.assertFalse(form.is_valid())
        codes = error_codes(form)
        self.assertEqual(codes["technical_decommission_date"], ["asset_not_decommissioned"])
        self.assertCountEqual(codes["sanitization_date"], ["date_order"])
        self.assertEqual(codes["sanitization_method"], ["sanitization_method_required"])

    def test_second_record_on_same_asset_rejected(self):
        self.make_record(self.retired)
        form = DecommissioningRecordForm(data={"asset": self.retired.pk})
        self.assertFalse(form.is_valid())
        self.assertIn("asset", form.errors)

    def test_asset_selector_lists_assets_without_record(self):
        """D3: the dropdown asks the API for assets without a record."""
        field = DecommissioningRecordForm().fields["asset"]
        self.assertEqual(field.query_params, {"has_decommissioning_record": "false"})
        self.assertFalse(field.disabled)

    def test_asset_locked_on_edit(self):
        """D3, V0: the asset field is disabled; a different submitted asset is ignored."""
        record = self.make_record(self.retired)
        form = DecommissioningRecordForm(
            data={"asset": self.disposed.pk, "disposal_document": "RAEE 1"}, instance=record
        )
        self.assertTrue(form.fields["asset"].disabled)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        record.refresh_from_db()
        self.assertEqual(record.asset, self.retired)
        self.assertEqual(record.disposal_document, "RAEE 1")

    def test_sanitization_method_choices_are_the_configured_list(self):
        field = DecommissioningRecordForm().fields["sanitization_method"]
        self.assertEqual(choice_values(field)[:2], ["clear", "purge"])
        self.assertIn("zeroize", choice_values(field))

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_method_selectable_only_for_its_record(self):
        record = self.make_record(self.retired, sanitization_date=TODAY, sanitization_method="zeroize")
        edit = DecommissioningRecordForm(instance=record)
        self.assertIn(("zeroize", "zeroize (not in configuration)"), edit.fields["sanitization_method"].choices)
        self.assertEqual(choice_values(DecommissioningRecordForm().fields["sanitization_method"]), ["clear"])

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_method_preserved_when_editing_another_field(self):
        record = self.make_record(self.retired, sanitization_date=TODAY, sanitization_method="zeroize")
        form = DecommissioningRecordForm(
            data={
                "sanitization_date": "2026-10-20",
                "sanitization_method": "zeroize",
                "disposal_document": "RAEE 2",
            },
            instance=record,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        record.refresh_from_db()
        self.assertEqual(record.sanitization_method, "zeroize")
        self.assertEqual(record.disposal_document, "RAEE 2")

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_removed_method_rejected_on_new_record(self):
        form = DecommissioningRecordForm(
            data={"asset": self.retired.pk, "sanitization_date": "2026-10-20", "sanitization_method": "zeroize"}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("sanitization_method", form.errors)

    def test_requirements_reminder_from_initial_asset(self):
        """?asset=<pk> reaches the form as a string in initial."""
        form = DecommissioningRecordForm(initial={"asset": str(self.retired.pk)})
        self.assertIn("Zeroize (Juniper)", str(form.fields["sanitization_method"].help_text))

    def test_requirements_reminder_from_instance(self):
        form = DecommissioningRecordForm(instance=self.make_record(self.retired))
        self.assertIn("Zeroize (Juniper)", str(form.fields["sanitization_method"].help_text))

    def test_no_reminder_without_requirements(self):
        form = DecommissioningRecordForm(instance=self.make_record(self.disposed))
        self.assertNotIn("Zeroize", str(form.fields["sanitization_method"].help_text))


class DecommissioningRecordBulkEditFormTest(DecommissioningUITestCase):
    def test_no_asset_field(self):
        """D3: the asset of a record never changes."""
        self.assertNotIn("asset", DecommissioningRecordBulkEditForm().fields)

    def test_fields_and_nullable_fields(self):
        form = DecommissioningRecordBulkEditForm()
        for name in (
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
        ):
            with self.subTest(field=name):
                self.assertIn(name, form.fields)
                self.assertIn(name, DecommissioningRecordBulkEditForm.nullable_fields)

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_method_offers_configured_values_only(self):
        self.assertEqual(choice_values(DecommissioningRecordBulkEditForm().fields["sanitization_method"]), ["clear"])


class DecommissioningRecordImportTest(DecommissioningUITestCase):
    """D4: distinct columns for ID and natural key of the asset and of each operator."""

    def assert_imported(self, record, **expected):
        form = import_form(record)
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        for field, value in expected.items():
            self.assertEqual(getattr(obj, field), value)
        return obj

    def test_asset_by_id(self):
        self.assert_imported(
            {"asset": str(self.retired.pk), "technical_decommission_date": "2026-10-20"}, asset=self.retired
        )

    def test_asset_by_unique_serial(self):
        self.assert_imported({"asset_serial": "SN-RET"}, asset=self.retired)

    def test_asset_by_ambiguous_serial_rejected(self):
        Asset.objects.create(serial="SN-RET", lifecycle_status=RETIRED)
        form = import_form({"asset_serial": "SN-RET"})
        self.assertFalse(form.is_valid())
        self.assertIn("asset_serial", form.errors)

    def test_asset_by_id_and_serial_rejected(self):
        form = import_form({"asset": str(self.retired.pk), "asset_serial": "SN-RET"})
        self.assertFalse(form.is_valid())

    def test_asset_required_on_create(self):
        form = import_form({"disposal_document": "RAEE 3"})
        self.assertFalse(form.is_valid())

    def test_operators_by_id_and_name(self):
        self.assert_imported(
            {
                "asset": str(self.retired.pk),
                "technical_decommission_date": "2026-10-20",
                "technical_decommission_operator": str(self.mario.pk),
                "sanitization_date": "2026-10-20",
                "sanitization_method": "zeroize",
                "sanitization_operator_name": "Anna Bianchi",
            },
            technical_decommission_operator=self.mario,
            sanitization_operator=self.anna,
        )

    def test_operator_by_name(self):
        self.assert_imported(
            {"asset": str(self.retired.pk), "technical_decommission_operator_name": "Mario Rossi"},
            technical_decommission_operator=self.mario,
        )

    def test_operator_by_ambiguous_name_rejected(self):
        Contact.objects.create(name="Mario Rossi", email="other@example.com")
        form = import_form({"asset": str(self.retired.pk), "technical_decommission_operator_name": "Mario Rossi"})
        self.assertFalse(form.is_valid())
        self.assertIn("technical_decommission_operator_name", form.errors)

    def test_operator_by_id_and_name_rejected(self):
        form = import_form(
            {
                "asset": str(self.retired.pk),
                "sanitization_operator": str(self.anna.pk),
                "sanitization_operator_name": "Anna Bianchi",
            }
        )
        self.assertFalse(form.is_valid())

    def test_unconfigured_method_rejected(self):
        form = import_form(
            {"asset": str(self.retired.pk), "sanitization_date": "2026-10-20", "sanitization_method": "burn"}
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(error_codes(form)["sanitization_method"], ["not_configured"])

    def test_update_without_asset_column(self):
        record = self.make_record(self.retired)
        form = import_form({"disposal_document": "RAEE 4"}, instance=record)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        record.refresh_from_db()
        self.assertEqual(record.asset, self.retired)
        self.assertEqual(record.disposal_document, "RAEE 4")

    def test_update_with_same_asset(self):
        record = self.make_record(self.retired)
        form = import_form({"asset_serial": "SN-RET", "disposal_document": "RAEE 5"}, instance=record)
        self.assertTrue(form.is_valid(), form.errors)

    def test_update_with_other_asset_rejected(self):
        """V0 through the CSV update channel."""
        record = self.make_record(self.retired)
        form = import_form({"asset": str(self.disposed.pk)}, instance=record)
        self.assertFalse(form.is_valid())
        self.assertEqual(error_codes(form)["asset"], ["asset_immutable"])

    def test_update_with_other_asset_by_serial_rejected(self):
        record = self.make_record(self.retired)
        form = import_form({"asset_serial": "SN-DIS"}, instance=record)
        self.assertFalse(form.is_valid())
        self.assertIn("asset_immutable", [e.code for errors in form.errors.as_data().values() for e in errors])

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_update_preserves_removed_method(self):
        record = self.make_record(self.retired, sanitization_date=TODAY, sanitization_method="zeroize")
        form = import_form({"disposal_document": "RAEE 6"}, instance=record)
        self.assertTrue(form.is_valid(), form.errors)


class DecommissioningRecordFilterTest(DecommissioningUITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.record_retired = DecommissioningRecord.objects.create(
            asset=cls.retired,
            technical_decommission_date=LAST_WEEK,
            technical_decommission_operator=cls.mario,
            sanitization_date=YESTERDAY,
            sanitization_method="zeroize",
            sanitization_operator=cls.anna,
            description="core switch",
        )
        cls.record_disposed = DecommissioningRecord.objects.create(
            asset=cls.disposed,
            technical_decommission_date=YESTERDAY,
            sanitization_date=TODAY,
            sanitization_method="destroy",
            disposal_date=TODAY,
            disposal_document="RAEE 2026/123",
        )
        cls.record_empty = DecommissioningRecord.objects.create(asset=cls.in_use)

    def filter(self, **params):
        return DecommissioningRecordFilterSet(params, DecommissioningRecord.objects.all()).qs

    def test_asset_id(self):
        self.assertCountEqual(self.filter(asset_id=[self.retired.pk]), [self.record_retired])

    def test_serial_is_exact(self):
        self.assertCountEqual(self.filter(serial=["SN-DIS"]), [self.record_disposed])
        self.assertCountEqual(self.filter(serial=["SN-DIS", "SN-USE"]), [self.record_disposed, self.record_empty])
        self.assertCountEqual(self.filter(serial=["SN-D"]), [])

    def test_date_ranges(self):
        self.assertCountEqual(self.filter(technical_decommission_date__gte=["2026-10-19"]), [self.record_disposed])
        self.assertCountEqual(
            self.filter(technical_decommission_date__lte=["2026-10-19"]), [self.record_retired, self.record_disposed]
        )
        self.assertCountEqual(self.filter(sanitization_date__lte=["2026-10-19"]), [self.record_retired])
        self.assertCountEqual(self.filter(disposal_date__gte=["2026-10-20"]), [self.record_disposed])
        self.assertCountEqual(self.filter(disposal_date=["2026-10-20"]), [self.record_disposed])

    def test_sanitization_method(self):
        self.assertCountEqual(self.filter(sanitization_method=["zeroize"]), [self.record_retired])
        self.assertCountEqual(
            self.filter(sanitization_method=["zeroize", "destroy"]), [self.record_retired, self.record_disposed]
        )

    def test_sanitization_method_configured(self):
        self.assertCountEqual(
            self.filter(sanitization_method_configured="true"), [self.record_retired, self.record_disposed]
        )
        self.assertCountEqual(self.filter(sanitization_method_configured="false"), [])

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_sanitization_method_not_configured(self):
        self.assertCountEqual(
            self.filter(sanitization_method_configured="false"), [self.record_retired, self.record_disposed]
        )
        self.assertCountEqual(self.filter(sanitization_method_configured="true"), [])

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_method_filter_offers_configured_values(self):
        filterset = DecommissioningRecordFilterSet({}, DecommissioningRecord.objects.all())
        self.assertEqual(choice_values(filterset.filters["sanitization_method"].field), ["clear"])
        self.assertEqual(choice_values(DecommissioningRecordFilterForm().fields["sanitization_method"]), ["clear"])

    def test_operators(self):
        self.assertCountEqual(self.filter(technical_decommission_operator_id=[self.mario.pk]), [self.record_retired])
        self.assertCountEqual(self.filter(sanitization_operator_id=[self.anna.pk]), [self.record_retired])
        self.assertCountEqual(self.filter(sanitization_operator_id=[self.mario.pk]), [])

    def test_q(self):
        self.assertCountEqual(self.filter(q="sn-ret"), [self.record_retired])
        self.assertCountEqual(self.filter(q="PN-1"), [self.record_retired])
        self.assertCountEqual(self.filter(q="2026/123"), [self.record_disposed])
        self.assertCountEqual(self.filter(q="core"), [self.record_retired])

    def test_filter_form_fields(self):
        form = DecommissioningRecordFilterForm()
        for name in (
            "q",
            "asset_id",
            "serial",
            "technical_decommission_date__gte",
            "technical_decommission_date__lte",
            "sanitization_date__gte",
            "sanitization_date__lte",
            "disposal_date__gte",
            "disposal_date__lte",
            "sanitization_method",
            "sanitization_method_configured",
            "technical_decommission_operator_id",
            "sanitization_operator_id",
        ):
            with self.subTest(field=name):
                self.assertIn(name, form.fields)


class DecommissioningRecordTableTest(DecommissioningUITestCase):
    def row(self, record):
        return DecommissioningRecordTable(DecommissioningRecord.objects.filter(pk=record.pk)).rows[0]

    def test_columns(self):
        fields = DecommissioningRecordTable.Meta.fields
        for name in (
            "asset",
            "serial",
            "asset_type",
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
            "last_related_info",
        ):
            with self.subTest(column=name):
                self.assertIn(name, fields)
        self.assertNotIn("last_related_info", DecommissioningRecordTable.Meta.default_columns)
        self.assertNotIn("asset_type", DecommissioningRecordTable.Meta.default_columns)

    def test_register_values(self):
        Asset.objects.filter(pk=self.retired.pk).update(last_related_info="device: sw-01 (id 1)")
        record = self.make_record(
            self.retired,
            technical_decommission_date=YESTERDAY,
            technical_decommission_operator=self.mario,
            sanitization_date=TODAY,
            sanitization_method="zeroize",
            disposal_document="RAEE 7",
        )
        row = self.row(record)
        # Export values, as written to CSV
        self.assertEqual(str(row.get_cell_value("serial")), "SN-RET")
        self.assertEqual(str(row.get_cell_value("asset_type")), "Switch")
        self.assertEqual(str(row.get_cell_value("technical_decommission_date")), "2026-10-19")
        self.assertEqual(str(row.get_cell_value("technical_decommission_operator")), "Mario Rossi")
        self.assertEqual(str(row.get_cell_value("sanitization_method")), "Zeroize (Juniper)")
        self.assertEqual(str(row.get_cell_value("disposal_document")), "RAEE 7")
        self.assertEqual(str(row.get_cell_value("last_related_info")), "device: sw-01 (id 1)")
        self.assertIn(record.asset.get_absolute_url(), str(row.get_cell("asset")))

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE)
    def test_badge_for_removed_method(self):
        record = self.make_record(self.retired, sanitization_date=TODAY, sanitization_method="zeroize")
        cell = str(self.row(record).get_cell("sanitization_method"))
        self.assertIn("text-bg-warning", cell)
        self.assertIn("zeroize (not in configuration)", cell)


class AssetDecommissioningUITest(DecommissioningUITestCase):
    def asset_form_data(self, asset, **kwargs):
        return {
            "serial": asset.serial,
            "quantity": 1,
            "assignment_status": asset.assignment_status,
            "lifecycle_status": asset.lifecycle_status,
            **kwargs,
        }

    def test_has_decommissioning_record_filter(self):
        record = self.make_record(self.retired)
        qs = Asset.objects.all()
        self.assertCountEqual(AssetFilterSet({"has_decommissioning_record": "true"}, qs).qs, [record.asset])
        self.assertCountEqual(
            AssetFilterSet({"has_decommissioning_record": "false"}, qs).qs, [self.disposed, self.in_use]
        )
        self.assertIn("has_decommissioning_record", AssetFilterForm().fields)

    def test_asset_table_optional_columns(self):
        for name in ("decommissioning_record", "technical_decommission_date", "sanitization_date", "disposal_date"):
            with self.subTest(column=name):
                self.assertIn(name, AssetTable.Meta.fields)
                self.assertNotIn(name, AssetTable.Meta.default_columns)

    def test_asset_table_column_values(self):
        self.make_record(self.retired, technical_decommission_date=YESTERDAY)
        table = AssetTable(Asset.objects.filter(pk__in=[self.retired.pk, self.in_use.pk]).order_by("pk"))
        with_record, without_record = table.rows
        self.assertIn("Yes", str(with_record.get_cell("decommissioning_record")))
        self.assertEqual(with_record.get_cell_value("technical_decommission_date"), "2026-10-19")
        self.assertIn("No", str(without_record.get_cell("decommissioning_record")))
        self.assertIn(without_record.get_cell_value("technical_decommission_date"), ("", None))

    def test_asset_form_last_related_info(self):
        form = AssetForm(
            data=self.asset_form_data(self.in_use, last_related_info="device: old (id 9)"), instance=self.in_use
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.in_use.refresh_from_db()
        self.assertEqual(self.in_use.last_related_info, "device: old (id 9)")

    def test_asset_import_last_related_info(self):
        form = asset_import_form({"last_related_info": "device: old (id 9)"}, instance=self.in_use)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["last_related_info"], "device: old (id 9)")

    def test_v6_asset_form(self):
        self.make_record(self.retired, technical_decommission_date=YESTERDAY)
        form = AssetForm(data=self.asset_form_data(self.retired, lifecycle_status=IN_USE), instance=self.retired)
        self.assertFalse(form.is_valid())
        self.assertEqual(error_codes(form)["lifecycle_status"], ["decommissioned_asset"])

    def test_v6_asset_import_update(self):
        self.make_record(self.disposed, technical_decommission_date=YESTERDAY, disposal_date=TODAY)
        form = asset_import_form({"lifecycle_status": RETIRED}, instance=self.disposed)
        self.assertFalse(form.is_valid())
        self.assertEqual(error_codes(form)["lifecycle_status"], ["disposed_asset"])
