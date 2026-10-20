from django import forms
from django.utils.translation import gettext_lazy as _
from netbox.forms import PrimaryModelBulkEditForm, PrimaryModelFilterSetForm, PrimaryModelForm, PrimaryModelImportForm
from tenancy.models import Contact
from utilities.forms import BOOLEAN_WITH_BLANK_CHOICES
from utilities.forms.fields import (
    CommentField,
    CSVModelChoiceField,
    DynamicModelChoiceField,
    DynamicModelMultipleChoiceField,
    TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.utils import add_blank_choice
from utilities.forms.widgets.datetime import DatePicker

from inventory_monitor.models import Asset, DecommissioningRecord
from inventory_monitor.settings import (
    DECOMMISSIONING_REQUIREMENTS_CHOICES,
    SANITIZATION_METHOD_CHOICES,
    choice_display,
    get_choices_including,
    get_sanitization_method_choices,
)


class DecommissioningRecordForm(PrimaryModelForm):
    # Only assets without a record are offered; on edit the field is locked (D3)
    asset = DynamicModelChoiceField(
        queryset=Asset.objects.all(),
        selector=True,
        query_params={"has_decommissioning_record": "false"},
        label=_("Asset"),
    )
    technical_decommission_operator = DynamicModelChoiceField(
        queryset=Contact.objects.all(), required=False, label=_("Operator")
    )
    sanitization_method = forms.ChoiceField(required=False, choices=[], label=_("Method"))
    sanitization_operator = DynamicModelChoiceField(queryset=Contact.objects.all(), required=False, label=_("Operator"))
    comments = CommentField()

    fieldsets = (
        FieldSet("asset", "description", name=_("Asset")),
        FieldSet("technical_decommission_date", "technical_decommission_operator", name=_("Technical decommission")),
        FieldSet("sanitization_date", "sanitization_method", "sanitization_operator", name=_("Sanitization")),
        FieldSet("disposal_date", "disposal_document", name=_("Disposal")),
        FieldSet("tags", name=_("Misc")),
    )

    class Meta:
        model = DecommissioningRecord
        fields = (
            "asset",
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
            "description",
            "owner",
            "tags",
            "comments",
        )
        widgets = {
            "technical_decommission_date": DatePicker(),
            "sanitization_date": DatePicker(),
            "disposal_date": DatePicker(),
            "disposal_document": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            # Django ignores submitted data for a disabled field; V0 still guards CSV and API
            self.fields["asset"].disabled = True

        # Configured methods, plus the saved method of this record if it was removed from the configuration (R4)
        current = self.instance._original_sanitization_method if self.instance.pk else ""
        self.fields["sanitization_method"].choices = add_blank_choice(
            get_choices_including(SANITIZATION_METHOD_CHOICES, current)
        )

        # Reminder of what the asset type requires (R2)
        asset = self._get_asset()
        requirements = asset.type.decommissioning_requirements if asset and asset.type else ""
        if requirements:
            self.fields["sanitization_method"].help_text = _(
                "Decommissioning requirements of the asset type: {value}"
            ).format(value=choice_display(DECOMMISSIONING_REQUIREMENTS_CHOICES, requirements))

    def _get_asset(self):
        """The asset of the record, or the one preselected with ?asset=<pk>."""
        if self.instance.asset_id:
            return self.instance.asset
        value = self.initial.get("asset")
        pk = getattr(value, "pk", value)
        try:
            pk = int(pk)
        except (TypeError, ValueError):
            return None
        return Asset.objects.select_related("type").filter(pk=pk).first()


class DecommissioningRecordFilterForm(PrimaryModelFilterSetForm):
    model = DecommissioningRecord
    fieldsets = (
        FieldSet("q", "filter_id", "tag", name=_("Misc")),
        FieldSet("asset_id", "serial", name=_("Asset")),
        FieldSet(
            "technical_decommission_date__gte",
            "technical_decommission_date__lte",
            "technical_decommission_operator_id",
            name=_("Technical decommission"),
        ),
        FieldSet(
            "sanitization_date__gte",
            "sanitization_date__lte",
            "sanitization_method",
            "sanitization_method_configured",
            "sanitization_operator_id",
            name=_("Sanitization"),
        ),
        FieldSet("disposal_date__gte", "disposal_date__lte", name=_("Disposal")),
        FieldSet("owner_group_id", "owner_id", name=_("Ownership")),
    )

    tag = TagFilterField(model)
    asset_id = DynamicModelMultipleChoiceField(queryset=Asset.objects.all(), required=False, label=_("Asset"))
    serial = forms.CharField(required=False, label=_("Serial"), help_text=_("Exact asset serial"))
    technical_decommission_date__gte = forms.DateField(required=False, label=_("Date: From"), widget=DatePicker())
    technical_decommission_date__lte = forms.DateField(required=False, label=_("Date: Till"), widget=DatePicker())
    technical_decommission_operator_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_("Operator")
    )
    sanitization_date__gte = forms.DateField(required=False, label=_("Date: From"), widget=DatePicker())
    sanitization_date__lte = forms.DateField(required=False, label=_("Date: Till"), widget=DatePicker())
    sanitization_method = forms.MultipleChoiceField(required=False, choices=[], label=_("Method"))
    sanitization_method_configured = forms.NullBooleanField(
        required=False,
        label=_("Method configured"),
        help_text=_("No: methods removed from the configuration"),
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )
    sanitization_operator_id = DynamicModelMultipleChoiceField(
        queryset=Contact.objects.all(), required=False, label=_("Operator")
    )
    disposal_date__gte = forms.DateField(required=False, label=_("Date: From"), widget=DatePicker())
    disposal_date__lte = forms.DateField(required=False, label=_("Date: Till"), widget=DatePicker())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sanitization_method"].choices = get_sanitization_method_choices()


class DecommissioningRecordBulkEditForm(PrimaryModelBulkEditForm):
    # No asset field: the asset of a record never changes (D3)
    technical_decommission_date = forms.DateField(required=False, widget=DatePicker())
    technical_decommission_operator = DynamicModelChoiceField(queryset=Contact.objects.all(), required=False)
    sanitization_date = forms.DateField(required=False, widget=DatePicker())
    sanitization_method = forms.ChoiceField(required=False, choices=[])
    sanitization_operator = DynamicModelChoiceField(queryset=Contact.objects.all(), required=False)
    disposal_date = forms.DateField(required=False, widget=DatePicker())
    disposal_document = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    comments = CommentField(required=False)

    model = DecommissioningRecord
    fieldsets = (
        FieldSet("technical_decommission_date", "technical_decommission_operator", name=_("Technical decommission")),
        FieldSet("sanitization_date", "sanitization_method", "sanitization_operator", name=_("Sanitization")),
        FieldSet("disposal_date", "disposal_document", name=_("Disposal")),
        FieldSet("description", "comments", name=_("Misc")),
    )
    nullable_fields = (
        "technical_decommission_date",
        "technical_decommission_operator",
        "sanitization_date",
        "sanitization_method",
        "sanitization_operator",
        "disposal_date",
        "disposal_document",
        "description",
        "comments",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sanitization_method"].choices = add_blank_choice(get_sanitization_method_choices())


class DecommissioningRecordBulkImportForm(PrimaryModelImportForm):
    """
    Form for bulk importing decommissioning records.

    The asset and each operator can be given by ID or by natural key, in distinct columns (D4).
    Asset serials and contact names are not unique: an ambiguous value is rejected.
    """

    # (ID column, natural key column): at most one of each pair
    ALTERNATE_COLUMNS = (
        ("asset", "asset_serial"),
        ("technical_decommission_operator", "technical_decommission_operator_name"),
        ("sanitization_operator", "sanitization_operator_name"),
    )

    asset = CSVModelChoiceField(
        queryset=Asset.objects.all(),
        required=False,
        to_field_name="pk",
        help_text="Numeric ID of the asset (or use asset_serial)",
    )
    asset_serial = CSVModelChoiceField(
        queryset=Asset.objects.all(),
        required=False,
        to_field_name="serial",
        help_text="Serial of the asset (or use asset); must match a single asset",
    )
    technical_decommission_date = forms.DateField(
        required=False, help_text="Date the asset was taken out of service (YYYY-MM-DD)"
    )
    technical_decommission_operator = CSVModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        to_field_name="pk",
        help_text="Numeric ID of the contact who took the asset out of service",
    )
    technical_decommission_operator_name = CSVModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        to_field_name="name",
        help_text="Name of the contact who took the asset out of service; must match a single contact",
    )
    sanitization_date = forms.DateField(required=False, help_text="Date the data was erased (YYYY-MM-DD)")
    # Free text: the model accepts configured methods, and keeps a removed method that is not changed
    sanitization_method = forms.CharField(
        required=False, help_text="Sanitization method (a value of sanitization_method_choices)"
    )
    sanitization_operator = CSVModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        to_field_name="pk",
        help_text="Numeric ID of the contact who erased the data",
    )
    sanitization_operator_name = CSVModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        to_field_name="name",
        help_text="Name of the contact who erased the data; must match a single contact",
    )
    disposal_date = forms.DateField(required=False, help_text="Date the asset was disposed of (YYYY-MM-DD)")
    disposal_document = forms.CharField(required=False, help_text="Reference of the disposal certificate")

    class Meta:
        model = DecommissioningRecord
        fields = [
            "asset",
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
            "description",
            "comments",
            "owner",
            "tags",
        ]

    def clean(self):
        super().clean()

        for field, alternate in self.ALTERNATE_COLUMNS:
            if self.cleaned_data.get(field) and self.cleaned_data.get(alternate):
                raise forms.ValidationError(
                    _("Use either {field} or {alternate}, not both.").format(field=field, alternate=alternate)
                )
            if self.cleaned_data.get(alternate):
                # Assigned through the model field, so that the model rules (V0, unique) see it
                self.cleaned_data[field] = self.cleaned_data[alternate]

        if not self.instance.pk and not self.cleaned_data.get("asset"):
            raise forms.ValidationError(_("An asset is required: set either asset or asset_serial."))

        return self.cleaned_data
