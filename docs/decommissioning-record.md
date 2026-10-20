# Decommissioning Record (NIS2)

## Overview

Every asset that leaves the organisation's control can have one **decommissioning record**: when it
was taken out of service and by whom, when and how its data was erased and by whom, and when and
under which certificate it was disposed of. Exporting the list of records as CSV gives the
decommissioning register required by NIS2 internal procedures.

The feature adds:

- the `DecommissioningRecord` model, at most one per asset;
- `Asset.last_related_info`, a text snapshot of the last Device the asset was installed in, kept
  after the Device is deleted;
- `Asset.nis_relevant`, a flag marking the assets relevant for NIS2;
- `AssetType.decommissioning_requirements`, how assets of a type must be sanitized;
- two configurable choice lists, for sanitization methods and decommissioning requirements.

Records are listed under **Inventory Monitor → Assets → Decommissioning Records**. Each asset page
has a **Decommissioning (NIS2)** panel to add, view, edit or delete its record.

## Typical workflow

1. Set the asset's lifecycle status to **Retired**.
2. On the asset page, click **Add decommissioning record**: the asset is prefilled and the form shows
   the decommissioning requirements of the asset type as a reminder. Enter the technical
   decommission date and operator.
3. When the data has been erased, edit the record: sanitization date, method and operator.
4. Set the asset to **Disposed**, then add the disposal date and the disposal certificate reference
   (for example the WEEE form number) to the record.

The rules below enforce this order: a record cannot claim a decommission that the asset's status
contradicts.

## Building the register

Open the record list and use **Export → Current view** (or **All data (CSV)**). The columns map to
the register as follows:

| Register column | Record field | Table column |
| --- | --- | --- |
| Device | `asset.last_related_info` (and the asset) | `Last related device info` (optional), `Asset` |
| S/N | `asset.serial` | `Serial` |
| Decommission date | `technical_decommission_date` | default |
| Decommission operator | `technical_decommission_operator` | default |
| Data erasure date | `sanitization_date` (and `sanitization_method`) | default |
| Data erasure operator | `sanitization_operator` | default |
| Disposal date | `disposal_date` | default |
| Disposal certificate reference (WEEE) | `disposal_document` | default |

**Current view** exports the columns selected with **Configure table**: add *Last related device
info*, and optionally *Asset NIS2 relevant*, to have them in the file. **All data (CSV)** always
includes them. Use the list filters (dates, operators, method, `Asset NIS2 relevant`) to restrict the
register to a period or to the NIS2-relevant assets.

The disposal company and the disposal operator are not recorded: they are in the referenced
documents, which stay outside NetBox.

## Data model

### DecommissioningRecord

| Field | Notes |
| --- | --- |
| `asset` | One-to-one with Asset, required, cannot be changed once the record exists |
| `technical_decommission_date` | Date the asset was taken out of service |
| `technical_decommission_operator` | Contact |
| `sanitization_date` | Date the data was erased |
| `sanitization_method` | A value of `sanitization_method_choices` |
| `sanitization_operator` | Contact |
| `disposal_date` | Date the asset was disposed of |
| `disposal_document` | Reference of the disposal certificate |

The usual NetBox fields are also available: description, comments, owner, tags, custom fields,
journal and change log.

- Deleting an asset deletes its record. The change log keeps an entry for both deletions.
- Deleting a record leaves the asset unchanged.
- A Contact used as an operator cannot be deleted, so the register stays traceable.
- Records are listed most recent decommission first; records without a decommission date come last.

### Asset

- `nis_relevant` (default `False`): a classification flag. It is shown on the asset page, as a
  default column of the asset list, as a filter (`?nis_relevant=true`), in bulk edit, in CSV import
  (optional column; an update without the column keeps the value) and in the REST and GraphQL APIs.
  It has no effect on the rules below.
- `last_related_info`: see [Last related device info](#last-related-device-info).
- New optional columns in the asset list: decommissioning record (yes/no) and its three dates.
  Filter: `has_decommissioning_record`.

### AssetType

- `decommissioning_requirements`: a value of `decommissioning_requirements_choices`. It is shown on
  the asset type page, as an optional column, as a filter, and as a reminder in the record form.

## Validation rules

The rules live in `Model.clean()`, so they apply to every channel that calls `full_clean()`: forms,
bulk edit, CSV import, the REST API and scripts that call `full_clean()`. Errors carry a stable code.

| Rule | Field | Code | Rejected when |
| --- | --- | --- | --- |
| V0 | `asset` | `asset_immutable` | the asset of an existing record is changed |
| V1 | the date | `future_date` | a date is in the future (NetBox `TIME_ZONE`) |
| V2 | the later date | `date_order` | decommission > sanitization, sanitization > disposal, or decommission > disposal (same day allowed; only dates that are set are compared) |
| V3 | `sanitization_method` / `sanitization_date` | `sanitization_method_required` / `sanitization_date_required` | a sanitization date without a method, or a method without a date |
| V4 | `sanitization_method` | `not_configured` | the method is not configured, unless it is the unchanged value of an existing record |
| V5 | `technical_decommission_date` / `disposal_date` | `asset_not_decommissioned` / `asset_not_disposed` | a decommission date while the asset is not Retired or Disposed; a disposal date while the asset is not Disposed |
| V6 | `Asset.lifecycle_status` | `disposed_asset` / `decommissioned_asset` | the record has a disposal date and the asset leaves Disposed; the record has a decommission date and the asset leaves Retired/Disposed |
| V7 | — | — | never: an asset can be Retired or Disposed without a record |

A record can be saved with every date empty, and then places no limit on the asset's status. To bring an asset back into service, clear the dates in
its record first, then change the status.

V5 and V6 use the built-in `retired` and `disposed` lifecycle values. Removing them through
`FIELD_CHOICES` makes the rules impossible to satisfy. Note that the `FIELD_CHOICES` key that
actually applies to the lifecycle status is `inventory_monitor.inventory_monitor.asset.lifecycle_status`,
not the one shown in the README (known issue).

### External scripts

Scripts that update assets through the REST API, or call `full_clean()`, get the
`disposed_asset` / `decommissioned_asset` errors like the UI. A direct `save()` or a
`QuerySet.update()` skips `clean()` and is **not** protected: such a script can set a decommissioned
asset back in use without any error.

## Configuration

```python
PLUGINS_CONFIG = {
    "inventory_monitor": {
        "sanitization_method_choices": [
            ("clear", "Clear (overwrite / shred)"),
            ("purge", "Purge (ATA Secure Erase / NVMe Sanitize)"),
            ("crypto_erase", "Cryptographic erase (Pure Drive Erase)"),
            ("zeroize", "Zeroize (Juniper)"),
            ("factory_reset", "Factory reset"),
            ("destroy", "Physical destruction"),
            ("delegated_vendor", "Delegated to vendor"),
            ("not_applicable", "Not applicable"),
        ],
        "decommissioning_requirements_choices": [
            # same default as sanitization_method_choices
        ],
    }
}
```

- Both keys are lists of `(value, label)` pairs. The list above is the default of both.
- A list in `PLUGINS_CONFIG` **replaces** the default list, it does not extend it.
- Values must be unique, non-empty strings of at most 50 characters, and labels non-empty strings.
  An invalid list stops NetBox at startup with an `ImproperlyConfigured` error that names the key
  and the value.

### Removing a value

Removing a value from a list never changes stored data:

- record and asset type pages, and their tables, show `<value> (not in configuration)` with a
  warning badge;
- the REST API returns `sanitization_method_configured` / `decommissioning_requirements_configured`
  as `false`, and the `*_configured=false` filters (UI, REST and GraphQL) find those objects;
- the edit form of an object that already has the value keeps it selectable, so other fields can
  still be changed; new records and other objects cannot select it;
- putting the value back in the list restores the normal display.

These fields deliberately have no `choices=` on the model and are not configurable through
`FIELD_CHOICES`: with model choices, `full_clean()` would reject a removed value on every save,
even when only another field changes, and `FIELD_CHOICES` cannot tell a removed value from an
invalid one.

## Last related device info

`Asset.last_related_info` keeps a description of the last Device (directly or through one of its
Modules) the asset was assigned to, so the register can still tell where an asset was installed
after the Device has been deleted. It is shown on the asset page and on the record page, and
exported with the records.

### Format

One `key: value` entry per line, keys always in this order; optional entries are omitted when empty.
The first `": "` separates key and value; values may contain colons (IPv6 addresses).

| Key | Required | Value |
| --- | --- | --- |
| `snapshot_date` | yes | When the snapshot was taken, ISO 8601 with the `TIME_ZONE` offset, whole seconds |
| `device` | yes | `<name> (id <pk>)`; `(unnamed)` for a Device without a name |
| `site` | yes | Site name |
| `location` | no | Location name |
| `rack` | no | `<rack>`, then ` (U <position>, <face>)` when the Device has a position |
| `role` | yes | Device role name |
| `device_type` | yes | Manufacturer and model |
| `device_serial` | no | Device serial |
| `primary_ip` | no | Primary IP address |
| `status` | yes | Device status label, always in English (`Active`), whatever the user's language |
| `tenant` | no | Tenant name |

Example:

```text
snapshot_date: 2026-10-20T09:00:48+02:00
device: sw-test-01 (id 3)
site: Test-Site
rack: R1 (U 12, front)
role: Access Switch
device_type: Test-Vendor Test-Switch-24
device_serial: SN-SW-TEST-01
primary_ip: 192.0.2.10/24
status: Active
tenant: Test-Tenant
```

### When it is updated

It is a snapshot, not a live copy: later changes to the Device (rack, IP, status) are not reflected
until one of these events.

| Event | Effect |
| --- | --- |
| The asset is assigned to a Device or Module (new asset or new assignment) | snapshot of that Device |
| The asset is saved with the same Device assignment and an empty field | snapshot of that Device |
| The asset is saved with the same Device assignment and a filled field | no change, even if written by hand |
| The asset leaves a Device or Module that still exists (for a Site, Location, Rack or nothing) | snapshot of the Device it leaves |
| The assigned Device is deleted | snapshot of the Device for every asset assigned to it or to one of its Modules |
| A Module is deleted on its own | snapshot of its Device for the assets assigned to the Module |
| The asset is saved while its Device no longer exists | no change |
| Site, Location or Rack assignments, `QuerySet.update()`, `loaddata` | no change |

When a Device is deleted, NetBox clears its primary IP before the Device itself is removed; the
snapshot still records the primary IP. When a **Module** is deleted on its own, and its Device's
primary IP was on one of the Module's interfaces, the Device really loses that IP: the snapshot
then has no `primary_ip`.

The bulk update on Device or Module deletion does **not** create change log entries for the assets:
the event is already in the change log as the deletion of the Device or Module.

The field can be edited by hand in the asset form; it is overwritten by the next event that writes
a snapshot.

## Upgrading: filling last_related_info for existing assets

Migration `0009` adds the field empty. To fill it for the assets that are already assigned to a
Device or Module, run once after `migrate`:

```bash
# standalone NetBox
python manage.py backfill_last_related_info --dry-run   # report only, writes nothing
python manage.py backfill_last_related_info

# netbox-docker
docker compose exec netbox /opt/netbox/netbox/manage.py backfill_last_related_info
```

- Only assets assigned to a Device or Module with an **empty** field are written. Filled fields
  (written by hand, or snapshots of deleted Devices) are never overwritten, so running the command
  again changes nothing.
- Assets assigned to a Device or Module that no longer exists (orphaned assignments) are skipped:
  there is nothing left to describe.
- `snapshot_date` is the time the command runs.
- At the end the command prints how many assets were updated, already filled and orphaned.
- Like the bulk update on deletion, it writes no change log entries; its summary is the trace.

Assets assigned only to a Site, Location or Rack keep an empty field.

## CSV import

The record import accepts, for each related object, a numeric ID column or a natural key column:

| ID column | Natural key column |
| --- | --- |
| `asset` | `asset_serial` |
| `technical_decommission_operator` | `technical_decommission_operator_name` |
| `sanitization_operator` | `sanitization_operator_name` |

- On creation exactly one asset column is required; on update (`id` column) the asset columns can be
  omitted, and changing the asset is rejected (V0).
- At most one column of each pair; a serial or name that matches more than one object is rejected.
- Other columns: `technical_decommission_date`, `sanitization_date`, `disposal_date` (YYYY-MM-DD),
  `sanitization_method` (a configured value), `disposal_document`, `description`, `comments`,
  `owner`, `tags`.

Example:

```csv
asset_serial,technical_decommission_date,technical_decommission_operator_name
SN-SW-TEST-01,2026-10-20,Mario Rossi
```

The asset import accepts `nis_relevant` and `last_related_info` columns, the asset type import a
`decommissioning_requirements` column.

## REST API and GraphQL

- `/api/plugins/inventory-monitor/decommissioning-records/`: list, create, update, delete. Nested
  asset and operators are brief objects; `sanitization_method_configured` is read-only. A second
  record for the same asset is rejected with a 400 error on `asset`.
- Asset: `last_related_info`, `nis_relevant` and the nested `decommissioning_record` (brief). The
  brief asset representation includes none of them.
- AssetType: `decommissioning_requirements` and the read-only
  `decommissioning_requirements_configured`.
- GraphQL: `inventory_monitor_decommissioning_record` and
  `inventory_monitor_decommissioning_record_list`, with filters on dates, operators, method,
  `sanitization_method_configured`, document and asset; on assets `nis_relevant` and
  `has_decommissioning_record`; on asset types `decommissioning_requirements` and
  `decommissioning_requirements_configured`.

## Permissions and search

- Records use the standard permissions `view`, `add`, `change` and `delete_decommissioningrecord`.
- A user who can view an asset but not decommissioning records sees only "Record present" or
  "No record" in the asset's panel, without details, links or buttons.
- The global search finds a record by the asset serial, the disposal document, the description and
  the comments. When an asset's serial changes, its record is reindexed.
