# NetBox serializers
from core.models import ObjectType
from dcim.api.serializers import (
    DeviceSerializer,
    LocationSerializer,
    SiteSerializer,
)
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from netbox.api.fields import ContentTypeField, SerializedPKRelatedField
from netbox.api.serializers import NetBoxModelSerializer, PrimaryModelSerializer
from rest_framework import serializers
from tenancy.api.serializers import ContactSerializer, TenantSerializer
from utilities.api import get_serializer_for_model

# Local models
from inventory_monitor.models import (
    ASSIGNED_OBJECT_MODELS_QUERY,
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
from inventory_monitor.settings import (
    DECOMMISSIONING_REQUIREMENTS_CHOICES,
    SANITIZATION_METHOD_CHOICES,
    is_configured,
)

#
# Base serializers
#


class AssetTypeSerializer(NetBoxModelSerializer):
    """Serializer for AssetType objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:assettype-detail")
    decommissioning_requirements_configured = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AssetType
        fields = [
            "id",
            "url",
            "name",
            "slug",
            "description",
            "color",
            "decommissioning_requirements",
            "decommissioning_requirements_configured",
            "display",
            "custom_fields",
            "created",
            "last_updated",
            "tags",
        ]

        brief_fields = [
            "id",
            "url",
            "name",
            "slug",
            "color",
            "display",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_decommissioning_requirements_configured(self, obj):
        """False for a value removed from the configuration (R4); the stored value is kept"""
        return is_configured(DECOMMISSIONING_REQUIREMENTS_CHOICES, obj.decommissioning_requirements)


class ContractorSerializer(PrimaryModelSerializer):
    """Serializer for Contractor objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:contractor-detail")
    tenant = TenantSerializer(nested=True)

    class Meta:
        model = Contractor
        fields = [
            "id",
            "url",
            "display",
            "name",
            "company",
            "address",
            "description",
            "tenant",
            "owner",
            "tags",
            "comments",
            "custom_fields",
        ]

        brief_fields = ["id", "url", "display", "name", "company", "address", "description"]


class ContractSerializer(PrimaryModelSerializer):
    """Serializer for Contract objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:contract-detail")
    contractor = ContractorSerializer(nested=True)

    class Meta:
        model = Contract
        fields = [
            "id",
            "url",
            "display",
            "name",
            "name_internal",
            "description",
            "contractor",
            "type",
            "contract_type",
            "price",
            "currency",
            "signed",
            "accepted",
            "invoicing_start",
            "invoicing_end",
            "parent",
            "owner",
            "tags",
            "comments",
            "custom_fields",
        ]
        brief_fields = [
            "id",
            "url",
            "display",
            "name",
            "name_internal",
            "description",
        ]

    def get_fields(self):
        """Handle nested parent contract references"""
        fields = super(ContractSerializer, self).get_fields()
        fields["parent"] = ContractSerializer(nested=True)
        return fields


#
# Main objects serializers
#


class AssetSerializer(PrimaryModelSerializer):
    """
    Serializer for Asset objects supporting GenericForeignKey relationships
    """

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:asset-detail")
    # Related object serializers
    order_contract = ContractSerializer(nested=True)
    type = AssetTypeSerializer(nested=True)

    # Generic relationship fields
    assigned_object_type = ContentTypeField(
        queryset=ObjectType.objects.filter(ASSIGNED_OBJECT_MODELS_QUERY),
        required=False,
        allow_null=True,
    )
    assigned_object = serializers.SerializerMethodField(read_only=True, allow_null=True)

    asset_numbers = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Asset
        fields = (
            # Identification fields
            "id",
            "url",
            "display",
            "partnumber",
            "serial",
            "asset_numbers",
            "description",
            # Assignment fields
            "assigned_object_type",
            "assigned_object_id",
            "assigned_object",
            "assignment_status",
            "lifecycle_status",
            "last_related_info",
            "nis_relevant",
            # Related objects
            "type",
            "order_contract",
            "decommissioning_record",
            # Additional information
            "project",
            "vendor",
            "quantity",
            "price",
            "currency",
            # Warranty information
            "warranty_start",
            "warranty_end",
            # Ownership
            "owner",
            # Notes and metadata
            "comments",
            "custom_fields",
            "tags",
            "created",
            "last_updated",
        )
        brief_fields = (
            "id",
            "url",
            "display",
            "partnumber",
            "serial",
            "asset_numbers",
            "type",
            "description",
            "assignment_status",
            "assigned_object",
            "order_contract",
            "lifecycle_status",
            "custom_fields",
        )

    def get_fields(self):
        """Nest the decommissioning record, whose serializer is defined below and nests the asset"""
        fields = super().get_fields()
        # Brief fields of the record have no asset, so the nesting does not recurse
        fields["decommissioning_record"] = DecommissioningRecordSerializer(nested=True, read_only=True, allow_null=True)
        return fields

    @extend_schema_field(serializers.JSONField(allow_null=True))
    def get_assigned_object(self, obj):
        """
        Dynamically serialize the assigned object based on its type

        Returns:
            dict: Serialized representation of the assigned object
            None: If no object is assigned
        """
        if obj.assigned_object is None:
            return None
        serializer = get_serializer_for_model(obj.assigned_object)
        context = {"request": self.context["request"]}
        return serializer(obj.assigned_object, nested=True, context=context).data

    @extend_schema_field(serializers.CharField(read_only=True))
    def get_asset_numbers(self, obj):
        """Get External Inventory asset numbers as comma-separated string"""
        return obj.get_external_inventory_asset_numbers_display()


class ProbeSerializer(NetBoxModelSerializer):
    """Serializer for Probe objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:probe-detail")
    device = DeviceSerializer(allow_null=True, nested=True)
    site = SiteSerializer(allow_null=True, nested=True)
    location = LocationSerializer(allow_null=True, nested=True)

    class Meta:
        model = Probe
        fields = [
            "id",
            "url",
            "display",
            "name",
            "time",
            "serial",
            "part",
            "device_descriptor",
            "device",
            "site_descriptor",
            "site",
            "location_descriptor",
            "location",
            "description",
            "category",
            "discovered_data",
            "tags",
            "comments",
            "custom_fields",
            "creation_time",
        ]

        brief_fields = [
            "id",
            "url",
            "display",
            "name",
            "serial",
            "time",
            "creation_time",
        ]


class InvoiceSerializer(PrimaryModelSerializer):
    """Serializer for Invoice objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:invoice-detail")
    contract = ContractSerializer(nested=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "url",
            "display",
            "name",
            "name_internal",
            "project",
            "description",
            "contract",
            "price",
            "currency",
            "invoicing_start",
            "invoicing_end",
            "owner",
            "tags",
            "comments",
            "custom_fields",
        ]

        brief_fields = ["id", "url", "display", "name", "name_internal", "description"]


class AssetServiceSerializer(PrimaryModelSerializer):
    """Serializer for AssetService objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:assetservice-detail")
    contract = ContractSerializer(nested=True)
    asset = AssetSerializer(nested=True)

    class Meta:
        model = AssetService
        fields = [
            "id",
            "url",
            "display",
            "service_start",
            "service_end",
            "service_price",
            "service_currency",
            "service_category",
            "service_category_vendor",
            "description",
            "asset",
            "contract",
            "owner",
            "tags",
            "comments",
            "custom_fields",
        ]

        brief_fields = [
            "id",
            "url",
            "display",
            "service_start",
            "service_end",
            "service_price",
            "description",
            "asset",
            "contract",
        ]


class RMASerializer(PrimaryModelSerializer):
    """Serializer for RMA (Return Merchandise Authorization) objects"""

    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:rma-detail")
    asset = AssetSerializer(nested=True)

    class Meta:
        model = RMA
        fields = [
            "id",
            "url",
            "display",
            "rma_number",
            "asset",
            "original_serial",
            "replacement_serial",
            "status",
            "date_issued",
            "date_replaced",
            "issue_description",
            "vendor_response",
            "description",
            "comments",
            "owner",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        ]

        brief_fields = [
            "id",
            "url",
            "display",
            "rma_number",
            "asset",
            "original_serial",
            "replacement_serial",
            "status",
            "date_issued",
            "date_replaced",
        ]


class ExternalInventorySerializer(PrimaryModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:externalinventory-detail")
    assets = SerializedPKRelatedField(
        queryset=Asset.objects.all(),
        serializer=AssetSerializer,
        nested=True,
        required=False,
        many=True,
    )

    class Meta:
        model = ExternalInventory
        fields = [
            "id",
            "url",
            "display",
            "external_id",
            "inventory_number",
            "name",
            "serial_number",
            "person_id",
            "person_name",
            "location_code",
            "location",
            "department_code",
            "project_code",
            "user_name",
            "user_note",
            "split_asset",
            "status",
            "assets",
            "description",
            "comments",
            "owner",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        ]
        brief_fields = ["id", "url", "display", "inventory_number", "name", "serial_number", "status"]


class DecommissioningRecordSerializer(PrimaryModelSerializer):
    """Serializer for DecommissioningRecord objects"""

    url = serializers.HyperlinkedIdentityField(
        view_name="plugins-api:inventory_monitor-api:decommissioningrecord-detail"
    )
    asset = AssetSerializer(nested=True)
    technical_decommission_operator = ContactSerializer(nested=True, required=False, allow_null=True)
    sanitization_operator = ContactSerializer(nested=True, required=False, allow_null=True)
    sanitization_method_configured = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DecommissioningRecord
        fields = [
            "id",
            "url",
            "display",
            "asset",
            "technical_decommission_date",
            "technical_decommission_operator",
            "sanitization_date",
            "sanitization_method",
            "sanitization_method_configured",
            "sanitization_operator",
            "disposal_date",
            "disposal_document",
            "description",
            "comments",
            "owner",
            "tags",
            "custom_fields",
            "created",
            "last_updated",
        ]
        # No asset: the record is nested in AssetSerializer
        brief_fields = [
            "id",
            "url",
            "display",
            "technical_decommission_date",
            "sanitization_date",
            "disposal_date",
        ]

    def validate_asset(self, value):
        """
        One record per asset. NetBox skips validate_unique() in the API and the asset field is
        declared here, so DRF adds no unique validator: without this check a second record
        would reach the database constraint.
        """
        records = DecommissioningRecord.objects.filter(asset=value)
        if self.instance is not None:
            records = records.exclude(pk=self.instance.pk)
        if records.exists():
            raise serializers.ValidationError(_("This asset already has a decommissioning record."), code="unique")
        return value

    def validate_sanitization_method(self, value):
        """Only configured methods, except a removed one the record already carries (V4)"""
        unchanged = self.instance is not None and value == self.instance.sanitization_method
        if value and not unchanged and not is_configured(SANITIZATION_METHOD_CHOICES, value):
            raise serializers.ValidationError(
                _("{value} is not a configured sanitization method.").format(value=value), code="not_configured"
            )
        return value

    @extend_schema_field(serializers.BooleanField())
    def get_sanitization_method_configured(self, obj):
        """False for a value removed from the configuration (R4); the stored value is kept"""
        return is_configured(SANITIZATION_METHOD_CHOICES, obj.sanitization_method)
