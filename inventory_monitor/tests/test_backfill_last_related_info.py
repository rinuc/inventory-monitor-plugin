"""manage.py backfill_last_related_info: one-off fill of existing assets (D12, spec §3.3)."""

from io import StringIO

from dcim.models import Device, Module, ModuleBay
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from inventory_monitor.models import Asset
from inventory_monitor.tests.dcim_fixtures import DcimFixturesMixin


class BackfillLastRelatedInfoTest(DcimFixturesMixin, TestCase):
    def make_asset(self, serial, assigned_object=None, last_related_info=""):
        """An asset as it was before 0009: the field is written with update(), bypassing save()."""
        asset = Asset.objects.create(serial=serial, assigned_object=assigned_object)
        Asset.objects.filter(pk=asset.pk).update(last_related_info=last_related_info)
        return asset

    def info(self, asset):
        return Asset.objects.get(pk=asset.pk).last_related_info

    def backfill(self, *args):
        out = StringIO()
        call_command("backfill_last_related_info", *args, stdout=out)
        return out.getvalue()

    def test_fills_device_and_module_assets(self):
        on_device = self.make_asset("SN-DEV", self.device)
        on_module = self.make_asset("SN-MOD", self.module)
        on_other = self.make_asset("SN-OTHER", self.other_device)
        self.backfill()
        self.assertEqual(self.info(on_device), self.full_snapshot())
        self.assertEqual(self.info(on_module), self.full_snapshot())
        self.assertEqual(self.info(on_other), self.bare_snapshot(self.other_device))

    def test_leaves_filled_and_non_device_assets_alone(self):
        filled = self.make_asset("SN-FILLED", self.device, "written by hand")
        on_site = self.make_asset("SN-SITE", self.site)
        on_rack = self.make_asset("SN-RACK", self.rack)
        unassigned = self.make_asset("SN-NONE")
        self.backfill()
        self.assertEqual(self.info(filled), "written by hand")
        for asset in (on_site, on_rack, unassigned):
            self.assertEqual(self.info(asset), "")

    def test_skips_orphans(self):
        gone = self.make_device("gone")
        bay = ModuleBay.objects.create(device=self.other_device, name="Bay X")
        gone_module = Module.objects.create(device=self.other_device, module_bay=bay, module_type=self.module_type)
        orphan_device = self.make_asset("SN-ORPHAN-D", gone)
        orphan_module = self.make_asset("SN-ORPHAN-M", gone_module)
        # Delete without the pre_delete receivers, as if the Device went before the plugin was upgraded
        Module.objects.filter(pk=gone_module.pk)._raw_delete(connection.alias)
        Device.objects.filter(pk=gone.pk)._raw_delete(connection.alias)

        output = self.backfill()
        self.assertEqual(self.info(orphan_device), "")
        self.assertEqual(self.info(orphan_module), "")
        self.assertIn("Orphaned assignments (skipped): 2", output)

    def test_idempotent(self):
        asset = self.make_asset("SN-DEV", self.device)
        self.backfill()
        first = self.info(asset)
        Device.objects.filter(pk=self.device.pk).update(serial="CHANGED")
        output = self.backfill()
        self.assertEqual(self.info(asset), first)
        self.assertIn("Assets updated: 0", output)
        self.assertIn("Already filled (skipped): 1", output)

    def test_dry_run_writes_nothing(self):
        asset = self.make_asset("SN-DEV", self.device)
        output = self.backfill("--dry-run")
        self.assertEqual(self.info(asset), "")
        self.assertIn("Dry run", output)
        self.assertIn("Assets updated: 1", output)

    def test_summary(self):
        self.make_asset("SN-A", self.device)
        self.make_asset("SN-B", self.module)
        self.make_asset("SN-C", self.device, "kept")
        self.make_asset("SN-D", self.site)
        output = self.backfill()
        self.assertIn("Assets updated: 2", output)
        self.assertIn("Already filled (skipped): 1", output)
        self.assertIn("Orphaned assignments (skipped): 0", output)

    def populate(self, count):
        for i in range(count):
            device = self.make_device(f"bulk-{count}-{i}")
            bay = ModuleBay.objects.create(device=device, name="Bay")
            module = Module.objects.create(device=device, module_bay=bay, module_type=self.module_type)
            self.make_asset(f"D{count}-{i}", device)
            self.make_asset(f"M{count}-{i}", module)

    def count_queries(self):
        with CaptureQueriesContext(connection) as ctx:
            self.backfill()
        return len(ctx.captured_queries)

    def test_constant_queries(self):
        """Queries grow with the number of batches, not with the number of assets."""
        self.populate(2)
        small = self.count_queries()
        Asset.objects.update(last_related_info="")
        self.populate(3)
        self.assertEqual(Asset.objects.filter(last_related_info="").count(), 10)
        self.assertEqual(self.count_queries(), small)
