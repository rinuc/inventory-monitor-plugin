import django_tables2 as tables
from netbox.tables import NetBoxTable, columns

from inventory_monitor.helpers import ConfiguredChoiceColumn
from inventory_monitor.models import AssetType
from inventory_monitor.settings import DECOMMISSIONING_REQUIREMENTS_CHOICES


class AssetTypeTable(NetBoxTable):
    name = tables.Column(linkify=True)
    color = columns.ColorColumn()
    decommissioning_requirements = ConfiguredChoiceColumn(choice_key=DECOMMISSIONING_REQUIREMENTS_CHOICES)
    tags = columns.TagColumn()

    class Meta(NetBoxTable.Meta):
        model = AssetType
        fields = (
            "pk",
            "id",
            "name",
            "slug",
            "description",
            "color",
            "decommissioning_requirements",
            "asset_count",
            "tags",
            "actions",
        )
        default_columns = (
            "name",
            "slug",
            "description",
            "color",
            "asset_count",
            "tags",
        )
