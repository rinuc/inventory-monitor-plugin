"""REST API of the decommissioning record (R1, R2, R3, R4, V0, V4, V6).

The record endpoint, the new fields of the Asset and AssetType serializers and the
OpenAPI schema. The rules live in Model.clean(), which the API reaches through
ValidatedModelSerializer; here they are checked through HTTP requests.
"""

import datetime
from unittest import mock

from dcim.models import Site
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from drf_spectacular.settings import spectacular_settings
from rest_framework import status
from tenancy.models import Contact
from utilities.testing import APITestCase

from inventory_monitor.models import (
    Asset,
    AssetType,
    DecommissioningRecord,
    ExternalInventory,
    LifecycleStatusChoices,
)

TODAY = datetime.date(2026, 10, 20)
YESTERDAY = TODAY - datetime.timedelta(days=1)
LAST_WEEK = TODAY - datetime.timedelta(days=7)

RETIRED = LifecycleStatusChoices.RETIRED
DISPOSED = LifecycleStatusChoices.DISPOSED
IN_USE = LifecycleStatusChoices.IN_USE

RECORD_BRIEF_FIELDS = {"id", "url", "display", "technical_decommission_date", "sanitization_date", "disposal_date"}

# sanitization_method_choices without "zeroize", which the records below keep
WITHOUT_ZEROIZE_METHOD = {"inventory_monitor": {"sanitization_method_choices": [("clear", "Clear")]}}
# decommissioning_requirements_choices without "zeroize", which the "switch" type keeps
WITHOUT_ZEROIZE_REQUIREMENT = {"inventory_monitor": {"decommissioning_requirements_choices": [("clear", "Clear")]}}


def api_url(name, *args):
    return reverse(f"plugins-api:inventory_monitor-api:{name}", args=args)


class DecommissioningAPITestCase(APITestCase):
    """API requests as a token user holding only the permissions each test adds."""

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
        super().setUp()
        now = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)
        patcher = mock.patch("django.utils.timezone.now", return_value=now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_record(self, asset, **kwargs):
        return DecommissioningRecord.objects.create(asset=asset, **kwargs)

    def full_record(self):
        return self.make_record(
            self.disposed,
            technical_decommission_date=LAST_WEEK,
            technical_decommission_operator=self.mario,
            sanitization_date=YESTERDAY,
            sanitization_method="zeroize",
            sanitization_operator=self.anna,
            disposal_date=TODAY,
            disposal_document="RAEE 2026/123",
        )

    def get(self, path, **params):
        return self.client.get(path, params, **self.header)

    def post(self, path, data):
        return self.client.post(path, data, format="json", **self.header)

    def patch(self, path, data):
        return self.client.patch(path, data, format="json", **self.header)

    def count_queries(self, path):
        # The first request of a token also records its last use (one UPDATE): keep it out of the count
        self.get(path)
        with CaptureQueriesContext(connection) as ctx:
            response = self.get(path)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return len(ctx)


class DecommissioningRecordAPITest(DecommissioningAPITestCase):
    def test_list(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        record = self.full_record()
        response = self.get(api_url("decommissioningrecord-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([r["id"] for r in response.data["results"]], [record.pk])

    def test_brief(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        self.full_record()
        response = self.get(api_url("decommissioningrecord-list"), brief=1)
        self.assertEqual(set(response.data["results"][0]), RECORD_BRIEF_FIELDS)

    def test_detail(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        record = self.full_record()
        response = self.get(api_url("decommissioningrecord-detail", record.pk))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(data["display"], "SN-DIS")
        self.assertEqual(data["asset"]["id"], self.disposed.pk)
        self.assertEqual(data["asset"]["serial"], "SN-DIS")
        self.assertEqual(data["technical_decommission_date"], "2026-10-13")
        self.assertEqual(data["technical_decommission_operator"]["name"], "Mario Rossi")
        self.assertEqual(data["sanitization_date"], "2026-10-19")
        self.assertEqual(data["sanitization_method"], "zeroize")
        self.assertIs(data["sanitization_method_configured"], True)
        self.assertEqual(data["sanitization_operator"]["name"], "Anna Bianchi")
        self.assertEqual(data["disposal_date"], "2026-10-20")
        self.assertEqual(data["disposal_document"], "RAEE 2026/123")

    def test_create(self):
        self.add_permissions("inventory_monitor.add_decommissioningrecord")
        response = self.post(
            api_url("decommissioningrecord-list"),
            {
                "asset": self.retired.pk,
                "technical_decommission_date": "2026-10-19",
                "technical_decommission_operator": self.mario.pk,
                "sanitization_date": "2026-10-20",
                "sanitization_method": "zeroize",
                "sanitization_operator": self.anna.pk,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        record = DecommissioningRecord.objects.get(pk=response.data["id"])
        self.assertEqual(record.asset, self.retired)
        self.assertEqual(record.technical_decommission_date, YESTERDAY)
        self.assertEqual(record.technical_decommission_operator, self.mario)
        self.assertEqual(record.sanitization_method, "zeroize")
        self.assertEqual(record.sanitization_operator, self.anna)

    def test_create_reports_model_rules_on_fields(self):
        self.add_permissions("inventory_monitor.add_decommissioningrecord")
        response = self.post(
            api_url("decommissioningrecord-list"),
            {"asset": self.in_use.pk, "technical_decommission_date": "2026-10-20", "sanitization_date": "2026-10-19"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("technical_decommission_date", response.data)
        self.assertIn("sanitization_date", response.data)
        self.assertIn("sanitization_method", response.data)
        self.assertFalse(DecommissioningRecord.objects.exists())

    def test_second_record_on_same_asset_rejected(self):
        """0:1: a field error, not an IntegrityError (the API skips validate_unique())."""
        self.add_permissions("inventory_monitor.add_decommissioningrecord")
        self.make_record(self.retired)
        response = self.post(api_url("decommissioningrecord-list"), {"asset": self.retired.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("asset", response.data)
        self.assertEqual(DecommissioningRecord.objects.filter(asset=self.retired).count(), 1)

    def test_patch(self):
        self.add_permissions("inventory_monitor.change_decommissioningrecord")
        record = self.make_record(self.retired)
        response = self.patch(
            api_url("decommissioningrecord-detail", record.pk),
            {"technical_decommission_date": "2026-10-19", "technical_decommission_operator": self.mario.pk},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        record.refresh_from_db()
        self.assertEqual(record.technical_decommission_date, YESTERDAY)
        self.assertEqual(record.technical_decommission_operator, self.mario)

    def test_patch_asset_immutable(self):
        """V0 through the API."""
        self.add_permissions("inventory_monitor.change_decommissioningrecord")
        record = self.make_record(self.retired)
        response = self.patch(api_url("decommissioningrecord-detail", record.pk), {"asset": self.disposed.pk})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot be changed", str(response.data["asset"]))
        record.refresh_from_db()
        self.assertEqual(record.asset, self.retired)

    def test_patch_asset_unchanged_accepted(self):
        self.add_permissions("inventory_monitor.change_decommissioningrecord")
        record = self.make_record(self.retired)
        response = self.patch(
            api_url("decommissioningrecord-detail", record.pk), {"asset": self.retired.pk, "description": "ok"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_sanitization_method_not_configured_rejected(self):
        """V4 through the API."""
        self.add_permissions("inventory_monitor.add_decommissioningrecord")
        response = self.post(
            api_url("decommissioningrecord-list"),
            {"asset": self.retired.pk, "sanitization_date": "2026-10-20", "sanitization_method": "shredder"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not a configured sanitization method", str(response.data["sanitization_method"]))

    def test_delete_keeps_asset(self):
        self.add_permissions("inventory_monitor.delete_decommissioningrecord")
        record = self.make_record(self.retired)
        response = self.client.delete(api_url("decommissioningrecord-detail", record.pk), **self.header)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DecommissioningRecord.objects.filter(pk=record.pk).exists())
        self.assertTrue(Asset.objects.filter(pk=self.retired.pk).exists())

    def test_filters(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        full = self.full_record()
        bare = self.make_record(self.retired)
        cases = {
            "serial": ("SN-DIS", [full]),
            "asset_id": (self.retired.pk, [bare]),
            "sanitization_method": ("zeroize", [full]),
            "technical_decommission_operator_id": (self.mario.pk, [full]),
            "disposal_date__gte": ("2026-10-20", [full]),
            "q": ("RAEE", [full]),
        }
        for name, (value, expected) in cases.items():
            with self.subTest(filter=name):
                response = self.get(api_url("decommissioningrecord-list"), **{name: value})
                self.assertEqual([r["id"] for r in response.data["results"]], [r.pk for r in expected])

    def test_list_constant_queries(self):
        """N+1: the nested asset (assignment, asset numbers) and the operators come with the list."""
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        assets = []
        for i in range(5):
            site = Site.objects.create(name=f"Site {i}", slug=f"site-{i}")
            asset = Asset.objects.create(
                serial=f"SN-N{i}", type=self.switch, lifecycle_status=RETIRED, assigned_object=site
            )
            ExternalInventory.objects.create(inventory_number=f"INV-{i}", name=f"Item {i}").assets.add(asset)
            assets.append(asset)
        for asset in assets[:2]:
            self.make_record(asset, technical_decommission_operator=self.mario, sanitization_operator=self.anna)
        two = self.count_queries(api_url("decommissioningrecord-list"))
        for asset in assets[2:]:
            self.make_record(asset, technical_decommission_operator=self.anna, sanitization_operator=self.mario)
        self.assertEqual(self.count_queries(api_url("decommissioningrecord-list")), two)

    def test_nested_asset_keeps_its_fields_with_prefetch(self):
        """The prefetched asset numbers and assignment give the same values as the queries they replace."""
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        site = Site.objects.create(name="Site A", slug="site-a")
        self.retired.assigned_object = site
        self.retired.save()
        for number in ("INV-2", "INV-1", "", "INV-1"):
            ExternalInventory.objects.create(inventory_number=number, name="Item").assets.add(self.retired)
        self.make_record(self.retired)
        asset = self.get(api_url("decommissioningrecord-list")).data["results"][0]["asset"]
        self.assertEqual(asset["asset_numbers"], "INV-1, INV-2")
        self.assertEqual(asset["assigned_object"]["id"], site.pk)


@override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE_METHOD)
class DecommissioningRecordRemovedMethodAPITest(DecommissioningAPITestCase):
    """R4: a sanitization method removed from the configuration."""

    def test_configured_false(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        record = self.full_record()
        response = self.get(api_url("decommissioningrecord-detail", record.pk))
        self.assertEqual(response.data["sanitization_method"], "zeroize")
        self.assertIs(response.data["sanitization_method_configured"], False)

    def test_filter_configured_false(self):
        self.add_permissions("inventory_monitor.view_decommissioningrecord")
        full = self.full_record()
        self.make_record(self.retired, sanitization_date=TODAY, sanitization_method="clear")
        response = self.get(api_url("decommissioningrecord-list"), sanitization_method_configured="false")
        self.assertEqual([r["id"] for r in response.data["results"]], [full.pk])

    def test_kept_on_patch_of_another_field(self):
        self.add_permissions("inventory_monitor.change_decommissioningrecord")
        record = self.full_record()
        response = self.patch(api_url("decommissioningrecord-detail", record.pk), {"disposal_document": "RAEE 2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        record.refresh_from_db()
        self.assertEqual(record.sanitization_method, "zeroize")
        self.assertEqual(record.disposal_document, "RAEE 2")

    def test_resent_unchanged_accepted(self):
        self.add_permissions("inventory_monitor.change_decommissioningrecord")
        record = self.full_record()
        response = self.patch(api_url("decommissioningrecord-detail", record.pk), {"sanitization_method": "zeroize"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_not_settable_on_another_record(self):
        self.add_permissions("inventory_monitor.change_decommissioningrecord")
        self.full_record()
        record = self.make_record(self.retired, sanitization_date=TODAY, sanitization_method="clear")
        response = self.patch(api_url("decommissioningrecord-detail", record.pk), {"sanitization_method": "zeroize"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("sanitization_method", response.data)


class AssetAPIDecommissioningTest(DecommissioningAPITestCase):
    def test_nested_record_and_last_related_info(self):
        self.add_permissions("inventory_monitor.view_asset")
        Asset.objects.filter(pk=self.disposed.pk).update(last_related_info="device: sw-01 (id 1)")
        record = self.full_record()
        data = self.get(api_url("asset-detail", self.disposed.pk)).data
        self.assertEqual(data["last_related_info"], "device: sw-01 (id 1)")
        self.assertEqual(set(data["decommissioning_record"]), RECORD_BRIEF_FIELDS)
        self.assertEqual(data["decommissioning_record"]["id"], record.pk)
        self.assertEqual(data["decommissioning_record"]["disposal_date"], "2026-10-20")

    def test_no_record_is_null(self):
        self.add_permissions("inventory_monitor.view_asset")
        data = self.get(api_url("asset-detail", self.in_use.pk)).data
        self.assertIsNone(data["decommissioning_record"])
        self.assertEqual(data["last_related_info"], "")

    def test_last_related_info_writable(self):
        self.add_permissions("inventory_monitor.change_asset")
        response = self.patch(api_url("asset-detail", self.in_use.pk), {"last_related_info": "device: old (id 9)"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.in_use.refresh_from_db()
        self.assertEqual(self.in_use.last_related_info, "device: old (id 9)")

    def test_decommissioning_record_read_only(self):
        self.add_permissions("inventory_monitor.change_asset")
        record = self.make_record(self.retired)
        response = self.patch(api_url("asset-detail", self.in_use.pk), {"decommissioning_record": record.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        record.refresh_from_db()
        self.assertEqual(record.asset, self.retired)

    def test_v6_patch_rejected(self):
        """V6 through the API: a decommissioned asset cannot go back in use."""
        self.add_permissions("inventory_monitor.change_asset")
        self.make_record(self.retired, technical_decommission_date=YESTERDAY)
        response = self.patch(api_url("asset-detail", self.retired.pk), {"lifecycle_status": IN_USE})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("it must stay Retired or Disposed", str(response.data["lifecycle_status"]))
        self.retired.refresh_from_db()
        self.assertEqual(self.retired.lifecycle_status, RETIRED)

    def test_filter_has_decommissioning_record(self):
        self.add_permissions("inventory_monitor.view_asset")
        self.make_record(self.retired)
        response = self.get(api_url("asset-list"), has_decommissioning_record="false")
        ids = {a["id"] for a in response.data["results"]}
        self.assertEqual(ids, {self.disposed.pk, self.in_use.pk})
        response = self.get(api_url("asset-list"), has_decommissioning_record="true")
        self.assertEqual([a["id"] for a in response.data["results"]], [self.retired.pk])

    def test_list_records_add_no_queries(self):
        """The nested record comes with the asset list: records add no query per asset."""
        self.add_permissions("inventory_monitor.view_asset")
        without = self.count_queries(api_url("asset-list"))
        for asset in Asset.objects.all():
            self.make_record(asset, technical_decommission_date=YESTERDAY)
        self.assertEqual(self.count_queries(api_url("asset-list")), without)


class AssetTypeAPIDecommissioningTest(DecommissioningAPITestCase):
    def test_fields(self):
        self.add_permissions("inventory_monitor.view_assettype")
        data = self.get(api_url("assettype-detail", self.switch.pk)).data
        self.assertEqual(data["decommissioning_requirements"], "zeroize")
        self.assertIs(data["decommissioning_requirements_configured"], True)

    def test_create_configured_value(self):
        self.add_permissions("inventory_monitor.add_assettype")
        response = self.post(
            api_url("assettype-list"), {"name": "Server", "slug": "server", "decommissioning_requirements": "purge"}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(AssetType.objects.get(slug="server").decommissioning_requirements, "purge")

    def test_create_not_configured_value_rejected(self):
        self.add_permissions("inventory_monitor.add_assettype")
        response = self.post(
            api_url("assettype-list"), {"name": "Server", "slug": "server", "decommissioning_requirements": "shredder"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("decommissioning_requirements", response.data)

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE_REQUIREMENT)
    def test_removed_value(self):
        self.add_permissions("inventory_monitor.view_assettype", "inventory_monitor.change_assettype")
        AssetType.objects.create(name="Router", slug="router", decommissioning_requirements="clear")
        data = self.get(api_url("assettype-detail", self.switch.pk)).data
        self.assertIs(data["decommissioning_requirements_configured"], False)

        response = self.get(api_url("assettype-list"), decommissioning_requirements_configured="false")
        self.assertEqual([t["id"] for t in response.data["results"]], [self.switch.pk])

        response = self.patch(api_url("assettype-detail", self.switch.pk), {"description": "Core"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.switch.refresh_from_db()
        self.assertEqual(self.switch.decommissioning_requirements, "zeroize")


class OpenAPISchemaTest(DecommissioningAPITestCase):
    def test_schema_generates(self):
        """The circular Asset <-> DecommissioningRecord nesting must not break /api/schema/."""
        generator = spectacular_settings.DEFAULT_GENERATOR_CLASS()
        schema = generator.get_schema(request=None, public=True)
        components = schema["components"]["schemas"]
        self.assertIn("DecommissioningRecord", set(components))
        self.assertIn("decommissioning_record", set(components["Asset"]["properties"]))
        self.assertIn("last_related_info", set(components["Asset"]["properties"]))
        self.assertIn("decommissioning_requirements_configured", set(components["AssetType"]["properties"]))
        self.assertIn("/api/plugins/inventory-monitor/decommissioning-records/", set(schema["paths"]))
