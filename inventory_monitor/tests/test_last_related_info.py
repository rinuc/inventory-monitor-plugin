"""Asset.last_related_info: snapshot of the last Device (R1, D5, D8, D10, D11).

The format is a contract with whoever reads the CSV export (spec §3.1); the
update rules are in spec §3.2.
"""

from decimal import Decimal

from dcim.models import Device, Interface, Module, ModuleBay
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import translation
from ipam.models import IPAddress

from inventory_monitor.models import Asset
from inventory_monitor.models.rma import RMA, RMAStatusChoices
from inventory_monitor.snapshot import build_device_snapshot, snapshot_of_assignment
from inventory_monitor.tests.dcim_fixtures import SNAPSHOT_DATE, DcimFixturesMixin


class LastRelatedInfoTestCase(DcimFixturesMixin, TestCase):
    def make_asset(self, serial="SN-1", **kwargs):
        return Asset.objects.create(serial=serial, **kwargs)

    def reload(self, asset):
        return Asset.objects.get(pk=asset.pk)


class SnapshotFormatTest(LastRelatedInfoTestCase):
    def test_snapshot_format_full(self):
        self.assertEqual(build_device_snapshot(self.device), self.full_snapshot())

    def test_snapshot_optional_lines_omitted(self):
        self.assertEqual(build_device_snapshot(self.other_device), self.bare_snapshot(self.other_device))

    def test_snapshot_has_no_trailing_newline_and_no_blank_lines(self):
        snapshot = build_device_snapshot(self.device)
        self.assertFalse(snapshot.endswith("\n"))
        self.assertNotIn("\n\n", snapshot)

    def test_unnamed_device(self):
        """Q2: a Device without a name."""
        device = self.make_device(None)
        self.assertIn(f"device: (unnamed) (id {device.pk})", build_device_snapshot(device).splitlines())

    def test_rack_position_variants(self):
        cases = [
            ({"position": Decimal("20.5"), "face": "rear"}, "rack: R12 (U 20.5, rear)"),
            ({"position": 7, "face": ""}, "rack: R12 (U 7)"),
            ({"position": None, "face": ""}, "rack: R12"),
        ]
        for i, (fields, line) in enumerate(cases):
            with self.subTest(line=line):
                device = self.make_device(f"racked-{i}", rack=self.rack, **fields)
                self.assertIn(line, build_device_snapshot(device).splitlines())

    def test_primary_ip_value_may_contain_colons(self):
        """The first ": " separates key and value; IPv6 values keep their colons."""
        device = self.make_device("v6", primary_ip6=IPAddress.objects.create(address="2001:db8::1/64"))
        lines = dict(line.split(": ", 1) for line in build_device_snapshot(device).splitlines())
        self.assertEqual(lines["primary_ip"], "2001:db8::1/64")

    def test_labels_are_english_in_any_language(self):
        """Q15: the stored text does not depend on the language of whoever triggers the snapshot."""
        self.in_italian()
        self.assertEqual(build_device_snapshot(self.device), self.full_snapshot())
        self.assertEqual(translation.get_language(), "it")

    def test_snapshot_date_is_local_time_whole_seconds(self):
        """D8: TIME_ZONE offset, no microseconds."""
        self.assertEqual(build_device_snapshot(self.device).splitlines()[0], f"snapshot_date: {SNAPSHOT_DATE}")

    def test_snapshot_of_assignment_costs_one_query(self):
        for obj in (self.device, self.module):
            with self.subTest(model=obj._meta.model_name), self.assertNumQueries(1):
                snapshot = snapshot_of_assignment(ContentType.objects.get_for_model(obj).pk, obj.pk)
            self.assertEqual(snapshot, self.full_snapshot())

    def test_snapshot_of_assignment_none_for_non_device_or_missing(self):
        ct_device = ContentType.objects.get_for_model(Device)
        self.assertIsNone(snapshot_of_assignment(ContentType.objects.get_for_model(self.site).pk, self.site.pk))
        self.assertIsNone(snapshot_of_assignment(ct_device.pk, 0))
        self.assertIsNone(snapshot_of_assignment(None, None))


class AssignmentOnSaveTest(LastRelatedInfoTestCase):
    def test_assign_device(self):
        asset = self.make_asset(assigned_object=self.device)
        self.assertEqual(asset.last_related_info, self.full_snapshot())
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_assign_device_in_another_language(self):
        self.in_italian()
        asset = self.make_asset(assigned_object=self.device)
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_assign_device_to_existing_asset(self):
        asset = self.make_asset()
        asset.assigned_object = self.device
        asset.save()
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_assign_module_uses_device(self):
        asset = self.make_asset(assigned_object=self.module)
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_site_location_rack_never_written(self):
        """From no assignment, or from another non-Device one: field unchanged, no Site/Location/Rack data."""
        for target in (self.site, self.location, self.rack):
            with self.subTest(target=target):
                asset = self.make_asset(f"SN-{target.pk}-{target._meta.model_name}", assigned_object=target)
                self.assertEqual(self.reload(asset).last_related_info, "")

        asset = self.make_asset("SN-MOVES", assigned_object=self.site, last_related_info="historical text")
        for target in (self.location, self.rack, self.other_site, None):
            with self.subTest(moved_to=target):
                asset.assigned_object = target
                asset.save()
                self.assertEqual(self.reload(asset).last_related_info, "historical text")

    def test_unchanged_assignment_keeps_value(self):
        """A filled field is not recomputed when the assignment does not change, even if written by hand."""
        asset = self.make_asset(assigned_object=self.device)
        asset.last_related_info = "written by hand"
        asset.save()
        self.assertEqual(self.reload(asset).last_related_info, "written by hand")

        reloaded = self.reload(asset)
        reloaded.description = "touched"
        reloaded.save()
        self.assertEqual(self.reload(asset).last_related_info, "written by hand")

    def test_unchanged_assignment_empty_field_is_filled(self):
        asset = self.make_asset(assigned_object=self.device)
        Asset.objects.filter(pk=asset.pk).update(last_related_info="")
        asset = self.reload(asset)
        asset.save()
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_device_change_overwrites(self):
        asset = self.make_asset(assigned_object=self.device, last_related_info="ignored")
        asset.last_related_info = "written by hand"
        asset.save()
        asset.assigned_object = self.other_device
        asset.save()
        self.assertEqual(self.reload(asset).last_related_info, self.bare_snapshot(self.other_device))

    def test_value_given_with_device_assignment_is_overwritten(self):
        """Q3: the field describes the last real Device."""
        asset = self.make_asset(assigned_object=self.device, last_related_info="historical text")
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_leaving_device_refreshes_outgoing_snapshot(self):
        """D10: Device → Site/Location/Rack/nothing takes a fresh snapshot of the outgoing Device."""
        for i, target in enumerate((self.site, self.location, self.rack, None)):
            with self.subTest(target=target):
                device = self.make_device(f"leaving-{i}", rack=self.rack, position=40 + i, face="front")
                asset = self.make_asset(f"SN-LEAVE-{i}", assigned_object=device)

                Device.objects.filter(pk=device.pk).update(
                    rack=self.other_rack,
                    position=12 + i,
                    primary_ip4=IPAddress.objects.create(address=f"192.0.2.{100 + i}/24"),
                )
                asset.assigned_object = target
                asset.save()

                lines = self.reload(asset).last_related_info.splitlines()
                self.assertIn(f"device: leaving-{i} (id {device.pk})", lines)
                self.assertIn(f"rack: R13 (U {12 + i}, front)", lines)
                self.assertIn(f"primary_ip: 192.0.2.{100 + i}/24", lines)
                self.assertNotIn("site: Roma", lines)

    def test_leaving_module_refreshes_outgoing_snapshot(self):
        asset = self.make_asset(assigned_object=self.module, last_related_info="")
        Device.objects.filter(pk=self.device.pk).update(serial="NEW-SERIAL")
        asset.assigned_object = None
        asset.save()
        self.assertIn("device_serial: NEW-SERIAL", self.reload(asset).last_related_info.splitlines())

    def test_orphan_assignment_changes_nothing(self):
        """The Device no longer exists: neither keeping nor leaving the assignment touches the field."""
        device = self.make_device("gone")
        asset = self.make_asset(assigned_object=device)
        snapshot = self.reload(asset).last_related_info
        device.delete()

        asset = self.reload(asset)
        asset.description = "still orphan"
        asset.save()
        self.assertEqual(self.reload(asset).last_related_info, snapshot)

        asset.assigned_object = self.site
        asset.save()
        self.assertEqual(self.reload(asset).last_related_info, snapshot)

    def test_update_fields_without_assignment_skips(self):
        asset = self.make_asset(assigned_object=self.device)
        Asset.objects.filter(pk=asset.pk).update(last_related_info="")
        asset = self.reload(asset)
        asset.description = "only description"
        asset.save(update_fields=["description"])
        self.assertEqual(self.reload(asset).last_related_info, "")

    def test_update_fields_with_assignment_writes_the_field(self):
        asset = self.make_asset()
        asset.assigned_object = self.device
        asset.save(update_fields=["assigned_object_type", "assigned_object_id"])
        self.assertEqual(self.reload(asset).last_related_info, self.full_snapshot())

    def test_unchanged_assignment_costs_no_query(self):
        asset = self.make_asset(assigned_object=self.device)
        with CaptureQueriesContext(connection) as ctx:
            asset.save()
        self.assertFalse([q for q in ctx.captured_queries if "dcim_device" in q["sql"]])

    def test_rma_update_asset_serial(self):
        """RMA.update_asset_serial() saves the asset without full_clean(): no error, field kept."""
        asset = self.make_asset(assigned_object=self.device)
        rma = RMA.objects.create(
            asset=asset,
            original_serial="SN-1",
            replacement_serial="SN-2",
            status=RMAStatusChoices.COMPLETED,
            issue_description="broken",
        )
        rma.update_asset_serial()
        asset = self.reload(asset)
        self.assertEqual(asset.serial, "SN-2")
        self.assertEqual(asset.last_related_info, self.full_snapshot())


class DeviceDeletionTest(LastRelatedInfoTestCase):
    def populate(self, count):
        """A fresh Device with `count` assets on it and `count` on its Module, plus one unrelated asset."""
        device = self.make_device(f"to-delete-{count}", rack=self.rack, position=30 + count, face="rear")
        bay = ModuleBay.objects.create(device=device, name="Bay")
        module = Module.objects.create(device=device, module_bay=bay, module_type=self.module_type)
        direct = [self.make_asset(f"D{count}-{i}", assigned_object=device) for i in range(count)]
        via_module = [self.make_asset(f"M{count}-{i}", assigned_object=module) for i in range(count)]
        unrelated = self.make_asset(f"U{count}", assigned_object=self.other_device)
        Asset.objects.filter(pk__in=[a.pk for a in direct + via_module]).update(last_related_info="stale")
        Device.objects.filter(pk=device.pk).update(serial="FINAL")
        return device, direct + via_module, unrelated

    def test_device_delete_in_another_language(self):
        device, assets, _ = self.populate(1)
        self.in_italian()
        device.delete()
        for asset in assets:
            self.assertIn("status: Active", self.reload(asset).last_related_info.splitlines())

    def delete_counting_queries(self, obj):
        with CaptureQueriesContext(connection) as ctx:
            obj.delete()
        return len(ctx.captured_queries)

    def test_device_delete_updates_direct_and_module_assets(self):
        device, assets, unrelated = self.populate(2)
        device_pk = device.pk
        unrelated_before = self.reload(unrelated).last_related_info
        device.delete()
        for asset in assets:
            lines = self.reload(asset).last_related_info.splitlines()
            self.assertIn(f"device: to-delete-2 (id {device_pk})", lines)
            self.assertIn("device_serial: FINAL", lines)
            self.assertIn("rack: R12 (U 32, rear)", lines)
        self.assertEqual(self.reload(unrelated).last_related_info, unrelated_before)

    def test_device_delete_updates_assets_constant_queries(self):
        """No query per asset: deleting a Device with 2+2 or 5+5 assets costs the same."""
        # Warm up the ContentType cache, which the first deletion would fill
        self.populate(1)[0].delete()
        small, _, _ = self.populate(2)
        large, _, _ = self.populate(5)
        self.assertEqual(self.delete_counting_queries(small), self.delete_counting_queries(large))

    def test_device_delete_keeps_primary_ips_of_its_interfaces(self):
        """T014: the cascade deletes the Interface IPs first and clears the primary IPs in the database."""
        for count, field, address in ((1, "primary_ip4", "192.0.2.50/24"), (2, "primary_ip6", "2001:db8::50/64")):
            with self.subTest(field=field):
                device, assets, _ = self.populate(count)
                interface = Interface.objects.create(device=device, name="et-0/0/0", type="1000base-t")
                ip = IPAddress.objects.create(address=address, assigned_object=interface)
                Device.objects.filter(pk=device.pk).update(**{field: ip})
                Device.objects.get(pk=device.pk).delete()
                self.assertFalse(IPAddress.objects.filter(pk=ip.pk).exists())
                for asset in assets:
                    lines = self.reload(asset).last_related_info.splitlines()
                    self.assertIn(f"primary_ip: {address}", lines)
                    self.assertIn("device_serial: FINAL", lines)

    def test_orphan_keeps_last_related_info(self):
        device, assets, _ = self.populate(2)
        device.delete()
        asset = self.reload(assets[0])
        self.assertIsNone(asset.assigned_object)
        self.assertIn("device_serial: FINAL", asset.last_related_info.splitlines())

    def test_module_delete_updates_assets(self):
        """D11: a Module deleted alone refreshes its assets with its Device's snapshot."""
        device, assets, _ = self.populate(2)
        module = Module.objects.get(device=device)
        module.delete()
        for asset in assets:
            info = self.reload(asset).last_related_info
            if asset.assigned_object_type.model == "module":
                self.assertIn("device_serial: FINAL", info.splitlines())
            else:
                self.assertEqual(info, "stale")
        self.assertTrue(Device.objects.filter(pk=device.pk).exists())

    def test_module_delete_updates_assets_constant_queries(self):
        Module.objects.get(device=self.populate(1)[0]).delete()
        small, _, _ = self.populate(2)
        large, _, _ = self.populate(5)
        self.assertEqual(
            self.delete_counting_queries(Module.objects.get(device=small)),
            self.delete_counting_queries(Module.objects.get(device=large)),
        )

    def test_no_object_change_for_bulk_update(self):
        """D5: the refresh is a QuerySet.update(), so it logs no ObjectChange for the assets."""
        from core.models import ObjectChange

        device, _, _ = self.populate(2)
        before = ObjectChange.objects.filter(changed_object_type__model="asset").count()
        with self.change_logging() as changes:
            device.delete()
        self.assertEqual(ObjectChange.objects.filter(changed_object_type__model="asset").count(), before)
        # Logging was on: the Device deletion itself is in the change log
        self.assertTrue(changes.filter(changed_object_type__model="device", action="delete").exists())
