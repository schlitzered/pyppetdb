# UI-Handoff: CA Secrets & geänderte Validation-Config

Stand: 2026-07-21. Zielgruppe: UI-/Frontend-Entwicklung (bzw. UI-LLM).
Beschreibt die neuen CA-Secrets-Endpunkte und die Breaking Changes an der
`validation_config` von CA Authorities und Spaces.

---

## 1. Neue Endpunkte: CA Secrets

Basis-Pfad `/api/v1/ca/secrets`. Secrets sind **write-only**: der Wert wird nie
zurückgegeben.

| Methode | Pfad | Permission | Erfolg |
|---|---|---|---|
| GET | `/api/v1/ca/secrets` | `CA::GET` | 200 |
| POST | `/api/v1/ca/secrets/{secret_id}` | `CA:SECRETS:CREATE` | **201** |
| GET | `/api/v1/ca/secrets/{secret_id}` | `CA::GET` | 200 |
| PUT | `/api/v1/ca/secrets/{secret_id}` | `CA:SECRETS:UPDATE` | 200 |
| DELETE | `/api/v1/ca/secrets/{secret_id}` | `CA:SECRETS:DELETE` | 200 |

**`secret_id`**: nur `[A-Za-z0-9_-]+` (sonst 422).

### Request-Bodies

```jsonc
// POST  (CASecretPost)
{ "secret": "…", "description": "…?" }

// PUT   (CASecretPut) – alle Felder optional
{ "secret": "…?", "description": "…?" }
```

### Response (CASecretGet)

Enthält **niemals** `secret`/`secret_encrypted`:

```json
{
  "id": "GITHUB_TOKEN",
  "description": "…",
  "created": "…ISO8601…",
  "updated": "…ISO8601…"
}
```

GET-Liste:

```json
{ "result": [ /* CASecretGet… */ ], "meta": { /* Pagination-Meta */ } }
```

### Query-Params (GET Liste)

| Param | Bedeutung |
|---|---|
| `secret_id` | Regex-Filter auf id |
| `description` | Regex-Filter auf description |
| `fields` | Teilmenge von `id,description,created,updated` |
| `sort` | `id \| created \| updated` |
| `sort_order` | `ascending \| descending` |
| `page` | ≥ 0 |
| `limit` | 10–1000 |

### Fehlercodes

- `404` – Secret existiert nicht (GET/PUT/DELETE).
- **`409`** – DELETE eines noch referenzierten Secrets. `detail` listet die
  Fundstellen, z. B.:
  `secret 'X' is still referenced by: ca_authority:my-ca, ca_space:my-space`
- `422` – ungültige `secret_id`.

### UI-Aufgabe

Neuer CA-Secrets-Verwaltungs-Screen: Liste (id/description/created/updated) plus
Anlegen/Bearbeiten/Löschen. Der Secret-Wert ist ein Passwort-Eingabefeld ohne
Anzeige-Möglichkeit. Beim `409` die Fundstellen anzeigen.

---

## 2. Geändert: `validation_config` bei CA Authorities **und** Spaces

Betrifft `POST/PUT /api/v1/ca/authorities/{id}` und
`POST/PUT /api/v1/ca/spaces/{id}`, Feld
`validation_config.san_validation.http_checks[]`.

### Weggefallen (Breaking)

- Das Header-Feld **`secret: bool` gibt es nicht mehr** → im Header-Editor den
  „secret"-Schalter entfernen. Header ist jetzt nur
  `{ "name": "...", "value": "..." }`.
- **Kein Masking mehr:** GET liefert die Config **verbatim** zurück (früher
  `*****`). Die bisherige Logik „maskierten Wert `*****` beim Update
  zurückschicken, um das Secret zu behalten" **muss raus** — einfach die Config
  senden, wie sie ist.

### Neu: Secret-Referenzen

Werte referenzieren Secrets via GitHub-Actions-Syntax `$secrets[SECRET_ID]`,
auch eingebettet:

```json
{ "name": "Authorization", "value": "Bearer $secrets[GITHUB_TOKEN]" }
```

- Erlaubt in: **Header-`value`**, **`password`** (basic auth),
  **`body_template`**, **`client_key`**.
- Literal `$secrets[…]` schreiben: mit `$$secrets[…]` escapen.
- **`username`** = normaler Text, **nie** Secret.
- **`url`** darf **keine** Referenz enthalten → sonst 422.

### Save-Zeit-Validierung (POST/PUT) → `422` mit `detail`

- unbekannte Referenz: `unknown secret references: X`
- Secret in URL: `secret references are not allowed in 'url' (…)`
- literales basic-auth-Passwort:
  `basic-auth 'password' must reference a secret …`
  → **`password` muss eine `$secrets[]`-Referenz sein**, kein Klartext.
- literaler `client_key`:
  `'client_key' must reference a secret …`
  → **`client_key` muss eine `$secrets[]`-Referenz sein**, kein Inline-Key.
  (`client_cert`/`ca_cert` sind öffentlich und bleiben Freitext.)

### UI-Empfehlung

- In den Feldern `value` / `password` / `body_template` / `client_key` einen
  Secret-Picker anbieten, der `GET /api/v1/ca/secrets` lädt und
  `$secrets[<id>]` einfügt.
- Beim `password`-Feld erzwingen, dass eine Referenz gewählt wird.
- `422`/`detail` als Formular-Fehler anzeigen.

---

## 3. Permissions-Übersicht

- Lesen (Authorities, Spaces, Secrets): `CA::GET`
- Secrets schreiben: `CA:SECRETS:CREATE` / `CA:SECRETS:UPDATE` /
  `CA:SECRETS:DELETE`
- Unverändert: `CA:AUTHORITIES:*`, `CA:SPACES:*`

---

## 4. Statuscodes bei POST (normalisiert)

Alle **Resource-erstellenden** POST-Endpunkte liefern jetzt einheitlich **201
Created** – inklusive der zuvor abweichenden `POST /api/v1/ca/authorities/{id}`,
`POST /api/v1/ca/spaces/{id}` und `POST /api/v1/nodes_secrets_redactor`
(vorher 200). Das UI-Erfolgs-Handling für diese drei ist entsprechend von 200
auf 201 umzustellen.

Nicht betroffen (kein „create", bleiben bei 200): Aktions-POSTs wie das
WS-Token, Job-Cancel sowie die Puppet-Protokoll-Endpunkte
(`/puppet/v3/catalog`, `/puppet-ca/v1/certificate_renewal`).

---

## 5. CSR-/Kontext-Platzhalter in HTTP- und Script-Checks

Ergänzt Abschnitt 2. Bei der Zertifikatsvalidierung stehen Werte aus dem CSR
und dem Kontext zur Verfügung. **Achtung: die Platzhalter-Syntax unterscheidet
sich je Feld** – das sollte das UI klar kommunizieren bzw. beim Einfügen
automatisch die richtige Form verwenden.

Verfügbare Werte:
- **CN** – Common Name aus dem CSR (der zu signierende Node-Name)
- **SANs** – Liste der DNS Subject Alternative Names aus dem CSR
- **ca_id**, **space_id** – Kontext (welche CA / welcher Space signiert)

### HTTP-Checks

| Feld | Platzhalter | Syntax / Hinweis |
|---|---|---|
| `url` (inkl. Query-String) | `{cert_cn}`, `{ca_id}`, `{space_id}` | Python-`str.format`, **einfache** geschweifte Klammern. Kein `sans`. Literale `{`/`}` müssen verdoppelt werden. **Keine** `$secrets[...]` (siehe Abschnitt 2). |
| `body_template` | `{{cn}}`, `{{sans}}` | **doppelte** geschweifte Klammern, reine String-Ersetzung. `{{sans}}` wird als **JSON-Array** eingesetzt (z. B. `["a.com","b.com"]`). Ergebnis muss valides JSON sein. `$secrets[...]` **erlaubt** (wird vorher aufgelöst). |
| `headers[].value` | – | **Keine** CSR-/Kontext-Platzhalter. Nur `$secrets[...]`. |
| `username` / `password` | – | Keine CSR-Platzhalter. `password` **muss** `$secrets[...]` sein (Abschnitt 2). |
| `client_key` | – | Keine CSR-Platzhalter. **Muss** `$secrets[...]` sein – kein Inline-Key. `client_cert`/`ca_cert` bleiben Freitext. |

### mTLS / TLS-Verhalten des HTTP-Checks

Die TLS-Felder werden beim Ausführen des Checks jetzt tatsächlich verwendet:

- `verify_ssl` (bool, default `true`): Server-Zertifikat prüfen ja/nein.
- `ca_cert` (PEM, optional): eigene CA zum Prüfen des Server-Zertifikats.
- `client_cert` + `client_key` (PEM): **mTLS** – nur aktiv, wenn **beide**
  gesetzt sind. `client_key` muss eine `$secrets[...]`-Referenz sein (siehe
  oben); `client_cert` ist Freitext (öffentlich).

UI-Hinweis: `client_cert` und `client_key` bilden ein Paar – im Editor beide
zusammen anbieten und darauf hinweisen, dass mTLS nur greift, wenn beide
gefüllt sind.

**Default-Body** (wenn `body_template` leer): es wird automatisch
`{"cn": "<CN>", "sans": ["<san>", …]}` als JSON gesendet.

**Verarbeitungsreihenfolge** (relevant, weil `body_template` beides kombinieren
kann): 1. `$secrets[...]` auflösen → 2. `{{cn}}`/`{{sans}}` ersetzen (body) →
3. `url.format(...)`.

Beispiele:
```jsonc
// url mit Query-Param
"url": "https://validate.example.com/check?cn={cert_cn}&ca={ca_id}"
// body_template: CN als String, SANs als JSON-Array, Token aus Secret
"body_template": "{\"node\":\"{{cn}}\",\"sans\":{{sans}},\"token\":\"$secrets[HOOK]\"}"
// header: nur Secret, KEINE CSR-Platzhalter
{ "name": "Authorization", "value": "Bearer $secrets[HOOK]" }
```

### Script-Checks

Das Script (`script_path`) bekommt die CSR-Werte als **Environment-Variablen**
übergeben (kein stdin, keine Argumente):

| Variable | Inhalt |
|---|---|
| `CN` | Common Name aus dem CSR |
| `SAN1`, `SAN2`, … `SANn` | je ein SAN, **1-basiert** durchnummeriert |

Ergebnis: Exit-Code `0` = Validierung bestanden, `!= 0` = abgelehnt
(stderr/stdout landen in der Fehlermeldung). `timeout_seconds` begrenzt die
Laufzeit. `$secrets[...]` werden in Script-Checks **nicht** aufgelöst.

### UI-Gotchas (bitte im Editor berücksichtigen)
- Zwei verschiedene Klammer-Syntaxen: URL `{cert_cn}` (einfach) vs. Body
  `{{cn}}` (doppelt) – nicht verwechseln.
- Uneinheitliche Namen: in der URL heißt es `cert_cn`, im Body `cn`.
- `{{sans}}` ist ein **Array**, kein String – im JSON-Body ohne umschließende
  Anführungszeichen verwenden.
- Header unterstützen **keine** CSR-Platzhalter (nur Secrets) – im UI dort also
  keine `{cert_cn}`/`{{cn}}`-Hilfen anbieten.
