from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from netbox.models import NetBoxModel
from taggit.managers import TaggableManager
from utilities.fields import ColorField

from inventory_monitor.settings import DECOMMISSIONING_REQUIREMENTS_CHOICES, is_configured


class AssetType(NetBoxModel):
    """
    Model for categorizing and organizing assets by type.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("name"),
    )
    slug = models.SlugField(max_length=100, unique=True)
    description = models.CharField(max_length=200, blank=True, default="", verbose_name=_("description"))
    color = ColorField(verbose_name=_("color"), blank=True)
    # No choices=: the configured list is applied at runtime (R4)
    decommissioning_requirements = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name=_("Decommissioning requirements"),
    )

    # Override tags field to avoid reverse accessor clash with other plugins
    tags = TaggableManager(
        through="extras.TaggedItem",
        related_name="inventory_monitor_asset_types",
        blank=True,
    )

    class Meta:
        ordering = ("name",)
        verbose_name = _("asset type")
        verbose_name_plural = _("asset types")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Persisted value, to accept a value removed from the configuration while it is unchanged
        self._original_decommissioning_requirements = self.__dict__.get("decommissioning_requirements")

    def __str__(self):
        if self.description:
            return f"{self.name} ({self.description})"
        return self.name

    def get_absolute_url(self):
        return reverse("plugins:inventory_monitor:assettype", args=[self.pk])

    def clean(self):
        super().clean()

        value = self.decommissioning_requirements
        unchanged = self.pk and value == self._original_decommissioning_requirements
        if value and not unchanged and not is_configured(DECOMMISSIONING_REQUIREMENTS_CHOICES, value):
            raise ValidationError(
                {
                    "decommissioning_requirements": ValidationError(
                        _("{value} is not a configured decommissioning requirement.").format(value=value),
                        code="not_configured",
                    )
                }
            )
