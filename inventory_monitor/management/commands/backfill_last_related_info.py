"""Fill Asset.last_related_info for assets that existed before migration 0009 (D12, spec §3.3).

Only assets assigned to a Device or a Module with an empty field are written, so the command is
idempotent. The write is a bulk_update(): no ObjectChange is logged (as for D5); the summary is
the trace.
"""

from dcim.models import Device, Module
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inventory_monitor.models import Asset
from inventory_monitor.snapshot import DEVICE_SNAPSHOT_RELATED, build_device_snapshot, device_like_content_types

BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Fill last_related_info for assets assigned to a Device or Module whose field is still empty."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Compute and report, write nothing.")

    def handle(self, *args, dry_run=False, **options):
        device_ct, module_ct = device_like_content_types()
        device_like = Asset.objects.filter(assigned_object_type_id__in=(device_ct, module_ct))
        already_filled = device_like.exclude(last_related_info="").count()
        assets = list(
            device_like.filter(last_related_info="").only("pk", "assigned_object_type_id", "assigned_object_id")
        )

        # Module -> Device, then every Device once with all it needs for the snapshot
        module_ids = {a.assigned_object_id for a in assets if a.assigned_object_type_id == module_ct}
        module_device = dict(Module.objects.filter(pk__in=module_ids).values_list("pk", "device_id"))
        device_ids = {a.assigned_object_id for a in assets if a.assigned_object_type_id == device_ct}
        device_ids |= set(module_device.values())
        now = timezone.now()
        snapshots = {
            device.pk: build_device_snapshot(device, now)
            for device in Device.objects.select_related(*DEVICE_SNAPSHOT_RELATED).filter(pk__in=device_ids)
        }

        to_update, orphans = [], 0
        for asset in assets:
            if asset.assigned_object_type_id == module_ct:
                device_id = module_device.get(asset.assigned_object_id)
            else:
                device_id = asset.assigned_object_id
            snapshot = snapshots.get(device_id)
            if snapshot is None:
                orphans += 1
                continue
            asset.last_related_info = snapshot
            to_update.append(asset)

        if dry_run:
            self.stdout.write("Dry run: nothing written.")
        else:
            with transaction.atomic():
                Asset.objects.bulk_update(to_update, ["last_related_info"], batch_size=BATCH_SIZE)

        self.stdout.write(f"Assets updated: {len(to_update)}")
        self.stdout.write(f"Already filled (skipped): {already_filled}")
        self.stdout.write(f"Orphaned assignments (skipped): {orphans}")
