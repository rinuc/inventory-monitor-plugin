"""Refresh Asset.last_related_info before a Device or Module is deleted (R1, D5, D11, spec §3.2).

Each receiver takes one snapshot and writes it with a single QuerySet.update(): the number of
queries does not depend on the number of assets, and no ObjectChange is logged for them (D5).
"""

from dcim.models import Device, Module
from django.db.models import Q, QuerySet
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from inventory_monitor.models import Asset
from inventory_monitor.snapshot import (
    device_like_content_types,
    snapshot_of_assignment,
    snapshot_of_deleted_device,
)


@receiver(pre_delete, sender=Device, dispatch_uid="inventory_monitor_device_pre_delete")
def snapshot_assets_of_deleted_device(sender, instance, **kwargs):
    device_ct, module_ct = device_like_content_types()
    snapshot = snapshot_of_deleted_device(instance)
    if snapshot is None:
        return
    Asset.objects.filter(
        Q(assigned_object_type_id=device_ct, assigned_object_id=instance.pk)
        | Q(
            assigned_object_type_id=module_ct,
            assigned_object_id__in=Module.objects.filter(device_id=instance.pk).values("pk"),
        )
    ).update(last_related_info=snapshot)


@receiver(pre_delete, sender=Module, dispatch_uid="inventory_monitor_module_pre_delete")
def snapshot_assets_of_deleted_module(sender, instance, origin=None, **kwargs):
    # Deleted in cascade with its Device: the Device receiver already covered these assets. The
    # Collector sends every pre_delete before deleting anything, so the Device still exists here.
    if isinstance(origin, Device) or (isinstance(origin, QuerySet) and origin.model is Device):
        return
    _, module_ct = device_like_content_types()
    snapshot = snapshot_of_assignment(module_ct, instance.pk)
    if snapshot is None:
        return
    Asset.objects.filter(assigned_object_type_id=module_ct, assigned_object_id=instance.pk).update(
        last_related_info=snapshot
    )
