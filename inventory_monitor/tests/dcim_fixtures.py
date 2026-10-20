"""DCIM objects shared by the last_related_info tests (R1, D10–D12)."""

import datetime
from unittest import mock

from dcim.models import (
    Device,
    DeviceRole,
    DeviceType,
    Location,
    Manufacturer,
    Module,
    ModuleBay,
    ModuleType,
    Rack,
    Site,
)
from django.test import override_settings
from ipam.models import IPAddress
from tenancy.models import Tenant

# 12:00 UTC on 2026-10-20 is 14:00 in Europe/Rome (CEST): snapshot_date is local time (D8)
NOW = datetime.datetime(2026, 10, 20, 12, 0, 0, 123456, tzinfo=datetime.UTC)
SNAPSHOT_DATE = "2026-10-20T14:00:00+02:00"


def fixed_now(now=NOW):
    return mock.patch("django.utils.timezone.now", return_value=now)


class DcimFixturesMixin:
    """setUpTestData() with a fully populated Device, a bare one, and a Module on the first.

    Every test runs in Europe/Rome with timezone.now() pinned to NOW.
    """

    def setUp(self):
        super().setUp()
        self.enterContext(override_settings(TIME_ZONE="Europe/Rome"))
        self.enterContext(fixed_now())

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.site = Site.objects.create(name="Milano-Caldera", slug="milano-caldera")
        cls.other_site = Site.objects.create(name="Roma", slug="roma")
        cls.location = Location.objects.create(site=cls.site, name="Sala 1", slug="sala-1")
        cls.rack = Rack.objects.create(site=cls.site, location=cls.location, name="R12")
        cls.other_rack = Rack.objects.create(site=cls.site, location=cls.location, name="R13")
        cls.tenant = Tenant.objects.create(name="GARR", slug="garr")
        manufacturer = Manufacturer.objects.create(name="Juniper", slug="juniper")
        cls.device_type = DeviceType.objects.create(manufacturer=manufacturer, model="QFX5120-48Y", slug="qfx5120")
        cls.role = DeviceRole.objects.create(name="Core Switch", slug="core-switch")
        cls.ip = IPAddress.objects.create(address="192.0.2.10/24")

        cls.device = cls.make_device(
            "core-sw-01",
            location=cls.location,
            rack=cls.rack,
            position=20,
            face="front",
            serial="WS1234567",
            primary_ip4=cls.ip,
            tenant=cls.tenant,
        )
        cls.other_device = cls.make_device("edge-sw-02", site=cls.other_site)

        cls.module_bay = ModuleBay.objects.create(device=cls.device, name="Bay 1")
        cls.module_type = ModuleType.objects.create(manufacturer=manufacturer, model="LC-1")
        cls.module = Module.objects.create(device=cls.device, module_bay=cls.module_bay, module_type=cls.module_type)

    @classmethod
    def make_device(cls, name, site=None, **kwargs):
        return Device.objects.create(
            name=name, site=site or cls.site, role=cls.role, device_type=cls.device_type, **kwargs
        )

    def full_snapshot(self, device=None):
        device = device or self.device
        return "\n".join(
            [
                f"snapshot_date: {SNAPSHOT_DATE}",
                f"device: core-sw-01 (id {device.pk})",
                "site: Milano-Caldera",
                "location: Sala 1",
                "rack: R12 (U 20, front)",
                "role: Core Switch",
                "device_type: Juniper QFX5120-48Y",
                "device_serial: WS1234567",
                "primary_ip: 192.0.2.10/24",
                "status: Active",
                "tenant: GARR",
            ]
        )

    def bare_snapshot(self, device):
        return "\n".join(
            [
                f"snapshot_date: {SNAPSHOT_DATE}",
                f"device: {device.name} (id {device.pk})",
                f"site: {device.site.name}",
                "role: Core Switch",
                "device_type: Juniper QFX5120-48Y",
                "status: Active",
            ]
        )
