from django import forms
from django.utils.translation import gettext_lazy as _
from netbox.forms import NetBoxModelBulkEditForm, NetBoxModelFilterSetForm, NetBoxModelForm, NetBoxModelImportForm
from utilities.forms import BOOLEAN_WITH_BLANK_CHOICES
from utilities.forms.fields import ColorField, CommentField, SlugField, TagFilterField
from utilities.forms.rendering import FieldSet
from utilities.forms.utils import add_blank_choice

from inventory_monitor.models import AssetType
from inventory_monitor.settings import (
    DECOMMISSIONING_REQUIREMENTS_CHOICES,
    get_choices_including,
    get_decommissioning_requirements_choices,
)


class AssetTypeForm(NetBoxModelForm):
    slug = SlugField()
    decommissioning_requirements = forms.ChoiceField(
        required=False,
        choices=[],
        label=_("Decommissioning requirements"),
        help_text=_("How assets of this type must be sanitized when decommissioned"),
    )

    fieldsets = (FieldSet("name", "slug", "color", "description", "decommissioning_requirements", "tags"),)

    class Meta:
        model = AssetType
        fields = [
            "name",
            "slug",
            "color",
            "description",
            "decommissioning_requirements",
            "tags",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Configured values, plus the saved value of this type if it was removed from the configuration (R4)
        current = self.instance._original_decommissioning_requirements if self.instance.pk else ""
        self.fields["decommissioning_requirements"].choices = add_blank_choice(
            get_choices_including(DECOMMISSIONING_REQUIREMENTS_CHOICES, current)
        )


class AssetTypeBulkEditForm(NetBoxModelBulkEditForm):
    color = ColorField(required=False)
    description = forms.CharField(widget=forms.Textarea, required=False)
    decommissioning_requirements = forms.ChoiceField(
        required=False, choices=[], label=_("Decommissioning requirements")
    )
    comments = CommentField(required=False)

    model = AssetType
    nullable_fields = ("color", "description", "decommissioning_requirements", "comments")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decommissioning_requirements"].choices = add_blank_choice(
            get_decommissioning_requirements_choices()
        )


class AssetTypeFilterForm(NetBoxModelFilterSetForm):
    model = AssetType
    fieldsets = (
        FieldSet("q", "filter_id", "tag"),
        FieldSet("color", name=_("Attributes")),
        FieldSet("decommissioning_requirements", "decommissioning_requirements_configured", name=_("Decommissioning")),
    )
    tag = TagFilterField(model)

    color = ColorField(label=_("Color"), required=False)
    decommissioning_requirements = forms.MultipleChoiceField(
        required=False, choices=[], label=_("Decommissioning requirements")
    )
    decommissioning_requirements_configured = forms.NullBooleanField(
        required=False,
        label=_("Requirements configured"),
        help_text=_("No: values removed from the configuration"),
        widget=forms.Select(choices=BOOLEAN_WITH_BLANK_CHOICES),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decommissioning_requirements"].choices = get_decommissioning_requirements_choices()


class AssetTypeBulkImportForm(NetBoxModelImportForm):
    """
    Form for bulk importing Asset Types
    """

    name = forms.CharField(required=True, help_text="Asset type name (required)")
    slug = SlugField(required=True, help_text="URL-friendly slug (required)")
    color = ColorField(required=False, help_text="Color hex code (e.g. aa1409)")
    description = forms.CharField(required=False, help_text="Short description of the asset type")
    # Free text: the model accepts configured values, and keeps a removed value that is not changed
    decommissioning_requirements = forms.CharField(
        required=False, help_text="Decommissioning requirements (a value of decommissioning_requirements_choices)"
    )

    class Meta:
        model = AssetType
        fields = [
            "name",
            "slug",
            "color",
            "description",
            "decommissioning_requirements",
            "tags",
        ]
