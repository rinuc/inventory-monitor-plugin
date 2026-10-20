# Task: Registro Dismissioni (NIS2)

Piano di implementazione di `docs/specs/decommissioning-record.md`, come checklist. Il numero tra
parentesi è il passo del piano in `docs/prompts/decommissioning-record-implementation.md` (§5).
Regole di aggiornamento: `CLAUDE.md`, sezione *Task tracking*.

## Stato

- **Task corrente**: T013 — verifica finale
- **CHECKPOINT 2** eseguito il 2026-10-20 da Claude in Chrome sull'harness su richiesta dell'utente
  (utenti `cp2-full`, `cp2-viewer`, `cp2-noregistry`): 14 passi e R6 riusciti; T017 e T018 (Q15)
  corretti e verificati sull'harness dopo la ricostruzione dell'immagine; ok dell'utente lo stesso giorno
- **Piano esteso il 2026-10-20**: R6 `Asset.nis_relevant` (specifica §2.5, Q11–Q14), richiesto
  dall'utente con un diagramma delle classi; aggiunti CHECKPOINT 3, T015, T016. Dallo stesso
  diagramma restano fuori piano, in attesa di decisione dell'utente: `Asset.technical_owner_group`
  (basta l'Owner standard di NetBox?), i valori `Kind` del Journal (configurazione dell'harness,
  `FIELD_CHOICES['extras.JournalEntry.kind+']`, non codice del plugin), `technical_decommission_operator`
  come testo invece di Contact
- **Ultimo task completato**: T012 — documentazione e versione `15.3.0`, commit (pending), 2026-10-20
- **Checkpoint raggiunti**: CHECKPOINT 1, CHECKPOINT 3, CHECKPOINT 2 (tutti 2026-10-20)
- **Problemi aperti** (fuori ambito, da aprire come issue separate; nessuno blocca il piano):
  - chiave `FIELD_CHOICES` documentata nel README per `lifecycle_status` senza effetto (D6);
  - `AssetBulkImportForm.save()` disassegna l'asset in un import di aggiornamento senza colonne
    `assigned_*_id` (Q7);
  - il `CLAUDE.md` dell'harness `netbox-docker` cita un `differenze.txt` che non esiste e descrive la
    guardia di `0001_initial_squashed` come modifica locale (ora è nel sorgente, T003);
  - `manage.py sqlmigrate inventory_monitor <n>` fallisce con `NodeNotFoundError`:
    `0001_initial_squashed` dipende da `('dcim', '0153_created_datetimefield')`, che in NetBox 4.7
    esiste solo dentro la squash `dcim/0131_squashed_0159`, e `sqlmigrate` costruisce il grafo con
    `replace_migrations=False`. `migrate` e `showmigrations` funzionano. Aggiramento: in
    `manage.py shell`, `MigrationLoader(connection).collect_sql([(nodo, backwards)])` (grafo con le
    squash). Trovato al CHECKPOINT 1.
  - `AssetSerializer` dichiara `type` e `order_contract` annidati senza `required=False`: un `POST`
    all'API che crea un asset senza tipo o contratto risponde 400, mentre modello e form li
    accettano vuoti. Preesistente, non legato a R6. Trovato in T016.
  - N+1 preesistente nelle liste API di Asset, RMA, AssetService ed ExternalInventory: ogni asset
    (anche annidato) serializza `assigned_object` (GFK) e `asset_numbers` con una query ciascuno.
    Corretto solo per la lista dei record (T010, §7.2 della specifica); per gli altri basterebbe
    `prefetch_related("assigned_object", "external_inventory_items")` (con prefisso `asset__` dove
    l'asset è annidato). Trovato in T010.
  - Q10 della specifica (aperta; il comportamento attuale è descritto in `docs/decommissioning-record.md`, T012): Module cancellato da solo con l'IP primario del Device sulle sue
    interfacce, l'istantanea non ha `primary_ip`. Trovato in T014.
- **Note per i task successivi**:
  - le fixture DCIM dei test di R1 stanno in `tests/dcim_fixtures.py` (`DcimFixturesMixin`, fuso
    `Europe/Rome` e `timezone.now()` fissati in `setUp`).
  - le scelte configurabili nei form usano `settings.get_choices_including()`; tabelle e filtri
    `*_configured` usano `helpers.ConfiguredChoiceColumn` e `helpers.filter_configured()`; i template
    usano i filtri `sanitization_method_display` / `decommissioning_requirements_display`
    (`templatetags/inventory_monitor.py`, su `helpers.render_configured_choice()`); il serializer
    usa `settings.is_configured()` per i booleani `*_configured`, riusato in GraphQL (T011); i filtri
    GraphQL `*_configured` usano `helpers.configured_q()`.
  - i test HTTP dell'API (`test_decommissioning_api.py`) usano `utilities.testing.APITestCase`; nei
    conteggi di query la prima richiesta di un token fa un `UPDATE` di `last_used` in più: il
    conteggio parte dopo una richiesta di riscaldamento.
  - i test HTTP delle viste usano `utilities.testing.TestCase` di NetBox: gli operatori si scelgono
    solo tra i Contact visibili all'utente, quindi servono `tenancy.view_contact` nei test che li
    impostano; la ricerca indicizza al commit, in un solo flush per transazione (vedi `SearchTest`).
  - buchi di test emersi al CHECKPOINT 1, da coprire nei task successivi: assenza di `ObjectChange`
    nel comando `backfill_last_related_info` (D12). Il vincolo 0:1 a livello di database è coperto
    da T010 (`test_one_record_per_asset_in_the_database`).

## Checklist

- [x] T001 Ambiente di sviluppo: `~/netbox-dev` (PostgreSQL 18, Valkey, NetBox 4.7.3, venv Python 3.12) e `dev/nb.sh` (passo 0) — requisiti: §3 prompt — test: — — commit `ee78ca0` — 2026-10-20
- [x] T002 Esclusione dei file Markdown da ruff, `ruff format --check` stabile tra versioni (passo 0) — requisiti: §3.3 prompt — test: — — commit `beeaa74` — 2026-10-20
- [x] T003 Guardia su database vuoto in `0001_initial_squashed` (passo 0) — requisiti: §3.4 prompt — test: tests/test_migrations.py — commit `d8970f6` — 2026-10-20
- [x] T004 Specifica, `CLAUDE.md`, D12, prompt versionato, domande aperte risolte (passo 1) — requisiti: §2.1 prompt — test: — — commit `14d8244`, `3a4a292`, `afb9798`, `de519c5` — 2026-10-20
- [x] T005 Configurazione R4, parte di base: chiavi in `default_settings`, helper in `settings.py`, controllo all'avvio (passo 2) — requisiti: R4 — test: tests/test_decommissioning_settings.py — commit `275ab02` — 2026-10-20
- [x] T006 Modelli e migrazione `0009`: `Asset.last_related_info`, `AssetType.decommissioning_requirements`, `DecommissioningRecord`, V0–V7, cascade e changelog, `EXCLUDED_MODELS` (passo 3) — requisiti: R2 (modello), R3 (modello, V0–V7), R5 (migrazione), D2, D3, D6, D7 — test: tests/test_decommissioning_record.py, tests/test_contacts.py — commit `b22bff6` — 2026-10-20
- [x] T007 `last_related_info`: calcolo al salvataggio (D10), `pre_delete` su Device e Module (D11), comando `backfill_last_related_info` (D12) (passo 4) — requisiti: R1, D5, D8, D10, D11, D12 — test: tests/test_last_related_info.py, tests/test_backfill_last_related_info.py — commit `83525a9` — 2026-10-20
- [x] CHECKPOINT 1 — schema della migrazione (`sqlmigrate inventory_monitor 0009`), `migrate` avanti e indietro, elenco dei test; attesa dell'ok prima dell'interfaccia (checkpoint A del prompt) — ok dell'utente — 2026-10-20
- [x] T008 Form, filtri, tabelle: AssetType (form, filtri, tabella, CSV), record (form, filtri, tabella, import), colonne e filtro `has_decommissioning_record` su Asset, campi nuovi in `AssetForm`/`AssetBulkImportForm` (passo 5) — requisiti: R2, R3, R4, D3, D4 — test: tests/test_asset_type_decommissioning.py, tests/test_decommissioning_views.py, tests/test_decommissioning_settings.py — commit `63ca4f1` — 2026-10-20
- [x] T009 Viste, URL, template, menu, ricerca: viste generiche, `decommissioningrecord.html`, pannelli in `asset.html`/`assettype.html`, badge, `navigation.py`, `search.py` (P6) (passo 6) — requisiti: R1 (pannello), R3, R4, D9 — test: tests/test_decommissioning_views.py, tests/test_decommissioning_record.py, tests/test_navigation.py — commit `19a44b5` — 2026-10-20
- [x] T010 API REST: serializer, viewset, router, campi su Asset e AssetType, `/api/schema/` (passo 7) — requisiti: R1, R2, R3, R4 — test: tests/test_decommissioning_api.py, tests/test_decommissioning_record.py; tolti i tre `mock.patch("core.signals.enqueue_event")` — commit `d161bd6` — 2026-10-20
- [x] T011 GraphQL: tipi, filtri, query, campi su Asset e AssetType (Q8) (passo 8) — requisiti: R1, R2, R3 — test: tests/test_decommissioning_graphql.py — commit `e60f757` — 2026-10-20
- [x] T014 Istantanea alla cancellazione del Device senza `primary_ip`: il Collector manda il `pre_delete`
  degli IPAddress in cascata (interfacce del Device) prima di quello del Device; `ipam.signals.clear_primary_ip`
  salva il Device con `primary_ip4=None` e `snapshot_assets_of_deleted_device` lo rilegge dal database, quindi
  sovrascrive l'istantanea precedente perdendo l'IP. Proposta: costruire l'istantanea dall'istanza in memoria
  passata a `pre_delete` (ha ancora `primary_ip4_id`; la riga IPAddress esiste fino alla fine dei `pre_delete`),
  numero di query costante. Trovato al CHECKPOINT 2, passo 9. Attuato: database per tutto, IP primari dall'istanza se
  azzerati nel database (il test esistente cancella un'istanza non aggiornata e vuole i valori del database) — requisiti: R1, D11 — test:
  tests/test_last_related_info.py — commit `49f1998` — 2026-10-20
- [x] CHECKPOINT 3 — approvazione dell'estensione R6 della specifica (§2.5) e risposta a Q11–Q14; attesa dell'ok prima del codice — ok dell'utente — 2026-10-20
- [x] T015 R6 modello e interfaccia: `Asset.nis_relevant`, `0009` rigenerata secondo Q11 (database di sviluppo, `test_netbox` e harness riportati a `0008` prima), form (`AssetForm`, filtro, bulk edit, import CSV), filtri (`nis_relevant` su Asset, `asset_nis_relevant` sui record), colonne (`AssetTable`, `DecommissioningRecordTable`), righe in `asset.html` e `decommissioningrecord.html`; colonna di default anche in `EnhancedAssetTable` — requisiti: R6, R5 — test: tests/test_nis_relevant.py — commit `d62235b` — 2026-10-20
- [x] T016 R6 API e GraphQL: `nis_relevant` in `AssetSerializer` (non in `brief`), campo sul tipo GraphQL, filtro `nis_relevant` in `InventoryMonitorAssetFilter`, `/api/schema/` — requisiti: R6 — test: tests/test_nis_relevant.py — commit `41624bb` — 2026-10-20
- [x] T017 Etichetta della ricerca globale per i record: il risultato mostra il campo trovato come
  `get_asset_serial_for_search` (nome del metodo indicizzato in `DecommissioningRecordIndex.fields`) invece di
  un'etichetta leggibile; NetBox usa il `verbose_name` del campo, che un metodo non ha. Trovato al CHECKPOINT 2,
  passo 12 (2026-10-20). Attuato: il seriale è indicizzato sotto il campo `asset` (etichetta *Asset*), metodo
  `get_asset_serial_for_search` tolto — requisiti: P6, D9 — test: tests/test_decommissioning_record.py (`SearchTest`) —
  commit `31338a5` — 2026-10-20
- [x] T018 Istantanea in inglese (Q15): `build_device_snapshot()` dentro `translation.override("en")`, così
  `status` (e ogni altra etichetta) non dipende dalla lingua di chi salva, cancella o esegue il backfill —
  requisiti: R1, D11, D12, Q15 — test: tests/test_last_related_info.py, tests/test_backfill_last_related_info.py
  (helper `DcimFixturesMixin.in_italian()` in tests/dcim_fixtures.py) — commit `ae0dc11` — 2026-10-20
- [x] CHECKPOINT 2 — prova manuale da browser con lo scenario in 14 passi (checkpoint B del prompt), più `nis_relevant` (scheda, form, colonna, filtro, bulk edit, CSV, API); attesa dell'ok — eseguito da Claude in Chrome sull'harness, T017 e T018 verificati dopo la ricostruzione dell'immagine — ok dell'utente — 2026-10-20
- [x] T012 Documentazione e versione: `docs/decommissioning-record.md` (incluso `nis_relevant`; sezione sul
  backfill di `last_related_info`: cos'è, quando eseguirlo cioè una volta dopo l'aggiornamento a `0009`, comando
  standalone e nell'harness Docker, `--dry-run`, riepilogo, campi pieni non sovrascritti, orfani saltati, nessun
  `ObjectChange`), README (incluse le chiavi R4), CHANGELOG `15.3.0` (incluso R6 e il backfill tra le note di aggiornamento), `version.py` (passo 9) — requisiti: R4, R5, R6, D1, D5, D6, D12 — test: — — commit (pending) — 2026-10-20
- [ ] T013 Verifica finale: suite su database di test ricreato, `makemigrations --check`, ruff, `migrate 0008` e ritorno, tabella requisito → test definitiva, `git log` (passo 10) — requisiti: §6 prompt — test: suite completa
