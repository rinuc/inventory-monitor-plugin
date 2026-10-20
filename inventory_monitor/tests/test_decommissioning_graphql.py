"""GraphQL of the decommissioning record (R1, R2, R3, R4, Q8).

The record type and its queries, the new fields of the Asset and AssetType types and the
filters, including the runtime-configured `*_configured` ones (Q8).
"""

import datetime
import json
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from tenancy.models import Contact
from utilities.testing import APITestCase

from inventory_monitor.models import (
    Asset,
    AssetType,
    DecommissioningRecord,
    LifecycleStatusChoices,
)

TODAY = datetime.date(2026, 10, 20)
YESTERDAY = TODAY - datetime.timedelta(days=1)
LAST_WEEK = TODAY - datetime.timedelta(days=7)

# sanitization_method_choices without "zeroize", which the full record keeps
WITHOUT_ZEROIZE_METHOD = {"inventory_monitor": {"sanitization_method_choices": [("clear", "Clear")]}}
# decommissioning_requirements_choices without "zeroize", which the "switch" type keeps
WITHOUT_ZEROIZE_REQUIREMENT = {"inventory_monitor": {"decommissioning_requirements_choices": [("clear", "Clear")]}}

RECORD_FIELDS = """
    id
    display
    asset { id serial }
    technical_decommission_date
    technical_decommission_operator { name }
    sanitization_date
    sanitization_method
    sanitization_method_configured
    sanitization_operator { name }
    disposal_date
    disposal_document
"""


class DecommissioningGraphQLTestCase(APITestCase):
    """GraphQL requests as a token user holding only the permissions each test adds."""

    @classmethod
    def setUpTestData(cls):
        cls.switch = AssetType.objects.create(name="Switch", slug="switch", decommissioning_requirements="zeroize")
        cls.router = AssetType.objects.create(name="Router", slug="router", decommissioning_requirements="clear")
        cls.mario = Contact.objects.create(name="Mario Rossi")
        cls.anna = Contact.objects.create(name="Anna Bianchi")

        cls.disposed = Asset.objects.create(
            serial="SN-DIS", type=cls.switch, lifecycle_status=LifecycleStatusChoices.DISPOSED
        )
        cls.retired = Asset.objects.create(serial="SN-RET", lifecycle_status=LifecycleStatusChoices.RETIRED)
        cls.in_use = Asset.objects.create(
            serial="SN-USE",
            lifecycle_status=LifecycleStatusChoices.IN_USE,
            last_related_info="device: core-sw-01 (id 7)",
        )

    def setUp(self):
        super().setUp()
        now = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)
        patcher = mock.patch("django.utils.timezone.now", return_value=now)
        patcher.start()
        self.addCleanup(patcher.stop)

    def full_record(self):
        return DecommissioningRecord.objects.create(
            asset=self.disposed,
            technical_decommission_date=LAST_WEEK,
            technical_decommission_operator=self.mario,
            sanitization_date=YESTERDAY,
            sanitization_method="zeroize",
            sanitization_operator=self.anna,
            disposal_date=TODAY,
            disposal_document="RAEE 2026/123",
        )

    def short_record(self):
        return DecommissioningRecord.objects.create(
            asset=self.retired, technical_decommission_date=YESTERDAY, technical_decommission_operator=self.anna
        )

    def query(self, query):
        response = self.client.post(reverse("graphql"), data={"query": query}, format="json", **self.header)
        self.assertHttpStatus(response, status.HTTP_200_OK)
        data = json.loads(response.content)
        self.assertNotIn("errors", data)
        return data["data"]

    def record_ids(self, filters):
        data = self.query(f"{{inventory_monitor_decommissioning_record_list(filters: {{{filters}}}) {{id}}}}")
        return {int(r["id"]) for r in data["inventory_monitor_decommissioning_record_list"]}

    def asset_serials(self, filters):
        data = self.query(f"{{inventory_monitor_asset_list(filters: {{{filters}}}) {{serial}}}}")
        return {a["serial"] for a in data["inventory_monitor_asset_list"]}

    def asset_type_slugs(self, filters):
        data = self.query(f"{{inventory_monitor_asset_type_list(filters: {{{filters}}}) {{slug}}}}")
        return {t["slug"] for t in data["inventory_monitor_asset_type_list"]}


class DecommissioningRecordGraphQLTest(DecommissioningGraphQLTestCase):
    def setUp(self):
        super().setUp()
        self.add_permissions(
            "inventory_monitor.view_decommissioningrecord", "inventory_monitor.view_asset", "tenancy.view_contact"
        )

    def test_single(self):
        record = self.full_record()
        data = self.query(f"{{inventory_monitor_decommissioning_record(id: {record.pk}) {{{RECORD_FIELDS}}}}}")
        self.assertEqual(
            data["inventory_monitor_decommissioning_record"],
            {
                "id": str(record.pk),
                "display": "SN-DIS",
                "asset": {"id": str(self.disposed.pk), "serial": "SN-DIS"},
                "technical_decommission_date": "2026-10-13",
                "technical_decommission_operator": {"name": "Mario Rossi"},
                "sanitization_date": "2026-10-19",
                "sanitization_method": "zeroize",
                "sanitization_method_configured": True,
                "sanitization_operator": {"name": "Anna Bianchi"},
                "disposal_date": "2026-10-20",
                "disposal_document": "RAEE 2026/123",
            },
        )

    def test_list(self):
        full = self.full_record()
        short = self.short_record()
        data = self.query(f"{{inventory_monitor_decommissioning_record_list {{{RECORD_FIELDS}}}}}")
        records = data["inventory_monitor_decommissioning_record_list"]
        # P1 ordering: most recent technical decommission first
        self.assertEqual([r["id"] for r in records], [str(short.pk), str(full.pk)])
        self.assertIsNone(records[0]["sanitization_operator"])
        self.assertEqual(records[0]["sanitization_method"], "")
        self.assertIs(records[0]["sanitization_method_configured"], False)

    def test_filter_dates(self):
        full = self.full_record()
        short = self.short_record()
        self.assertEqual(self.record_ids('technical_decommission_date: {lt: "2026-10-15"}'), {full.pk})
        self.assertEqual(self.record_ids('technical_decommission_date: {exact: "2026-10-19"}'), {short.pk})
        self.assertEqual(self.record_ids('sanitization_date: {gte: "2026-10-19"}'), {full.pk})
        self.assertEqual(self.record_ids("disposal_date: {is_null: true}"), {short.pk})

    def test_filter_sanitization_method(self):
        full = self.full_record()
        self.short_record()
        self.assertEqual(self.record_ids('sanitization_method: {exact: "zeroize"}'), {full.pk})

    def test_filter_disposal_document(self):
        full = self.full_record()
        self.short_record()
        self.assertEqual(self.record_ids('disposal_document: {i_contains: "raee"}'), {full.pk})

    def test_filter_operators(self):
        full = self.full_record()
        short = self.short_record()
        self.assertEqual(self.record_ids(f'technical_decommission_operator_id: "{self.mario.pk}"'), {full.pk})
        self.assertEqual(
            self.record_ids('technical_decommission_operator: {name: {exact: "Anna Bianchi"}}'), {short.pk}
        )
        self.assertEqual(self.record_ids(f'sanitization_operator_id: "{self.anna.pk}"'), {full.pk})
        self.assertEqual(self.record_ids('sanitization_operator: {name: {exact: "Mario Rossi"}}'), set())

    def test_filter_asset(self):
        full = self.full_record()
        short = self.short_record()
        self.assertEqual(self.record_ids(f'asset_id: "{self.retired.pk}"'), {short.pk})
        self.assertEqual(self.record_ids('asset: {serial: {exact: "SN-DIS"}}'), {full.pk})

    def test_filter_sanitization_method_configured(self):
        full = self.full_record()
        self.short_record()
        self.assertEqual(self.record_ids("sanitization_method_configured: true"), {full.pk})
        # An empty method is neither configured nor removed
        self.assertEqual(self.record_ids("sanitization_method_configured: false"), set())

    def test_no_permission_sees_nothing(self):
        self.full_record()
        self.remove_permissions("inventory_monitor.view_decommissioningrecord")
        data = self.query("{inventory_monitor_decommissioning_record_list {id}}")
        self.assertEqual(data["inventory_monitor_decommissioning_record_list"], [])


@override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE_METHOD)
class DecommissioningRecordRemovedMethodGraphQLTest(DecommissioningGraphQLTestCase):
    def setUp(self):
        super().setUp()
        self.add_permissions("inventory_monitor.view_decommissioningrecord")

    def test_configured_false(self):
        record = self.full_record()
        data = self.query(
            f"{{inventory_monitor_decommissioning_record(id: {record.pk}) "
            "{sanitization_method sanitization_method_configured}}"
        )
        self.assertEqual(
            data["inventory_monitor_decommissioning_record"],
            {"sanitization_method": "zeroize", "sanitization_method_configured": False},
        )

    def test_filter_configured(self):
        full = self.full_record()
        self.short_record()
        self.assertEqual(self.record_ids("sanitization_method_configured: false"), {full.pk})
        self.assertEqual(self.record_ids("sanitization_method_configured: true"), set())


class AssetGraphQLDecommissioningTest(DecommissioningGraphQLTestCase):
    def setUp(self):
        super().setUp()
        self.add_permissions("inventory_monitor.view_asset", "inventory_monitor.view_decommissioningrecord")

    def test_record_and_last_related_info(self):
        record = self.full_record()
        data = self.query(
            "{inventory_monitor_asset_list {serial last_related_info decommissioning_record {id disposal_date}}}"
        )
        assets = {a["serial"]: a for a in data["inventory_monitor_asset_list"]}
        self.assertEqual(
            assets["SN-DIS"]["decommissioning_record"], {"id": str(record.pk), "disposal_date": "2026-10-20"}
        )
        self.assertIsNone(assets["SN-RET"]["decommissioning_record"])
        self.assertEqual(assets["SN-USE"]["last_related_info"], "device: core-sw-01 (id 7)")
        self.assertEqual(assets["SN-DIS"]["last_related_info"], "")

    def test_filter_has_decommissioning_record(self):
        self.full_record()
        self.assertEqual(self.asset_serials("has_decommissioning_record: true"), {"SN-DIS"})
        self.assertEqual(self.asset_serials("has_decommissioning_record: false"), {"SN-RET", "SN-USE"})

    def test_filter_decommissioning_record(self):
        self.full_record()
        self.short_record()
        self.assertEqual(
            self.asset_serials('decommissioning_record: {disposal_date: {exact: "2026-10-20"}}'), {"SN-DIS"}
        )

    def test_filter_last_related_info(self):
        self.assertEqual(self.asset_serials('last_related_info: {i_contains: "core-sw-01"}'), {"SN-USE"})


class AssetTypeGraphQLDecommissioningTest(DecommissioningGraphQLTestCase):
    def setUp(self):
        super().setUp()
        self.add_permissions("inventory_monitor.view_assettype")

    def test_fields(self):
        data = self.query(
            f"{{inventory_monitor_asset_type(id: {self.switch.pk}) "
            "{decommissioning_requirements decommissioning_requirements_configured}}"
        )
        self.assertEqual(
            data["inventory_monitor_asset_type"],
            {"decommissioning_requirements": "zeroize", "decommissioning_requirements_configured": True},
        )

    def test_filter_decommissioning_requirements(self):
        self.assertEqual(self.asset_type_slugs('decommissioning_requirements: {exact: "clear"}'), {"router"})

    def test_filter_configured(self):
        self.assertEqual(self.asset_type_slugs("decommissioning_requirements_configured: true"), {"switch", "router"})
        self.assertEqual(self.asset_type_slugs("decommissioning_requirements_configured: false"), set())

    @override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE_REQUIREMENT)
    def test_removed_value(self):
        data = self.query(
            f"{{inventory_monitor_asset_type(id: {self.switch.pk}) {{decommissioning_requirements_configured}}}}"
        )
        self.assertIs(data["inventory_monitor_asset_type"]["decommissioning_requirements_configured"], False)
        self.assertEqual(self.asset_type_slugs("decommissioning_requirements_configured: false"), {"switch"})
        self.assertEqual(self.asset_type_slugs("decommissioning_requirements_configured: true"), {"router"})
