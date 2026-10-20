"""Model layer of the decommissioning record (R2, R3, V0–V7, D2, D7, P6).

Rules live in Model.clean(), which forms, bulk edit, CSV import and API
serializers all reach through full_clean(); the per-channel tests come with
those layers. Plain save() and QuerySet.update() bypass the rules by design.
"""

import datetime
import uuid
from unittest import mock

from core.models import ObjectChange
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from netbox.context_managers import event_tracking
from netbox.search.backends import search_backend
from tenancy.models import Contact
from users.models import User

from inventory_monitor.models import Asset, AssetType, DecommissioningRecord, LifecycleStatusChoices

TODAY = datetime.date(2026, 10, 20)
YESTERDAY = TODAY - datetime.timedelta(days=1)
TOMORROW = TODAY + datetime.timedelta(days=1)

RETIRED = LifecycleStatusChoices.RETIRED
DISPOSED = LifecycleStatusChoices.DISPOSED
IN_USE = LifecycleStatusChoices.IN_USE

# sanitization_method_choices without "zeroize", which the records below keep
WITHOUT_ZEROIZE = {"inventory_monitor": {"sanitization_method_choices": [("clear", "Clear")]}}


def error_codes(exc):
    """{field: [codes]} of a ValidationError raised with a dict."""
    return {field: [e.code for e in errors] for field, errors in exc.error_dict.items()}


def fixed_today():
    """Pin timezone.now() so that the local date is TODAY."""
    now = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.UTC)
    return mock.patch("django.utils.timezone.now", return_value=now)


class DecommissioningRecordTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.contact = Contact.objects.create(name="Mario Rossi")
        cls.other_contact = Contact.objects.create(name="Anna Bianchi")

    def setUp(self):
        patcher = fixed_today()
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_asset(self, serial="SN-1", lifecycle_status=RETIRED, **kwargs):
        return Asset.objects.create(serial=serial, lifecycle_status=lifecycle_status, **kwargs)

    def assert_invalid(self, obj, expected):
        """full_clean() fails with exactly the expected {field: [codes]}."""
        with self.assertRaises(ValidationError) as cm:
            obj.full_clean()
        self.assertEqual(error_codes(cm.exception), expected)


class DecommissioningRecordModelTest(DecommissioningRecordTestCase):
    def test_minimal_record_is_valid(self):
        record = DecommissioningRecord(asset=self.make_asset(lifecycle_status=IN_USE))
        record.full_clean()
        record.save()
        self.assertEqual(record.sanitization_method, "")
        self.assertEqual(record.disposal_document, "")

    def test_str_uses_asset_without_pk(self):
        asset = self.make_asset(serial="SN-STR", partnumber="PN-1")
        record = DecommissioningRecord.objects.create(asset=asset)
        self.assertEqual(str(record), "PN-1 (SN-STR)")

    def test_asset_reverse_accessor(self):
        asset = self.make_asset()
        record = DecommissioningRecord.objects.create(asset=asset)
        self.assertEqual(Asset.objects.get(pk=asset.pk).decommissioning_record, record)

    def test_operator_reverse_accessors(self):
        """D7: explicit related_name on both operator foreign keys."""
        record = DecommissioningRecord.objects.create(
            asset=self.make_asset(),
            technical_decommission_operator=self.contact,
            sanitization_operator=self.other_contact,
        )
        self.assertEqual(list(self.contact.inventory_monitor_decommissions.all()), [record])
        self.assertEqual(list(self.other_contact.inventory_monitor_sanitizations.all()), [record])
        self.assertFalse(self.contact.inventory_monitor_sanitizations.exists())

    def test_one_record_per_asset(self):
        asset = self.make_asset()
        DecommissioningRecord.objects.create(asset=asset)
        self.assert_invalid(DecommissioningRecord(asset=asset), {"asset": ["unique"]})

    def test_one_record_per_asset_in_the_database(self):
        """The 0:1 rule holds for a plain save() too, which skips full_clean()."""
        asset = self.make_asset()
        DecommissioningRecord.objects.create(asset=asset)
        with self.assertRaises(IntegrityError), transaction.atomic():
            DecommissioningRecord(asset=asset).save()

    def test_ordering_newest_first_undated_last(self):
        """P1: most recent technical decommission first, records without the date at the bottom."""
        undated = DecommissioningRecord.objects.create(asset=self.make_asset("SN-A"))
        old = DecommissioningRecord.objects.create(
            asset=self.make_asset("SN-B"), technical_decommission_date=datetime.date(2025, 1, 1)
        )
        new = DecommissioningRecord.objects.create(asset=self.make_asset("SN-C"), technical_decommission_date=TODAY)
        self.assertEqual(list(DecommissioningRecord.objects.all()), [new, old, undated])

    def test_sanitization_method_display_helpers(self):
        record = DecommissioningRecord(asset=self.make_asset(), sanitization_method="zeroize")
        self.assertTrue(record.is_sanitization_method_configured())
        self.assertEqual(record.get_sanitization_method_display(), "Zeroize (Juniper)")
        with override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE):
            self.assertFalse(record.is_sanitization_method_configured())
            self.assertEqual(record.get_sanitization_method_display(), "zeroize")

    def test_asset_last_related_info_defaults_to_empty(self):
        self.assertEqual(self.make_asset().last_related_info, "")


class DeletionTest(DecommissioningRecordTestCase):
    def test_delete_record_keeps_asset(self):
        asset = self.make_asset()
        DecommissioningRecord.objects.create(asset=asset).delete()
        self.assertTrue(Asset.objects.filter(pk=asset.pk).exists())

    def test_delete_asset_cascades_with_two_objectchanges(self):
        asset = self.make_asset()
        record = DecommissioningRecord.objects.create(asset=asset)
        request = RequestFactory().get("/")
        request.id = uuid.uuid4()
        request.user = User.objects.create_user(username="deleter")
        asset_pk, record_pk = asset.pk, record.pk

        with event_tracking(request):
            asset.delete()

        self.assertFalse(DecommissioningRecord.objects.filter(pk=record_pk).exists())
        deletions = ObjectChange.objects.filter(request_id=request.id, action="delete")
        self.assertEqual(
            {(c.changed_object_type, c.changed_object_id) for c in deletions},
            {
                (ContentType.objects.get_for_model(Asset), asset_pk),
                (ContentType.objects.get_for_model(DecommissioningRecord), record_pk),
            },
        )

    def test_contact_protect(self):
        for field in ("technical_decommission_operator", "sanitization_operator"):
            with self.subTest(field=field):
                contact = Contact.objects.create(name=f"Operator {field}")
                DecommissioningRecord.objects.create(asset=self.make_asset(f"SN-{field}"), **{field: contact})
                with self.assertRaises(ProtectedError):
                    contact.delete()


class AssetImmutableTest(DecommissioningRecordTestCase):
    """V0"""

    def test_asset_cannot_change_on_existing_record(self):
        record = DecommissioningRecord.objects.create(asset=self.make_asset("SN-A"))
        record.asset = self.make_asset("SN-B")
        self.assert_invalid(record, {"asset": ["asset_immutable"]})

    def test_same_asset_is_accepted(self):
        record = DecommissioningRecord.objects.create(asset=self.make_asset())
        record = DecommissioningRecord.objects.get(pk=record.pk)
        record.full_clean()


class FutureDateTest(DecommissioningRecordTestCase):
    """V1"""

    DATE_FIELDS = ("technical_decommission_date", "sanitization_date", "disposal_date")

    def record(self, **dates):
        kwargs = {"sanitization_method": "zeroize"} if "sanitization_date" in dates else {}
        return DecommissioningRecord(asset=self.make_asset(lifecycle_status=DISPOSED), **kwargs, **dates)

    def test_future_date_rejected(self):
        for field in self.DATE_FIELDS:
            with self.subTest(field=field):
                self.assert_invalid(self.record(**{field: TOMORROW}), {field: ["future_date"]})

    def test_today_accepted(self):
        self.record(technical_decommission_date=TODAY, sanitization_date=TODAY, disposal_date=TODAY).full_clean()

    @override_settings(TIME_ZONE="Europe/Rome")
    def test_today_is_the_local_date(self):
        """D8: 23:30 UTC on the 19th is already the 20th in Rome."""
        with mock.patch(
            "django.utils.timezone.now",
            return_value=datetime.datetime(2026, 10, 19, 23, 30, tzinfo=datetime.UTC),
        ):
            self.record(disposal_date=TODAY).full_clean()
            self.assert_invalid(self.record(disposal_date=TOMORROW), {"disposal_date": ["future_date"]})


class DateOrderTest(DecommissioningRecordTestCase):
    """V2: the error goes on the later field of each pair."""

    def record(self, **dates):
        return DecommissioningRecord(
            asset=self.make_asset(lifecycle_status=DISPOSED),
            sanitization_method="zeroize" if dates.get("sanitization_date") else "",
            **dates,
        )

    def test_wrong_order_rejected(self):
        cases = (
            ({"technical_decommission_date": TODAY, "sanitization_date": YESTERDAY}, "sanitization_date"),
            ({"sanitization_date": TODAY, "disposal_date": YESTERDAY}, "disposal_date"),
            ({"technical_decommission_date": TODAY, "disposal_date": YESTERDAY}, "disposal_date"),
        )
        for dates, field in cases:
            with self.subTest(dates=dates):
                self.assert_invalid(self.record(**dates), {field: ["date_order"]})

    def test_same_day_accepted(self):
        self.record(technical_decommission_date=TODAY, sanitization_date=TODAY, disposal_date=TODAY).full_clean()

    def test_right_order_accepted(self):
        self.record(
            technical_decommission_date=YESTERDAY - datetime.timedelta(days=1),
            sanitization_date=YESTERDAY,
            disposal_date=TODAY,
        ).full_clean()


class SanitizationPairTest(DecommissioningRecordTestCase):
    """V3"""

    def test_date_without_method(self):
        record = DecommissioningRecord(asset=self.make_asset(), sanitization_date=TODAY)
        self.assert_invalid(record, {"sanitization_method": ["sanitization_method_required"]})

    def test_method_without_date(self):
        record = DecommissioningRecord(asset=self.make_asset(), sanitization_method="zeroize")
        self.assert_invalid(record, {"sanitization_date": ["sanitization_date_required"]})

    def test_both_accepted(self):
        DecommissioningRecord(
            asset=self.make_asset(), sanitization_date=TODAY, sanitization_method="zeroize"
        ).full_clean()


class SanitizationMethodConfiguredTest(DecommissioningRecordTestCase):
    """V4"""

    def test_unconfigured_value_rejected(self):
        record = DecommissioningRecord(asset=self.make_asset(), sanitization_date=TODAY, sanitization_method="bogus")
        self.assert_invalid(record, {"sanitization_method": ["not_configured"]})

    def test_removed_value_kept_on_existing_record(self):
        record = DecommissioningRecord.objects.create(
            asset=self.make_asset(), sanitization_date=TODAY, sanitization_method="zeroize"
        )
        with override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE):
            record = DecommissioningRecord.objects.get(pk=record.pk)
            record.disposal_document = "RAEE 2026/123"
            record.full_clean()

    def test_removed_value_rejected_on_new_record(self):
        with override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE):
            record = DecommissioningRecord(
                asset=self.make_asset(), sanitization_date=TODAY, sanitization_method="zeroize"
            )
            self.assert_invalid(record, {"sanitization_method": ["not_configured"]})

    def test_removed_value_rejected_when_changed_to(self):
        record = DecommissioningRecord.objects.create(
            asset=self.make_asset(), sanitization_date=TODAY, sanitization_method="clear"
        )
        with override_settings(PLUGINS_CONFIG=WITHOUT_ZEROIZE):
            record = DecommissioningRecord.objects.get(pk=record.pk)
            record.sanitization_method = "zeroize"
            self.assert_invalid(record, {"sanitization_method": ["not_configured"]})


class AssetStatusOnRecordTest(DecommissioningRecordTestCase):
    """V5"""

    def test_technical_date_requires_retired_or_disposed(self):
        for status in (IN_USE, LifecycleStatusChoices.NEW, LifecycleStatusChoices.IN_STOCK):
            with self.subTest(status=status):
                record = DecommissioningRecord(
                    asset=self.make_asset(f"SN-{status}", lifecycle_status=status), technical_decommission_date=TODAY
                )
                self.assert_invalid(record, {"technical_decommission_date": ["asset_not_decommissioned"]})

    def test_technical_date_accepted_when_retired_or_disposed(self):
        for status in (RETIRED, DISPOSED):
            with self.subTest(status=status):
                DecommissioningRecord(
                    asset=self.make_asset(f"SN-{status}", lifecycle_status=status), technical_decommission_date=TODAY
                ).full_clean()

    def test_disposal_date_requires_disposed(self):
        record = DecommissioningRecord(asset=self.make_asset(lifecycle_status=RETIRED), disposal_date=TODAY)
        self.assert_invalid(record, {"disposal_date": ["asset_not_disposed"]})

    def test_disposal_date_accepted_when_disposed(self):
        DecommissioningRecord(asset=self.make_asset(lifecycle_status=DISPOSED), disposal_date=TODAY).full_clean()


class AggregatedErrorsTest(DecommissioningRecordTestCase):
    """P2: every problem is reported at once."""

    def test_errors_on_several_fields(self):
        record = DecommissioningRecord(
            asset=self.make_asset(lifecycle_status=IN_USE),
            technical_decommission_date=TODAY,
            sanitization_date=TOMORROW,
            disposal_date=YESTERDAY,
        )
        with self.assertRaises(ValidationError) as cm:
            record.full_clean()
        codes = error_codes(cm.exception)
        self.assertIn("asset_not_decommissioned", codes["technical_decommission_date"])
        self.assertIn("future_date", codes["sanitization_date"])
        self.assertIn("sanitization_method_required", codes["sanitization_method"])
        self.assertIn("date_order", codes["disposal_date"])
        self.assertIn("asset_not_disposed", codes["disposal_date"])


class AssetLifecycleGuardTest(DecommissioningRecordTestCase):
    """V6 in Asset.clean() and V7"""

    def asset_with_record(self, status, **dates):
        asset = self.make_asset(lifecycle_status=status)
        DecommissioningRecord.objects.create(asset=asset, **dates)
        return Asset.objects.get(pk=asset.pk)

    def test_decommissioned_asset_cannot_go_back(self):
        asset = self.asset_with_record(RETIRED, technical_decommission_date=TODAY)
        for status in (IN_USE, LifecycleStatusChoices.NEW, LifecycleStatusChoices.IN_MAINTENANCE):
            with self.subTest(status=status):
                asset.lifecycle_status = status
                self.assert_invalid(asset, {"lifecycle_status": ["decommissioned_asset"]})

    def test_decommissioned_asset_can_be_disposed(self):
        asset = self.asset_with_record(RETIRED, technical_decommission_date=TODAY)
        asset.lifecycle_status = DISPOSED
        asset.full_clean()

    def test_disposed_asset_cannot_go_back(self):
        asset = self.asset_with_record(DISPOSED, disposal_date=TODAY)
        asset.lifecycle_status = RETIRED
        self.assert_invalid(asset, {"lifecycle_status": ["disposed_asset"]})

    def test_both_dates_report_disposed(self):
        asset = self.asset_with_record(DISPOSED, technical_decommission_date=TODAY, disposal_date=TODAY)
        asset.lifecycle_status = IN_USE
        self.assert_invalid(asset, {"lifecycle_status": ["disposed_asset"]})

    def test_record_without_dates_does_not_block(self):
        asset = self.asset_with_record(RETIRED)
        asset.lifecycle_status = IN_USE
        asset.full_clean()

    def test_other_changes_on_decommissioned_asset_allowed(self):
        asset = self.asset_with_record(DISPOSED, technical_decommission_date=TODAY, disposal_date=TODAY)
        asset.description = "kept for the records"
        asset.full_clean()

    def test_new_asset_runs_no_record_query(self):
        asset = Asset(serial="SN-NEW", lifecycle_status=IN_USE)
        with CaptureQueriesContext(connection) as queries:
            asset.clean()
        table = DecommissioningRecord._meta.db_table
        self.assertFalse([q["sql"] for q in queries if table in q["sql"]])

    def test_retired_or_disposed_without_record_is_free(self):
        """V7: no record, no restriction in any direction."""
        asset = self.make_asset(lifecycle_status=DISPOSED)
        for status in (RETIRED, IN_USE, DISPOSED, LifecycleStatusChoices.NEW):
            with self.subTest(status=status):
                asset.lifecycle_status = status
                asset.full_clean()
                asset.save()


class AssetTypeDecommissioningRequirementsTest(TestCase):
    """R2 at model level: only configured values, a removed value survives unchanged."""

    def test_defaults_to_empty(self):
        asset_type = AssetType.objects.create(name="Switch", slug="switch")
        self.assertEqual(asset_type.decommissioning_requirements, "")
        asset_type.full_clean()

    def test_configured_value_accepted(self):
        AssetType(name="Switch", slug="switch", decommissioning_requirements="zeroize").full_clean()

    def test_unconfigured_value_rejected(self):
        asset_type = AssetType(name="Switch", slug="switch", decommissioning_requirements="bogus")
        with self.assertRaises(ValidationError) as cm:
            asset_type.full_clean()
        self.assertEqual(error_codes(cm.exception), {"decommissioning_requirements": ["not_configured"]})

    def test_removed_value_kept_unchanged(self):
        asset_type = AssetType.objects.create(name="Switch", slug="switch", decommissioning_requirements="zeroize")
        with override_settings(
            PLUGINS_CONFIG={"inventory_monitor": {"decommissioning_requirements_choices": [("clear", "Clear")]}}
        ):
            asset_type = AssetType.objects.get(pk=asset_type.pk)
            asset_type.description = "core switches"
            asset_type.full_clean()

            asset_type.decommissioning_requirements = "destroy"
            with self.assertRaises(ValidationError) as cm:
                asset_type.full_clean()
            self.assertEqual(error_codes(cm.exception), {"decommissioning_requirements": ["not_configured"]})


class SearchTest(DecommissioningRecordTestCase):
    """Global search finds a record by its document and by the serial of its asset (P6)."""

    def search(self, value):
        return [(result.object_type.model_class(), result.object_id) for result in search_backend.search(value)]

    def make_indexed_record(self, serial="SN-1", **kwargs):
        # Search indexing is deferred to the commit of the transaction, in one flush per transaction:
        # the asset and the record are both created inside the block, or the record would join a
        # flush registered before it
        with self.captureOnCommitCallbacks(execute=True):
            asset = self.make_asset(serial, lifecycle_status=DISPOSED)
            return DecommissioningRecord.objects.create(asset=asset, **kwargs)

    def test_by_disposal_document(self):
        record = self.make_indexed_record(disposal_document="RAEE 2026/123")
        self.assertIn((DecommissioningRecord, record.pk), self.search("RAEE 2026/123"))

    def test_by_asset_serial(self):
        record = self.make_indexed_record("SN-SEARCH-1")
        self.assertIn((DecommissioningRecord, record.pk), self.search("SN-SEARCH-1"))

    def test_serial_change_reindexes_record(self):
        record = self.make_indexed_record("SN-OLD")
        asset = record.asset
        asset.serial = "SN-NEW"
        with self.captureOnCommitCallbacks(execute=True):
            asset.save()
        self.assertIn((DecommissioningRecord, record.pk), self.search("SN-NEW"))
        self.assertNotIn((DecommissioningRecord, record.pk), self.search("SN-OLD"))

    def test_unchanged_serial_runs_no_record_query(self):
        asset = Asset.objects.get(pk=self.make_indexed_record("SN-SAME").asset_id)
        asset.description = "changed"
        with CaptureQueriesContext(connection) as ctx:
            asset.save()
        self.assertFalse(
            [q for q in ctx.captured_queries if DecommissioningRecord._meta.db_table in q["sql"]],
            "an unchanged serial must not look up the record",
        )
