# VideoToKeyframes

Aplicație desktop pentru extragerea cadrelor reprezentative din videoclipuri, selectarea imaginilor relevante și generarea de observații structurate cu ajutorul modelelor vizuale de limbaj (VLM).

Extragerea folosește **PySceneDetect** pentru detectarea scenelor și **Katna** pentru alegerea keyframe-urilor. Interpretarea imaginilor se face prin **OpenAI**, **Gemini** sau **OpenRouter**, folosind strategii separate și un contract comun de răspuns. Rezultatele pot fi salvate în **JSON-LD**.

Se pot încărca și imagini existente, fără extragere dintr-un videoclip.

**Stadiu:** ontologia poate ghida terminologia descrierilor. Extragerea indivizilor, clasificarea lor și popularea proprietăților ontologiei nu sunt încă implementate. JSON-LD-ul exportat reprezintă observațiile aplicației, nu popularea ontologiei încărcate.

## Funcționalități

- Detectarea scenelor și comasarea fragmentelor foarte scurte.
- Extragerea unui număr de cadre adaptat duratei scenelor, cu limită globală opțională.
- Configurarea pragului de detectare și a proceselor Katna.
- Galerie cu miniaturi, previzualizare și selecție manuală.
- Încărcarea directă a imaginilor JPEG, PNG și WEBP.
- Interpretarea imaginilor în grupuri de 1–4 cadre, cu observații separate pentru fiecare cadru.
- Alegerea furnizorului și a modelului din interfață.
- Context de domeniu și vocabular ontologic opționale.
- Descrieri, entități, relații, acțiuni, text relevant și incertitudini.
- Validarea răspunsurilor și păstrarea provenienței analizelor.
- Regenerare explicită, anulare între operații și păstrarea rezultatelor deja obținute.
- Afișarea rezultatelor selectate și salvarea sesiunii în JSON-LD.
- Interfață separată pentru diagnosticarea performanței extragerii.

## Fluxul aplicației

```text
Video → detectare scene → extragere keyframes ──┐
                                              ├→ galerie → selecție → interpretare VLM
Imagini încărcate direct ──────────────────────┘                         ↓
                                                            validare Pydantic
Ontologie → catalog și namespace → context Turtle ──→ VLM               ↓
                                                               export JSON-LD
```

O sesiune conține fie cadrele unei extrageri, fie imagini încărcate direct. Încărcarea unui set nou înlocuiește sesiunea din interfață, după confirmare dacă există modificări nesalvate.

VLM-ul generează JSON conform unei scheme. Aplicația validează răspunsul, adaugă metadatele și construiește local JSON-LD, fără un apel suplimentar la model. Detalii: [Workflow și JSON-LD](workflow/README.md).

## Cerințe

Configurația de dezvoltare și testare folosește Windows și Python 3.11, pe 64 de biți; instalarea inițială a fost verificată cu Python 3.11.11.

Sunt necesare:

- Python cu Tkinter disponibil;
- dependențele din `requirements.txt` și wheelul local PySceneDetect;
- FFmpeg pentru exportul scenelor;
- internet și o cheie API pentru furnizorul folosit la interpretare.

Extragerea, galeria și prelucrarea locală a ontologiei pot fi folosite fără o cheie API. Interfața actuală este orientată către Windows.

## Instalare

Comenzile următoare se execută în PowerShell.

### Obținerea proiectului

Versiunea cu interfața unificată este dezvoltată pe branchul `feature/interpretation`:

```powershell
git clone --branch feature/interpretation https://github.com/elena33e/VideoToKeyframes.git
cd VideoToKeyframes
```

Dacă proiectul există deja local, execută pașii următori din rădăcina lui.

### Mediul virtual și dependențele

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Comenzile folosesc direct interpretul mediului virtual; activarea acestuia nu este necesară. Se recomandă un mediu nou, fără pachete preluate din alte proiecte.

Wheelul următor trebuie să fie prezent în repository:

```text
wheels/scenedetect_core-0.7.2-py3-none-any.whl
```

Proiectul folosește un wheel construit din configurația `scenedetect-core` a sursei PySceneDetect, pentru a permite folosirea `opencv-contrib-python`, necesar pentru Katna. Nu instala suplimentar `opencv-python`, variante OpenCV headless sau `scenedetect[opencv]` în același mediu: distribuțiile furnizează același modul `cv2`.

Opțiunea `--only-binary katna` din `requirements.txt` solicită instalarea Katna din wheel. Dependențele principale sunt configurate în acel fișier; nu toate versiunile și dependențele tranzitive sunt fixate exact.

### Verificarea Tkinter și FFmpeg

```powershell
.\.venv\Scripts\python.exe -m tkinter
.\.venv\Scripts\python.exe -c "from scenedetect import is_ffmpeg_available; print(is_ffmpeg_available())"
```

Prima comandă trebuie să deschidă fereastra demonstrativă Tkinter, iar a doua să afișeze `True`.

FFmpeg poate fi furnizat de `imageio-ffmpeg`, instalat ca dependență a Katna, sau de un executabil disponibil în `PATH`, în funcție de configurația PySceneDetect.

## Configurarea furnizorilor VLM

Creează `.env` în rădăcina proiectului. De exemplu, pentru OpenAI:

```dotenv
VLM_PROVIDER=openai
OPENAI_API_KEY=cheia_ta
```

Este suficientă cheia furnizorului pe care îl folosești. Poți configura mai mulți furnizori și poți schimba selecția din GUI.

| Furnizor | Valoare `VLM_PROVIDER` | Cheie API | Model inițial opțional |
|---|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| Gemini | `gemini` | `GEMINI_API_KEY` | `GEMINI_MODEL` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` |

Dacă `VLM_PROVIDER` lipsește, aplicația pornește cu `openrouter`. Dacă variabila modelului lipsește, lansatorul folosește `DEFAULT_MODELS` din `interpretation/config.py`. Aceste valori sunt configurația proiectului; disponibilitatea modelelor, limitele și costurile depind de furnizor.

Variabilele deja definite în mediul procesului au prioritate față de `.env`. Fișierul `.env` este exclus din Git. Repornește aplicația după schimbarea cheilor sau a configurației de pornire.

### Configurația interpretării

| Element | Locație | Rol |
|---|---|---|
| `DEFAULT_MODELS` | `interpretation/config.py` | Modelul inițial pentru fiecare furnizor |
| `DEFAULT_LANGUAGE` | `interpretation/config.py` | Limba implicită: română |
| `DEFAULT_DOMAIN_CONTEXT` | `interpretation/config.py` | Domeniul implicit: încondeierea ouălor |
| `DEFAULT_MIN_REQUEST_INTERVAL_SECONDS` | `interpretation/config.py` | Intervalul minim între începuturile cererilor: 13 secunde |
| `InterpretationConfig.max_output_tokens_per_image` | `interpretation/config.py` | Bugetul de ieșire folosit la calcularea limitei cererii: 4.096 de tokeni per imagine |
| `MAX_GROUP_SIZE` | `interpretation/contracts.py` | Limita aplicației: 4 imagini per cerere |
| `PROMPT_VERSION` | `interpretation/prompting.py` | Versiunea instrucțiunilor de interpretare |

Furnizorul, modelul, limba, domeniul și numărul imaginilor per apel sunt editabile în GUI. Pentru interpretare fără context de domeniu, golește câmpul domeniului. Ontologia este activată separat.

Limita totală de ieșire a unei cereri este bugetul per imagine înmulțit cu numărul imaginilor din grup. Consumul raportat de API aparține întregii cereri.

## Pornire

### Interfața unificată

```powershell
.\.venv\Scripts\python.exe run_workflow_gui.py
```

În PyCharm, selectează interpretul `.venv/Scripts/python.exe` și rulează `run_workflow_gui.py` cu **Run**.

### Diagnosticul extragerii

```powershell
.\.venv\Scripts\python.exe run_diagnostics.py
```

Lansatorul deschide interfața de extragere din `gui/app.py`, cu monitorizarea performanței. Monitorul încearcă să salveze `performance.json`; indisponibilitatea diagnosticului nu trebuie să oprească extragerea.

Această interfață nu include interpretarea VLM. Monitorizarea poate introduce un cost suplimentar de execuție; pentru utilizarea obișnuită folosește interfața unificată. Rulează diagnosticul fără un alt profiler activ.

## Utilizare

### 1. Alegerea sursei

Pentru un videoclip, selectează fișierul și directorul rezultatelor. Configurează intervalul și limita opțională de cadre; pragul detectorului și procesele Katna sunt în **Setări avansate de extragere**. Apasă **Extrage cadrele**.

Pentru imagini existente, alege **Am deja imagini**, apoi **Încarcă imaginile…**. Sunt acceptate JPEG, PNG și WEBP. Imaginile sunt folosite din locația originală, fără copiere, și nu primesc scene sau intervale temporale artificiale.

### 2. Selectarea imaginilor

Apasă pe o miniatură pentru previzualizare și bifează imaginile relevante. Selecția pentru analiză este independentă de previzualizare. Apasă **Continuă cu … imagini**.

### 3. Configurarea și pornirea interpretării

Alege furnizorul, modelul, limba, domeniul și numărul imaginilor per apel. Interfața folosește implicit grupuri de 3 imagini; sunt permise 1–4.

Pregătește opțional contextul ontologic, verifică rezumatul și apasă **Descrie cele … imagini**.

Grupurile sunt procesate succesiv. Fiecare imagine are propria observație; promptul cere interpretări independente, fără transferarea faptelor sau presupunerea continuității temporale între cadre.

O eroare de pregătire poate afecta un singur cadru. O cerere eșuată sau un răspuns invalid poate afecta întregul grup; procesarea continuă cu grupurile următoare.

Intervalul minim dintre cereri se măsoară între începuturile acestora. Durata apelului este inclusă în interval; nu se adaugă automat încă 13 secunde după răspuns.

### 4. Examinarea și regenerarea rezultatelor

În **Rezultate**, alege o imagine selectată și consultă filele **Descriere** și **JSON-LD**. Deselecția ascunde imaginea din lista rezultatelor, fără să șteargă observația din sesiune.

Descrierile existente sunt păstrate fără apeluri noi dacă imaginile nu s-au schimbat și regenerarea nu este activată. Pentru refacerea lor, inclusiv după schimbarea modelului, furnizorului, domeniului, limbii sau ontologiei, activează **Regenerează și descrierile existente la următoarea analiză**.

Dacă o regenerare eșuează, ultima observație validă este păstrată împreună cu eroarea ultimei încercări. Dacă imaginea s-a schimbat, reutilizarea observației este blocată până la regenerarea explicită.

Poți reveni între pași fără să pierzi selecția sau observațiile existente.

### Salvarea și anularea

**Salvează sesiunea…** și **Salvează rezultatele…** salvează sesiunea în JSON-LD la destinația aleasă. Afișarea rezultatelor nu salvează automat fișierul.

Sesiunea include referințele către toate imaginile, selecția, stările, observațiile disponibile, configurația curentă și contextul pregătit. Imaginile nu sunt încorporate în JSON-LD; mutarea sau ștergerea lor afectează accesul ulterior.

**Oprește după operația curentă** solicită oprirea între operații. Un apel VLM sau o operație de extragere în curs poate trebui să se încheie; rezultatele primite până la oprire sunt păstrate. Salvează sesiunea pentru a le conserva.

**Reîncărcarea unei sesiuni JSON-LD în GUI nu este încă implementată.**

## Contextul ontologic

În pasul de configurare, activează **Ghidează descrierea folosind o ontologie**, încarcă fișierul, verifică namespace-ul propus și apasă **Pregătește contextul**.

Pentru context sunt acceptate RDF/XML, Turtle și N-Triples. Pentru `.owl` se presupune RDF/XML; selectează explicit Turtle dacă fișierul are acel conținut. Namespace-ul propus este editabil și trebuie verificat.

### Informații selectate

Extragerea pornește de la IRI-urile din namespace-ul propriu și păstrează:

- etichete, sinonime, definiții și comentarii recunoscute, dacă există;
- declarații de tip selectate;
- relații simple: subclasă, subproprietate, domeniu, interval și ierarhii SKOS;
- metadatele disponibile ale termenilor externi referiți direct.

Expresiile OWL complexe, regulile SWRL, metadatele administrative și relațiile din afara selecției simple sunt omise. Selecția este structurală, pe baza namespace-ului și a predicatelor; nu este o căutare a tripletelor relevante pentru fiecare imagine. Nu se execută inferență și nu se încarcă automat `owl:imports`.

Contextul Turtle și raportul pot fi consultate în **Vezi contextul și detaliile**. Contextul poate fi exportat separat.

### Reutilizarea sursei

Citirea RDF, construirea catalogului, propunerea namespace-urilor și extragerea contextului sunt separate în pachetul `ontology`.

La pregătirea contextului, fișierul este recitit pentru verificarea amprentei. Graful existent este reutilizat dacă fișierul, formatul și amprenta corespund sursei păstrate; altfel, sursa este parsată din nou. Schimbarea namespace-ului necesită refacerea selecției, fără să impună reparsarea unei surse neschimbate.

Schimbarea fișierului, formatului sau namespace-ului invalidează contextul pregătit. La pornirea interpretării se verifică din nou amprenta fișierului, pentru a evita utilizarea unui context devenit neactual.

### Rolul ontologiei în interpretare

Pentru entitățile de domeniu identificate cu suficientă certitudine, promptul cere etichete furnizate de ontologie sau, în lipsa lor, numele locale din IRI. În descriere sunt permise forme gramaticale naturale ale termenilor.

Identificările incerte folosesc denumiri neutre. Ipotezele despre identitate, materiale, activități sau etape trebuie susținute vizual, formulate cu precauție și explicate în `uncertainties`. Contextul de domeniu sau prezența unui termen în ontologie nu confirmă singure identificarea.

Relațiile dintre entități sunt formulate în limbaj natural; nu sunt limitate la proprietățile ontologiei. Lipsa unui termen potrivit este diferențiată de incertitudinea vizuală.

Acestea sunt instrucțiuni pentru model. Validarea structurii nu garantează corectitudinea vizuală sau respectarea terminologiei. Nu se creează indivizi și nu se populează ontologia în această etapă.

## Observațiile și JSON-LD

Clasele Pydantic definesc schema răspunsului, transmisă API-ului prin `response_format`. La primire sunt verificate structura, referințele dintre entități și corespondența rezultatelor cu imaginile trimise.

O observație include `description`, `entities`, `relations`, `actions`, `visible_text` și `uncertainties`. Aplicația adaugă modelul, furnizorul, versiunea promptului, amprenta imaginii, configurația cererii și metadatele disponibile de consum.

JSON-LD este construit local, cu identificatori absoluți și un context definit de aplicație. Proveniența fiecărei observații păstrează configurația efectiv folosită, separat de configurația curentă a sesiunii.

La procesarea pe grupuri, durata și `usage.request_usage` aparțin întregii cereri. Observațiile din același grup pot repeta aceste metadate; consumul trebuie numărat o singură dată per cerere.

Detalii despre schema exportului: [workflow/README.md](workflow/README.md).

## Cum funcționează extragerea

PySceneDetect identifică scenele folosind `ContentDetector`. Pipeline-ul comasează fragmentele mai scurte de 0,5 secunde, distribuie numărul solicitat de cadre și exportă scenele selectate prin FFmpeg. Katna alege imaginile reprezentative din fiecare clip.

Dacă după comasare rezultă o singură scenă, videoclipul original este transmis direct către Katna. Scenele sunt procesate succesiv; Katna folosește intern procesare paralelă.

Fără limită globală, cererea pentru fiecare scenă este:

```text
cadre solicitate = max(1, ceil(durata scenei / secunde per keyframe))
```

Un interval de 15 secunde și o scenă de 40 de secunde solicită trei cadre. Intervalul controlează numărul solicitat, nu extragerea la momente temporale fixe.

Dacă limita permite câte un cadru pentru fiecare scenă, pipeline-ul rezervă aceste cadre și distribuie restul proporțional cu cererea suplimentară. Dacă limita este mai mică decât numărul scenelor, sunt selectate scene distribuite pe durata videoclipului.

Limita este un plafon: Katna poate produce mai puține imagini decât cele solicitate. Numerotarea imaginilor nu garantează ordinea lor cronologică în interiorul scenei.

| Parametru | Efect |
|---|---|
| Secunde de scenă / keyframe | Controlează numărul de cadre solicitate |
| Limită globală | Plafonează cererea; poate omite scene |
| Prag detectare | Un prag mai mic produce, în general, mai multe delimitări |
| Procese Katna | Controlează paralelismul intern; mai multe procese nu garantează accelerarea |

Pragul comasării este `MIN_SCENE_DURATION_SECONDS` în `extraction/pipeline.py`. Fereastra Katna este `KATNA_WINDOW_FRAMES` în `extraction/keyframe_extractor.py`. Nu sunt editabile din GUI.

`ExtractionSettings` validează parametrii numerici. Interfețele păstrează verificări suplimentare pentru prag, fișiere, destinație și capacitatea calculatorului; pipeline-ul și serviciile își verifică propriile condiții de executare.

## Fișierele rezultate

Fiecare extragere creează un director separat:

```text
output/
└── videoclip_DATA_ORA_ID/
    ├── scenes/
    ├── keyframes/
    ├── manifest.json
    └── performance.json
```

| Fișier sau director | Conținut |
|---|---|
| `scenes/` | Clipurile exportate; poate lipsi când este folosit direct videoclipul original |
| `keyframes/` | Imaginile extrase, organizate pe scene |
| `manifest.json` | Configurația, intervalele scenelor, cadrele, stările și erorile extragerii |
| `performance.json` | Diagnosticul opțional, dacă monitorizarea și salvarea raportului au reușit |
| `workflow_<session_id>.jsonld` | Sesiunea, salvată separat la destinația aleasă în GUI |

Manifestul este actualizat pe parcursul extragerii și la final. O închidere forțată poate lăsa ultima stare salvată, fără finalizarea raportului.

Intervalele temporale aparțin scenelor. Momentul exact al fiecărui keyframe nu este disponibil.

| Stare a extragerii | Semnificație |
|---|---|
| `success` | Toate scenele selectate au produs cel puțin o imagine validă |
| `partial` | Există imagini valide, dar unele scene au eșuat |
| `failed` | Eroare critică sau nicio imagine extrasă |
| `cancelled` | Procesare oprită; rezultatele deja obținute sunt păstrate |

Scenele omise intenționat prin limita globală nu reprezintă erori. Succesul tehnic al extragerii nu garantează relevanța semantică a imaginilor.

Raportul de performanță include timpi de detectare, export, extragere și selecție. Unele măsurători se suprapun și nu trebuie însumate ca etape independente. Nu reprezintă o măsurare completă CPU/RAM.

## Structura proiectului

```text
VideoToKeyframes/
├── extraction/
│   ├── factory.py
│   ├── interfaces.py
│   ├── models.py
│   ├── scene_detector.py
│   ├── keyframe_extractor.py
│   ├── pipeline.py
│   └── performance_monitor.py
├── interpretation/
│   ├── config.py
│   ├── contracts.py
│   ├── images.py
│   ├── jsonld_context.py
│   ├── observations.py
│   ├── prompting.py
│   ├── service.py
│   └── strategies/
│       ├── base.py
│       ├── factory.py
│       ├── _chat_completions.py
│       ├── openai.py
│       ├── gemini.py
│       └── openrouter.py
├── ontology/
│   ├── reader.py
│   ├── models.py
│   ├── catalog.py
│   ├── context.py
│   └── namespaces.py
├── workflow/
│   ├── models.py
│   ├── service.py
│   ├── description.py
│   ├── description_batch.py
│   ├── jsonld.py
│   ├── persistence.py
│   └── README.md
├── gui/
│   ├── workflow_app.py
│   ├── keyframe_gallery.py
│   ├── formatting.py
│   └── app.py
├── tests/
│   ├── test_description_batches.py
│   ├── test_interpretation_service.py
│   ├── test_vlm_strategies.py
│   └── test_workflow_gui.py
├── wheels/
│   └── scenedetect_core-0.7.2-py3-none-any.whl
├── run_workflow_gui.py
├── run_diagnostics.py
├── run_ontology_context_test.py
├── requirements.txt
├── README.md
└── .gitignore
```

Fișierele `__init__.py` sunt omise din schemă.

| Pachet | Responsabilitate |
|---|---|
| `extraction` | Construirea pipeline-ului, scenele, keyframe-urile și diagnosticul |
| `interpretation` | Prompturile, contractele, strategiile VLM și validarea observațiilor |
| `ontology` | Citirea RDF, catalogul, namespace-urile și contextul pentru interpretare |
| `workflow` | Sesiunea, selecția, procesarea pe grupuri și salvarea JSON-LD |
| `gui` | Interfețele, galeria, previzualizările și formatarea pentru afișare |
| `tests` | Verificările automate ale comportamentelor implementate |

Strategiile implementează un contract comun, iar funcțiile din modulele `factory.py` construiesc strategiile și pipeline-ul. Componentele detectorului și extractorului sunt injectate prin constructorul pipeline-ului.

## Testare

Rulează din rădăcina proiectului:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Suita verifică strategiile și parametrii cererilor, validarea răspunsurilor, selecția, fluxurile interfeței, contextul ontologic și reutilizarea grafului. Testele procesării pe grupuri verifică anularea, păstrarea observațiilor la regenerare eșuată, evitarea apelurilor inutile și respingerea unui grup cu rezultate invalide.

Apelurile VLM sunt simulate. Testele automate nu consumă tokeni, nu verifică disponibilitatea reală a furnizorilor și nu evaluează calitatea descrierilor AI. Testele GUI necesită Tkinter și folosesc fișiere temporare locale.

Extragerea video reală se verifică separat, în ambele interfețe. Pentru evaluarea interpretării sunt necesare exemple vizuale și apeluri reale la furnizori.

`run_ontology_context_test.py` este un script manual pentru verificarea stabilității contextului și a parsării Turtle. Sursa și namespace-ul sunt configurate în acel fișier; scriptul nu face parte din suita automată și exportă în `output/ontology_context_reference/`.

## Limitări și etape următoare

- Maparea observațiilor la clasele și proprietățile ontologiei nu este implementată.
- Nu este stabilită identitatea obiectelor sau continuitatea temporală între cadre.
- Reîncărcarea sesiunilor salvate nu este disponibilă în GUI.
- API-ul aplicației și un frontend separat nu sunt implementate.
- Sesiunile conțin căi către imaginile locale, fără împachetarea acestora pentru transfer.
- Limitele și erorile furnizorilor pot întrerupe cererile VLM; un răspuns valid structural poate conține interpretări incorecte.
- Pentru extrageri simultane, configurația globală Katna și instanțele extractorului necesită izolare sau sincronizare.

## Întreținerea wheelului PySceneDetect

Wheelul inclus folosește sursa corespunzătoare commitului:

```text
7cd1005e8349d8e913d0930fc1750363eb4ddc51
```

Reconstruire din rădăcina proiectului:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir .\wheels "https://github.com/Breakthrough/PySceneDetect/archive/7cd1005e8349d8e913d0930fc1750363eb4ddc51.zip"
```

Reconstruirea necesită internet și nu este necesară dacă wheelul existent este potrivit configurației. La actualizare, verifică metadatele, compatibilitatea cu OpenCV contrib și rezultatele extragerii, apoi actualizează calea din `requirements.txt` dacă numele fișierului se schimbă.

## Fișiere locale

`.gitignore` exclude `.venv/`, `.venv-test/`, `.env`, configurația PyCharm, fișierele Python generate, `output/`, `test_videos/` și fragmentele temporare Katna din `clipped/`.

Exporturile salvate în alte directoare nu sunt excluse automat de regula pentru `output/`. Wheelul necesar instalării este păstrat în repository. Păstrează imaginile împreună cu datele necesare accesării rezultatelor salvate.

## Biblioteci principale

- **PySceneDetect și FFmpeg:** detectarea scenelor și exportul clipurilor.
- **Katna, OpenCV și NumPy:** procesarea video și selecția cadrelor.
- **Pillow și Tkinter:** imaginile, previzualizările și interfața desktop.
- **HTTPX:** comunicarea cu API-urile OpenAI, Gemini și OpenRouter.
- **Pydantic:** schemele JSON și validarea configurației, observațiilor și sesiunilor.
- **RDFLib:** citirea și prelucrarea grafurilor ontologice.
- **python-dotenv:** încărcarea configurației locale din `.env`.
