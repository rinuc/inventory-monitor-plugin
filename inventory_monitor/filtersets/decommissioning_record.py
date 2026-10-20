import django_filters
from django.db.models import Q
from netbox.filtersets import PrimaryModelFilterSet
from tenancy.models import Contact
from utilities.filters import MultiValueCharFilter
from utilities.filtersets import register_filterset

from inventory_monitor.helpers import filter_configured
from inventory_monitor.models import Asset, DecommissioningRecord
from inventory_monitor.settings import SANITIZATION_METHOD_CHOICES, get_sanitization_method_choices


@register_filterset
class DecommissioningRecordFilterSet(PrimaryModelFilterSet):
    asset_id = django_filters.ModelMultipleChoiceFilter(
        field_name="asset",
        queryset=Asset.objects.all(),
        label="Asset (ID)",
    )
    # Exact match; partial matches go through q
    serial = MultiValueCharFilter(field_name="asset__serial", label="Asset serial")
    asset_nis_relevant = django_filters.BooleanFilter(field_name="asset__nis_relevant", label="Asset NIS2 relevant")
    sanitization_method = django_filters.MultipleChoiceFilter(choices=[])
    sanitization_method_configured = django_filters.BooleanFilter(
        method="filter_sanitization_method_configured",
        label="Sanitization method configured",
    )
    technical_decommission_operator_id = django_filters.ModelMultipleChoiceFilter(
        field_name="technical_decommission_operator",
        queryset=Contact.objects.all(),
        label="Technical decommission operator (ID)",
    )
    sanitization_operator_id = django_filters.ModelMultipleChoiceFilter(
        field_name="sanitization_operator",
        queryset=Contact.objects.all(),
        label="Sanitization operator (ID)",
    )

    class Meta:
        model = DecommissioningRecord
        # The date fields get __gte/__lte/... lookups from NetBox
        fields = [
            "id",
            "technical_decommission_date",
            "sanitization_date",
            "disposal_date",
            "disposal_document",
            "description",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Choices from config (R4)
        self.filters["sanitization_method"].field.choices = get_sanitization_method_choices()

    def filter_sanitization_method_configured(self, queryset, name, value):
        return filter_configured(queryset, "sanitization_method", SANITIZATION_METHOD_CHOICES, value)

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(asset__serial__icontains=value)
            | Q(asset__partnumber__icontains=value)
            | Q(disposal_document__icontains=value)
            | Q(description__icontains=value)
        )
