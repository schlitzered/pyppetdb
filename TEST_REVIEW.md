# Review der Unit- & Integrationstests — pyppetdb

**Datum:** 2026-07-20
**Umfang:** 93 Testdateien, ~15.400 Zeilen (76 Unit-, 17 Integrationstests)
**Methode:** Statische Analyse — je Testdatei wurde zusätzlich der getestete Quellcode gelesen.
Die Tests wurden **nicht** ausgeführt; alle Befunde stammen aus der Code-Analyse.
Test-Framework: `unittest` (`unittest.TestCase` / `IsolatedAsyncioTestCase`).

---

## Gesamturteil

Die Suite ist breit und in der Fläche solide, aber sie testet den Code an genau den
fachlich wichtigsten Stellen nicht sauber. Es zieht sich ein Muster durch alle Domänen:
**die sicherheits- und domänenkritischen Entscheidungspunkte werden weggemockt** und
dann wird nur geprüft, *dass* delegiert/aufgerufen wurde — nicht, *ob die Regel stimmt*.
Dadurch würden viele echte Regressionen (Berechtigungslecks, Scoping-Fehler,
Krypto-Fehler, Secret-Leaks) grün bleiben.

Kurz: gute **Coverage-Breite**, aber lückenhafte **Verhaltens-Tiefe** dort, wo es zählt.

**Note gesamt: 3 (befriedigend)** — solide Grundlage, aber mit ernsten
sicherheitsrelevanten Blindstellen.

| Domäne | Note | Kern-Befund |
|---|---|---|
| API/Controller | 2– (gut) | Delete-Kaskaden & `_self`-Logik echt getestet; Denied-Pfade + einzelne Endpunkte fehlen |
| Auth/Autz/Redaction | 2–/3+ | `require_perm`-Regel & argon2 echt getestet; echte Autz-Kette (DB) nie end-to-end |
| Hiera | 3– | Lookup-Integration stark; mehrere Unit-Tests laufen gar nicht |
| CRUD | 3 | Basis/AST/Redaction gut; Query-Scoping nur „assert_called" |
| CA/Krypto | 3 (m. Vorbehalt) | Happy-Path echt; keine Krypto-Verifikation, kein CRL-Parse, CN-Schutz nur gg. Mock |
| WebSockets/Jobs/PDB | 3– | Job-Validierung gut; `ws/hub.py` praktisch ungetestet |
| Integrations-Infra | 3– | CI + echtes Mongo vorhanden; Isolation/Mock-Hygiene mangelhaft |

---

## Was wirklich gut gemacht ist

- **Echte Domänenlogik statt Mock-Theater** an mehreren Kernstellen: die PuppetDB-AST-/
  PQL-Query-Übersetzung (`tests/unit/test_crud_nodes.py:194-243`), die CRUD-Basis mit
  Fehlerpfaden (`tests/unit/test_crud_common.py`), die Filter-/Projection-Konstruktion
  (`tests/unit/test_crud_mixins.py`).
- **Redaction (Aho-Corasick) ist vorbildlich** getestet (`tests/unit/test_redactors.py`):
  überlappende Matches, rekursive dict/list-Redaction, selektive Feld-Redaction
  (nur `parameters`/`message`/`new_value`, nicht `title`/`status`).
- **`require_perm`-Regel echt getestet** inkl. anker-korrektem Regex `^(...)$` gegen
  Prefix-Escalation (`tests/unit/test_authorize.py`).
  `tests/unit/test_authorization_denied.py` prüft, dass bei Denial die Mutation *nicht*
  ausgeführt wird — der stärkste Test der Suite.
- **Integration mit echtem Stack**: echtes MongoDB, echte argon2
  (`tests/integration/test_authenticate.py`), echte Hierarchie-Semantik bei Hiera-Lookups
  (Priorität, Fallback, Interpolation, first-found), echter CA-End-to-End-Fluss über HTTP
  (`tests/integration/test_puppet_ca.py`).
- **Delete-Kaskaden** fachlich geprüft inkl. Cert-Revoke beim Node-Delete
  (`tests/unit/test_api_v1_nodes.py:74`), Credentials/Teams-Cleanup
  (`tests/unit/test_api_v1_users.py:130`).
- **`_self`-vs-Fremdzugriff** sauber getrennt mit korrektem Permission-Enum je Zweig
  (`tests/unit/test_api_v1_users_credentials.py`).
- **Job-Parametervalidierung** systematisch — bool/enum/float/int-bounds/regex
  (`tests/unit/test_controller_api_v1_jobs.py:298-373`).
- **CI existiert und ist sauber**: `.github/workflows/tests.yml` startet MongoDB 8.0 als
  Replica-Set `rs0`; Unit- und Integrationstests laufen in getrennten Jobs.

---

## Die durchgängigen Schwächen (nach Wichtigkeit)

### 1. Sicherheitskritische Entscheidungen werden wegmockt — größtes Problem

Dasselbe Anti-Muster in *jeder* Domäne:

- **Autorisierung**: Alle Integrationstests laufen als **admin**
  (`tests/integration/base.py:41-62`). Die eigentliche Autz-Entscheidung liegt in einer
  MongoDB-Team/Permission-Query (`pyppetdb/authorize/__init__.py:311-316`), die **in keinem
  einzigen Test real ausgeführt** wird. Es gibt **keinen 403-Test** für
  authentifiziert-aber-unberechtigt. Ein Bug im Permission-Filter bliebe unentdeckt.
  *Schweregrad: hoch.*
- **Client-Cert-Auth global deaktiviert**: `tests/integration/base.py:84-86` ersetzt
  `AuthorizeClientCert.require_cn` / `require_cn_match` / `require_cn_trusted` per direkter
  Klassenattribut-Zuweisung durch `AsyncMock` und setzt es **nie zurück** (kein `patch`,
  kein `tearDownClass`-Restore) → die gesamte Puppet-/CA-/PDB-Autorisierung ist in
  Integrationstests blind. *Schweregrad: hoch.*
- **CA CN-Schutz nur gegen Mock**: „Node bekommt kein Zertifikat für fremden CN"
  (`pyppetdb/ca/service.py:645-648`) wird real nie ausgelöst; die CSR trägt im Test immer
  CN == nodename. Der Unit-Test lässt nur den gemockten Service werfen
  (`tests/unit/test_controller_puppet_ca_v1.py:156`). *Schweregrad: hoch.*
- **Query-Scoping ungeprüft**: `get`/`search`/`resource_exists` in nodes_catalogs/reports/
  groups mocken `_get`/`_search` und prüfen nur `assert_called_once()` — die Aufnahme von
  `placement`/`node_groups`/`teams_list` in die Query wird **nicht** verifiziert:
  - `tests/unit/test_crud_nodes_catalogs.py:57-65,85-93`
  - `tests/unit/test_crud_nodes_reports.py:65-74,86-94`
  - `tests/unit/test_crud_nodes_groups.py:65-70`
  - `tests/unit/test_crud_nodes.py:52-55` (`resource_exists`)

  *Schweregrad: hoch* — ein Regress, der das Scoping entfernt, bliebe unentdeckt.
- **Hiera per-key-Permission** (`PERM_HIERA_LEVEL_DATA_*_DYNAMIC.format(key_id=...)`) wird
  nie durchgesetzt getestet; Unit-Tests mocken `require_perm` als immer erfolgreich,
  Integration testet nur 401 (keine Creds), nie 403. *Schweregrad: mittel.*

### 2. Krypto-Invarianten werden nicht kryptografisch geprüft (CA)

- **Kein Test verifiziert, dass ein ausgestelltes Zertifikat wirklich von der CA signiert
  ist** — kein `verify_directly_issued_by` / `ca_pubkey.verify(...)`, nur
  `startswith("-----BEGIN CERTIFICATE-----")` und SAN-Inhalt. *Schweregrad: hoch.*
- **Kein Negativtest für manipulierte CSR-Signatur** (`pyppetdb/ca/utils.py:343`,
  `not csr.is_signature_valid`). Nur der Garbage-String `b"INVALID_CSR"` wird geprüft, und
  das gegen einen gemockten Service. *Schweregrad: hoch.*
- **CRL wird nie geparst** (`tests/integration/test_api_v1_ca.py:251`) — nur
  `"BEGIN X509 CRL" in crl_pem`. Es wird nie geprüft, dass das revoked Serial wirklich in
  der CRL steht; eine leere/falsche CRL bestünde den Test. *Schweregrad: mittel.*
- **Keine Space/Authority-Isolation im Negativfall**: kein Test, dass ein Cert aus Space A
  nicht über Space B abrufbar/signierbar ist. *Schweregrad: mittel.*
- **Renewal ohne Gate ungetestet**: `renew_certificate` (`pyppetdb/ca/service.py:776`) —
  nicht getestet, ob ein abgelaufenes oder bereits revoked Cert renewt werden darf.
  *Schweregrad: mittel.*

### 3. Redaction ist fail-open — und das wird nicht geflaggt

`pyppetdb/crud/nodes_secrets_redactor.py:191-199` und `:216-222`: Schlägt `decrypt` fehl
(z. B. nach Key-Rotation), wird das Secret **still übersprungen → Klartext leakt** in
Reports/Facts. Der Test (`tests/unit/test_crud_nodes_secrets_redactor.py:99-107`) prüft
nur, dass der Fehler geschluckt wird, nicht dass kein Leak entsteht. Bei
Fehlkonfiguration leaken **alle** Secrets. *Schweregrad: hoch.*

Ebenfalls ungetestet: Auslieferung vor Abschluss des initialen Ladens
(`:113`, `_secrets_count == 0` → Daten unverändert zurück; `:233-238` asynchrones
Befüllen). *Schweregrad: mittel-hoch.*

Facts-Redaction ist gar nicht abgedeckt (nur Reports und Catalogs). *Schweregrad: mittel.*

### 4. Ganze kritische Module ohne Tests

- **`pyppetdb/ws/hub.py`** — kein einziger Unit-Test. `tests/unit/test_api_v1_ws.py` testet
  nur den dünnen Controller gegen einen komplett gemockten Hub. Ungetestet:
  `subscribe`/`unsubscribe`-Lifecycle, first-subscriber-Routing lokal vs. `via`,
  Dead-Socket-Removal bei `send_text`-Exception (`:128-133`), `get_log_chunks`/
  `get_log_chunk` inkl. `asyncio.wait_for(timeout=20)` (`:253-328`). *Schweregrad: hoch.*
- **Job-State-Machine**: `pyppetdb/crud/jobs_nodes_jobs.py` und `jobs_definitions.py` haben
  **keine** Testdatei. Ungetestet: `expire_scheduled_jobs`, `cancel_node_jobs`,
  `get_oldest_scheduled`, `update_status`, `create_node_jobs`. `tests/unit/test_crud_jobs.py`
  testet nur `CrudJobs.create`. *Schweregrad: hoch.*
- **`pyppetdb/crud/ca_authorities.py`** (12,9 KB, sicherheitskritischste Klasse) — nur
  delete/count/create getestet. Ungetestet: `get_private_key`/`get_private_key_cached`
  (Herausgabe von CA-Private-Keys), `_has_masks`/`_encrypt_validation_config`
  (Secret-Masken-Merge `*****`), `sync_crl_data` (optimistic lock über `crl.generation`),
  `get_revoked_for_ca`. *Schweregrad: hoch.*
- **`pyppetdb/ws/inter_api.py:124-177,348-374`** — Nachrichten-Routing und
  Future-Auflösung ungetestet. *Schweregrad: hoch.*
- **`pyppetdb/ws/remote_executor.py`** — `handle_heartbeat`, `mark_job_failed`,
  `mark_all_jobs_failed`, `_cleanup_stale_jobs` (`:153-191`), ACK-Wait/Timeout
  (`:418-451`). *Schweregrad: mittel.*
- **`pyppetdb/jobs/service.py:26-51`** — `expire_scheduled_jobs_worker` (Leader-Election +
  Timeout-Expiry) ungetestet. *Schweregrad: mittel.*
- **`pyppetdb/crud/nodes.py`** — `count()` (inkl. `node_groups`-Scoping),
  `query_exported_resources`, `get_placement`, `cleanup_remote_agents` ohne Test.
  *Schweregrad: mittel.*
- **`pyppetdb/crud/common.py`** — `_convert_to_mongo_schema`, `migrate_1` /
  `_run_migration_transactional`, `_sync_index` (IndexOptionsConflict, Code 85)
  ungetestet. *Schweregrad: mittel.*
- **`pyppetdb/controller/api/v1/nodes.py:259`** (`distinct_fact_values`) — Endpunkt mit
  node_group-Scoping, komplett ohne Test. *Schweregrad: hoch.*

### 5. Tote und wertlose Tests (am Code verifiziert)

- **`tests/unit/test_pyhiera_adapters.py`**: Mehrere Tests sind auf **Modulebene statt als
  Klassenmethoden** definiert (`:40`, `:53`) und werden von `unittest` **nie ausgeführt**.
  Betroffen u. a. der einzige Negativ-Validierungstest des dynamischen Key-Models und der
  Changestream-Key-Sync. *Verifiziert per Grep. Schweregrad: hoch.*
- **`tests/unit/test_controller_pdb_cmd_v1.py`, `test_create_gzip`**: enthält **keine
  einzige Assertion** — prüft nur, dass gzip+json nicht crasht; zudem trifft
  `command="unknown"` keinen Branch. *Verifiziert. Schweregrad: mittel.*
- **`tests/unit/test_issue_expired_csr.py` / `test_issue_repro.py` /
  `test_issue_reproduction.py`**: existieren nicht mehr (nur alte `.pyc` im
  `__pycache__`) — waren Wegwerf-Repros, die nicht in Regressionstests überführt wurden.
  *Verifiziert. Schweregrad: mittel* (falls die Bugs real waren, fehlt jede Absicherung).
- `tests/unit/test_remote_executor_protocol.py:156` mockt eine **nicht existierende**
  Methode (`_heartbeat`) — toter Mock; `:74` (`assertIn(123, self._pending_acks)`) ist
  tautologisch. *Schweregrad: niedrig.*
- `tests/unit/test_ws_inter_api.py:72-99` patcht die Zeit mit fixer
  `side_effect=[100.0, 115.0]` — extrem brüchig, testet Aufrufreihenfolge statt Verhalten.
  *Schweregrad: niedrig.*
- `tests/integration/test_puppet_pdb_api.py:110-119` erwartet `[]` bei leerer DB — würde
  auch bei völlig kaputter Query-Übersetzung grün bleiben (nicht diskriminierend).
  *Schweregrad: mittel.*
- `tests/unit/test_ca_validation_enhanced.py:336` prüft SAN-Injection über positionellen
  Index `args[8]` — bricht still bei Signaturänderung von `sign_csr`. *Schweregrad: niedrig.*

### 6. Fehlende Negativpfade auf Controller-Ebene

- **Kein einziger Denied-Pfad**: `require_perm`/`require_user` sind überall
  immer-erfolgreiche `AsyncMocks`; „Recht fehlt → Exception propagiert" wird nirgends
  getestet. *Schweregrad: mittel.*
- **Permission-Enum nicht asserted**: z. B.
  `tests/unit/test_api_v1_nodes_secrets_redactor.py:44,54` nutzen
  `require_perm.assert_called_once()` ohne `permission=...`; ein falsches Enum (CREATE
  statt DELETE) würde durchrutschen. *Schweregrad: mittel.*
- **Cert-Revoke-Payload nicht verifiziert**: `tests/unit/test_api_v1_nodes.py:90` prüft nur
  `update_certificate_status.assert_called_once()`, nicht `cn`/`status="revoked"`.
  *Schweregrad: niedrig-mittel.*
- **OAuth**: Token-/Signatur-/State-/Nonce-Validierung komplett ungetestet
  (`tests/unit/test_controller_oauth_authenticate.py:44-51` mockt alles weg).
  *Schweregrad: mittel* (Delegation an authlib vertretbar, aber unvalidiert).
- **Credential-Ablauf existiert nicht**: `pyppetdb/crud/credentials.py:104-107` speichert
  `created`, prüft es aber nie — API-Secrets laufen nie ab. Design-/Sicherheitslücke,
  daher auch nicht testbar. *Schweregrad: mittel.*

### 7. Integrationstest-Hygiene

- **Kein Aufräumen zwischen Testklassen**: `tests/integration/base.py:36-37` löscht in
  `setUpClass` nur `users`/`users_credentials`; alle anderen Collections erst am
  Prozessende via `atexit`. 12 von ~22 Integrationsdateien haben gar kein Cleanup.
  *Schweregrad: mittel.*
- **Feste IDs + Exact-Count-Assertion**: `tests/integration/test_api_v1_nodes.py:110-128`
  fügt `n1/n2/n3` ein und prüft `results["prod"] == 2` — bricht, sobald ein vorher
  laufender Test einen Node mit `facts.env == "prod"` hinterlässt (unittest sortiert
  alphabetisch). *Schweregrad: mittel.*
- **`time.sleep(1)` als Sync-Mechanismus**: `tests/integration/test_pdb_cmd_api.py:45,85,121`
  — flaky unter CI-Last. *Schweregrad: mittel.*
- **Kein Skip-Guard**: `tests/integration/base.py:33` verbindet sofort per `MongoClient`;
  fehlt MongoDB, brechen alle Tests als *Error* statt *Skip* ab. Der Config-Default
  `mongodb://localhost:27017` (`pyppetdb/config.py:131`) hat kein `replicaSet`, obwohl
  Change Streams eines brauchen. *Schweregrad: mittel.*
- **Helper-Duplikation**: `_auth_headers()` ist in praktisch jeder Integrationsdatei
  identisch kopiert statt in `IntegrationTestBase`. `atexit.register` wird pro Testklasse
  erneut registriert. *Schweregrad: niedrig.*
- **Kein Test-Runner konfiguriert**: keine `pytest.ini`/`conftest.py`/`[tool.pytest]`;
  Ausführung ausschließlich über `unittest discover`. *Schweregrad: niedrig.*

### 8. Weitere fachliche Lücken (Hiera)

- **Schema-Durchsetzung unvollständig und unsichtbar**:
  `pyppetdb/hiera/schema_model_factory.py:45-71` ignoriert `minimum`/`maximum`,
  `minLength`/`maxLength`, `format`, `additionalProperties`.
  `tests/integration/test_api_v1_hiera_key_models.py:550` definiert `port` mit min/max,
  fügt aber nie out-of-range-Daten ein — die fehlende Durchsetzung bleibt unentdeckt.
  *Schweregrad: mittel.*
- **Merge-Semantik unterverifiziert**: nur einstufiger flacher Hash-Merge + first-found
  (`tests/integration/test_api_v1_hiera_lookup.py:316,436`); kein deep/nested-Merge, kein
  Array-Merge, kein Typkonflikt, kein Merge über 3+ Ebenen. *Schweregrad: mittel.*
- **Cache-Invalidierung**: fact-scoped `$all`-Pfad nur per Mock geprüft, nie e2e verifiziert;
  Dynamic-Key-Model create/delete invalidiert den Lookup-Cache gar nicht → potenziell stale,
  ungetestet (`pyppetdb/crud/hiera_key_models_dynamic.py:225,255`). *Schweregrad: mittel.*
- Kommentar-/Daten-Widerspruch: `tests/integration/test_api_v1_hiera_lookup.py:129` sagt
  „priority 10 (highest)", angelegt wird `priority: 100`; Tiebreak bei gleicher Priorität
  ungetestet. *Schweregrad: niedrig.*

---

## Priorisierte Empfehlungen

### Sofort (Sicherheit)

1. **Integrationstest mit non-admin-User + echter Team/Permission-DB**: mit passender
   Permission → 2xx, ohne → echte **403**. Schließt die kritischste Lücke (echte
   Autz-Kette + node_group-Scoping über die reale Mongo-Query) auf einen Schlag.
2. **Redaction fail-closed machen und testen**: nicht-entschlüsselbares Secret → **kein
   Klartext ausliefern** statt still überspringen; plus Guard/Test gegen Auslieferung vor
   abgeschlossenem Initial-Load. Facts-Redaction ergänzen.
3. **CA-Krypto real verifizieren**:
   (a) ungültig signierte CSR → abgelehnt;
   (b) CN ≠ csr_cn mit echter CSR auf Service-Ebene → `QueryParamValidationError`;
   (c) jedes ausgestellte Cert gegen den CA-PublicKey verifizieren
       (`verify_directly_issued_by`);
   (d) CRL nach Revoke parsen (`x509.load_pem_x509_crl`) und Serial-Anwesenheit prüfen;
   (e) Cross-Space-Isolationstest.

### Kurzfristig (Testqualität)

4. **Scoping-Assertions nachrüsten**: in allen `get`/`search`/`resource_exists`-Tests die
   *konstruierte Query* gegen `placement`/`node_groups`/`teams_list` prüfen
   (`call_args[...]["query"]`) statt nur `assert_called_once()` — analog zum bereits guten
   Muster in `test_crud_users.py`/`test_crud_credentials.py`.
   Ebenso überall `require_perm` mit `permission=PERM_...` asserten.
5. **Tote Tests reparieren/entfernen**: `test_pyhiera_adapters.py` einrücken (Methoden der
   Klasse), `test_create_gzip` mit echtem Command + Assertion versehen,
   `test_remote_executor_protocol` tote Mocks bereinigen, `test_ws_inter_api`
   Zeit-Patching durch Verhaltenstest ersetzen.
6. **`ws/hub.py` und die Job-State-Machine** mit echten Unit-Tests versehen — größter
   Risiko/Nutzen-Hebel im ungetesteten Code (Fan-out mit einem funktionierenden und einem
   exception-werfenden Fake-WebSocket, Chunking-Timeout, `expire_scheduled_jobs`,
   `update_status`, `mark_all_jobs_failed`).
7. **Je Endpunkt einen Denied-Test** (`require_perm` als `AsyncMock(side_effect=...)` →
   Exception erwartet **und** CRUD nicht aufgerufen).
8. **`ca_authorities` absichern**: Private-Key-Herausgabe, `_encrypt_validation_config`
   Masken-Merge, `sync_crl_data`-Generationslogik.

### Mittelfristig (Infrastruktur)

9. **Integrations-Hygiene**:
   - `require_cn*` per `patch.object` + `addClassCleanup` statt globaler Zuweisung, und
     mindestens ein Test, der die echte CN-Autorisierung *ohne* Mock durchläuft;
   - generisches Collection-Cleanup in `base.py`;
   - feste IDs (`n1/n2/n3`, `12345`, `test-node-*`) → uuid-Präfixe, Count-Assertions auf
     gefilterte Teilmengen;
   - `time.sleep` → Polling mit Timeout;
   - `raise unittest.SkipTest` bei nicht erreichbarem MongoDB;
   - `_auth_headers()` in `IntegrationTestBase` zentralisieren;
   - README/docs-Abschnitt „Tests ausführen (Replica-Set nötig)".
10. **Hiera**: Schema-Randfälle (out-of-range/minLength) negativ testen bzw. explizit
    dokumentieren, dass nur `type`/`enum`/`pattern` durchgesetzt werden; deep-merge- und
    3-Ebenen-Merge-Szenario; fact-scoped Cache-Invalidierung e2e.
11. **PDB-Format echt verifizieren** statt Smoke-Test: Integration mit vorbefüllter DB und
    realer exported-resource-Query mit Treffer; `num_resources_exported` /
    `catalog.resources_exported` und `facts.values`-Mapping asserten.

---

## Anhang: Verifizierte Einzelbefunde

Die folgenden drei Befunde wurden direkt am Code gegengeprüft (nicht nur aus der
Analyse übernommen):

| Befund | Prüfung | Ergebnis |
|---|---|---|
| Tote Tests in `test_pyhiera_adapters.py` | `grep -nE "^(class \|    def \|def )"` | bestätigt — `def` auf Modulebene in Z. 40 und 53 |
| `test_issue_*.py` gelöscht | `ls tests/unit/test_issue_*` | bestätigt — keine Datei, nur alte `.pyc` |
| `test_create_gzip` ohne Assertion | Bereichs-Grep auf `assert` | bestätigt — keine Assertion im Test |
