"""The squashed initial migration must apply on an empty database.

copy_to_assigned_object / reverse_migration resolve dcim ContentTypes, which do
not exist yet on a fresh database: Django creates them in post_migrate, after
every migration has run. Without the early return on "no assets" a fresh
install, and the test database itself, fails with ContentType.DoesNotExist.

The real test database cannot show this (its ContentTypes exist by the time a
test runs), so the functions are called with a fake app registry whose
ContentType lookups always fail.
"""

from importlib import import_module
from unittest import mock

from django.test import SimpleTestCase

squashed = import_module("inventory_monitor.migrations.0001_initial_squashed")


class ContentTypeDoesNotExist(Exception):
    pass


def fake_apps():
    asset = mock.Mock()
    asset.objects.exists.return_value = False
    asset.objects.filter.return_value = []

    content_type = mock.Mock()
    content_type.DoesNotExist = ContentTypeDoesNotExist
    content_type.objects.get.side_effect = ContentTypeDoesNotExist("ContentType matching query does not exist.")

    models = {
        ("inventory_monitor", "Asset"): asset,
        ("contenttypes", "ContentType"): content_type,
    }
    apps = mock.Mock()
    apps.get_model.side_effect = lambda app_label, model_name: models[(app_label, model_name)]
    return apps, content_type


class SquashedInitialMigrationEmptyDatabaseTest(SimpleTestCase):
    def test_copy_to_assigned_object_without_assets(self):
        apps, content_type = fake_apps()
        squashed.copy_to_assigned_object(apps, None)
        content_type.objects.get.assert_not_called()

    def test_reverse_migration_without_assets(self):
        apps, content_type = fake_apps()
        squashed.reverse_migration(apps, None)
        content_type.objects.get.assert_not_called()
