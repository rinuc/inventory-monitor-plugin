from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from netbox.models import PrimaryModel
from taggit.managers import TaggableManager
from utilities.querysets import RestrictedQuerySet

from inventory_monitor.models.asset import LifecycleStatusChoices
from inventory_monitor.settings import SANITIZATION_METHOD_CHOICES, choice_label, is_configured

# Pairs (earlier, later) that must not be in reverse order; the error goes on the later field
DATE_ORDER = (
    ("technical_decommission_date", "sanitization_date"),
    ("sanitization_date", "disposal_date"),
    ("technical_decommission_date", "disposal_date"),
)


class DecommissioningRecord(PrimaryModel):
    """
    NIS2 decommissioning register entry of an Asset: technical decommission, data sanitization and
    disposal. Operators are explicit Contact foreign keys, so the model has no ContactsMixin.
    """

    objects = RestrictedQuerySet.as_manager()

    asset = models.OneToOneField(
        to="inventory_monitor.Asset",
        on_delete=models.CASCADE,
        related_name="decommissioning_record",
        verbose_name=_("asset"),
    )
    technical_decommission_date = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("technical decommission date"),
    )
    technical_decommission_operator = models.ForeignKey(
        to="tenancy.Contact",
        on_delete=models.PROTECT,
        related_name="inventory_monitor_decommissions",
        blank=True,
        null=True,
        verbose_name=_("technical decommission operator"),
    )
    sanitization_date = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("sanitization date"),
    )
    # No choices=: the configured list is applied at runtime (R4)
    sanitization_method = models.CharField(
        max_length=50,
        blank=True,
        default="",
        verbose_name=_("sanitization method"),
    )
    sanitization_operator = models.ForeignKey(
        to="tenancy.Contact",
        on_delete=models.PROTECT,
        related_name="inventory_monitor_sanitizations",
        blank=True,
        null=True,
        verbose_name=_("sanitization operator"),
    )
    disposal_date = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("disposal date"),
    )
    disposal_document = models.TextField(
        blank=True,
        default="",
        verbose_name=_("disposal document"),
        help_text=_("Reference of the disposal certificate (e.g. WEEE form number)"),
    )

    # Override tags field to avoid reverse accessor clash with other plugins
    tags = TaggableManager(
        through="extras.TaggedItem",
        related_name="inventory_monitor_decommissioning_records",
        blank=True,
    )

    class Meta:
        ordering = (models.F("technical_decommission_date").desc(nulls_last=True), "-pk")
        verbose_name = _("decommissioning record")
        verbose_name_plural = _("decommissioning records")
        indexes = [
            models.Index(fields=["technical_decommission_date"], name="invmon_decom_tech_date_idx"),
            models.Index(fields=["sanitization_date"], name="invmon_decom_sanit_date_idx"),
            models.Index(fields=["disposal_date"], name="invmon_decom_disp_date_idx"),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Persisted values, to tell a change from an untouched field in clean()
        self._original_asset_id = self.__dict__.get("asset_id")
        self._original_sanitization_method = self.__dict__.get("sanitization_method")

    def __str__(self):
        return self.asset.str_no_pk()

    def get_absolute_url(self):
        return reverse("plugins:inventory_monitor:decommissioningrecord", args=[self.pk])

    def get_asset_serial_for_search(self):
        return self.asset.serial

    def is_sanitization_method_configured(self):
        return is_configured(SANITIZATION_METHOD_CHOICES, self.sanitization_method)

    def get_sanitization_method_display(self):
        return choice_label(SANITIZATION_METHOD_CHOICES, self.sanitization_method)

    def clean(self):
        super().clean()

        errors = {}

        def add_error(field, message, code):
            errors.setdefault(field, [])
            if code not in [e.code for e in errors[field]]:
                errors[field].append(ValidationError(message, code=code))

        # V0: a record belongs to its asset for good
        if self.pk and self.asset_id != self._original_asset_id:
            add_error(
                "asset", _("The asset of an existing decommissioning record cannot be changed."), "asset_immutable"
            )

        # V1: no dates in the future, in the local time zone
        today = timezone.localdate()
        for field in ("technical_decommission_date", "sanitization_date", "disposal_date"):
            value = getattr(self, field)
            if value and value > today:
                add_error(field, _("The date cannot be in the future."), "future_date")

        # V2: technical decommission, then sanitization, then disposal (same day allowed)
        for earlier, later in DATE_ORDER:
            earlier_date, later_date = getattr(self, earlier), getattr(self, later)
            if earlier_date and later_date and earlier_date > later_date:
                add_error(
                    later,
                    _("This date cannot be earlier than the {field}.").format(
                        field=self._meta.get_field(earlier).verbose_name
                    ),
                    "date_order",
                )

        # V3: sanitization date and method go together
        if self.sanitization_date and not self.sanitization_method:
            add_error(
                "sanitization_method",
                _("A sanitization method is required when the sanitization date is set."),
                "sanitization_method_required",
            )
        if self.sanitization_method and not self.sanitization_date:
            add_error(
                "sanitization_date",
                _("A sanitization date is required when the sanitization method is set."),
                "sanitization_date_required",
            )

        # V4: only configured methods, except a removed one the record already carries
        unchanged = self.pk and self.sanitization_method == self._original_sanitization_method
        if self.sanitization_method and not unchanged and not self.is_sanitization_method_configured():
            add_error(
                "sanitization_method",
                _("{value} is not a configured sanitization method.").format(value=self.sanitization_method),
                "not_configured",
            )

        # V5: the dates follow the lifecycle status of the asset
        if self.asset_id:
            status = self.asset.lifecycle_status
            if self.technical_decommission_date and status not in (
                LifecycleStatusChoices.RETIRED,
                LifecycleStatusChoices.DISPOSED,
            ):
                add_error(
                    "technical_decommission_date",
                    _("The asset must be Retired or Disposed to record a technical decommission."),
                    "asset_not_decommissioned",
                )
            if self.disposal_date and status != LifecycleStatusChoices.DISPOSED:
                add_error(
                    "disposal_date",
                    _("The asset must be Disposed to record a disposal."),
                    "asset_not_disposed",
                )

        if errors:
            raise ValidationError(errors)
