from netbox.views import generic
from utilities.views import register_model_view

from inventory_monitor import filtersets, forms, models, tables

# Everything the detail page and every table column show
RELATED = ("asset", "asset__type", "technical_decommission_operator", "sanitization_operator", "owner__group")


@register_model_view(models.DecommissioningRecord)
class DecommissioningRecordView(generic.ObjectView):
    queryset = models.DecommissioningRecord.objects.select_related(*RELATED)


@register_model_view(models.DecommissioningRecord, "list", path="", detail=False)
class DecommissioningRecordListView(generic.ObjectListView):
    queryset = models.DecommissioningRecord.objects.select_related(*RELATED)
    table = tables.DecommissioningRecordTable
    filterset = filtersets.DecommissioningRecordFilterSet
    filterset_form = forms.DecommissioningRecordFilterForm


# ObjectEditView fills the form initial from request.GET: ?asset=<pk> preselects the asset
@register_model_view(models.DecommissioningRecord, "add", detail=False)
@register_model_view(models.DecommissioningRecord, "edit")
class DecommissioningRecordEditView(generic.ObjectEditView):
    queryset = models.DecommissioningRecord.objects.all()
    form = forms.DecommissioningRecordForm


@register_model_view(models.DecommissioningRecord, "delete")
class DecommissioningRecordDeleteView(generic.ObjectDeleteView):
    queryset = models.DecommissioningRecord.objects.all()


@register_model_view(models.DecommissioningRecord, "bulk_edit", path="edit", detail=False)
class DecommissioningRecordBulkEditView(generic.BulkEditView):
    queryset = models.DecommissioningRecord.objects.select_related(*RELATED)
    filterset = filtersets.DecommissioningRecordFilterSet
    table = tables.DecommissioningRecordTable
    form = forms.DecommissioningRecordBulkEditForm


@register_model_view(models.DecommissioningRecord, "bulk_delete", path="delete", detail=False)
class DecommissioningRecordBulkDeleteView(generic.BulkDeleteView):
    queryset = models.DecommissioningRecord.objects.select_related(*RELATED)
    filterset = filtersets.DecommissioningRecordFilterSet
    table = tables.DecommissioningRecordTable
    default_return_url = "plugins:inventory_monitor:decommissioningrecord_list"


@register_model_view(models.DecommissioningRecord, "bulk_import", path="import", detail=False)
class DecommissioningRecordBulkImportView(generic.BulkImportView):
    queryset = models.DecommissioningRecord.objects.all()
    model_form = forms.DecommissioningRecordBulkImportForm
