"""Device snapshot stored in Asset.last_related_info (R1, spec §3.1).

The text is a contract with whoever reads the CSV export: one "key: value" line per entry, keys
always in this order, optional entries omitted when empty, no blank lines, no trailing newline.
Labels are always in English, whatever the language of the request that triggers the snapshot (Q15).
"""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone, translation

# Everything build_device_snapshot() reads, loaded with the Device in one query
DEVICE_SNAPSHOT_RELATED = (
    "site",
    "location",
    "rack",
    "role",
    "device_type__manufacturer",
    "tenant",
    "primary_ip4",
    "primary_ip6",
)


def _format_rack(device):
    rack = device.rack.name
    if device.position is None:
        return rack
    # DecimalField: 20.0 -> "20", 20.5 -> "20.5"
    position = f"{Decimal(device.position).normalize():f}"
    if device.face:
        return f"{rack} (U {position}, {device.face})"
    return f"{rack} (U {position})"


def build_device_snapshot(device, now=None):
    """Return the last_related_info text for a Device (spec §3.1); `now` defaults to timezone.now()."""
    with translation.override("en"):
        return _build_device_snapshot(device, now)


def _build_device_snapshot(device, now):
    snapshot_date = timezone.localtime(now or timezone.now()).replace(microsecond=0).isoformat()
    primary_ip = device.primary_ip
    entries = [
        ("snapshot_date", snapshot_date),
        ("device", f"{device.name or '(unnamed)'} (id {device.pk})"),
        ("site", device.site.name),
        ("location", device.location.name if device.location else ""),
        ("rack", _format_rack(device) if device.rack else ""),
        ("role", device.role.name),
        ("device_type", device.device_type.full_name),
        ("device_serial", device.serial),
        ("primary_ip", str(primary_ip.address) if primary_ip else ""),
        ("status", device.get_status_display()),
        ("tenant", device.tenant.name if device.tenant else ""),
    ]
    return "\n".join(f"{key}: {value}" for key, value in entries if value)


def device_like_content_types():
    """(Device ContentType id, Module ContentType id); get_for_model() is cached."""
    from dcim.models import Device, Module

    return ContentType.objects.get_for_model(Device).pk, ContentType.objects.get_for_model(Module).pk


def snapshot_of_assignment(content_type_id, object_id, now=None):
    """Snapshot of the Device behind a Device or Module assignment, in one query.

    None when the assignment is not a Device/Module or the object no longer exists.
    """
    from dcim.models import Device

    if content_type_id is None or object_id is None:
        return None
    device_ct, module_ct = device_like_content_types()
    devices = Device.objects.select_related(*DEVICE_SNAPSHOT_RELATED)
    if content_type_id == device_ct:
        device = devices.filter(pk=object_id).first()
    elif content_type_id == module_ct:
        device = devices.filter(modules__pk=object_id).first()
    else:
        return None
    return build_device_snapshot(device, now) if device else None


def snapshot_of_deleted_device(instance, now=None):
    """Snapshot of a Device in pre_delete: database values, primary IPs from `instance`.

    The Collector sends pre_delete to the IPAddresses of the Device's interfaces before the Device,
    and ipam.signals.clear_primary_ip saves the Device with the primary IP set to None. The instance
    passed to delete() still has the primary IP ids, and the IPAddress rows exist until every
    pre_delete has been sent. At most one extra query per cleared primary IP.
    """
    from dcim.models import Device
    from ipam.models import IPAddress

    device = Device.objects.select_related(*DEVICE_SNAPSHOT_RELATED).filter(pk=instance.pk).first()
    if device is None:
        return None
    for field in ("primary_ip4", "primary_ip6"):
        original_id = getattr(instance, f"{field}_id")
        if getattr(device, f"{field}_id") is None and original_id is not None:
            setattr(device, field, IPAddress.objects.filter(pk=original_id).first())
    return build_device_snapshot(device, now)
