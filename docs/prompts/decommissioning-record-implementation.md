# Prompt: Registro Dismissioni (NIS2) nel plugin `inventory_monitor`

Questo prompt è pensato per una sessione di Claude Code che non ha visto la conversazione in cui è
stato scritto. Leggilo tutto prima di agire. I riferimenti a file, classi e righe sono stati
verificati sul ramo `feat/decommissioning-record` (HEAD `893dfef`, identico a `upstream/main`) il
2026-10-19 e riverificati il 2026-10-20 (sorgente del plugin e sorgente di NetBox 4.7.3 nel
container `netbox-docker-netbox-1`). Se qualcosa non corrisponde più, fidati del codice e
segnalalo.

---

## 1. Contesto

### 1.1 Il plugin

Il repository è un fork (`origin` = `rinuc/inventory-monitor-plugin`, `upstream` =
`CESNET/inventory-monitor-plugin`) del plugin NetBox **`inventory_monitor`**: gestione di asset
hardware, tipi di asset, contratti, fatture, servizi, RMA, inventario esterno e "probe" SNMP.

- Versione del plugin: **15.2.0** (`inventory_monitor/version.py`).
- NetBox richiesto: **`min_version = "4.7.0"`, `max_version = "4.7.99"`**
  (`inventory_monitor/__init__.py`). L'ambiente Docker di riferimento usa NetBox **4.7.3**.
- Python: `pyproject.toml` richiede `>=3.12,<3.15`. L'immagine Docker usa Python 3.14.
- Lint: **ruff** con `line-length = 120`, regole `E`, `F`, `W` (`pyproject.toml`). Comandi:
  `ruff check . && ruff format --check .` dalla radice del plugin.
- Test: `inventory_monitor/tests/`, test Django (`django.test.TestCase`) eseguiti con il test
  runner di NetBox (`manage.py test inventory_monitor`). Non c'è CI che esegua i test (in
  `.github/workflows/` c'è solo `release.yml`).
- Nel repository non c'è un `CLAUDE.md` (il `CLAUDE.md` di `netbox-docker`, due livelli sopra, ne
  cita uno che non esiste ancora).

### 1.2 Perché: NIS2

GARR usa il plugin come inventario autoritativo dell'hardware. Le procedure NIS2 interne chiedono,
per ogni apparato che esce dal controllo dell'organizzazione, un **Registro Dismissioni** con
queste colonne:

| Colonna del registro | Campo previsto |
| --- | --- |
| Device | `asset` (+ `asset.last_related_info` per il nome del Device) |
| S/N | `asset.serial` |
| Data messa fuori linea | `technical_decommission_date` |
| Operatore messa fuori linea | `technical_decommission_operator` |
| Data cancellazione dati (zeroize/sanificazione) | `sanitization_date` (+ `sanitization_method`) |
| Operatore cancellazione dati | `sanitization_operator` |
| Data di smaltimento | `disposal_date` |
| Riferimento certificato di smaltimento (RAEE) | `disposal_document` |

Questi eventi avvengono **al più una volta per asset**, quindi stanno in un'entità dedicata
`DecommissioningRecord`, in relazione 0:1 con `Asset`. I documenti (certificati RAEE, delibere del
CdA) restano fuori da NetBox: NetBox ne conserva solo un riferimento testuale. Ditta di
smaltimento e operatore dello smaltimento **non** si registrano: stanno nei documenti citati.

Script esterni al plugin (NetBox Custom Scripts di GARR) sincronizzano gli asset con DCIM e salvano
gli asset con `full_clean()`. Oggi possono riportare *In Use* un asset già dismesso se il suo
seriale è ancora in DCIM. Le regole V5 e V6 (sotto) servono a impedirlo.

### 1.3 Cosa c'è già nel codice (verificato)

**`inventory_monitor/models/asset.py`**
- `ASSIGNED_OBJECT_MODELS_QUERY`: `Q(app_label="dcim", model__in=("site", "location", "rack",
  "device", "module"))`.
- `LifecycleStatusChoices(ChoiceSet)`, `key = "inventory_monitor.asset.lifecycle_status"`,
  valori `new`, `in_stock`, `in_use`, `in_maintenance`, `retired`, `disposed`.
  `AssignmentStatusChoices` analoga.
- `class Asset(ContactsMixin, PrimaryModel, DateStatusMixin, ImageAttachmentsMixin)`, manager
  `RestrictedQuerySet.as_manager()`.
  - Assegnazione GFK: `assigned_object_type` (FK `contenttypes.ContentType`, `PROTECT`,
    `limit_choices_to=ASSIGNED_OBJECT_MODELS_QUERY`), `assigned_object_id`
    (`PositiveBigIntegerField`), `assigned_object = GenericForeignKey(...)`. Non esiste una
    `GenericRelation` dal lato DCIM: cancellare un Device lascia l'asset con
    `assigned_object_type/id` valorizzati e `assigned_object` che restituisce `None` (assegnazione
    orfana).
  - `serial` è `CharField(max_length=255)` **non univoco** (esiste l'estensione `AssetDuplicates`
    in `template_content.py` e il filtro `has_duplicates`).
  - `tags = TaggableManager(through="extras.TaggedItem", related_name="inventory_monitor_assets")`.
  - `clean()`: controlla solo la coerenza `price`/`currency` e solleva `ValidationError` con dict.
  - `delete()`: solleva `ProtectedError` se c'è `order_contract` o se ci sono
    `external_inventory_items`, poi `super().delete()`. `RMA.asset` è `PROTECT`, quindi anche un
    RMA blocca la cancellazione.
- `PrimaryModel` (NetBox 4.7, `netbox/models/__init__.py`) = `OwnerMixin` + `NetBoxModel` +
  `description` + `comments`. `NetBoxModel` fornisce tag, changelog, journal, custom field, ecc.

**`inventory_monitor/models/asset_type.py`**
- `class AssetType(NetBoxModel)`, **non** `PrimaryModel`: ha `name`, `slug`, `description`
  (`CharField(200, blank=True, default="")`), `color`, `tags`
  (`related_name="inventory_monitor_asset_types"`). Niente `comments` né `owner`.

**`inventory_monitor/models/rma.py`** (modello figlio dell'Asset da usare come esempio)
- `class RMA(ContactsMixin, PrimaryModel)`, `asset = ForeignKey(Asset, PROTECT,
  related_name="rmas")`, `tags` con `related_name="inventory_monitor_rmas"`, `Meta` con
  `verbose_name`, `get_absolute_url()` con `reverse("plugins:inventory_monitor:rma", ...)`.
- `save()` è `@transaction.atomic` e chiama `update_asset_serial()`, che fa
  `self.asset.save()` **senza** `full_clean()`. **Non modificare** `RMA.update_asset_serial()`.

**Viste, form, filtri, tabelle (pattern da seguire)**
- `views/rma.py`: viste generiche registrate con `@register_model_view(models.RMA, ...)`:
  `ObjectView`, `ObjectListView` (`"list", path="", detail=False`), `ObjectEditView`
  (`"add", detail=False` + `"edit"`), `ObjectDeleteView`, `BulkEditView`
  (`"bulk_edit", path="edit", detail=False`), `BulkDeleteView` (`"bulk_delete", path="delete",
  detail=False`), `BulkImportView` (`"bulk_import", path="import", detail=False`). Ogni vista va
  esportata in `views/__init__.py`.
- `urls.py`: per ogni modello due righe `path("<prefisso>/", include(get_model_urls(
  "inventory_monitor", "<model>", detail=False)))` e `path("<prefisso>/<int:pk>/", include(
  get_model_urls("inventory_monitor", "<model>")))`.
- `views/asset.py`: `AssetListView.queryset` usa già `select_related(...)` e
  `prefetch_related(...)` per evitare N+1; `get_queryset()` aggiunge
  `Asset.annotate_with_probe_data()`. `AssetEditView.alter_object()` precompila l'assegnazione GFK
  da `request.GET`; per un campo normale come `asset` **non serve**: `ObjectEditView.get()` passa
  già `normalize_querydict(request.GET)` come `initial` al form, quindi `?asset=<pk>` precompila
  la tendina senza codice aggiuntivo.
- `forms/rma.py`: `RMAForm(PrimaryModelForm)` con `fieldsets`, `DynamicModelChoiceField(
  queryset=Asset.objects.all(), selector=True)`, `DatePicker()`; `RMAFilterForm(
  ContactModelFilterForm, PrimaryModelFilterSetForm)`; `RMABulkEditForm(PrimaryModelBulkEditForm)`
  con `nullable_fields`; `RMABulkImportForm(PrimaryModelImportForm)` con `CSVModelChoiceField`.
  Nota: i form usano `from django.utils.translation import gettext as _` (valutato all'import),
  i modelli `gettext_lazy`. Nel codice nuovo usa `gettext_lazy` per le etichette.
- `forms/asset.py`: `AssetForm.__init__` imposta le scelte di `currency` a runtime con
  `add_blank_choice(get_currency_choices())`. È il pattern per le scelte da configurazione (R4).
- `filtersets/rma.py`: `@register_filterset class RMAFilterSet(PrimaryModelFilterSet,
  ContactModelFilterSet)` con `search()`. `filtersets/asset.py`: `AssetFilterSet.__init__` imposta
  `self.filters["currency"].field.choices = get_currency_choices()`, e
  `filter_has_external_inventory_items()` mostra il pattern booleano "con/senza" (`exclude` per il
  caso falso, per evitare duplicati da join).
- `tables/rma.py`: `RMATable(ContactsColumnMixin, PrimaryModelTable)` con `fields` e
  `default_columns`. `tables/asset.py`: `AssetTable` ed `EnhancedAssetTable(AssetTable)`, usata
  anche da molte viste figlie in `template_content.py`.
- `helpers.py`: `get_currency_choices()`. `settings.py`: helper `get_plugin_settings()`,
  `get_probe_recent_days()`, `get_external_inventory_status_config_safe()`, `get_warning_days()`
  letti a runtime da `settings.PLUGINS_CONFIG["inventory_monitor"]`.
- `__init__.py`: `NetBoxInventoryMonitorConfig.default_settings` contiene `probe_recent_days`,
  `currencies`, `default_currency`, `enable_netbox_attachments`. Non esiste ancora un controllo
  della configurazione all'avvio. `PluginConfig` di NetBox 4.7 offre `validate(cls, user_config,
  netbox_version)` (classmethod) e `ready()`.

**Interfaccia della scheda Asset**
- `templates/inventory_monitor/asset.html` estende `generic/object.html`, pannelli `card` con
  `table attr-table`, blocco `{% block content %}`. Lì vanno i pannelli *Last related device info*
  e *Decommissioning (NIS2)*.
- `template_content.py`: `PluginTemplateExtension` (es. `AssetDuplicates`, `models =
  ["inventory_monitor.asset"]`, `full_width_page`), registrate in `template_extensions`.
- `search.py`: `@register_search class RMAIndex(SearchIndex)` con `fields` e `display_attrs`.
  `AssetIndex.get_field_value()` mostra come indicizzare un valore calcolato (metodo richiamabile):
  `SearchIndex` legge attributi, non percorsi `asset__serial`.
- `navigation.py`: `PluginMenu` con gruppo `"Assets"` e `PluginMenuItem` con pulsanti *Add* e
  *Import*. `tests/test_navigation.py` verifica che tutti i link del menu facciano `reverse`.

**API e GraphQL**
- `api/serializers.py`: `AssetTypeSerializer(NetBoxModelSerializer)`,
  `AssetSerializer(PrimaryModelSerializer)` con `type = AssetTypeSerializer(nested=True)`,
  `fields` e `brief_fields` come tuple, `RMASerializer` con `asset = AssetSerializer(nested=True)`
  ed elenchi `fields`/`brief_fields`. URL: `HyperlinkedIdentityField(view_name=
  "plugins-api:inventory_monitor-api:<model>-detail")`. `AssetSerializer.get_assigned_object()` è
  un `SerializerMethodField` con `@extend_schema_field(serializers.JSONField(allow_null=True))`:
  precedente utile per annidare il record nell'Asset senza import circolari.
- `api/views.py`: `NetBoxModelViewSet` con `queryset` ottimizzato, `serializer_class`,
  `filterset_class`. `api/urls.py`: `router.register("rmas", views.RMAViewSet)`.
- `graphql/types.py`: `@strawberry_django.type(models.RMA, fields="__all__",
  filters=InventoryMonitorRMAFilter) class InventoryMonitorRMAType(GQLContactsMixin,
  PrimaryObjectType)`, relazioni con `Annotated[..., strawberry.lazy(...)]`.
  `InventoryMonitorAssetTypeType(NetBoxObjectType)`. `graphql/filters.py`:
  `@strawberry_django.filter_type(RMA, lookups=True)` con `PrimaryModelFilter`,
  `ContactFilterMixin`, `OwnerFilterMixin`. `graphql/schema.py`: una classe `Query` per modello
  (`inventory_monitor_rma`, `inventory_monitor_rma_list`), elencata in `graphql/__init__.py`
  (`schema = [...]`).

**Migrazioni**
- Ultima: `0008_alter_owner_related_name.py`. La nuova sarà `0009_...`.
- `0001_initial_squashed.py`: `copy_to_assigned_object()` e `reverse_migration()` fanno
  `ContentType.objects.get(app_label="dcim", model="site"|"device"|"location")` **senza guardia**.
  Vedi §3.4.

**Test esistenti** (`inventory_monitor/tests/`): `test_contacts.py` (con le tuple
`SUPPORTED_MODELS`, `EXCLUDED_MODELS`, `EDIT_FORMS`, `FILTERSETS`), `test_date_status.py`,
`test_external_inventory_filters.py`, `test_navigation.py`, `test_probe_diff.py`. Sono il modello
di stile per i test nuovi.

**Comportamenti di NetBox 4.7 rilevanti (verificati nel sorgente dentro il container)**
- `BulkEditView._update_objects()` chiama `obj.full_clean()` per ogni oggetto
  (`netbox/views/generic/bulk_views.py`). Anche i form modello e i serializer
  (`ValidatedModelSerializer`) passano da `full_clean()`. Quindi una regola in `Asset.clean()`
  vale per UI, modifica massiva, import CSV, API e script che chiamano `full_clean()`. Non vale per
  `save()` diretto né per `QuerySet.update()`.
- `core/signals.py::handle_deleted_object` è un ricevitore `pre_delete` generico: registra un
  `ObjectChange` anche per gli oggetti cancellati in cascata.
- `utilities/migration.py` esclude `choices` dalla `deconstruct()` dei campi: in NetBox un
  `choices=` sul modello **non** genera migrazioni. Vedi §9, decisione D1.
- `tenancy.Contact.name` **non** è univoco.
- `utilities/forms/fields/csv.py::CSVModelChoiceField.to_python()` intercetta
  `MultipleObjectsReturned` e restituisce l'errore di riga *"… is not a unique value for this
  field; multiple objects were found"*. Con `to_field_name="serial"` o `"name"` l'ambiguità è già
  gestita da NetBox.
- `BulkDeleteView` chiama `obj.delete()` per ogni oggetto (`bulk_views.py`), quindi le protezioni
  di `Asset.delete()` valgono anche nella cancellazione massiva.
- `PluginConfig.validate(user_config, netbox_version)` (`netbox/plugins/__init__.py`) completa
  `user_config` con `default_settings` **per chiave**: una lista in `PLUGINS_CONFIG` sostituisce
  per intero quella predefinita (non la estende).
- `ChoiceSetMeta` (`utilities/choices.py`) cerca in `FIELD_CHOICES` la chiave
  `f"{app}.{key}"`, dove `app` è il primo segmento del modulo. Per `LifecycleStatusChoices` (`key =
  "inventory_monitor.asset.lifecycle_status"`) la chiave effettiva è quindi
  `inventory_monitor.inventory_monitor.asset.lifecycle_status`. La chiave documentata nel README
  (`inventory_monitor.Asset.lifecycle_status`) **non ha effetto** (il confronto ignora le maiuscole,
  ma il prefisso è doppio). È un difetto preesistente, fuori ambito: non correggerlo, citalo solo
  nella specifica (vedi D6).

---

## 2. Regole di lavoro

1. **Fase di analisi e specifica, poi stop.** Prima di toccare il codice:
   - scrivi `docs/specs/decommissioning-record.md`: modello dati, regole V0–V7, comportamento di
     `last_related_info`, configurazione, elenco file da toccare, tabella requisito → test,
     sezione **§Decisioni** (riporta D1–D11 di §9, già approvate) e sezione **§Domande aperte**
     per le ambiguità nuove che trovi;
   - scrivi `CLAUDE.md` nella radice del repository del plugin con le regole di questa sezione,
     i comandi di `dev/nb.sh` e un puntatore alla specifica;
   - fai un commit (`Docs: decommissioning record spec and CLAUDE.md`), riassumi e **fermati** in
     attesa della mia approvazione.
2. **Implementazione un passo alla volta**, nell'ordine del piano (§5). Per ogni passo:
   1. scrivi prima i test e verifica che **falliscano** per il motivo giusto;
   2. scrivi il codice;
   3. esegui la **suite completa** (`dev/nb.sh check`: lint + `makemigrations --check` + test);
   4. un commit per passo, messaggio in inglese nello stile del repository
      (`Feat: ...`, `Fix: ...`, `Docs: ...`, `Test: ...`);
   5. riepilogo in chat (cosa, test aggiunti, esito suite) e **fermati**.
3. **Mai `git push`.** Mai `--no-verify`, mai riscrivere la storia.
4. **Mai indebolire test esistenti**: niente `skip`, niente asserzioni rimosse o allentate. Puoi
   aggiungere un modello a una tupla di `test_contacts.py` se la sua natura lo richiede.
5. **Ambiguità**: scrivile in §Domande aperte della specifica e chiedimele. Non inventare.
6. **Segui i pattern esistenti** (§1.3): stessi mixin, nomi, `register_model_view`, struttura di
   form, filtri, tabelle, serializer, GraphQL. Etichette nuove con `gettext_lazy`.
7. **Nessuna dipendenza nuova** nel plugin (`dependencies = []` resta vuoto). Gli strumenti di
   sviluppo (ruff) vanno solo nel virtualenv di sviluppo.
8. Non modificare `RMA.update_asset_serial()` né gli script esterni GARR.
9. **Tracciamento dell'avanzamento** in `docs/specs/decommissioning-record-tasks.md` (checklist
   `- [ ] T0NN Descrizione — requisiti: R… — test: tests/test_….py`, checkpoint come righe a sé,
   sezione `## Stato` in cima con task corrente, ultimo task completato, checkpoint raggiunti,
   problemi aperti). I tre file del lavoro sono:
   - specifica: `docs/specs/decommissioning-record.md`;
   - task: `docs/specs/decommissioning-record-tasks.md`;
   - prompt di implementazione: `docs/prompts/decommissioning-record-implementation.md`.

   Regole:
   - all'inizio di ogni sessione leggi `CLAUDE.md`, la specifica e il file dei task, ed esegui
     **solo il primo task non spuntato**;
   - a fine task la riga diventa `- [x] T00N … — commit <hash breve> — <data>` e `## Stato` viene
     aggiornata, **nello stesso commit del codice**. Un commit non può contenere il proprio hash (e
     `--amend` lo cambierebbe), quindi il commit del task scrive `commit (pending)` e il commit
     successivo, che tocca sempre il file dei task, lo sostituisce con l'hash reale: nessuna
     riscrittura della storia;
   - i problemi scoperti durante il lavoro diventano nuovi task o voci in §Domande aperte della
     specifica, mai note solo in chat;
   - ai checkpoint fermati e aspetta la mia conferma prima di spuntarli.

---

## 3. Ambiente di sviluppo

### 3.1 Verifica se esiste già

Controlla, in quest'ordine, e riportami cosa trovi:

1. Un NetBox di sviluppo già indicato in `CLAUDE.md`, `dev/` o nelle variabili `NETBOX_DIR` /
   `NETBOX_CONFIGURATION`.
2. Una cartella `~/netbox-dev/` (ambiente proposto in §3.2).
3. L'harness `netbox-docker` due livelli sopra il plugin
   (`/home/rino/progetti/inventoryItem/netbox-docker`): container `netbox-docker-netbox-1`
   (immagine `netbox-plugins:local`, NetBox 4.7.3, Python 3.14) e `netbox-docker-postgres-1`.
   **Attenzione**: lì il plugin è installato come **copia non editabile** in
   `site-packages/inventory_monitor` (da `Dockerfile-Plugins`), costruita da uno stato precedente
   del sorgente (contiene la guardia di §3.4, che il ramo attuale non ha). I test eseguiti lì con
   `docker compose exec netbox manage.py test` **non** vedono le modifiche del working tree senza
   ricostruire l'immagine. Non usarlo per il ciclo test-codice; va bene per la prova manuale
   finale, dopo `docker build -f Dockerfile-Plugins -t netbox-plugins:local .` e
   `docker compose up -d --force-recreate`, se l'utente lo chiede. Il `CLAUDE.md` di
   `netbox-docker` cita un `differenze.txt` nella cartella del plugin e dice che la guardia di §3.4
   è una modifica locale: nel ramo attuale quel file non c'è e la guardia nemmeno (né su altri rami
   locali né in `git stash`).

Stato dell'host al 2026-10-20: `~/netbox-dev/` non esiste; `python3` è 3.11.7; pyenv ha solo
3.9.16 e 3.10.6; `uv` non è installato. Docker è disponibile.

### 3.2 Se manca: proposta (non eseguire prima del mio ok)

Proponi questo ambiente **fuori dal repository**, in `~/netbox-dev/`:

- `~/netbox-dev/docker-compose.yml` con:
  - `postgres:18-alpine` (NetBox 4.7 richiede PostgreSQL ≥ 14), porta pubblicata solo su
    `127.0.0.1:55432`, volume dedicato. Script di init che crea l'utente `netbox` con `CREATEDB`
    (serve al test runner per creare `test_netbox`) e il database `netbox`;
  - `valkey/valkey:9.1-alpine` (o `redis:7-alpine`) su `127.0.0.1:56379`.
  Porte non standard per non scontrarsi con l'harness `netbox-docker` già attivo.
- `~/netbox-dev/.env` con le credenziali (non versionato, è fuori dal repository).
- Sorgente NetBox: `git clone --branch v4.7.3 --depth 1 https://github.com/netbox-community/netbox.git
  ~/netbox-dev/netbox` (tag compatibile con `min_version`/`max_version`).
- Virtualenv `~/netbox-dev/venv` con **Python ≥ 3.12**: sull'host non c'è (vedi §3.1), quindi
  proponi `pyenv install 3.12` (o 3.13), oppure l'installazione di `uv` e `uv venv --python 3.12`.
  Poi
  `pip install -r netbox/requirements.txt`, `pip install -e <radice del plugin>`, `pip install ruff`.
- `~/netbox-dev/netbox/netbox/netbox/configuration.py` (copiato da `configuration_example.py`) con
  `DATABASES`/`REDIS` puntati alle porte sopra, `SECRET_KEY` generata, `ALLOWED_HOSTS = ["*"]`,
  `DEBUG = False`, `DEVELOPER = True` (permette `makemigrations` nelle app NetBox e i test),
  `PLUGINS = ["inventory_monitor"]`. Le credenziali le legge da `~/netbox-dev/.env`.
- Nel repository, **`dev/nb.sh`** (versionato, senza credenziali), che legge da
  `dev/.env.local` (escluso da git: aggiungi `dev/.env.local` a `.gitignore`) i percorsi
  `NETBOX_DIR` e `VENV`, e offre:
  - `dev/nb.sh test [label...]` → `manage.py test --keepdb --parallel 1 ${@:-inventory_monitor}`;
  - `dev/nb.sh lint` → `ruff check . && ruff format --check .`;
  - `dev/nb.sh migrations` → `manage.py makemigrations inventory_monitor`;
  - `dev/nb.sh check` → lint + `manage.py makemigrations inventory_monitor --check --dry-run` +
    test completi; esce con codice ≠ 0 al primo errore;
  - `dev/nb.sh runserver` → `manage.py runserver 127.0.0.1:8001 --insecure`.
  Includi in `dev/nb.sh` un controllo che fallisca con messaggio chiaro se `dev/.env.local` manca.

### 3.3 Prima di qualsiasi modifica

Con l'ambiente pronto, registra lo stato di partenza: `dev/nb.sh lint`,
`makemigrations --check` e la suite completa sul codice attuale. Se qualcosa fallisce già prima
delle tue modifiche, riportalo e chiedimi se correggerlo in un commit separato.

### 3.4 Problema noto: `0001_initial_squashed` su database vuoto

**Verificato leggendo il codice**: in questo ramo `copy_to_assigned_object()` e
`reverse_migration()` in `migrations/0001_initial_squashed.py` chiamano
`ContentType.objects.get(app_label="dcim", model=...)` senza guardia. Su un database vuoto le
ContentType di `dcim` non esistono ancora (Django le crea nel `post_migrate`, dopo tutte le
migrazioni), quindi `migrate` fallisce con `ContentType matching query does not exist`. Questo
colpisce anche la creazione del database di test. L'harness `netbox-docker` ne documenta il
crashloop su volume vuoto; la copia installata nel container ha la guardia, il sorgente attuale no.

Come gestirlo:

1. Verificalo empiricamente: `dev/nb.sh test inventory_monitor.tests.test_navigation` su un
   database di test nuovo (senza `--keepdb` la prima volta).
2. Se fallisce, proponimi (e applica solo dopo il mio ok) un commit separato, prima del passo 1,
   `Fix: squashed initial migration on an empty database`, che aggiunge in testa a entrambe le
   funzioni:
   ```python
   if not Asset.objects.exists():
       return
   ```
   (dopo `Asset = apps.get_model(...)`). Nessun asset ⇒ niente da copiare: il comportamento sui
   database esistenti non cambia. Aggiungi un test che documenti la guardia se è fattibile senza
   orchestrare migrazioni (altrimenti dichiaralo nel riepilogo).
3. Ogni nuova migrazione di dati che risolve una ContentType deve avere la stessa guardia.
   La migrazione di R5 dovrebbe essere solo di schema.

---

## 4. Requisiti

### R1 — `Asset.last_related_info`

**Definizione**
- `last_related_info = models.TextField(blank=True, default="", verbose_name=_("Last related
  device info"))`.
- Conserva le informazioni sull'ultimo Device a cui l'asset è stato associato, leggibili anche
  dopo la cancellazione del Device (assegnazione GFK orfana) o la disassociazione.
- Formato stabile, una riga `chiave: valore` per voce, chiavi in inglese e in quest'ordine; le voci
  facoltative si omettono se vuote:
  ```
  snapshot_date: 2026-10-19T10:15:00+02:00
  device: core-sw-01 (id 123)
  site: Milano-Caldera
  location: Sala 1
  rack: R12 (U 20, front)
  role: Core Switch
  device_type: Juniper QFX5120-48Y
  device_serial: WS1234567
  primary_ip: 192.0.2.10/24
  status: Active
  tenant: GARR
  ```
  Definisci formato e chiavi nella specifica; è un contratto con chi legge l'export CSV.
  `snapshot_date` in ISO 8601 con offset e secondi interi, nel fuso `TIME_ZONE` di NetBox (D8).

**Quando si valorizza**
- Al salvataggio di un asset assegnato a un `dcim.Device`, o a un `dcim.Module` (si usa
  `module.device`), **se l'assegnazione è cambiata o il campo è vuoto**. Per sapere se è cambiata
  serve il valore precedente: proponi nella specifica come ricavarlo (es. valori salvati in
  `from_db()`/`__init__`, oppure una query sull'originale solo quando l'oggetto ha `pk`).
- Prima della cancellazione di un `dcim.Device` (`pre_delete`), per tutti gli asset assegnati a
  quel Device **o a un suo Module**: istantanea calcolata una sola volta, poi aggiornamento in
  blocco (`QuerySet.update()` o `bulk_update()`), **senza query per asset**. Nessun
  `ObjectChange` per gli asset aggiornati così (D5): va documentato.
- Prima della cancellazione di un solo `dcim.Module` (`pre_delete`): stesso aggiornamento in
  blocco per gli asset assegnati a quel Module, con l'istantanea del suo Device (D11). Se il Module
  viene cancellato in cascata con il suo Device, l'esito deve restare corretto (l'istantanea è la
  stessa).
- **Asset che lascia un Device** (D10): se l'assegnazione precedente era un Device o un Module
  ancora esistente e la nuova non è un Device/Module (disassegnazione, oppure Site/Location/Rack),
  prima del salvataggio si riprende l'istantanea **del Device uscente**. Così il campo non resta
  con rack/IP superati.
- Assegnazioni a Site, Location, Rack non vi scrivono mai i propri dati (al più rinfrescano il
  Device uscente, sopra); da un'assegnazione non-Device a un'altra non-Device il campo non cambia;
  la disassegnazione non lo svuota.
- La logica sta nel modello (`Asset.save()` o un helper chiamato da lì) e in un ricevitore di
  segnale del plugin (nuovo `inventory_monitor/signals.py`, collegato in
  `NetBoxInventoryMonitorConfig.ready()` chiamando `super().ready()`), così vale anche per script
  e API.
- Modificabile da form, API e CSV; un successivo cambio di Device lo sovrascrive.

**File da toccare**: `models/asset.py`, nuovo `signals.py`, `__init__.py` (`ready()`),
`forms/asset.py` (`AssetForm`, `AssetBulkImportForm`; nel bulk edit valuta se ha senso),
`api/serializers.py` (`AssetSerializer.fields`), `graphql/types.py`/`filters.py`,
`templates/inventory_monitor/asset.html` (pannello con `<pre>`), migrazione (R5).

**Test** (nuovo `tests/test_last_related_info.py`)
- asset assegnato a Device → campo valorizzato con tutte le chiavi attese; formato esatto;
- asset assegnato a Module → usa il Device del modulo;
- Device con rack/posizione/faccia, IP primario e tenant → righe presenti; senza → righe omesse;
- assegnazione a Site/Location/Rack partendo da nessuna assegnazione o da un'altra non-Device →
  campo invariato, e nessun dato di Site/Location/Rack nel campo;
- da Device a Site/Location/Rack o a nessuna assegnazione → campo rinfrescato con i dati
  **attuali** del Device uscente (modifica rack/IP del Device prima, verifica che compaiano), non
  svuotato (D10);
- nuovo salvataggio senza cambio di assegnazione con campo pieno → invariato (anche se a mano);
- cambio di Device → sovrascritto;
- cancellazione del Device → tutti gli asset (diretti e via Module) aggiornati prima della
  cancellazione, con `assertNumQueries` che non cresce col numero di asset (2 asset vs 5 asset);
- dopo la cancellazione `assigned_object` è `None` ma `last_related_info` è leggibile;
- cancellazione di un solo Module (Device intatto) → asset del Module aggiornati, numero di query
  costante (D11);
- `RMA` completato con `replacement_serial` → `update_asset_serial()` non solleva errori.

**Completato quando**: test verdi, pannello visibile in scheda, campo in API/CSV/GraphQL.

### R2 — `AssetType.decommissioning_requirements`

- `CharField(max_length=50, blank=True, default="", verbose_name=_("Decommissioning
  requirements"))`, nessun `choices=` (R4). Menu a tendina con i valori di
  `decommissioning_requirements_choices`.
- Visibile in: scheda `assettype.html`, `AssetTypeTable` (colonna opzionale, non in
  `default_columns`), `AssetTypeForm`, `AssetTypeBulkEditForm`, `AssetTypeFilterForm` e
  `AssetTypeFilterSet` (scelta multipla + `decommissioning_requirements_configured`, R4),
  `AssetTypeBulkImportForm`, `AssetTypeSerializer` (con `*_configured`), GraphQL
  (`InventoryMonitorAssetTypeType`, `InventoryMonitorAssetTypeFilter`).
- Mostrato **in sola lettura** nel form e nella scheda del DecommissioningRecord (via
  `asset.type`) come promemoria. Nessun vincolo con `sanitization_method`.

**Test** (`tests/test_asset_type_decommissioning.py`): valore configurato accettato da form, CSV
e API; valore non configurato rifiutato; valore dismesso già salvato preservato (R4); filtro per
valore e per `_configured=false`; colonna tabella renderizzata.

**Completato quando**: test verdi e campo visibile nei punti elencati.

### R3 — Nuova entità `DecommissioningRecord`

**Modello** (`inventory_monitor/models/decommissioning_record.py`, esportato in
`models/__init__.py` e in `__all__`)

```python
class DecommissioningRecord(PrimaryModel):  # niente ContactsMixin (D2)
    objects = RestrictedQuerySet.as_manager()
    asset = OneToOneField("inventory_monitor.Asset", CASCADE, related_name="decommissioning_record")
    technical_decommission_date = DateField(null=True, blank=True)
    technical_decommission_operator = ForeignKey("tenancy.Contact", PROTECT, null=True, blank=True,
                                                 related_name="inventory_monitor_decommissions")  # D7
    sanitization_date = DateField(null=True, blank=True)
    sanitization_method = CharField(max_length=50, blank=True, default="")
    sanitization_operator = ForeignKey("tenancy.Contact", PROTECT, null=True, blank=True,
                                       related_name="inventory_monitor_sanitizations")  # D7
    disposal_date = DateField(null=True, blank=True)
    disposal_document = TextField(blank=True, default="")
    tags = TaggableManager(through="extras.TaggedItem",
                           related_name="inventory_monitor_decommissioning_records", blank=True)
```
`Meta`: `ordering`, `verbose_name = _("decommissioning record")`, plurale, indici sulle tre date.
`__str__`: basato su `asset.str_no_pk()`. `get_absolute_url()`:
`plugins:inventory_monitor:decommissioningrecord`.

`PrimaryModel` fornisce descrizione, commenti, owner, changelog, journal, custom field, permessi
standard (`view/add/change/delete_decommissioningrecord`). Niente `ContactsMixin` (D2): gli
operatori sono le due FK; aggiungi `DecommissioningRecord` a `EXCLUDED_MODELS` in
`tests/test_contacts.py` con un commento che lo spiega (è un'aggiunta, non un indebolimento).

**Cancellazione**
- Cancellare il record non cancella l'asset.
- Cancellare l'asset cancella il record (CASCADE). `Asset.delete()` chiama `super().delete()`, che
  usa il Collector di Django: il `pre_delete` del record parte e NetBox registra un `ObjectChange`
  per entrambi. Verificalo con un test. Le protezioni esistenti di `Asset.delete()` (contratto,
  inventario esterno, RMA) restano prioritarie.
- `PROTECT` sui Contact: un Contact usato come operatore non si può cancellare. È voluto
  (tracciabilità).

**Validazione** in `DecommissioningRecord.clean()` (codici errore stabili in inglese, messaggi con
`gettext_lazy`). Ogni regola ha almeno un test positivo e uno negativo:

- **V0** (D3) su un record esistente `asset` non può cambiare (codice `asset_immutable`): vale per
  form, import CSV con `id`, API `PUT/PATCH`.
- **V1** nessuna delle tre date è nel futuro rispetto a `timezone.localdate()`, cioè nel fuso
  `TIME_ZONE` di NetBox (D8).
- **V2** `technical_decommission_date ≤ sanitization_date ≤ disposal_date`, confrontando solo le
  date presenti (anche tecnica ≤ smaltimento se manca la sanificazione); stesso giorno ammesso.
- **V3** `sanitization_method` obbligatorio se c'è `sanitization_date`, e viceversa.
- **V4** `sanitization_method` deve essere tra i valori configurati, **salvo** che sia il valore
  già salvato e non modificato (record esistente, valore uguale a quello in DB).
- **V5** se c'è `technical_decommission_date`, `asset.lifecycle_status` ∈ {`retired`,
  `disposed`}; se c'è `disposal_date`, `asset.lifecycle_status == disposed`.
- **V6** in `Asset.clean()` (nel modello Asset, non nel record): se esiste un record con
  `disposal_date`, `lifecycle_status` può essere solo `disposed` (codice `disposed_asset`); se
  esiste un record con `technical_decommission_date`, solo `retired`/`disposed` (codice
  `decommissioned_asset`). Errore sul campo `lifecycle_status`. Per riattivare un asset si
  svuotano prima le date nel record. Attenzione: `self.decommissioning_record` solleva
  `RelatedObjectDoesNotExist` se il record manca; su un asset nuovo (`pk is None`) non c'è record.
  V5 e V6 usano le costanti `LifecycleStatusChoices.RETIRED/DISPOSED` (D6); la documentazione
  dichiara che togliere quei valori via `FIELD_CHOICES` rende le regole insoddisfacibili.
- **V7** un asset già *Retired*/*Disposed* senza record non viene bloccato da nulla.

Test di V6 per tutti i canali: `full_clean()` diretto (come gli script GARR), `AssetForm`,
`AssetBulkEditView` (POST), `AssetBulkImportForm` (aggiornamento con `id`), API `PATCH
/api/plugins/inventory-monitor/assets/<id>/` → 400 con il codice/messaggio atteso.

**Interfaccia**
- Pannello *Decommissioning (NIS2)* nella scheda Asset (`asset.html`):
  - senza record e con `add_decommissioningrecord` → pulsante *Add decommissioning record* verso
    `decommissioningrecord_add?asset=<pk>&return_url=<url asset>`;
  - con record → campi principali, link al record, pulsanti *Edit*/*Delete* secondo i permessi;
  - con `view_asset` ma senza `view_decommissioningrecord` → il pannello mostra solo "record
    presente" / "nessun record", senza dettagli, link né pulsanti (D9).
- Viste: lista, dettaglio (`decommissioningrecord.html`), crea, modifica, cancella, modifica
  massiva, cancellazione massiva, import CSV (pattern di `views/rma.py`). La creazione precompila
  `asset` da `?asset=<pk>` tramite l'`initial` che `ObjectEditView` ricava già da `request.GET`
  (§1.3): nessun `alter_object()` necessario.
- Form: `asset` come `DynamicModelChoiceField` limitato agli asset **senza record** tramite
  `query_params={"has_decommissioning_record": "false"}`, solo in creazione; in modifica il campo è
  disabilitato (mostra l'asset corrente) e non compare nel form di modifica massiva (D3, V0);
  `DatePicker` per le date; operatori come `DynamicModelChoiceField(queryset=Contact.objects.all())`;
  `sanitization_method` come `ChoiceField` con le scelte da configurazione (R4);
  `asset.type.decommissioning_requirements` mostrato in sola lettura (help text o campo disabilitato).
- Import CSV (D4): colonne `asset` (ID) / `asset_serial`, `technical_decommission_operator` (ID) /
  `technical_decommission_operator_name`, `sanitization_operator` (ID) /
  `sanitization_operator_name`; ognuna è un `CSVModelChoiceField` (`to_field_name` = `pk`,
  `serial` o `name`). Nel `clean()` del form: per l'asset esattamente una delle due colonne (in
  creazione), per ogni operatore al più una. `Asset.serial` e `Contact.name` non sono univoci: il
  messaggio di ambiguità lo produce già `CSVModelChoiceField` (§1.3), va solo coperto da test.
- Tabella `DecommissioningRecordTable(PrimaryModelTable)` con colonne per asset (link), seriale,
  tipo, tutte le date, metodo (con badge per valore non configurato), operatori, documento, e
  `asset.last_related_info` opzionale (è la colonna *Device* del registro).
- Tabella Asset: colonne opzionali (non di default) per lo stato del record e le sue date, con
  `select_related("decommissioning_record")` in `AssetListView.queryset` e
  `AssetViewSet.queryset`. Le altre viste che usano `EnhancedAssetTable` in
  `template_content.py` non mostrano quelle colonne di default; verifica comunque che attivarle
  non generi N+1 nella lista principale.
- Filtri UI/API: su Asset `has_decommissioning_record` (booleano, pattern di
  `filter_has_external_inventory_items`); sul record `asset_id`, `serial` (seriale dell'asset),
  intervalli `__gte/__lte` per le tre date, `sanitization_method` (scelta multipla da
  configurazione), `sanitization_method_configured`, `technical_decommission_operator_id`,
  `sanitization_operator_id`, `q`.
- Voce di menu *Decommissioning Records* nel gruppo `"Assets"` di `navigation.py`, con pulsanti
  *Add* e *Import* (`test_navigation.py` la copre).
- Ricerca globale (`search.py`): `DecommissioningRecordIndex` su `disposal_document`,
  `description`, `comments` e seriale dell'asset (con `get_field_value()` come in `AssetIndex`).
  Nota: cambiando il seriale dell'asset l'indice del record non si aggiorna da solo; dichiaralo
  nella specifica o reindicizza il record al salvataggio dell'asset.

**API REST**
- `DecommissioningRecordSerializer(PrimaryModelSerializer)` in `api/serializers.py` con `asset =
  AssetSerializer(nested=True)`, contatti con `ContactSerializer(nested=True)` di
  `tenancy.api.serializers`, `sanitization_method_configured` (sola lettura), `fields` e
  `brief_fields`. Validazione delle scelte di `sanitization_method` lato serializer (R4).
- ViewSet in `api/views.py` con `select_related("asset", "asset__type",
  "technical_decommission_operator", "sanitization_operator", "owner__group")`; registrato come
  `router.register("decommissioning-records", ...)` in `api/urls.py`.
- `AssetSerializer`: aggiungi `last_related_info` e `decommissioning_record` annidato in sola
  lettura. **Riferimento circolare**: `DecommissioningRecordSerializer` annida `AssetSerializer` e
  viceversa. Proponi nella specifica la soluzione (es. un serializer annidato ridotto senza
  `asset`, oppure `SerializerMethodField` con `@extend_schema_field`) e verifica che
  `/api/schema/` si generi senza errori.
- `AssetTypeSerializer`: `decommissioning_requirements` e `decommissioning_requirements_configured`.

**GraphQL**
- `InventoryMonitorDecommissioningRecordType(PrimaryObjectType)` con `asset` e operatori lazy;
  `InventoryMonitorDecommissioningRecordFilter(OwnerFilterMixin, PrimaryModelFilter)`;
  query `inventory_monitor_decommissioning_record` e `..._list`, aggiunte a `schema`.
- In `InventoryMonitorAssetType`: `last_related_info` e `decommissioning_record` (reverse
  one-to-one, opzionale). In `InventoryMonitorAssetTypeType`: `decommissioning_requirements`.

**File da toccare**: `models/decommissioning_record.py`, `models/__init__.py`, `models/asset.py`
(V6), `forms/decommissioning_record.py` + `forms/__init__.py`, `filtersets/decommissioning_record.py`
+ `filtersets/__init__.py` + `filtersets/asset.py`, `tables/decommissioning_record.py` +
`tables/__init__.py` + `tables/asset.py`, `views/decommissioning_record.py` + `views/__init__.py`
+ `views/asset.py`, `urls.py`, `navigation.py`, `search.py`, `api/serializers.py`,
`api/views.py`, `api/urls.py`, `graphql/types.py`, `graphql/filters.py`, `graphql/schema.py`,
`graphql/__init__.py`, `templates/inventory_monitor/decommissioningrecord.html`,
`templates/inventory_monitor/asset.html`, migrazione (R5).

**Test** (`tests/test_decommissioning_record.py`, `tests/test_decommissioning_views.py`,
`tests/test_decommissioning_api.py`, `tests/test_decommissioning_graphql.py`)
- V0–V7 positivi e negativi; V6 su tutti i canali elencati;
- unicità 0:1 (secondo record sullo stesso asset rifiutato da form e API);
- V0: cambio di `asset` su record esistente rifiutato da form, CSV con `id` e API;
- `EXCLUDED_MODELS` in `test_contacts.py` include il record (D2); reverse accessor
  `contact.inventory_monitor_decommissions` / `inventory_monitor_sanitizations` funzionanti (D7);
- cancellazione record → asset presente; cancellazione asset → record cancellato e due
  `ObjectChange` con `action=delete`;
- `PROTECT` su Contact;
- viste: lista, dettaglio, add con `?asset=` precompilato, edit, delete, bulk edit, bulk delete,
  import CSV (per ID, per seriale univoco, seriale ambiguo → errore, contatto per nome, nome
  ambiguo → errore, ID e seriale insieme → errore);
- pannello in scheda Asset: pulsante *Add* solo senza record e con permesso; *Edit*/*Delete* con
  record; utente con `view_asset` ma senza `view_decommissioningrecord` → solo "record presente" /
  "nessun record", nessun dettaglio (D9);
- tendina asset: il filtro API `has_decommissioning_record=false` esclude gli asset con record;
- filtri UI/API, uno per filtro;
- ricerca globale trova il record per `disposal_document` e per seriale;
- menu: coperto da `test_navigation.py`;
- API: CRUD completo, `brief`, record annidato e `last_related_info` nel serializer Asset,
  generazione di `/api/schema/`;
- GraphQL: query singola e lista, campo `decommissioning_record` su asset;
- N+1: `assertNumQueries` costante su lista record (UI e API) e lista asset con le colonne nuove
  attive, con 2 e con 5 oggetti.

**Completato quando**: tutto sopra verde e scenario manuale (§5, checkpoint B) riuscito.

### R4 — Valori configurabili

- In `default_settings` di `__init__.py` due chiavi, sovrascrivibili in `PLUGINS_CONFIG`, liste di
  `(valore, etichetta)`, con predefiniti identici:
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
  Chiavi: `decommissioning_requirements_choices`, `sanitization_method_choices`.
- **Nessun `choices=` sul modello.** La scelta la applicano form, serializer, filtri e `clean()`
  tramite helper in `settings.py` letti a runtime, per esempio
  `get_sanitization_method_choices()`, `get_decommissioning_requirements_choices()`,
  `is_configured(key, value)`, `choice_label(key, value)`. Motivazione corretta (D1): non le
  migrazioni (NetBox già ignora `choices` nella `deconstruct()`), ma il fatto che con `choices=`
  `full_clean()` rifiuterebbe un valore dismesso a ogni salvataggio del record. Scrivila così nella
  documentazione.
- Controllo della configurazione all'avvio (`validate()` o `ready()` di
  `NetBoxInventoryMonitorConfig`): ogni lista è una sequenza di coppie, valori univoci, non vuoti,
  lunghi ≤ 50; altrimenti `ImproperlyConfigured` con messaggio che indica chiave e valore.
- Valore tolto dalla configurazione:
  - il dato salvato non si tocca (nessuna migrazione, nessun aggiornamento automatico);
  - in scheda e in tabella si mostra `<valore> (not in configuration)` con badge di avviso
    (`text-bg-warning`);
  - l'API restituisce anche il booleano `sanitization_method_configured` /
    `decommissioning_requirements_configured`;
  - nel form di modifica il valore dismesso resta selezionabile **solo per quel record** (aggiunto
    alle scelte in `__init__` se è il valore dell'istanza);
  - filtro `*_configured=false` (UI, API, GraphQL dove possibile);
  - se il valore torna in configurazione, tutto torna normale.

**Test** (`tests/test_decommissioning_settings.py`, con `override_settings(PLUGINS_CONFIG=...)`):
predefiniti; override; configurazione invalida (duplicati, vuoti, > 50, formato errato) →
`ImproperlyConfigured`; valore dismesso: preservato al salvataggio di un altro campo, mostrato con
badge, `*_configured=false` in API e filtro, selezionabile nel form solo per quel record, non
selezionabile per un record nuovo; valore che torna in configurazione → normale.

**Completato quando**: test verdi, README aggiornato con le due chiavi.

### R5 — Migrazione, documentazione, versione

- **Una** migrazione nuova (`0009_...`), generata con `dev/nb.sh migrations`, reversibile, solo
  di schema: `Asset.last_related_info`, `AssetType.decommissioning_requirements`, modello
  `DecommissioningRecord`. Nessun cambiamento per gli asset senza record. Se durante i passi
  servono più migrazioni intermedie, unificale prima del commit finale del passo che le introduce
  (non esistono rilasci intermedi).
- Test di reversibilità: `migrate inventory_monitor 0008` e di nuovo `migrate` sul database di
  sviluppo, documentato nel riepilogo.
- `docs/decommissioning-record.md`: mappatura colonne del Registro Dismissioni → campi (tabella di
  §1.2), configurazione R4 (con la motivazione di D1), regole V0–V7 (e il vincolo su
  `retired`/`disposed` di D6), comportamento di `last_related_info` (formato, quando si aggiorna
  inclusi D10 e D11, cosa non lo modifica, assenza di `ObjectChange` per l'aggiornamento in blocco
  di D5), impatto sugli script esterni (errori `disposed_asset` e `decommissioned_asset` sollevati
  da `full_clean()`; `save()` diretto e `QuerySet.update()` non sono protetti), import CSV (colonne
  di D4), come ottenere il registro (export CSV della lista record con le colonne giuste).
- `README.md`: sezione modello, configurazione (`PLUGINS_CONFIG`), link al documento.
- `CHANGELOG.md`: voce `## [15.3.0] - <data>` in stile Keep a Changelog, come le voci esistenti.
- `inventory_monitor/version.py`: `15.2.0` → `15.3.0` (minore).
- Liste senza N+1 verificate da test, etichette con `gettext_lazy`, ogni requisito con almeno un
  test.

---

## 5. Piano a passi

Ogni passo: test che falliscono → codice → `dev/nb.sh check` → commit → riepilogo → stop.

La checklist operativa di questi passi (task T0NN e i due checkpoint) è in
`docs/specs/decommissioning-record-tasks.md`; lo stato corrente si legge lì, non qui.

0. **Ambiente** (§3): verifica, proposta, attesa dell'ok, creazione, stato di partenza, eventuale
   fix di `0001_initial_squashed` in commit separato (§3.4).
1. **Specifica e `CLAUDE.md`** (§2.1). Stop per approvazione.
2. **Configurazione (R4, parte di base)**: chiavi in `default_settings`, helper in `settings.py`,
   controllo all'avvio. Test di `test_decommissioning_settings.py` relativi agli helper e alla
   validazione.
3. **Modelli e migrazione**: `Asset.last_related_info`, `AssetType.decommissioning_requirements`,
   modello `DecommissioningRecord` (FK con `related_name` di D7, niente `ContactsMixin`),
   `clean()` con V0–V5, V6 in `Asset.clean()`, V7, cascade e changelog. Migrazione `0009`. Test a
   livello di modello.
4. **`last_related_info` (R1)**: calcolo al salvataggio (incluso il Device uscente, D10), segnali
   `pre_delete` su Device e su Module (D11), test inclusi quelli di `assertNumQueries`.

   **Checkpoint A** — dopo i passi 3 e 4: riepilogo con lo schema della migrazione
   (`sqlmigrate inventory_monitor 0009`), esito di `migrate` avanti e indietro, elenco dei test.
   Fermati e aspetta il mio ok prima dell'interfaccia.

5. **Form, filtri, tabelle (R2, R3, R4)**: `AssetType` (form, filtri, tabella, CSV), form, filtri,
   tabella e import del record, colonne e filtro `has_decommissioning_record` su Asset, campi
   nuovi in `AssetForm`/`AssetBulkImportForm`.
6. **Viste, URL, template, menu, ricerca**: viste generiche, `urls.py`, `decommissioningrecord.html`,
   pannelli in `asset.html` e `assettype.html`, badge per valori non configurati, `navigation.py`,
   `search.py`.
7. **API REST**: serializer, viewset, router, campi su Asset e AssetType, schema OpenAPI.
8. **GraphQL**: tipi, filtri, query, campi su Asset e AssetType.

   **Checkpoint B** — prova manuale da browser (`dev/nb.sh runserver`, utente con tutti i permessi
   e un secondo utente con sola vista). Scenario guidato da descrivermi con l'esito di ogni passo:

   1. Crea Site *Test-Site*, Manufacturer, DeviceType, DeviceRole, Device *sw-test-01* con seriale,
      Rack *R1* (U 10, front), IP primario e tenant; due Contact *Mario Rossi* e *Anna Bianchi*.
   2. Imposta sull'AssetType *Switch* `decommissioning_requirements = zeroize`; verifica scheda,
      colonna opzionale in tabella, filtro.
   3. Crea un Asset con lo stesso seriale assegnato a *sw-test-01*: il pannello *Last related
      device info* mostra il testo preformattato con tutte le chiavi.
      Crea un secondo Asset *spare* assegnato a *sw-test-01*, poi sposta il Device in U 12 e
      assegna *spare* al Site *Test-Site*: il suo `last_related_info` mostra `U 12` e nessun dato
      del Site (D10).
   4. Nella scheda Asset, pannello *Decommissioning (NIS2)*: c'è *Add decommissioning record*.
      Prova a creare il record con data di messa fuori linea mentre l'asset è *In Use* → errore V5.
   5. Porta l'asset a *Retired*, crea il record (asset precompilato, promemoria *zeroize* visibile)
      con data di oggi, operatore *Mario Rossi*. Il pulsante *Add* sparisce, compaiono
      *Edit*/*Delete*. In *Edit* il campo asset è bloccato (D3); nella tendina di un nuovo record
      l'asset non compare più.
   6. Prova a rimettere l'asset *In Use* da form, da modifica massiva e da import CSV →
      errore `decommissioned_asset`. Ripeti con un `PATCH` API (curl con token) → 400.
   7. Aggiungi `sanitization_date` di ieri → errore V2. Con data di oggi ma senza metodo → errore
      V3. Con metodo *zeroize* e operatore *Anna Bianchi* → ok.
   8. Porta l'asset a *Disposed*, aggiungi `disposal_date` e `disposal_document = "RAEE
      2026/123"`. Prova a riportarlo a *Retired* → errore `disposed_asset`.
   9. Cancella il Device *sw-test-01*: la scheda Asset mostra ancora `last_related_info`;
      l'assegnazione è orfana.
   10. Togli `zeroize` da `sanitization_method_choices` in configurazione e riavvia: il record
       mostra `zeroize (not in configuration)` con badge; l'API dà
       `sanitization_method_configured: false`; il filtro `_configured=false` lo trova; nel form
       di modifica `zeroize` è ancora selezionabile; in un record nuovo no. Ripristina la
       configurazione: tutto torna normale.
   11. Lista record → export CSV: ci sono tutte le colonne del Registro Dismissioni (§1.2).
   12. Ricerca globale per `RAEE 2026/123` e per il seriale: trova il record.
   13. Con l'utente in sola vista: niente pulsanti *Add*/*Edit*/*Delete*. Con un terzo utente che
       ha `view_asset` ma non `view_decommissioningrecord`: il pannello dice solo "record
       presente", senza dettagli (D9).
   14. Cancella l'asset (senza contratto, inventario esterno, RMA): il record sparisce; il
       changelog mostra entrambe le cancellazioni.

   Aspetta il mio ok.

9. **Documentazione e versione (R5)**: `docs/decommissioning-record.md`, README, CHANGELOG,
   `version.py`.
10. **Verifica finale** (§6 sotto).

---

## 6. Verifica finale

- Database di test **ricreato da zero**: `dev/nb.sh test` senza `--keepdb` (o eliminando
  `test_netbox`), suite completa verde.
- `manage.py makemigrations inventory_monitor --check --dry-run` → nessuna migrazione mancante.
- `ruff check . && ruff format --check .` puliti.
- `manage.py migrate inventory_monitor 0008` e ritorno a `migrate` riusciti sul database di
  sviluppo.
- Tabella finale nel riepilogo (e nella specifica): **requisito/regola → test** (R1, R2, R3 con
  V0–V7 una riga ciascuna, R4, R5, D2, D4, D7, D9, D10, D11, N+1), con nome del test e file.
- `git log --oneline` dei commit del lavoro. Nessun push.

---

## 7. Fuori ambito

- Modifiche agli script esterni GARR.
- Viste di report dedicate: il registro si ottiene esportando in CSV la lista dei record.
- Più eventi di sanificazione per asset.
- Archiviazione dei file in NetBox (certificati, delibere).
- Traduzione italiana.

## 8. Criteri di successo

- Le colonne del Registro Dismissioni sono ottenibili dall'export CSV della lista dei record.
- Nessun asset con `disposal_date` torna in uso da UI, API, script o `full_clean()`.
- Dopo la cancellazione di un Device gli asset ne conservano i dati in `last_related_info`.
- Togliere un valore dalla configurazione non modifica i dati salvati.
- Lint, `makemigrations --check` e test passano.

---

## 9. Decisioni approvate (D1–D11)

Queste decisioni sono state prese dall'utente il 2026-10-20 accettando le raccomandazioni. Sono già
integrate nei requisiti sopra; riportale nella specifica nella sezione §Decisioni. Non riaprirle:
se il codice le rende impraticabili, segnalalo e chiedi.

- **D1 — Scelte da configurazione, non `choices=` sul modello.** NetBox (`utilities/migration.py`)
  esclude già `choices` dalla `deconstruct()`, quindi la motivazione "evitare migrazioni" di R4 è
  errata. La ragione valida: con `choices=` sul modello `full_clean()` rifiuterebbe un valore
  dismesso a ogni salvataggio del record. **Deciso**: scelte applicate a runtime come da R4;
  documentazione con la motivazione corretta. `FIELD_CHOICES` non si usa per questi campi (non
  distingue i valori dismessi).
- **D2 — Niente `ContactsMixin` sul record.** Gli operatori sono le due FK esplicite; un secondo
  canale per i contatti creerebbe ambiguità. **Deciso**: `DecommissioningRecord(PrimaryModel)` senza
  `ContactsMixin`, aggiunto a `EXCLUDED_MODELS` in `tests/test_contacts.py` con commento.
- **D3 — `asset` immutabile dopo la creazione.** **Deciso**: in creazione la tendina usa
  `query_params={"has_decommissioning_record": "false"}`; in modifica il campo è disabilitato e non
  è nel bulk edit; `clean()` del modello rifiuta il cambio su un record esistente (regola V0, codice
  `asset_immutable`), così vale anche per CSV con `id` e API.
- **D4 — Import CSV con colonne distinte.** **Deciso**: `asset` (ID) / `asset_serial`,
  `technical_decommission_operator` (ID) / `technical_decommission_operator_name`,
  `sanitization_operator` (ID) / `sanitization_operator_name`, tutte `CSVModelChoiceField`
  (`to_field_name` = `serial` / `name` per le colonne testuali), che segnalano già i valori non
  univoci. Nel `clean()` del form: per l'asset esattamente una colonna (in creazione), per ogni
  operatore al più una.
- **D5 — Nessun `ObjectChange` per l'aggiornamento in blocco di `last_related_info`.** **Deciso**:
  accettato (l'evento è già nel changelog come cancellazione del Device/Module) e documentato in
  `docs/decommissioning-record.md`.
- **D6 — V5/V6 legati a `retired`/`disposed`.** **Deciso**: V5/V6 usano
  `LifecycleStatusChoices.RETIRED/DISPOSED`; la documentazione dichiara che togliere quei valori
  via `FIELD_CHOICES` rende le regole insoddisfacibili. Il difetto preesistente della chiave
  `FIELD_CHOICES` (quella del README non ha effetto, l'effettiva è
  `inventory_monitor.inventory_monitor.asset.lifecycle_status`, §1.3) **non** si corregge in
  questo lavoro: citalo nella specifica come issue separata.
- **D7 — `related_name` delle FK ai Contact.** **Deciso**:
  `technical_decommission_operator` → `related_name="inventory_monitor_decommissions"`,
  `sanitization_operator` → `related_name="inventory_monitor_sanitizations"`.
- **D8 — Fuso orario.** **Deciso**: V1 confronta con `timezone.localdate()` (fuso `TIME_ZONE` di
  NetBox); `snapshot_date` di `last_related_info` in ISO 8601 con offset, secondi interi
  (`timezone.localtime().replace(microsecond=0).isoformat()`).
- **D9 — Pannello senza permesso di vista sui record.** **Deciso**: con `view_asset` ma senza
  `view_decommissioningrecord` il pannello *Decommissioning (NIS2)* mostra solo "record presente" /
  "nessun record", senza dettagli, link né pulsanti.
- **D10 — Istantanea del Device uscente.** **Deciso**: quando l'assegnazione precedente era un
  Device o un Module ancora esistente e la nuova non è un Device/Module, prima di salvare si
  riprende l'istantanea **di quel Device uscente**. Site/Location/Rack non entrano mai nel campo;
  la disassegnazione non lo svuota.
- **D11 — Cancellazione di un solo Module.** **Deciso**: ricevitore `pre_delete` anche su
  `dcim.Module`, che aggiorna in blocco gli asset del Module con l'istantanea del suo Device, con
  numero di query costante.
