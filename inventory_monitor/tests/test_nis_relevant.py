"""Asset.nis_relevant (R6, spec §2.5).

A plain classification flag: no rule in Model.clean() and no link to the
decommissioning record or the asset type. Here it is checked through every
channel that manages an Asset: model, forms, bulk edit, CSV import, filters,
tables, pages, REST API and GraphQL.
"""

import json

from django.test import TestCase
from django.urls import reverse
from drf_spectacular.settings import spectacular_settings
from rest_framework import status
from utilities.forms import BOOLEAN_WITH_BLANK_CHOICES
from utilities.testing import APITestCase
from utilities.testing import TestCase as NetBoxTestCase

from inventory_monitor.filtersets import AssetFilterSet, DecommissioningRecordFilterSet
from inventory_monitor.forms import AssetBulkEditForm, AssetBulkImportForm, AssetFilterForm, AssetForm
from inventory_monitor.models import Asset, AssetType, DecommissioningRecord, LifecycleStatusChoices
from inventory_monitor.tables import AssetTable, DecommissioningRecordTable, EnhancedAssetTable

RETIRED = LifecycleStatusChoices.RETIRED


def import_form(record, instance=None):
    """AssetBulkImportForm as BulkImportView builds it: on update, only the CSV columns."""
    form = AssetBulkImportForm(data=record, instance=instance)
    if instance is not None:
        for name in [f for f in form.fields if f not in record]:
            del form.fields[name]
    return form


class NisRelevantTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.switch = AssetType.objects.create(name="Switch", slug="switch")
        cls.relevant = Asset.objects.create(serial="SN-NIS", type=cls.switch, nis_relevant=True)
        cls.other = Asset.objects.create(serial="SN-OTHER", type=cls.switch)

    def asset_form_data(self, asset, **kwargs):
        return {
            "serial": asset.serial,
            "quantity": 1,
            "assignment_status": asset.assignment_status,
            "lifecycle_status": asset.lifecycle_status,
            **kwargs,
        }


class NisRelevantModelTest(NisRelevantTestCase):
    def test_default_is_false(self):
        self.assertIs(Asset.objects.create(serial="SN-NEW").nis_relevant, False)

    def test_saved_true(self):
        self.relevant.refresh_from_db()
        self.assertIs(self.relevant.nis_relevant, True)

    def test_no_rule_on_lifecycle(self):
        """A relevant asset can be retired without a decommissioning record (Q13)."""
        self.relevant.lifecycle_status = RETIRED
        self.relevant.full_clean()


class NisRelevantFormTest(NisRelevantTestCase):
    def test_asset_form_sets_the_flag(self):
        form = AssetForm(data=self.asset_form_data(self.other, nis_relevant="on"), instance=self.other)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.other.refresh_from_db()
        self.assertIs(self.other.nis_relevant, True)

    def test_asset_form_clears_the_flag(self):
        # An unchecked checkbox is not in the POST data
        form = AssetForm(data=self.asset_form_data(self.relevant), instance=self.relevant)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.relevant.refresh_from_db()
        self.assertIs(self.relevant.nis_relevant, False)

    def test_asset_form_fieldset(self):
        asset_fieldset = AssetForm.fieldsets[0]
        self.assertIn("nis_relevant", asset_fieldset.items)

    def test_filter_form_field(self):
        form = AssetFilterForm()
        self.assertIn("nis_relevant", form.fields)
        self.assertEqual(list(form.fields["nis_relevant"].widget.choices), list(BOOLEAN_WITH_BLANK_CHOICES))
        self.assertCountEqual(AssetFilterSet({"nis_relevant": "True"}, Asset.objects.all()).qs, [self.relevant])


class NisRelevantBulkEditTest(NisRelevantTestCase):
    def test_field_is_not_nullable(self):
        self.assertIn("nis_relevant", AssetBulkEditForm().fields)
        self.assertNotIn("nis_relevant", AssetBulkEditForm.nullable_fields)

    def test_values(self):
        for value, expected in (("true", True), ("false", False), ("", None)):
            with self.subTest(value=value):
                form = AssetBulkEditForm(data={"pk": [self.other.pk], "nis_relevant": value})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertIs(form.cleaned_data["nis_relevant"], expected)


class NisRelevantImportTest(NisRelevantTestCase):
    def test_create_with_column(self):
        form = import_form({"serial": "SN-CSV", "nis_relevant": "true"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.save().nis_relevant, True)

    def test_create_without_column(self):
        form = import_form({"serial": "SN-CSV"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.save().nis_relevant, False)

    def test_update_with_column(self):
        form = import_form({"nis_relevant": "false"}, instance=self.relevant)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.relevant.refresh_from_db()
        self.assertIs(self.relevant.nis_relevant, False)

    def test_update_without_column_keeps_the_value(self):
        form = import_form({"description": "core switch"}, instance=self.relevant)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.relevant.refresh_from_db()
        self.assertIs(self.relevant.nis_relevant, True)
        self.assertEqual(self.relevant.description, "core switch")


class NisRelevantFilterTest(NisRelevantTestCase):
    def test_asset_filter(self):
        qs = Asset.objects.all()
        self.assertCountEqual(AssetFilterSet({"nis_relevant": "true"}, qs).qs, [self.relevant])
        self.assertCountEqual(AssetFilterSet({"nis_relevant": "false"}, qs).qs, [self.other])

    def test_record_filter(self):
        Asset.objects.filter(pk__in=[self.relevant.pk, self.other.pk]).update(lifecycle_status=RETIRED)
        relevant = DecommissioningRecord.objects.create(asset=self.relevant)
        other = DecommissioningRecord.objects.create(asset=self.other)
        qs = DecommissioningRecord.objects.all()
        self.assertCountEqual(DecommissioningRecordFilterSet({"asset_nis_relevant": "true"}, qs).qs, [relevant])
        self.assertCountEqual(DecommissioningRecordFilterSet({"asset_nis_relevant": "false"}, qs).qs, [other])


class NisRelevantTableTest(NisRelevantTestCase):
    def test_asset_table_default_column(self):
        # EnhancedAssetTable, used by the asset list and the child views, has its own default columns
        for table in (AssetTable, EnhancedAssetTable):
            with self.subTest(table=table.__name__):
                self.assertIn("nis_relevant", table.Meta.fields)
                self.assertIn("nis_relevant", table.Meta.default_columns)

    def test_asset_table_values(self):
        table = AssetTable(Asset.objects.filter(pk__in=[self.relevant.pk, self.other.pk]).order_by("pk"))
        relevant, other = table.rows
        self.assertIn("mdi-check-bold", str(relevant.get_cell("nis_relevant")))
        self.assertIn("mdi-close-thick", str(other.get_cell("nis_relevant")))
        self.assertEqual(relevant.get_cell_value("nis_relevant"), "True")

    def test_record_table_optional_column(self):
        self.assertIn("asset_nis_relevant", DecommissioningRecordTable.Meta.fields)
        self.assertNotIn("asset_nis_relevant", DecommissioningRecordTable.Meta.default_columns)
        Asset.objects.filter(pk=self.relevant.pk).update(lifecycle_status=RETIRED)
        record = DecommissioningRecord.objects.create(asset=self.relevant)
        row = DecommissioningRecordTable(DecommissioningRecord.objects.filter(pk=record.pk)).rows[0]
        self.assertEqual(row.get_cell_value("asset_nis_relevant"), "True")


class NisRelevantPagesTest(NetBoxTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.relevant = Asset.objects.create(serial="SN-NIS", nis_relevant=True, lifecycle_status=RETIRED)
        cls.other = Asset.objects.create(serial="SN-OTHER")

    def nis_row(self, response):
        """The cell after the "NIS2 relevant" header of the page."""
        html = response.content.decode()
        self.assertIn("NIS2 relevant</th>", html)
        return html.split("NIS2 relevant</th>", 1)[1].split("</td>", 1)[0]

    def test_asset_page(self):
        self.add_permissions("inventory_monitor.view_asset")
        self.assertIn("mdi-check-bold", self.nis_row(self.client.get(self.relevant.get_absolute_url())))
        self.assertIn("mdi-close-thick", self.nis_row(self.client.get(self.other.get_absolute_url())))

    def test_record_page(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        record = DecommissioningRecord.objects.create(asset=self.relevant)
        self.assertIn("mdi-check-bold", self.nis_row(self.client.get(record.get_absolute_url())))

    def test_asset_list_export(self):
        self.add_permissions("inventory_monitor.view_asset")
        response = self.client.get(reverse("plugins:inventory_monitor:asset_list") + "?export=table")
        self.assertIn("NIS2 relevant", response.content.decode().splitlines()[0])

    def test_bulk_edit(self):
        self.add_permissions("inventory_monitor.view_asset", "inventory_monitor.change_asset")
        response = self.client.post(
            reverse("plugins:inventory_monitor:asset_bulk_edit"),
            {"pk": [self.other.pk], "_apply": True, "nis_relevant": "true"},
        )
        self.assertEqual(response.status_code, 302)
        self.other.refresh_from_db()
        self.assertIs(self.other.nis_relevant, True)


class NisRelevantAPITest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.relevant = Asset.objects.create(serial="SN-NIS", nis_relevant=True)
        cls.other = Asset.objects.create(serial="SN-OTHER")

    def setUp(self):
        super().setUp()
        self.add_permissions("inventory_monitor.view_asset")

    def url(self, asset=None):
        if asset is None:
            return reverse("plugins-api:inventory_monitor-api:asset-list")
        return reverse("plugins-api:inventory_monitor-api:asset-detail", args=[asset.pk])

    def test_list(self):
        response = self.client.get(self.url(), {"ordering": "id"}, **self.header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([a["nis_relevant"] for a in response.data["results"]], [True, False])

    def test_detail(self):
        response = self.client.get(self.url(self.relevant), **self.header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIs(response.data["nis_relevant"], True)

    def test_not_in_brief(self):
        response = self.client.get(self.url(), {"brief": 1}, **self.header)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("nis_relevant", response.data["results"][0])

    def test_filter(self):
        response = self.client.get(self.url(), {"nis_relevant": "true"}, **self.header)
        self.assertEqual([a["id"] for a in response.data["results"]], [self.relevant.pk])

    def test_patch(self):
        self.add_permissions("inventory_monitor.change_asset")
        for value in (True, False):
            with self.subTest(value=value):
                response = self.client.patch(
                    self.url(self.other), {"nis_relevant": value}, format="json", **self.header
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                self.other.refresh_from_db()
                self.assertIs(self.other.nis_relevant, value)

    def test_schema(self):
        schema = spectacular_settings.DEFAULT_GENERATOR_CLASS().get_schema(request=None, public=True)
        components = schema["components"]["schemas"]
        self.assertEqual(components["Asset"]["properties"]["nis_relevant"]["type"], "boolean")
        self.assertIn("nis_relevant", components["PatchedAssetRequest"]["properties"])
        self.assertNotIn("nis_relevant", components["BriefAsset"]["properties"])


class NisRelevantGraphQLTest(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.relevant = Asset.objects.create(serial="SN-NIS", nis_relevant=True)
        cls.other = Asset.objects.create(serial="SN-OTHER")

    def setUp(self):
        super().setUp()
        self.add_permissions("inventory_monitor.view_asset")

    def query(self, query):
        response = self.client.post(reverse("graphql"), data={"query": query}, format="json", **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        data = json.loads(response.content)
        self.assertNotIn("errors", data)
        return data["data"]

    def test_field(self):
        data = self.query(f"{{inventory_monitor_asset(id: {self.relevant.pk}) {{serial nis_relevant}}}}")
        self.assertEqual(data["inventory_monitor_asset"], {"serial": "SN-NIS", "nis_relevant": True})

    def test_filter(self):
        for value, serials in (("true", ["SN-NIS"]), ("false", ["SN-OTHER"])):
            with self.subTest(value=value):
                data = self.query(
                    f"{{inventory_monitor_asset_list(filters: {{nis_relevant: {{exact: {value}}}}}) {{serial}}}}"
                )
                self.assertEqual([a["serial"] for a in data["inventory_monitor_asset_list"]], serials)
