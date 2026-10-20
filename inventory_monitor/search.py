from netbox.search import SearchIndex, register_search

from inventory_monitor.models import (
    RMA,
    Asset,
    AssetService,
    AssetType,
    Contract,
    Contractor,
    DecommissioningRecord,
    ExternalInventory,
    Invoice,
    Probe,
)


@register_search
class ContractIndex(SearchIndex):
    model = Contract
    fields = (
        ("name", 100),
        ("name_internal", 100),
        ("comments", 5000),
    )
    display_attrs = ("name", "name_internal")


@register_search
class ContractorIndex(SearchIndex):
    model = Contractor
    fields = (
        ("name", 100),
        ("company", 100),
        ("address", 5000),
    )
    display_attrs = ("name", "company")


@register_search
class InvoiceIndex(SearchIndex):
    model = Invoice
    fields = (
        ("name", 100),
        ("name_internal", 100),
        ("project", 300),
        ("comments", 5000),
    )
    display_attrs = ("name", "project")


@register_search
class ProbeIndex(SearchIndex):
    model = Probe
    fields = (
        ("device_descriptor", 100),
        ("site_descriptor", 100),
        ("location_descriptor", 100),
        ("name", 100),
        ("serial", 100),
        ("part", 100),
        ("category", 100),
        ("description", 5000),
        ("comments", 5000),
    )
    display_attrs = ("name", "serial", "device_descriptor")


@register_search
class AssetIndex(SearchIndex):
    model = Asset
    fields = (
        ("serial", 100),
        ("partnumber", 100),
        ("vendor", 100),
        ("project", 100),
        ("description", 5000),
        ("comments", 5000),
        ("get_external_inventory_asset_numbers_for_search", 80),
    )
    display_attrs = ("serial", "partnumber", "vendor", "description")

    # get_external_inventory_asset_numbers_for_search is a method from Asset which is callable
    @staticmethod
    def get_field_value(instance, field_name):
        value = getattr(instance, field_name)
        if callable(value):
            value = value()
        return str(value) if value is not None else None


@register_search
class AssetServiceIndex(SearchIndex):
    model = AssetService
    fields = (
        ("service_category", 100),
        ("service_category_vendor", 100),
        ("comments", 5000),
    )
    display_attrs = ("service_category", "service_category_vendor")


@register_search
class AssetTypeIndex(SearchIndex):
    model = AssetType
    fields = (
        ("name", 100),
        ("slug", 110),
        ("description", 500),
    )
    display_attrs = ("name", "description")


@register_search
class DecommissioningRecordIndex(SearchIndex):
    model = DecommissioningRecord
    fields = (
        ("asset", 100),
        ("disposal_document", 500),
        ("description", 500),
        ("comments", 5000),
    )
    display_attrs = ("asset", "technical_decommission_date", "sanitization_date", "disposal_date")

    # "asset" caches the asset's serial: the search results label it with the field's verbose_name,
    # which a method would not have. Asset.save() reindexes the record when the serial changes
    @staticmethod
    def get_field_value(instance, field_name):
        value = instance.asset.serial if field_name == "asset" else getattr(instance, field_name)
        return str(value) if value else None


@register_search
class ExternalInventoryIndex(SearchIndex):
    model = ExternalInventory
    fields = (
        ("external_id", 100),
        ("inventory_number", 100),
        ("name", 100),
        ("serial_number", 100),
        ("person_id", 100),
        ("person_name", 100),
        ("location_code", 100),
        ("location", 100),
        ("department_code", 100),
        ("project_code", 100),
        ("user_name", 100),
        ("user_note", 5000),
    )
    display_attrs = ("inventory_number", "name", "serial_number")


@register_search
class RMAIndex(SearchIndex):
    model = RMA
    fields = (
        ("rma_number", 100),
        ("original_serial", 100),
        ("replacement_serial", 100),
        ("issue_description", 5000),
        ("vendor_response", 5000),
    )
    display_attrs = ("rma_number", "original_serial", "replacement_serial")
