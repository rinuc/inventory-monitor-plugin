# Task: Registro Dismissioni (NIS2)

Piano di implementazione di `docs/specs/decommissioning-record.md`, come checklist. Il numero tra
parentesi è il passo del piano in `docs/prompts/decommissioning-record-implementation.md` (§5).
Regole di aggiornamento: `CLAUDE.md`, sezione *Task tracking*.

## Stato

- **Task corrente**: T006 — Modelli e migrazione (passo 3)
- **Ultimo task completato**: T005 — Configurazione R4, parte di base (passo 2), commit `275ab02`,
  2026-10-20
- **Checkpoint raggiunti**: nessuno
- **Problemi aperti** (fuori ambito, da aprire come issue separate; nessuno blocca il piano):
  - chiave `FIELD_CHOICES` documentata nel README per `lifecycle_status` senza effetto (D6);
  - `AssetBulkImportForm.save()` disassegna l'asset in un import di aggiornamento senza colonne
    `assigned_*_id` (Q7);
  - il `CLAUDE.md` dell'harness `netbox-docker` cita un `differenze.txt` che non esiste e descrive la
    guardia di `0001_initial_squashed` come modifica locale (ora è nel sorgente, T003).

## Checklist

- [x] T001 Ambiente di sviluppo: `~/netbox-dev` (PostgreSQL 18, Valkey, NetBox 4.7.3, venv Python 3.12) e `dev/nb.sh` (passo 0) — requisiti: §3 prompt — test: — — commit `ee78ca0` — 2026-10-20
- [x] T002 Esclusione dei file Markdown da ruff, `ruff format --check` stabile tra versioni (passo 0) — requisiti: §3.3 prompt — test: — — commit `beeaa74` — 2026-10-20
- [x] T003 Guardia su database vuoto in `0001_initial_squashed` (passo 0) — requisiti: §3.4 prompt — test: tests/test_migrations.py — commit `d8970f6` — 2026-10-20
- [x] T004 Specifica, `CLAUDE.md`, D12, prompt versionato, domande aperte risolte (passo 1) — requisiti: §2.1 prompt — test: — — commit `14d8244`, `3a4a292`, `afb9798`, `de519c5` — 2026-10-20
- [x] T005 Configurazione R4, parte di base: chiavi in `default_settings`, helper in `settings.py`, controllo all'avvio (passo 2) — requisiti: R4 — test: tests/test_decommissioning_settings.py — commit `275ab02` — 2026-10-20
- [ ] T006 Modelli e migrazione `0009`: `Asset.last_related_info`, `AssetType.decommissioning_requirements`, `DecommissioningRecord`, V0–V7, cascade e changelog, `EXCLUDED_MODELS` (passo 3) — requisiti: R2 (modello), R3 (modello, V0–V7), R5 (migrazione), D2, D3, D6, D7 — test: tests/test_decommissioning_record.py, tests/test_contacts.py
- [ ] T007 `last_related_info`: calcolo al salvataggio (D10), `pre_delete` su Device e Module (D11), comando `backfill_last_related_info` (D12) (passo 4) — requisiti: R1, D5, D8, D10, D11, D12 — test: tests/test_last_related_info.py, tests/test_backfill_last_related_info.py
- [ ] CHECKPOINT 1 — schema della migrazione (`sqlmigrate inventory_monitor 0009`), `migrate` avanti e indietro, elenco dei test; attesa dell'ok prima dell'interfaccia (checkpoint A del prompt)
- [ ] T008 Form, filtri, tabelle: AssetType (form, filtri, tabella, CSV), record (form, filtri, tabella, import), colonne e filtro `has_decommissioning_record` su Asset, campi nuovi in `AssetForm`/`AssetBulkImportForm` (passo 5) — requisiti: R2, R3, R4, D3, D4 — test: tests/test_asset_type_decommissioning.py, tests/test_decommissioning_views.py, tests/test_decommissioning_settings.py
- [ ] T009 Viste, URL, template, menu, ricerca: viste generiche, `decommissioningrecord.html`, pannelli in `asset.html`/`assettype.html`, badge, `navigation.py`, `search.py` (P6) (passo 6) — requisiti: R1 (pannello), R3, R4, D9 — test: tests/test_decommissioning_views.py, tests/test_decommissioning_record.py, tests/test_navigation.py
- [ ] T010 API REST: serializer, viewset, router, campi su Asset e AssetType, `/api/schema/` (passo 7) — requisiti: R1, R2, R3, R4 — test: tests/test_decommissioning_api.py
- [ ] T011 GraphQL: tipi, filtri, query, campi su Asset e AssetType (Q8) (passo 8) — requisiti: R1, R2, R3 — test: tests/test_decommissioning_graphql.py
- [ ] CHECKPOINT 2 — prova manuale da browser con lo scenario in 14 passi (checkpoint B del prompt); attesa dell'ok
- [ ] T012 Documentazione e versione: `docs/decommissioning-record.md`, README (incluse le chiavi R4), CHANGELOG `15.3.0`, `version.py` (passo 9) — requisiti: R4, R5, D1, D5, D6, D12 — test: —
- [ ] T013 Verifica finale: suite su database di test ricreato, `makemigrations --check`, ruff, `migrate 0008` e ritorno, tabella requisito → test definitiva, `git log` (passo 10) — requisiti: §6 prompt — test: suite completa
