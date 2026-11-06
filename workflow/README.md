# Workflow și reprezentarea rezultatelor în JSON-LD

Pachetul `workflow` gestionează sesiunea care leagă extragerea cadrelor,
selecția utilizatorului și descrierea imaginilor. 

Rezultatul salvat în JSON-LD păstrează descrierile și metadatele sesiunii,
adăugând interpretarea semantică a câmpurilor și identificatori pentru noduri.

## 1. Cum se construiește rezultatul

```text
Video → extragere keyframes → selecție → descriere prin VLM
                                             ↓
                              JSON conform schemei cerute
                                             ↓
                               Validare prin Pydantic
                                             ↓
                         Adăugare metadate și identificator de analiză
                                             ↓
                         Construire JSON-LD pentru afișare și salvare
```

VLM-ul generează conținutul observației în JSON, conform schemei
`ImageObservation`. Pydantic verifică structura, unicitatea identificatorilor
entităților și existența referințelor din relații și acțiuni.

Aplicația adaugă proveniența și construiește reprezentarea JSON-LD local,
fără un apel suplimentar către VLM sau LLM. Contextul JSON-LD este atașat de
cod; nu este generat de model. Reprezentarea internă Pydantic rămâne separată
de documentul JSON-LD rezultat.

Am ales generarea observațiilor în JSON și construirea JSON-LD în cod pentru a controla exact contextul și identificatorii, fără ca VLM-ul să repete aceste elemente fixe în fiecare răspuns.
Această separare permite schimbarea reprezentării pe baza observațiilor salvate, fără reanalizarea imaginilor sau apeluri suplimentare la model.

## 2. Structura documentului

```text
WorkflowSession
├── id, type, @context
├── session_id, schema_version, created_at
├── extraction
├── ontology_path
├── interpretation_settings — configurația curentă și contextul pregătit
└── frames — listă ordonată de KeyframeState
    ├── id, type, frame_id
    ├── selected, description_status, error
    └── observation — FrameObservation sau null
        ├── id, type, @context, analysis_id
        ├── frame_id, scene_index, image_sha256
        ├── schema_version, created_at, prompt_version
        ├── requested_model, resolved_model, provider, api_request_id
        ├── elapsed_seconds, parameters, usage
        └── observation — ImageObservation
            ├── id, type, description
            ├── entities
            ├── relations
            ├── actions
            ├── visible_text
            └── uncertainties
```

### Sesiunea și starea cadrelor

`WorkflowSession` grupează informațiile despre procesarea unui video.
`frames` păstrează toate cadrele extrase valide, inclusiv pe cele neselectate
sau nedescrise.

Fiecare `KeyframeState` conține selecția utilizatorului și starea descrierii:
`pending`, `running`, `completed` sau `failed`. Când nu există o observație,
`observation` este `null`. Dacă regenerarea eșuează, o observație validă
anterioară poate fi păstrată împreună cu eroarea ultimei încercări.

`ontology_path` înregistrează calea ontologiei încărcate. Prezența ei nu
înseamnă că descrierea a fost mapată la acea ontologie.

În schema sesiunii 2.2, `interpretation_settings` păstrează modelul, limba,
domeniul, activarea contextului, namespace-ul, formatul, Turtle-ul și raportul
extragerii. Este serializat ca valoare JSON în JSON-LD. Sesiunile 2.0 și 2.1
rămân acceptate de modelul de date, cu setări implicite.

Fiecare observație păstrează în `parameters.ontology_context` contextul folosit
efectiv (sau `null`), inclusiv textul, hash-urile și versiunea extragerii.
Schimbarea setărilor curente nu rescrie proveniența observațiilor existente.

### Proveniența și conținutul vizual

`FrameObservation` leagă conținutul descrierii de cadrul analizat, hash-ul
imaginii, momentul generării, model și configurația cererii.

`ImageObservation` păstrează informațiile vizuale:

| Câmp | Conținut |
|---|---|
| `description` | Descrierea textuală generală |
| `entities` | Elementele observate: denumire, caracteristici, poziție, vizibilitate |
| `relations` | Relații cu subiect, etichetă textuală și obiect |
| `actions` | Acțiuni sau posturi, participanți și indicatorul de incertitudine |
| `visible_text` | Textul transcris din imagine |
| `uncertainties` | Aspecte pe care modelul nu le poate identifica sigur |

## 3. Rolul contextului JSON-LD

`@context` asociază câmpurile cu termeni identificați prin IRI-uri și precizează
cum se interpretează valorile. Fragment ilustrativ din context:

```json
{
  "id": "@id",
  "type": "@type",
  "name": "rdfs:label",
  "description": "dcterms:description",
  "subject_id": {
    "@id": "obs:subject",
    "@type": "@id"
  }
}
```

Prefixele `rdfs`, `dcterms` și `obs` sunt definite în contextul complet.
Aliasurile permit folosirea câmpurilor `id` și `type` cu sensul cuvintelor-cheie
JSON-LD `@id` și `@type`. `subject_id` este interpretat ca o legătură către un
nod, iar `name` și `description` conțin text.

Vocabularul combină termeni existenți cu termeni proprii `obs:` pentru
observațiile aplicației. Nu este necesar un fișier Turtle separat pentru
procesarea acestei reprezentări. Contextul nu înlocuiește validarea Pydantic.

Fiecare observație include propriul context pentru a putea fi utilizată și
separat de sesiune. Contextul sesiunii adaugă termenii specifici workflow-ului.

## 4. Identificatorii și relațiile

Configurația separă trei roluri:

| Constantă | Identifică |
|---|---|
| `OBSERVATION_NAMESPACE` | Termenii vocabularului aplicației |
| `OBSERVATION_BASE_IRI` | Rezultatele analizelor și nodurile lor |
| `SESSION_BASE_IRI` | Sesiunile și stările cadrelor |

VLM-ul folosește identificatori locali precum `e1` și `e2`. La construirea
JSON-LD, aplicația îi înlocuiește cu identificatori absoluți și actualizează
toate referințele structurate către ei. Forma este:

```text
<OBSERVATION_BASE_IRI><analysis_id>/entities/e1
```

`analysis_id` este generat la construirea observației și păstrat la serializare.
Afișarea sau salvarea repetată a aceleiași observații nu generează un nou ID.
O analiză nouă primește propriul identificator.

Pentru „mâna ține instrumentul”, relația este reprezentată astfel:

```text
RelationObservation
├── subject → identificatorul observației despre mână
├── relationLabel → "holding"
└── object → identificatorul observației despre instrument
```

În JSON, câmpurile rămân `subject_id`, `predicate` și `object_id`. Contextul
le asociază cu `obs:subject`, `obs:relationLabel` și `obs:object`.
`predicate` este încă o etichetă textuală; nu reprezintă automat o proprietate
din ontologia țintă.

Adresele folosite ca identificatori nu sunt accesate prin rețea la construirea
documentului și nu presupun existența unor pagini web pentru fiecare nod.

## 5. Listele și metadatele tehnice

`frames` folosește `@list`, astfel încât ordinea cadrelor să fie reprezentată
și în graful RDF. Colecții precum `entities`, `relations` și `features` folosesc
`@set`; ordinea lor nu are semnificație în graf.

Următoarele câmpuri sunt păstrate ca valori JSON integrale, prin `@type: @json`:

| Câmp | Motiv |
|---|---|
| `extraction` | Păstrează structura completă a rezultatului extragerii, inclusiv căi și erori |
| `parameters` | Păstrează configurația cererii: temperatură, limită de tokeni, limbă, domeniu etc. |
| `usage` | Păstrează consumul și costul raportate de furnizor, cu detaliile disponibile |


## 6. Cum ajută reprezentarea în etapele următoare

| Utilizare | Avantaj |
|---|---|
| Mapare la ontologie | Rezultatul mapării poate indica exact observația din care provine |
| Trasabilitate | O asociere poate fi urmărită până la cadru, descriere, model și prompt |
| Interogare | Un procesor JSON-LD poate construi un graf RDF pentru interogări SPARQL |
| Integrare | Alte instrumente pot interpreta termenii și legăturile folosind contextul |

De exemplu, o etapă viitoare poate produce o asociere între identificatorul
instrumentului observat într-un cadru și identificatorul unui concept din
ontologia aleasă. Observația originală rămâne disponibilă pentru verificare.

JSON-LD nu îmbunătățește singur recunoașterea vizuală, nu corectează descrierile
și nu realizează maparea. Aparițiile unui obiect în cadre diferite rămân
observații distincte până la implementarea unei etape explicite de asociere.


