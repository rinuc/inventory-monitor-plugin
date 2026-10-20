from netbox.api.routers import NetBoxRouter

from inventory_monitor.api import views

app_name = "inventory_monitor"
router = NetBoxRouter()
router.register("probes", views.ProbeViewSet)
router.register("contractors", views.ContractorViewSet)
router.register("contracts", views.ContractViewSet)
router.register("invoices", views.InvoiceViewSet)
router.register("assets", views.AssetViewSet)
router.register("asset-types", views.AssetTypeViewSet)
router.register("asset-services", views.AssetServiceViewSet)
router.register("rmas", views.RMAViewSet)
router.register("external-inventory", views.ExternalInventoryViewSet)
router.register("decommissioning-records", views.DecommissioningRecordViewSet)

urlpatterns = router.urls
