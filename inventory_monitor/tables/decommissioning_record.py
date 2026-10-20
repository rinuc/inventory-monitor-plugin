import django_tables2 as tables
from django.template.defaultfilters import linebreaksbr
from django.utils.translation import gettext_lazy as _
from netbox.tables import PrimaryModelTable, columns

from inventory_monitor.helpers import ConfiguredChoiceColumn
from inventory_monitor.models import DecommissioningRecord
from inventory_monitor.settings import SANITIZATION_METHOD_CHOICES


class DecommissioningRecordTable(PrimaryModelTable):
    """The NIS2 decommissioning register: its CSV export holds every column of the register."""

    asset = tables.Column(linkify=True, verbose_name=_("Asset"))
    serial = tables.Column(accessor="asset__serial", verbose_name=_("Serial"))
    asset_type = tables.Column(accessor="asset__type", linkify=True, verbose_name=_("Type"))
    technical_decommission_date = columns.DateColumn()
    technical_decommission_operator = tables.Column(linkify=True)
    sanitization_date = columns.DateColumn()
    sanitization_method = ConfiguredChoiceColumn(choice_key=SANITIZATION_METHOD_CHOICES)
    sanitization_operator = tables.Column(linkify=True)
    disposal_date = columns.DateColumn()
    disposal_document = tables.Column()
    # The "Device" column of the register
    last_related_info = tables.Column(
        accessor="asset__last_related_info", orderable=False, verbose_name=_("Last related device info")
    )
    tags = columns.TagColumn()

    class Meta(PrimaryModelTable.Meta):
        model = DecommissioningRecord
        fields = (
            "pk",
            "id",
            "asset",
            "serial",
            "asset_type",
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
            "last_related_info",
            "description",
            "owner",
            "owner_group",
            "comments",
            "tags",
            "actions",
        )
        default_columns = (
            "asset",
            "serial",
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
            "actions",
        )

    def render_last_related_info(self, value):
        return linebreaksbr(value)

    def value_last_related_info(self, value):
        return value
