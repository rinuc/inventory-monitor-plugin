# Specifica: Registro Dismissioni (NIS2)

Stato: **approvata** il 2026-10-20 (passo 1 del piano).
Fonte dei requisiti: `docs/prompts/decommissioning-record-implementation.md` (R1–R5, D1–D11).
Riferimenti al codice verificati sul ramo `feat/decommissioning-record` il 2026-10-20 (plugin
15.2.0, NetBox 4.7.3, Django 6.1.2).

Questa specifica fissa il *cosa* e il *come*; le scelte di progetto non coperte dai requisiti sono
marcate **P*n*** (proposte, approvate con la specifica) e le ambiguità che richiedevano una
risposta sono in [§Domande aperte](#domande-aperte) (tutte risolte).

---

## 1. Obiettivo

Per ogni apparato che esce dal controllo dell'organizzazione, il plugin deve permettere di
ricostruire il Registro Dismissioni richiesto dalle procedure NIS2 interne, esportando in CSV la
lista dei `DecommissioningRecord`.

| Colonna del registro | Campo | Colonna della tabella record |
| --- | --- | --- |
| Device | `asset.last_related_info` (+ `asset`) | `last_related_info` (opzionale), `asset` |
| S/N | `asset.serial` | `serial` |
| Data messa fuori linea | `technical_decommission_date` | idem |
| Operatore messa fuori linea | `technical_decommission_operator` | idem |
| Data cancellazione dati | `sanitization_date` (+ `sanitization_method`) | idem |
| Operatore cancellazione dati | `sanitization_operator` | idem |
| Data di smaltimento | `disposal_date` | idem |
| Riferimento certificato di smaltimento (RAEE) | `disposal_document` | idem |

Ditta e operatore dello smaltimento non si registrano (stanno nei documenti citati). I documenti
restano fuori da NetBox.

---

## 2. Modello dati

### 2.1 `Asset` (modifiche)

| Campo | Tipo | Note |
| --- | --- | --- |
| `last_related_info` | `TextField(blank=True, default="", verbose_name=_("Last related device info"))` | R1, §3 |

- `__init__` salva i valori persistiti necessari a riconoscere i cambiamenti, con il pattern di
  NetBox (`dcim/models/mixins.py`, `dcim/models/devices.py`: `self.__dict__.get(...)` dopo
  `super().__init__()`): `_original_assigned_object_type_id`, `_original_assigned_object_id`,
  `_original_serial`. Dopo `save()` gli originali vengono riallineati. Zero query aggiuntive.
- `clean()`: aggiunge **V6** (§4) dopo i controlli esistenti su `price`/`currency`.
- `save()`: nuovo override che calcola `last_related_info` (§3) e, se `serial` è cambiato e
  l'asset ha un record, reindicizza il record nella ricerca globale (P6).
- `delete()`: invariato. Le protezioni esistenti (contratto, inventario esterno, `RMA.asset`
  `PROTECT`) restano prioritarie sul CASCADE verso il record.

### 2.2 `AssetType` (modifiche)

| Campo | Tipo | Note |
| --- | --- | --- |
| `decommissioning_requirements` | `CharField(max_length=50, blank=True, default="", verbose_name=_("Decommissioning requirements"))` | R2, nessun `choices=` (D1) |

`clean()`: il valore, se non vuoto, deve essere tra quelli configurati, **salvo** che sia il valore
già salvato e non modificato (stesso schema di V4, con `_original_decommissioning_requirements`
salvato in `__init__`). Codice errore `not_configured`.

### 2.3 `DecommissioningRecord` (nuovo, `models/decommissioning_record.py`)

```python
class DecommissioningRecord(PrimaryModel):  # niente ContactsMixin (D2)
    objects = RestrictedQuerySet.as_manager()

    asset = models.OneToOneField(
        to="inventory_monitor.Asset", on_delete=models.CASCADE, related_name="decommissioning_record"
    )
    technical_decommission_date = models.DateField(null=True, blank=True)
    technical_decommission_operator = models.ForeignKey(
        to="tenancy.Contact", on_delete=models.PROTECT, null=True, blank=True,
        related_name="inventory_monitor_decommissions",  # D7
    )
    sanitization_date = models.DateField(null=True, blank=True)
    sanitization_method = models.CharField(max_length=50, blank=True, default="")  # D1: niente choices=
    sanitization_operator = models.ForeignKey(
        to="tenancy.Contact", on_delete=models.PROTECT, null=True, blank=True,
        related_name="inventory_monitor_sanitizations",  # D7
    )
    disposal_date = models.DateField(null=True, blank=True)
    disposal_document = models.TextField(blank=True, default="")
    tags = TaggableManager(
        through="extras.TaggedItem", related_name="inventory_monitor_decommissioning_records", blank=True
    )
```

- `Meta`: `ordering` (P1), `verbose_name = _("decommissioning record")`,
  `verbose_name_plural = _("decommissioning records")`, tre indici
  (`invmon_decom_tech_date_idx`, `invmon_decom_sanit_date_idx`, `invmon_decom_disp_date_idx`).
- `__str__`: `asset.str_no_pk()`; `get_absolute_url()`:
  `reverse("plugins:inventory_monitor:decommissioningrecord", args=[self.pk])`.
- `__init__`: salva `_original_asset_id` e `_original_sanitization_method` (V0, V4).
- `clean()`: V0–V5 (§4). Gli errori sono raccolti e sollevati insieme come `ValidationError` con
  dizionario per campo (P2), così il form mostra tutti i problemi in una volta.
- `PrimaryModel` fornisce `description`, `comments`, `owner`, changelog, journal, custom field,
  permessi standard `view/add/change/delete_decommissioningrecord`.
- Cancellare il record non tocca l'asset. Cancellare l'asset cancella il record (CASCADE): il
  Collector di Django invia `pre_delete` anche per il record e `core/signals.py::handle_deleted_object`
  registra un `ObjectChange` per entrambi.
- `PROTECT` sui Contact: un Contact usato come operatore non si può cancellare (tracciabilità).
- Helper per l'interfaccia: `is_sanitization_method_configured()`,
  `get_sanitization_method_display()` (etichetta configurata, oppure il valore grezzo).

**P1 — Ordinamento.** Più recenti in alto, record senza data tecnica in fondo:
`ordering = (models.F("technical_decommission_date").desc(nulls_last=True), "-pk")` (PostgreSQL
mette i `NULL` per primi in `DESC`, da qui `nulls_last`).

### 2.4 Migrazione

Una sola migrazione `0009_decommissioning_record.py`, generata con `dev/nb.sh migrations`, solo di
schema e reversibile: `AddField` su `Asset.last_related_info` e
`AssetType.decommissioning_requirements`, `CreateModel` di `DecommissioningRecord` con indici.
Nessuna `RunPython`: gli asset esistenti si popolano con il comando di gestione di §3.3 (D12),
da eseguire una volta dopo `migrate`.

---

## 3. `last_related_info` (R1)

### 3.1 Formato (contratto con chi legge l'export CSV)

Testo su più righe, una voce per riga, `chiave: valore`, separatore `": "` (la prima occorrenza
separa chiave e valore; i valori possono contenere `:`). Righe separate da `\n`, nessuna riga vuota,
nessun `\n` finale. Chiavi in inglese, **sempre in quest'ordine**; le voci facoltative si omettono
se vuote.

| # | Chiave | Obbligatoria | Valore |
| --- | --- | --- | --- |
| 1 | `snapshot_date` | sì | `timezone.localtime().replace(microsecond=0).isoformat()`, fuso `TIME_ZONE` (D8), es. `2026-10-19T10:15:00+02:00` |
| 2 | `device` | sì | `<device.name> (id <device.pk>)`; Device senza nome: vedi Q2 |
| 3 | `site` | sì | `device.site.name` |
| 4 | `location` | no | `device.location.name` |
| 5 | `rack` | no | `<rack.name>`, seguito da ` (U <position>, <face>)` se c'è la posizione, ` (U <position>)` se manca la faccia; `position` senza decimali se intera (`20`, `20.5`); `face` è il valore (`front`/`rear`) |
| 6 | `role` | sì | `device.role.name` |
| 7 | `device_type` | sì | `device.device_type.full_name` (`<manufacturer> <model>`) |
| 8 | `device_serial` | no | `device.serial` |
| 9 | `primary_ip` | no | `str(device.primary_ip.address)` (`Device.primary_ip` rispetta `PREFER_IPV4`) |
| 10 | `status` | sì | `device.get_status_display()` (etichetta, es. `Active`) |
| 11 | `tenant` | no | `device.tenant.name` |

Il formattatore è una funzione pura `build_device_snapshot(device) -> str` in
`inventory_monitor/models/asset.py` (o in un modulo `inventory_monitor/snapshot.py`, P3), testata
direttamente. Il Device va caricato con
`select_related("site", "location", "rack", "role", "device_type__manufacturer", "tenant",
"primary_ip4", "primary_ip6")`: una query.

È un'**istantanea**, non una sincronizzazione: se il Device cambia rack o IP dopo l'assegnazione, il
campo non si aggiorna finché non avviene uno degli eventi sotto.

### 3.2 Quando si aggiorna

Siano *prima* = (`_original_assigned_object_type_id`, `_original_assigned_object_id`) e *dopo* =
l'assegnazione corrente; "Device-like" = `dcim.Device` o `dcim.Module` (per il Module si usa
`module.device`).

| Evento | Effetto |
| --- | --- |
| `Asset.save()`, *dopo* è Device-like, assegnazione cambiata (incluso asset nuovo) | istantanea del Device di *dopo* |
| `Asset.save()`, *dopo* è Device-like, assegnazione invariata, campo vuoto | istantanea del Device di *dopo* |
| `Asset.save()`, *dopo* è Device-like, assegnazione invariata, campo pieno | nessuna modifica (anche se scritto a mano) |
| `Asset.save()`, *prima* Device-like ancora esistente, *dopo* non Device-like (nessuna, Site, Location, Rack) | istantanea **del Device uscente** (D10) |
| `Asset.save()`, *prima* Device-like che non esiste più (assegnazione orfana) | nessuna modifica |
| `Asset.save()`, da non Device-like a non Device-like | nessuna modifica |
| `pre_delete` su `dcim.Device` | aggiornamento in blocco di tutti gli asset assegnati al Device o a un suo Module |
| `pre_delete` su `dcim.Module` (cancellato da solo) | aggiornamento in blocco degli asset del Module con l'istantanea di `module.device` (D11) |
| `pre_delete` su `dcim.Module` in cascata da un Device | ignorato: se ne occupa il ricevitore del Device (P4) |
| `QuerySet.update()`, `save()` con `update_fields` senza i campi di assegnazione, `loaddata` (`raw=True`) | nessuna modifica |

Conseguenze esplicite:
- Site, Location e Rack non entrano mai nel campo come oggetto assegnato.
- La disassegnazione non svuota il campo.
- Con assegnazione Device-like invariata il campo **non si può svuotare**: al salvataggio verrebbe
  ricalcolato (regola "campo vuoto"). È voluto.
- Il campo è modificabile da form, API e CSV; un successivo cambio di Device lo sovrascrive. Un
  valore fornito insieme a un cambio di assegnazione Device-like (es. creazione via CSV con
  `assigned_device_id`) viene sovrascritto: vedi Q3.

**P3 — Dove sta la logica.** In `Asset.save()` tramite un helper privato
`_refresh_last_related_info()`; il formattatore in `inventory_monitor/snapshot.py` (funzione pura,
importata da `models/asset.py` e da `signals.py`, nessun import circolare).

**P4 — Ricevitori di segnale** (nuovo `inventory_monitor/signals.py`, importato in
`NetBoxInventoryMonitorConfig.ready()` dopo `super().ready()`; oggi `ready()` non è definito):
- `pre_delete` su `dcim.Device`: istantanea calcolata una volta (1 query), poi un solo
  `Asset.objects.filter(Q(assigned_object_type=<ct device>, assigned_object_id=device.pk) |
  Q(assigned_object_type=<ct module>, assigned_object_id__in=Module.objects.filter(device=device)
  .values("pk"))).update(last_related_info=...)` (sottoquery, 1 query). `ContentType` via
  `ContentType.objects.get_for_model()` (in cache).
- `pre_delete` su `dcim.Module`: se `origin` (argomento di `pre_delete` da Django 4.1) è un Device o
  un QuerySet di Device, esce; altrimenti istantanea di `module.device` e un `update()`.
  `BulkDeleteView` di NetBox chiama `obj.delete()` per oggetto, quindi `origin` è il Device anche
  nella cancellazione massiva.
- Numero di query costante rispetto al numero di asset, verificato con `assertNumQueries` (2 vs 5
  asset). Il Collector invia tutti i `pre_delete` prima di cancellare, quindi il Device esiste
  ancora quando il ricevitore del Module legge `module.device`.
- **Nessun `ObjectChange`** per gli asset aggiornati così (D5): l'evento è già nel changelog come
  cancellazione del Device/Module. Documentato in `docs/decommissioning-record.md`.

### 3.3 Riempimento iniziale (D12)

Comando di gestione `manage.py backfill_last_related_info`
(`inventory_monitor/management/commands/backfill_last_related_info.py`), da eseguire una volta dopo
la migrazione `0009` (nell'harness: `docker compose exec netbox /opt/netbox/netbox/manage.py
backfill_last_related_info`).

- Considera gli asset assegnati a un `dcim.Device` o a un `dcim.Module` con `last_related_info`
  vuoto. Per ognuno scrive l'istantanea (§3.1) del Device (per il Module: `module.device`).
- **Non sovrascrive** campi già pieni: è idempotente, rieseguirlo non cambia nulla e non tocca testi
  scritti a mano o istantanee di Device cancellati.
- Salta le assegnazioni orfane (Device/Module non più esistente) e le conta nel riepilogo.
- `--dry-run`: calcola e riporta i conteggi senza scrivere.
- Riepilogo finale: asset aggiornati, già valorizzati (saltati), orfani (saltati).
- Efficienza: Device e Module caricati in blocco (una query per tipo, con il `select_related` di
  §3.1), un'istantanea per Device (riusata dagli asset dello stesso Device e dei suoi Module),
  scrittura con `bulk_update(..., ["last_related_info"], batch_size=500)`. Le query crescono con il
  numero di lotti, non con il numero di asset.
- Usa lo stesso formattatore di §3.1; `snapshot_date` è l'ora di esecuzione del comando.
- Come per D5, **nessun `ObjectChange`** per gli asset aggiornati (scrittura in blocco); il
  riepilogo del comando è la traccia. Documentato in `docs/decommissioning-record.md`.
- Implementato nel passo 4, insieme al resto di R1.

### 3.4 Interazioni

- `RMA.update_asset_serial()` (non modificato) chiama `asset.save()` senza `full_clean()`:
  assegnazione invariata ⇒ nessun effetto se il campo è pieno, calcolo se è vuoto. Nessun errore.
- `AssetBulkImportForm.save()` (preesistente) imposta `assigned_object = None` se nessuna colonna
  `assigned_*_id` è presente: un import di aggiornamento con `id` ma senza colonne di assegnazione
  **disassegna** l'asset. Con D10 il campo viene rinfrescato col Device uscente. Comportamento
  preesistente, fuori ambito: vedi Q7.

---

## 4. Regole di validazione

Codici stabili in inglese (`ValidationError(..., code=...)`), messaggi con `gettext_lazy`. Errori
attaccati al campo indicato.

| Regola | Dove | Campo | Codice | Condizione di errore |
| --- | --- | --- | --- | --- |
| **V0** | `DecommissioningRecord.clean()` | `asset` | `asset_immutable` | record esistente (`pk` valorizzato) e `asset_id != _original_asset_id` |
| **V1** | idem | la data | `future_date` | una delle tre date `> timezone.localdate()` (D8) |
| **V2** | idem | la data successiva | `date_order` | `technical > sanitization`, `sanitization > disposal`, oppure `technical > disposal` (confronto solo tra date presenti; stesso giorno ammesso) |
| **V3** | idem | `sanitization_method` / `sanitization_date` | `sanitization_method_required` / `sanitization_date_required` | data senza metodo / metodo senza data |
| **V4** | idem | `sanitization_method` | `not_configured` | valore non vuoto, non configurato, e non (record esistente e valore == `_original_sanitization_method`) |
| **V5** | idem | `technical_decommission_date` / `disposal_date` | `asset_not_decommissioned` / `asset_not_disposed` | data tecnica presente e `asset.lifecycle_status ∉ {retired, disposed}`; data smaltimento presente e `asset.lifecycle_status != disposed` |
| **V6** | `Asset.clean()` | `lifecycle_status` | `disposed_asset` / `decommissioned_asset` | esiste un record con `disposal_date` e stato `!= disposed`; esiste un record con `technical_decommission_date` e stato `∉ {retired, disposed}` |
| **V7** | — | — | — | asset *Retired*/*Disposed* senza record: nessun blocco (test di non regressione) |

Dettagli:
- V6 legge il record con `DecommissioningRecord.objects.filter(asset_id=self.pk).values(
  "technical_decommission_date", "disposal_date").first()` solo se `self.pk` è valorizzato (asset
  nuovo ⇒ nessun record), evitando `RelatedObjectDoesNotExist` e la cache del reverse accessor che
  potrebbe essere stantia. Se valgono entrambe le condizioni si riporta `disposed_asset`.
- V5 e V6 usano `LifecycleStatusChoices.RETIRED/DISPOSED` (D6). Togliere quei valori via
  `FIELD_CHOICES` rende le regole insoddisfacibili: documentato.
- Per riattivare un asset si svuotano prima le date nel record, poi si cambia lo stato.
- Ordine operativo previsto: asset → *Retired* → record con data tecnica → asset → *Disposed* →
  `disposal_date` nel record.
- V6 vale per ogni canale che passa da `full_clean()`: `AssetForm`, `AssetBulkEditView`
  (`_update_objects()` chiama `full_clean()`), `AssetBulkImportForm`, API
  (`ValidatedModelSerializer`), script che chiamano `full_clean()`. **Non** vale per `save()`
  diretto né per `QuerySet.update()`: documentato come limite per gli script esterni.
- Unicità 0:1: garantita dal `OneToOneField`; `validate_unique()` di `full_clean()` produce l'errore
  sul campo `asset` per form, CSV e API.

**P2 — Errori aggregati.** `DecommissioningRecord.clean()` raccoglie gli errori in un dict e li
solleva insieme. `Asset.clean()` mantiene lo stile esistente (sollevamento al primo errore) e
aggiunge V6 in coda.

---

## 5. Configurazione (R4)

### 5.1 Chiavi

In `NetBoxInventoryMonitorConfig.default_settings`, sovrascrivibili in `PLUGINS_CONFIG`:

- `decommissioning_requirements_choices`
- `sanitization_method_choices`

Liste di coppie `(valore, etichetta)`; predefinito identico per entrambe:

```python
[
    ("clear", "Clear (overwrite / shred)"),
    ("purge", "Purge (ATA Secure Erase / NVMe Sanitize)"),
    ("crypto_erase", "Cryptographic erase (Pure Drive Erase)"),
    ("zeroize", "Zeroize (Juniper)"),
    ("factory_reset", "Factory reset"),
    ("destroy", "Physical destruction"),
    ("delegated_vendor", "Delegated to vendor"),
    ("not_applicable", "Not applicable"),
]
```

Una lista in `PLUGINS_CONFIG` **sostituisce** quella predefinita (NetBox completa `user_config`
per chiave, non estende le liste).

### 5.2 Helper in `settings.py`

- `get_decommissioning_requirements_choices()`, `get_sanitization_method_choices()` → lista di
  tuple; se la chiave manca da `PLUGINS_CONFIG` (es. `override_settings` nei test) usano il
  predefinito di `default_settings`.
- `is_configured(key, value) -> bool`, `choice_label(key, value) -> str` (etichetta, oppure il
  valore grezzo se non configurato).
- `validate_choice_settings(plugin_config)` → solleva `ImproperlyConfigured` con chiave e valore
  incriminato se una lista non è una sequenza di coppie, ha valori duplicati, vuoti, non stringa o
  più lunghi di 50 caratteri, o etichette non stringa/vuote. Chiamata da
  `NetBoxInventoryMonitorConfig.validate()` dopo `super().validate()` (che applica i predefiniti),
  quindi all'avvio di NetBox.

### 5.3 Perché niente `choices=` sul modello (D1)

Non per le migrazioni: NetBox (`utilities/migration.py`) esclude già `choices` dalla
`deconstruct()`. La ragione è che con `choices=` sul modello `full_clean()` rifiuterebbe un valore
tolto dalla configurazione a **ogni** salvataggio del record, anche per modificare un altro campo.
`FIELD_CHOICES` non si usa per questi campi perché non distingue i valori dismessi.

### 5.4 Valore tolto dalla configurazione

- Il dato salvato non si tocca (nessuna migrazione, nessun aggiornamento automatico).
- Scheda e tabella: `<valore> (not in configuration)` con badge `text-bg-warning`.
- API: `sanitization_method_configured` / `decommissioning_requirements_configured` (booleani, sola
  lettura).
- Form di modifica: il valore dismesso è aggiunto alle scelte solo se è il valore dell'istanza.
  Form di creazione e altri record: non selezionabile.
- Filtri `sanitization_method_configured` / `decommissioning_requirements_configured` (booleani) in
  UI e API; in GraphQL vedi Q6.
- Se il valore torna in configurazione, tutto torna normale (nessuno stato salvato).
- Il filtro a scelta multipla `sanitization_method` / `decommissioning_requirements` offre solo i
  valori configurati (come `currency` in `AssetFilterSet.__init__`).

---

## 6. Interfaccia

### 6.1 Scheda Asset (`templates/inventory_monitor/asset.html`)

- Pannello **Last related device info**: `<pre>` con `last_related_info`; "—" se vuoto.
- Pannello **Decommissioning (NIS2)**:

| Condizione | Contenuto |
| --- | --- |
| senza `view_decommissioningrecord` | solo "Record present" / "No record" (D9) |
| con permesso, nessun record, con `add_decommissioningrecord` | pulsante *Add decommissioning record* → `decommissioningrecord_add?asset=<pk>&return_url=<url asset>` |
| con permesso, nessun record, senza `add_` | "No record" |
| con permesso e record | tre date, metodo (badge se non configurato), operatori, documento, link al record; *Edit*/*Delete* secondo `change_`/`delete_` |

Per la presenza del record senza permesso di vista basta `hasattr`/query sull'asset: non si
espongono campi. I pulsanti usano i permessi di modello (non per oggetto), come gli altri pannelli
del plugin (P5).

### 6.2 Scheda `AssetType` (`assettype.html`)

Riga *Decommissioning requirements* con etichetta configurata, badge se non configurato.

### 6.3 Record (`decommissioningrecord.html`)

Estende `generic/object.html`: asset (link), seriale, tipo, *Decommissioning requirements* del tipo
(promemoria), le tre date, metodo con badge, operatori (link), documento, `last_related_info` in
`<pre>`, poi i pannelli standard (tag, commenti, custom field, journal).

### 6.4 Viste e URL (pattern di `views/rma.py`)

`DecommissioningRecordView`, `...ListView`, `...EditView`, `...DeleteView`, `...BulkEditView`,
`...BulkDeleteView`, `...BulkImportView`, registrate con `@register_model_view` ed esportate in
`views/__init__.py`. `urls.py`: prefisso `decommissioning-records/` (con e senza `<int:pk>/`).
La creazione precompila `asset` da `?asset=<pk>` tramite l'`initial` di `ObjectEditView`.
`queryset` della lista e del dettaglio con
`select_related("asset", "asset__type", "technical_decommission_operator", "sanitization_operator",
"owner__group")`.

### 6.5 Form (`forms/decommissioning_record.py`)

- `DecommissioningRecordForm(PrimaryModelForm)`:
  - `asset`: `DynamicModelChoiceField(queryset=Asset.objects.all(), selector=True,
    query_params={"has_decommissioning_record": "false"})` in creazione; in modifica
    `disabled=True` (mostra l'asset corrente; Django ignora i dati inviati per un campo disabilitato,
    V0 resta come difesa per CSV/API). Nota: la tendina filtra gli asset senza record, ma l'asset
    precompilato da `?asset=` resta valido anche se la tendina non lo elencherebbe.
  - date con `DatePicker()`; operatori `DynamicModelChoiceField(queryset=Contact.objects.all(),
    required=False)`; `sanitization_method` `ChoiceField` con `add_blank_choice(...)` dalle scelte
    configurate (+ valore dell'istanza se dismesso); promemoria `asset.type.decommissioning_requirements`
    come help text del campo `sanitization_method` quando l'asset è noto (istanza o `initial`).
  - fieldsets: *Asset*, *Technical decommission*, *Sanitization*, *Disposal*, *Misc* (tag),
    più `description`/`comments`/`owner` come in `RMAForm`.
- `DecommissioningRecordFilterForm(PrimaryModelFilterSetForm)` (senza `ContactModelFilterForm`, D2).
- `DecommissioningRecordBulkEditForm(PrimaryModelBulkEditForm)`: date, operatori, metodo,
  documento, descrizione, commenti; **niente `asset`** (D3); `nullable_fields` per date, operatori,
  metodo e documento.
- `DecommissioningRecordBulkImportForm(PrimaryModelImportForm)` (D4): colonne `asset` /
  `asset_serial`, `technical_decommission_operator` / `technical_decommission_operator_name`,
  `sanitization_operator` / `sanitization_operator_name`, tutte `CSVModelChoiceField`
  (`to_field_name` = `pk`, `serial`, `name`). `clean()`: in creazione esattamente una colonna asset;
  in aggiornamento (`id`) nessuna o una (se presente e diversa ⇒ V0); per ogni operatore al più una.
  Ambiguità di seriale/nome segnalata da `CSVModelChoiceField`.

### 6.6 Filtri (`filtersets/decommissioning_record.py`)

`DecommissioningRecordFilterSet(PrimaryModelFilterSet)`: `asset_id`, `serial`
(`asset__serial`), `technical_decommission_date`, `sanitization_date`,
`disposal_date` con `__gte/__lte` (via `fields` + lookup automatici di NetBox),
`sanitization_method` (scelta multipla dalla configurazione),
`sanitization_method_configured` (booleano), `technical_decommission_operator_id`,
`sanitization_operator_id`, `q` (seriale, partnumber dell'asset, documento, descrizione).
`serial` filtra per uguaglianza esatta su `asset__serial` (multivalore, come i filtri `serial`
esistenti); la ricerca parziale passa da `q`.

Su `AssetFilterSet`: `has_decommissioning_record` (booleano, pattern di
`filter_has_external_inventory_items`). Su `AssetTypeFilterSet`: `decommissioning_requirements`
(scelta multipla) e `decommissioning_requirements_configured`.

### 6.7 Tabelle

- `DecommissioningRecordTable(PrimaryModelTable)`: `asset` (link), `serial`, `asset_type`, tre date,
  `sanitization_method` (template con badge), operatori (link), `disposal_document`,
  `last_related_info` (opzionale, `asset.last_related_info`). `default_columns`: `asset`, `serial`,
  date, `sanitization_method`, operatori, `disposal_document`.
- `AssetTable`: colonne opzionali `decommissioning_record` (sì/no con link),
  `technical_decommission_date`, `sanitization_date`, `disposal_date` (accessor
  `decommissioning_record__...`), non in `default_columns`. `select_related("decommissioning_record")`
  in `AssetListView.queryset` e `AssetViewSet.queryset`. Le viste figlie di `template_content.py` che
  usano `EnhancedAssetTable` non le mostrano di default.
- `AssetTypeTable`: colonna opzionale `decommissioning_requirements` (badge se non configurato).

### 6.8 Menu e ricerca

- `navigation.py`, gruppo `"Assets"`: voce *Decommissioning Records* con pulsanti *Add* e *Import*.
- `search.py`: `DecommissioningRecordIndex` con `disposal_document`, `description`, `comments` e
  `get_asset_serial_for_search` (metodo del modello, come `AssetIndex`); `display_attrs` con asset e
  date.

**P5 — Permessi dei pulsanti** a livello di modello (`perms.inventory_monitor.change_...`), come il
resto del plugin; i permessi con vincoli per oggetto restano applicati dalle viste generiche.

**P6 — Reindicizzazione.** Se `Asset.serial` cambia e l'asset ha un record, `Asset.save()` chiama
`search_backend.cache(record)` (`netbox.search.backends`), così la ricerca per seriale resta
corretta. Una query in più solo quando il seriale cambia.

---

## 7. API REST e GraphQL

### 7.1 Serializer

- `DecommissioningRecordSerializer(PrimaryModelSerializer)`: `url`, `asset =
  AssetSerializer(nested=True)`, operatori `ContactSerializer(nested=True, required=False,
  allow_null=True)` di `tenancy.api.serializers`, `sanitization_method_configured`
  (`SerializerMethodField`, `BooleanField`), `fields` completo; `brief_fields = ("id", "url",
  "display", "technical_decommission_date", "sanitization_date", "disposal_date")` (**senza
  `asset`**). Validazione delle scelte di `sanitization_method` in `validate_sanitization_method()`
  (stesso criterio di V4, con il valore dell'istanza ammesso).
- `AssetSerializer`: aggiunge `last_related_info` (lettura/scrittura) e `decommissioning_record`
  in sola lettura.
- **Riferimento circolare (proposta):** stesso schema già usato da `ContractSerializer.get_fields()`
  per `parent`. `AssetSerializer.get_fields()` aggiunge
  `fields["decommissioning_record"] = DecommissioningRecordSerializer(nested=True, read_only=True,
  allow_null=True)`, risolto a runtime quando entrambe le classi esistono. La versione annidata usa
  i `brief_fields` (senza `asset`), quindi non c'è ricorsione. DRF restituisce `null` quando il
  reverse one-to-one manca (`ObjectDoesNotExist` gestito in `get_attribute`). Verifica: test che
  genera `/api/schema/` senza errori.
- `AssetTypeSerializer`: `decommissioning_requirements` e `decommissioning_requirements_configured`.
- `AssetViewSet.queryset`: `select_related("decommissioning_record")`.

### 7.2 ViewSet e router

`DecommissioningRecordViewSet(NetBoxModelViewSet)` con il `queryset` di §6.4,
`router.register("decommissioning-records", ...)`.

### 7.3 GraphQL

- `InventoryMonitorDecommissioningRecordType(PrimaryObjectType)` (`fields="__all__"`), `asset` e
  operatori con `Annotated[..., strawberry.lazy(...)]`.
- `InventoryMonitorDecommissioningRecordFilter(OwnerFilterMixin, PrimaryModelFilter)` con filtri per
  le date, `sanitization_method`, operatori.
- Query `inventory_monitor_decommissioning_record` e `inventory_monitor_decommissioning_record_list`
  in `graphql/schema.py`, aggiunte a `schema` in `graphql/__init__.py`.
- `InventoryMonitorAssetType`: `last_related_info: str`, `decommissioning_record:
  Annotated[...] | None`. `InventoryMonitorAssetTypeType`: `decommissioning_requirements: str`.

---

## 8. File da toccare

| File | Passo | Modifica |
| --- | --- | --- |
| `inventory_monitor/__init__.py` | 2, 4 | `default_settings`, `validate()`, `ready()` |
| `inventory_monitor/settings.py` | 2 | helper §5.2 |
| `inventory_monitor/models/asset.py` | 3, 4 | campo, `__init__`, `clean()` V6, `save()` |
| `inventory_monitor/models/asset_type.py` | 3 | campo, `clean()` |
| `inventory_monitor/models/decommissioning_record.py` | 3 | nuovo |
| `inventory_monitor/models/__init__.py` | 3 | export |
| `inventory_monitor/migrations/0009_decommissioning_record.py` | 3 | nuova (unica) |
| `inventory_monitor/snapshot.py` | 4 | nuovo, formattatore |
| `inventory_monitor/signals.py` | 4 | nuovo, `pre_delete` Device/Module |
| `inventory_monitor/management/__init__.py`, `management/commands/__init__.py`, `management/commands/backfill_last_related_info.py` | 4 | nuovo, D12 |
| `inventory_monitor/forms/decommissioning_record.py`, `forms/__init__.py` | 5 | nuovo |
| `inventory_monitor/forms/asset.py` | 5 | `last_related_info` in `AssetForm`, `AssetBulkImportForm`, filtro `has_decommissioning_record` |
| `inventory_monitor/forms/asset_type.py` | 5 | campo in form, bulk edit, filtro, import |
| `inventory_monitor/filtersets/decommissioning_record.py`, `filtersets/__init__.py` | 5 | nuovo |
| `inventory_monitor/filtersets/asset.py`, `filtersets/asset_type.py` | 5 | filtri nuovi |
| `inventory_monitor/tables/decommissioning_record.py`, `tables/__init__.py` | 5 | nuovo |
| `inventory_monitor/tables/asset.py`, `tables/asset_type.py` | 5 | colonne opzionali |
| `inventory_monitor/views/decommissioning_record.py`, `views/__init__.py` | 6 | nuovo |
| `inventory_monitor/views/asset.py` | 6 | `select_related` |
| `inventory_monitor/urls.py`, `navigation.py`, `search.py` | 6 | voci nuove |
| `inventory_monitor/templates/inventory_monitor/decommissioningrecord.html` | 6 | nuovo |
| `inventory_monitor/templates/inventory_monitor/asset.html`, `assettype.html` | 6 | pannelli/righe |
| `inventory_monitor/api/serializers.py`, `api/views.py`, `api/urls.py` | 7 | §7 |
| `inventory_monitor/graphql/types.py`, `filters.py`, `schema.py`, `__init__.py` | 8 | §7.3 |
| `inventory_monitor/tests/test_contacts.py` | 3 | `DecommissioningRecord` in `EXCLUDED_MODELS` con commento (D2) |
| `docs/decommissioning-record.md`, `README.md`, `CHANGELOG.md`, `inventory_monitor/version.py` | 9 | R5 |

Nessuna dipendenza nuova. `RMA.update_asset_serial()` e gli script GARR non si toccano.

---

## 9. Requisito → test

Nomi indicativi; la tabella definitiva con i nomi reali sarà aggiornata nella verifica finale.

| Requisito / regola | File di test | Test |
| --- | --- | --- |
| §3.4 prompt (0001 su DB vuoto) | `test_migrations.py` | `SquashedInitialMigrationEmptyDatabaseTest` (già presente) |
| R4 predefiniti / override | `test_decommissioning_settings.py` | `test_defaults`, `test_override_replaces_list` |
| R4 config invalida | idem | `test_invalid_*` (duplicati, vuoti, > 50, non coppie, etichetta) |
| R4 valore dismesso | idem | preservato al salvataggio, badge, `_configured=false` API/filtro, form istanza sì / nuovo no, ritorno in config |
| R1 formato | `test_last_related_info.py` | `test_snapshot_format_full`, `test_snapshot_optional_lines_omitted` |
| R1 Device / Module | idem | `test_assign_device`, `test_assign_module_uses_device` |
| R1 non-Device | idem | `test_site_location_rack_never_written` |
| R1 invariato / manuale | idem | `test_unchanged_assignment_keeps_value` |
| R1 cambio Device | idem | `test_device_change_overwrites` |
| D10 | idem | `test_leaving_device_refreshes_outgoing_snapshot` |
| R1 cancellazione Device, N+1 | idem | `test_device_delete_updates_assets_constant_queries` (2 vs 5) |
| R1 dopo cancellazione | idem | `test_orphan_keeps_last_related_info` |
| D11 | idem | `test_module_delete_updates_assets_constant_queries` |
| D12 | `test_backfill_last_related_info.py` | popola Device e Module, non tocca campi pieni né non-Device, salta orfani, idempotente, `--dry-run` non scrive, riepilogo, query costanti (2 vs 5 asset) |
| R1 + RMA | idem | `test_rma_update_asset_serial` |
| R2 | `test_asset_type_decommissioning.py` | form/CSV/API accettano/rifiutano, valore dismesso preservato, filtri, colonna |
| R3 modello, cascata | `test_decommissioning_record.py` | `test_delete_record_keeps_asset`, `test_delete_asset_cascades_with_two_objectchanges`, `test_contact_protect` |
| V0 | idem + views + api | form, CSV con `id`, API `PATCH` → `asset_immutable` |
| V1 | idem | futuro rifiutato, oggi accettato (fuso `Europe/Rome`) |
| V2 | idem | ordine errato rifiutato per ogni coppia, stesso giorno ammesso |
| V3 | idem | data senza metodo, metodo senza data |
| V4 | idem | non configurato rifiutato, dismesso invariato ammesso |
| V5 | idem | data tecnica con *In Use*, smaltimento con *Retired* rifiutati |
| V6 | idem + views + api | `full_clean()`, `AssetForm`, bulk edit POST, CSV con `id`, API `PATCH` → 400 |
| V7 | idem | *Retired*/*Disposed* senza record salvabile in qualsiasi stato |
| 0:1 | views + api | secondo record rifiutato da form e API |
| D2 | `test_contacts.py` | `EXCLUDED_MODELS` |
| D4 | `test_decommissioning_views.py` | import per ID, seriale univoco, seriale ambiguo, nome, nome ambiguo, ID+seriale |
| D7 | `test_decommissioning_record.py` | reverse accessor sui Contact |
| D9 | `test_decommissioning_views.py` | pannello senza `view_decommissioningrecord` |
| Viste | idem | lista, dettaglio, add con `?asset=`, edit con asset bloccato, delete, bulk edit, bulk delete |
| Filtri | idem / api | uno per filtro, `has_decommissioning_record=false` |
| Ricerca | `test_decommissioning_record.py` | per documento, per seriale, dopo cambio seriale (P6) |
| Menu | `test_navigation.py` | esistente |
| API | `test_decommissioning_api.py` | CRUD, `brief`, annidato su Asset, `last_related_info`, `/api/schema/` |
| GraphQL | `test_decommissioning_graphql.py` | query singola, lista, `decommissioning_record` su asset |
| N+1 | views + api | lista record UI/API, lista asset con colonne nuove: 2 vs 5 |
| R5 | — | `makemigrations --check`, `migrate 0008` e ritorno (riepilogo) |

---

## §Decisioni

Approvate dall'utente il 2026-10-20 (dal prompt, §9). Non si riaprono.

- **D1 — Scelte da configurazione, non `choices=` sul modello.** NetBox esclude già `choices` dalla
  `deconstruct()`; la ragione è che `full_clean()` rifiuterebbe un valore dismesso a ogni
  salvataggio. Scelte applicate a runtime; `FIELD_CHOICES` non si usa per questi campi.
- **D2 — Niente `ContactsMixin` sul record.** Operatori = due FK esplicite;
  `DecommissioningRecord` in `EXCLUDED_MODELS` di `tests/test_contacts.py` con commento.
- **D3 — `asset` immutabile dopo la creazione.** Tendina con
  `query_params={"has_decommissioning_record": "false"}` in creazione, campo disabilitato in
  modifica, assente dal bulk edit; V0 (`asset_immutable`) nel modello.
- **D4 — Import CSV con colonne distinte** `asset`/`asset_serial`,
  `technical_decommission_operator`/`..._name`, `sanitization_operator`/`..._name`, tutte
  `CSVModelChoiceField`; asset: esattamente una (in creazione); operatori: al più una ciascuno.
- **D5 — Nessun `ObjectChange`** per l'aggiornamento in blocco di `last_related_info`; documentato.
- **D6 — V5/V6 legati a `retired`/`disposed`.** Usano `LifecycleStatusChoices.RETIRED/DISPOSED`;
  togliere quei valori via `FIELD_CHOICES` rende le regole insoddisfacibili (documentato).
  Difetto preesistente, **non** corretto qui (issue separata): la chiave `FIELD_CHOICES` del
  README (`inventory_monitor.Asset.lifecycle_status`) non ha effetto; quella effettiva è
  `inventory_monitor.inventory_monitor.asset.lifecycle_status` (`ChoiceSetMeta` antepone il primo
  segmento del modulo a `key`).
- **D7 — `related_name`**: `inventory_monitor_decommissions`, `inventory_monitor_sanitizations`.
- **D8 — Fuso orario.** V1 con `timezone.localdate()`; `snapshot_date` con
  `timezone.localtime().replace(microsecond=0).isoformat()`.
- **D9 — Pannello senza permesso di vista**: solo "record presente" / "nessun record".
- **D10 — Istantanea del Device uscente** quando si lascia un Device/Module ancora esistente per
  un'assegnazione non Device/Module; Site/Location/Rack mai nel campo; la disassegnazione non lo
  svuota.
- **D11 — Cancellazione di un solo Module**: `pre_delete` su `dcim.Module`, aggiornamento in blocco
  con l'istantanea del suo Device, query costanti.
- **D12 — Riempimento iniziale** (deciso il 2026-10-20, era Q1): comando di gestione
  `backfill_last_related_info` che popola `last_related_info` per gli asset esistenti assegnati a un
  Device/Module, solo dove il campo è vuoto (§3.3). La migrazione `0009` resta solo di schema.

---

## §Domande aperte

**Tutte risolte il 2026-10-20**: Q1 è diventata D12; Q2–Q9 approvate con la raccomandazione, che
vale come decisione. Il testo resta qui per la motivazione.

- ~~Q1~~ — risolta: vedi D12.
- **Q2 — Device senza nome.** In NetBox `Device.name` può essere nullo. *Raccomandazione*:
  `device: (unnamed) (id 123)`.
- **Q3 — `last_related_info` fornito insieme a un cambio di assegnazione Device-like** (es.
  creazione via CSV/API con `assigned_device_id` e un testo storico). La regola del prompt lo
  sovrascrive. *Raccomandazione*: sovrascrivere sempre (il campo descrive l'ultimo Device reale);
  per caricare dati storici si importa prima senza assegnazione, oppure si assegna e poi si corregge
  il testo in un secondo salvataggio.
- **Q4 — `not_applicable` e V3.** Con metodo `not_applicable` (apparato senza memoria) V3 impone
  comunque una `sanitization_date`, e viceversa. *Raccomandazione*: mantenere V3 senza eccezioni
  (la data registra quando si è valutato che la sanificazione non serviva; regola più semplice,
  valida anche se l'etichetta viene rinominata).
- **Q5 — Lista di scelte vuota.** `sanitization_method_choices = []` rende impossibile registrare
  una `sanitization_date` (V3 + V4). *Raccomandazione*: `ImproperlyConfigured` per
  `sanitization_method_choices` vuota; ammessa vuota per `decommissioning_requirements_choices`
  (il campo resta solo vuoto).
- **Q6 — Visibilità dei dati del record fuori dal pannello (D9).** D9 copre il pannello della
  scheda. Le colonne opzionali della tabella Asset, il campo `decommissioning_record` annidato
  nell'API Asset e quello GraphQL mostrerebbero date del record a chi ha `view_asset` ma non
  `view_decommissioningrecord`. NetBox di norma non filtra per permesso gli oggetti annidati in
  forma *brief*. *Raccomandazione*: seguire la convenzione di NetBox (nessun filtro per permesso su
  annidati e colonne), documentarlo; il dettaglio completo (operatori, metodo, documento) resta
  visibile solo con `view_decommissioningrecord` (lista, dettaglio, API del record). In alternativa
  le colonne/annidati mostrano solo la presenza del record senza permesso (più codice, più test).
- **Q7 — Import CSV di aggiornamento Asset senza colonne di assegnazione** (preesistente):
  `AssetBulkImportForm.save()` disassegna l'asset. Con D10 il campo viene rinfrescato col Device
  uscente, ma l'asset perde l'assegnazione. *Raccomandazione*: fuori ambito, non correggere ora;
  segnalarlo come issue separata.
- **Q8 — Filtro GraphQL `*_configured`.** Il filtro dipende dalla configurazione a runtime; nel
  `filter_type` di strawberry-django serve un metodo filtro personalizzato. *Raccomandazione*:
  includerlo se il pattern dei filtri custom in `graphql/filter_mixins.py` lo permette senza
  forzature, altrimenti solo UI/API (il prompt dice "dove possibile").
- **Q9 — Lingua dei documenti.** Questa specifica è in italiano; `CLAUDE.md`,
  `docs/decommissioning-record.md`, README e CHANGELOG in inglese come il resto del repository.
  *Raccomandazione*: così.
