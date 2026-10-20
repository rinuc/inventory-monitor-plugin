import django_filters
from django.db.models import Q
from netbox.filtersets import NetBoxModelFilterSet
from utilities.filtersets import register_filterset

from inventory_monitor.helpers import filter_configured
from inventory_monitor.models import AssetType
from inventory_monitor.settings import DECOMMISSIONING_REQUIREMENTS_CHOICES, get_decommissioning_requirements_choices


@register_filterset
class AssetTypeFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = AssetType
        fields = ["id", "name", "slug", "description", "color"]

    name = django_filters.CharFilter(lookup_expr="icontains")
    description = django_filters.CharFilter(lookup_expr="icontains")
    slug = django_filters.CharFilter(lookup_expr="iexact")
    decommissioning_requirements = django_filters.MultipleChoiceFilter(choices=[])
    decommissioning_requirements_configured = django_filters.BooleanFilter(
        method="filter_decommissioning_requirements_configured",
        label="Decommissioning requirements configured",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Choices from config (R4)
        self.filters["decommissioning_requirements"].field.choices = get_decommissioning_requirements_choices()

    def filter_decommissioning_requirements_configured(self, queryset, name, value):
        return filter_configured(queryset, "decommissioning_requirements", DECOMMISSIONING_REQUIREMENTS_CHOICES, value)

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(slug__icontains=value) | Q(description__icontains=value))
