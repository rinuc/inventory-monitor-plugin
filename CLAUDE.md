# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

`inventory_monitor`, a NetBox plugin for hardware assets, asset types, contracts, invoices,
services, RMAs, external inventory and SNMP "probes". This clone has `origin` = the rinuc fork and
`upstream` = `CESNET/inventory-monitor-plugin`.

- Plugin version: `inventory_monitor/version.py`. NetBox: `min_version`/`max_version` in
  `inventory_monitor/__init__.py` (currently 4.7.x). Python `>=3.12,<3.15` (`pyproject.toml`).
- No runtime dependencies beyond NetBox (`dependencies = []` stays empty).
- Lint/format: ruff, line length 120, rules `E`, `F`, `W`; Markdown is excluded.
- Tests: `inventory_monitor/tests/`, Django tests run by NetBox's test runner. No CI runs them
  (`.github/workflows/` only has `release.yml`), so run them locally before every commit.

## Development environment

A local NetBox checkout with this plugin installed in editable mode. `dev/nb.sh` wraps it and reads
`NETBOX_DIR` and `VENV` from `dev/.env.local` (git-ignored; the script fails with a clear message if
it is missing).

```bash
dev/nb.sh test [label...]   # manage.py test --keepdb --parallel 1 (default label: inventory_monitor)
dev/nb.sh lint              # ruff check . && ruff format --check .
dev/nb.sh migrations        # manage.py makemigrations inventory_monitor
dev/nb.sh check             # lint + makemigrations --check --dry-run + full test suite; stops at first failure
dev/nb.sh runserver         # manage.py runserver 127.0.0.1:8001 --insecure
dev/nb.sh manage <args...>  # any other manage.py command
```

On the maintainer's machine the environment lives in `~/netbox-dev/` (outside the repository):
`docker-compose.yml` with PostgreSQL 18 on `127.0.0.1:55432` and Valkey on `127.0.0.1:56379`,
`.env` with credentials, NetBox source in `netbox/` (tag matching `max_version`), virtualenv in
`venv/` (Python 3.12, NetBox requirements, `pip install -e` of this plugin, ruff), and
`netbox/netbox/netbox/configuration.py` with `DEVELOPER = True`, `TIME_ZONE = "Europe/Rome"`,
`PLUGINS = ["inventory_monitor"]`. Start the services with `docker compose up -d` in `~/netbox-dev`.

`--keepdb` reuses `test_netbox`. To test on a fresh database (required before finishing a feature),
drop it first: `docker exec netbox-dev-postgres-1 psql -U postgres -c "DROP DATABASE test_netbox"`.
A run with only `SimpleTestCase` tests never creates the database, so it proves nothing about
migrations.

The `netbox-docker` harness two directories up installs a **non-editable** copy of the plugin into
its image: it does not see working-tree changes until the image is rebuilt. Use it only for final
manual checks, not for the test/code loop.

## Working rules

1. **Spec first.** For a non-trivial feature, write or update the spec in `docs/specs/` (data model,
   rules, configuration, files to touch, requirement → test table, decisions, open questions) and
   wait for approval before touching code.
2. **One step at a time**, in the order of the approved plan. For each step:
   1. write the tests first and check they **fail for the right reason**;
   2. write the code;
   3. run the **full suite** with `dev/nb.sh check`;
   4. one commit per step, English message in the repository style (`Feat: ...`, `Fix: ...`,
      `Docs: ...`, `Test: ...`, `Chore: ...`);
   5. summarise (what, tests added, suite result) and stop.
3. **Never `git push`.** Never `--no-verify`, never rewrite history.
4. **Never weaken existing tests**: no `skip`, no removed or loosened assertions. Adding a model to
   a tuple in `tests/test_contacts.py` when its nature requires it is fine.
5. **Ambiguities** go into the spec's open questions and are asked, not guessed.
6. **Follow the existing patterns** (below). New labels use `gettext_lazy`.
7. **No new dependencies** in the plugin. Dev tools go only into the dev virtualenv.
8. Do not modify `RMA.update_asset_serial()` or the external GARR scripts.

## Code layout and patterns

One module per model in each layer: `models/`, `forms/`, `filtersets/`, `tables/`, `views/`, each
re-exported from its package `__init__.py`. `RMA` is the reference child model of `Asset`:

- **Models**: `PrimaryModel` (+ `ContactsMixin` where contacts make sense), `objects =
  RestrictedQuerySet.as_manager()`, `tags = TaggableManager(through="extras.TaggedItem",
  related_name="inventory_monitor_<model>s")` to avoid accessor clashes, `get_absolute_url()` with
  `plugins:inventory_monitor:<model>`. To detect changes on save, store the persisted value in
  `__init__` with `self.__dict__.get(...)` (NetBox's own pattern).
- **Views**: generic views registered with `@register_model_view` (`views/rma.py`); `urls.py` has
  two `get_model_urls()` lines per model (with and without `<int:pk>/`). List querysets use
  `select_related`/`prefetch_related` to avoid N+1.
- **Forms**: `PrimaryModelForm` with `fieldsets`, `DynamicModelChoiceField(selector=True)`,
  `DatePicker()`; filter, bulk edit and `PrimaryModelImportForm` (with `CSVModelChoiceField`)
  variants. Configuration-driven choices are set in `__init__` (see `currency` in `forms/asset.py`).
- **Filtersets**: `@register_filterset`, `search()`; boolean "has X" filters use `exclude` for the
  false case (`filter_has_external_inventory_items`).
- **Tables**: `PrimaryModelTable` with `fields` and `default_columns`.
- **API**: `PrimaryModelSerializer`/`NetBoxModelSerializer` with `fields` and `brief_fields`,
  `HyperlinkedIdentityField(view_name="plugins-api:inventory_monitor-api:<model>-detail")`;
  `NetBoxModelViewSet` registered in `api/urls.py`. Circular nesting is resolved in `get_fields()`
  (see `ContractSerializer`).
- **GraphQL**: `@strawberry_django.type(..., fields="__all__", filters=...)` in `graphql/types.py`,
  filters in `graphql/filters.py`, one `Query` class per model in `graphql/schema.py`, listed in
  `graphql/__init__.py`.
- **Search**: `@register_search` indexes in `search.py`; computed values via a model method named
  in `fields` (see `AssetIndex`).
- **Settings**: read at runtime through helpers in `settings.py` from
  `settings.PLUGINS_CONFIG["inventory_monitor"]`; defaults in `default_settings` in `__init__.py`.
  A list in `PLUGINS_CONFIG` replaces the default list, it does not extend it.
- **Menu**: `navigation.py`; `tests/test_navigation.py` checks every link reverses.

## NetBox behaviours worth knowing

- Model forms, `BulkEditView._update_objects()`, CSV import and API serializers all call
  `full_clean()`, so a rule in `Model.clean()` covers every UI/API channel. Plain `save()` and
  `QuerySet.update()` bypass it.
- `utilities/migration.py` drops `choices` from field `deconstruct()`: changing `choices=` never
  creates a migration.
- `core/signals.py` logs an `ObjectChange` for every object deleted, cascades included.
  `QuerySet.update()` logs nothing.
- `ChoiceSet.key` is prefixed with the app label by `ChoiceSetMeta`, so the effective
  `FIELD_CHOICES` key for `LifecycleStatusChoices` is
  `inventory_monitor.inventory_monitor.asset.lifecycle_status` (the README's key has no effect —
  known, not yet fixed).
- On an empty database the `dcim` ContentTypes do not exist during migrations (Django creates them
  in `post_migrate`). Any data migration that resolves a ContentType must return early when there is
  nothing to migrate (see `migrations/0001_initial_squashed.py` and `tests/test_migrations.py`).

## Current work

Decommissioning record (NIS2): spec in `docs/specs/decommissioning-record.md`, original brief in
`docs/prompts/decommissioning-record-implementation.md`.
