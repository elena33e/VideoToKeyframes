# VideoToKeyframes

Aplicație desktop pentru extragerea cadrelor reprezentative din videoclipuri, selectarea lor manuală și generarea descrierilor cu ajutorul unui model vizual de limbaj — VLM.

Extragerea folosește **PySceneDetect** pentru detectarea scenelor și **Katna** pentru selectarea keyframe-urilor. Imaginile selectate de utilizator sunt descrise prin API-ul OpenRouter, iar rezultatele pot fi salvate în **JSON-LD**.

Aplicația permite și încărcarea directă a unor imagini existente, fără procesarea unui video.

## Funcționalități

- Detectarea scenelor și comasarea fragmentelor foarte scurte.
- Extragerea unui număr de cadre adaptat duratei fiecărei scene.
- Limitarea opțională a numărului total de cadre.
- Configurarea numărului de procese utilizate de Katna.
- Păstrarea rezultatelor valide când unele scene nu pot fi procesate.
- Galerie cu miniaturi, previzualizare și selecție prin bifare.
- Încărcarea directă a imaginilor JPEG, PNG și WEBP.
- Descrierea imaginilor selectate: obiecte, caracteristici, relații, acțiuni, text vizibil și incertitudini.
- Afișarea observațiilor și salvarea sesiunii în JSON-LD.
- Pregătirea unui vocabular compact din ontologie, opțional pentru ghidarea descrierii.
- Diagnosticarea separată a performanței extragerii.

**Maparea observațiilor la ontologia încărcată nu este încă implementată.** VLM-ul poate primi contextul Turtle extras local, pentru ghidarea vocabularului. Folosirea lui este opțională.

## Fluxul aplicației

```text
Video → extragere keyframes ──┐
                             ├→ galerie → selecție → descriere VLM → JSON-LD
Imagini încărcate direct ─────┘

Ontologie + namespace → vocabular Turtle → context opțional pentru descrierea VLM
```

O sesiune conține fie cadrele unei extrageri, fie imagini încărcate direct. Începerea unei noi extrageri sau încărcarea unui nou set de imagini înlocuiește sesiunea din interfață, după confirmare dacă există modificări nesalvate.

VLM-ul produce observații în JSON conform unei scheme. Aplicația validează structura și referințele dintre entități, adaugă metadatele și construiește local JSON-LD. Această conversie nu necesită un apel suplimentar la model.

Detalii despre reprezentare: [Workflow și JSON-LD](workflow/README.md).

## Cerințe

Configurația folosită la testare:

- Windows;
- Python 3.11.11, pe 64 de biți;
- Tkinter disponibil;
- dependențele din `requirements.txt`;
- FFmpeg disponibil pentru procesarea video;
- acces la internet și o cheie OpenRouter pentru descrierea imaginilor.

Extragerea, galeria și încărcarea ontologiei pot fi folosite fără cheia API.

FFmpeg poate fi furnizat de `imageio-ffmpeg`, instalat ca dependență a Katna. PySceneDetect poate folosi și un executabil FFmpeg disponibil în `PATH`.

## Instalare

Comenzile următoare se execută în PowerShell.

### 1. Obținerea proiectului

Versiunea cu interfața unificată este dezvoltată pe branchul `feature/interpretation`:

```powershell
git clone --branch feature/interpretation https://github.com/elena33e/VideoToKeyframes.git
cd VideoToKeyframes
```

### 2. Crearea mediului virtual

```powershell
py -3.11 -m venv .venv
```

Se recomandă un mediu virtual nou, fără pachete preluate din alte proiecte.

### 3. Instalarea dependențelor

Verifică existența wheelului inclus în proiect:

```text
wheels/scenedetect_core-0.7.2-py3-none-any.whl
```

Apoi rulează:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Comenzile folosesc direct interpretul mediului virtual; activarea acestuia nu este necesară.

### 4. Verificarea componentelor

Pentru Tkinter:

```powershell
.\.venv\Scripts\python.exe -m tkinter
```

Pentru disponibilitatea FFmpeg în PySceneDetect:

```powershell
.\.venv\Scripts\python.exe -c "from scenedetect import is_ffmpeg_available; print(is_ffmpeg_available())"
```

Rezultatul așteptat pentru FFmpeg este `True`.

## Particularități ale dependențelor

Proiectul folosește un wheel local construit din configurația `scenedetect-core` a sursei PySceneDetect. Acesta permite utilizarea `opencv-contrib-python`, necesar pentru Katna, fără instalarea simultană a `opencv-python`.

Cele două distribuții OpenCV furnizează același modul `cv2`. Nu instala suplimentar `scenedetect[opencv]`, `opencv-python` sau variante OpenCV headless în acest mediu.

Opțiunea `--only-binary katna` din `requirements.txt` impune instalarea Katna din wheel. Configurația proiectului a fost testată cu Python 3.11.11 și Katna 0.9.2.

Dependențele principale sunt fixate în `requirements.txt`; dependențele tranzitive nu sunt toate fixate individual.

## Configurarea descrierii imaginilor

Creează un fișier `.env` în rădăcina proiectului:

```dotenv
OPENROUTER_API_KEY=cheia_ta
OPENROUTER_MODEL=nvidia/nemotron-3.5-super-vl:free
```

`OPENROUTER_MODEL` este opțional. Dacă lipsește, aplicația folosește modelul implicit din `interpretation/config.py`. Variabilele deja definite în mediul procesului au prioritate față de `.env`.

Fișierul `.env` este exclus din Git.

Valorile implicite sunt centralizate în `interpretation/config.py`:

| Constantă | Rol |
|---|---|
| `DEFAULT_MODEL` | Modelul folosit implicit |
| `DEFAULT_LANGUAGE` | Limba descrierilor |
| `DEFAULT_DOMAIN_CONTEXT` | Domeniul folosit pentru ghidarea observației vizuale |

Configurația actuală folosește limba engleză și domeniul încondeierii ouălor. Pentru testarea fără domeniu, setează `DEFAULT_DOMAIN_CONTEXT = ""`. Repornește aplicația după modificarea configurației.

Domeniul poate ghida atenția modelului, dar nu confirmă prezența unui obiect, material sau procedeu. El este independent de ontologia încărcată.

Modelul poate fi modificat și în GUI. Interfața de test acceptă identificatori terminați în `:free`; disponibilitatea și limitele lor depind de OpenRouter.

## Pornirea aplicației

### Interfața unificată

```powershell
.\.venv\Scripts\python.exe run_workflow_gui.py
```

Din PyCharm, selectează interpretul `.venv/Scripts/python.exe` și pornește `run_workflow_gui.py` cu **Run**.

### Diagnosticarea extragerii

```powershell
.\.venv\Scripts\python.exe run_diagnostics.py
```

Acest lansator deschide interfața separată de extragere din `gui/app.py`, păstrată pentru diagnosticare. Monitorul încearcă să genereze suplimentar raportul `performance.json`.

Diagnosticarea nu include fluxul de descriere VLM. Monitorizarea poate introduce un cost suplimentar de execuție; pentru utilizarea obișnuită folosește interfața unificată.

## Utilizarea interfeței unificate

### Extragerea din video

1. În **1. Sursă**, alege pornirea de la un videoclip și directorul rezultatelor.
2. Configurează intervalul și limita de cadre. Pragul detectorului și procesele sunt în **Setări avansate de extragere**.
3. Apasă **Extrage cadrele**.
4. Aplicația deschide **2. Selectare imagini**.

### Încărcarea imaginilor existente

În **1. Sursă**, alege **Am deja imagini**, apoi **Încarcă imaginile…**.

Fișierele sunt utilizate din locația originală, fără copiere. Dacă le muți sau le ștergi, sesiunea nu le mai poate accesa. Pentru acestea nu sunt atribuite artificial scene sau intervale temporale.

### Selecția și descrierea

1. În **2. Selectare imagini**, apasă pe miniaturi pentru previzualizare și bifează imaginile relevante.
2. Apasă **Continuă cu … imagini**.
3. În **3. Configurare interpretare**, verifică domeniul, limba și modelul; pregătește opțional contextul ontologic.
4. Verifică rezumatul și apasă **Descrie cele … imagini**.
5. În **4. Rezultate**, alege imaginea din listă și consultă **Descriere** sau **JSON-LD**.

Poți reveni între pași fără să pierzi selecția sau rezultatele.

Descrierea se execută secvențial pentru imaginile selectate. O eroare este asociată imaginii respective și nu oprește automat restul lotului.

Observațiile existente sunt păstrate fără un nou apel dacă imaginea nu s-a schimbat și regenerarea nu este bifată. Pentru repetarea analizei, inclusiv după schimbarea modelului, domeniului sau contextului, bifează regenerarea în **4. Rezultate**, apoi revino la configurare.

### Ontologia

În **3. Configurare interpretare**, activează **Ghidează descrierea folosind o ontologie**.
Încarcă fișierul RDF/XML, Turtle sau N-Triples, verifică namespace-ul propus (editabil)
și apasă **Pregătește contextul**. Pentru un fișier cu extensie ambiguă, selectează explicit formatul.

Contextul pornește de la IRI-urile proprii și păstrează referințele externe relevante.
Poți consulta și exporta Turtle-ul din **Vezi contextul și detaliile**.
Schimbarea fișierului, formatului sau namespace-ului invalidează contextul pregătit.
La pornirea analizei se verifică și dacă fișierul sursă s-a schimbat pe disc.
Același context este folosit pentru toate imaginile din lot; fiecare observație păstrează
textul și hash-ul contextului efectiv utilizat.

Cu context activ, promptul cere denumiri de domeniu din vocabularul furnizat:
etichete existente sau, în lipsa lor, numele locale din IRI. Termenii românești
sunt păstrați și când limba descrierii este alta. Detaliile vizuale rămân în
limbaj natural. Un obiect fără termen potrivit primește o descriere neutră,
iar lipsa termenului sau identificarea incertă se consemnează în incertitudini.
Relațiile structurate folosesc numai termeni de relație disponibili; dacă lipsesc,
aranjamentul vizual este descris în text. Nu se clasifică indivizi și nu se
populează ontologia în această etapă.

Acestea sunt instrucțiuni pentru model; validarea curentă verifică schema
răspunsului, nu garantează respectarea vocabularului sau identificarea corectă.

Încărcarea nu declanșează descriere, mapare sau inferență ontologică. Importurile externe declarate în ontologie nu sunt încărcate automat.

### Salvarea

Apasă **Salvează sesiunea…** sau **Salvează rezultatele…** și alege destinația.

Sesiunea include toate imaginile și stările lor, selecția, observațiile disponibile, configurația curentă și contextul pregătit. Salvarea este explicită; afișarea descrierilor nu salvează automat sesiunea.

**Reîncărcarea unei sesiuni salvate nu este încă implementată în GUI.**

### Anularea

**Oprește după operația curentă** solicită oprirea între operații. O operație de extragere sau o cerere VLM deja începută poate trebui să se încheie înainte de oprire.

Rezultatele obținute până atunci rămân disponibile. Pentru păstrarea observațiilor, salvează sesiunea.

## Cum funcționează extragerea

PySceneDetect identifică scenele folosind `ContentDetector`. Aplicația comasează fragmentele mai scurte de 0,5 secunde, calculează numărul de cadre solicitate și exportă scenele selectate prin FFmpeg. Katna analizează clipurile și alege imaginile reprezentative.

Dacă rezultă o singură scenă, videoclipul original este transmis direct către Katna.

Scenele sunt procesate succesiv. Katna folosește intern procesare paralelă, configurabilă din GUI.

Fără limită globală:

```text
cadre solicitate = max(1, ceil(durata scenei / secunde per keyframe))
```

Pentru un interval de 15 secunde, o scenă de 40 de secunde solicită trei cadre. Aceasta nu înseamnă extragerea unei imagini exact la fiecare 15 secunde; pozițiile sunt alese de Katna.

Dacă limita globală permite cel puțin un cadru pentru fiecare scenă, aplicația rezervă câte unul și distribuie restul proporțional cu cererea. Dacă limita este mai mică decât numărul scenelor, selectează scene distribuite pe durata videoclipului.

Limita este un plafon, nu o garanție: Katna poate furniza mai puține imagini decât cele solicitate.

| Parametru | Efect |
|---|---|
| Secunde de scenă / keyframe | Controlează numărul de cadre solicitate |
| Limită cadre | Plafonează planul de extragere; câmpul gol dezactivează limita |
| Prag detectare scene | Un prag mai mic produce, în general, mai multe delimitări |
| Procese Katna | Controlează paralelismul intern; creșterea valorii nu garantează accelerarea |

Pragul intern pentru comasare este definit prin `MIN_SCENE_DURATION_SECONDS` în `extraction/pipeline.py`. Fereastra Katna este de 15 cadre, definită prin `KATNA_WINDOW_FRAMES` în `extraction/keyframe_extractor.py`. Acești parametri nu sunt expuși în GUI.

## Rezultate și rapoarte

Fiecare extragere creează un director separat:

```text
output/
└── videoclip_DATA_ORA_ID/
    ├── scenes/
    ├── keyframes/
    ├── manifest.json
    └── performance.json
```

- `scenes/` conține clipurile exportate; poate lipsi pentru o singură scenă.
- `keyframes/` conține imaginile organizate pe scene.
- `manifest.json` conține setările, intervalele scenelor, cadrele, stările și erorile extragerii.
- `performance.json` apare numai dacă diagnosticarea a fost activată și raportul a putut fi salvat.
- `workflow_<session_id>.jsonld` este salvat separat, la destinația aleasă din GUI.

Manifestul este scris la încheierea controlată a extragerii. O închidere forțată poate lăsa rezultate fără raport final.

Intervalele temporale aparțin scenelor; momentul exact al fiecărui keyframe nu este disponibil. Numerotarea imaginilor nu garantează ordinea lor cronologică în scenă.

Raportul de performanță include timpi pentru detectare, export și extragere. Unele măsurători se suprapun și nu trebuie însumate ca etape independente. Raportul nu reprezintă o măsurare completă CPU/RAM.

### Stările extragerii

| Stare | Semnificație |
|---|---|
| `success` | Toate scenele selectate au produs cel puțin o imagine validă |
| `partial` | Există imagini salvate, dar unele scene au eșuat |
| `failed` | Eroare critică sau nicio imagine extrasă |
| `cancelled` | Procesarea a fost anulată; rezultatele deja salvate sunt păstrate |

Scenele omise intenționat prin limita globală nu fac automat rularea nereușită.

Succesul tehnic confirmă obținerea imaginilor, nu relevanța lor semantică. Similar, validarea observațiilor verifică structura datelor și referințele, fără să garanteze corectitudinea descrierii vizuale.

## Structura proiectului

```text
VideoToKeyframes/
├── extraction/
│   ├── interfaces.py
│   ├── models.py
│   ├── scene_detector.py
│   ├── keyframe_extractor.py
│   ├── pipeline.py
│   └── performance_monitor.py
├── interpretation/
│   ├── config.py
│   ├── describe.py
│   ├── observations.py
│   ├── ontology.py
│   ├── models.py
│   └── jsonld_context.py
├── workflow/
│   ├── models.py
│   ├── service.py
│   ├── description.py
│   ├── jsonld.py
│   └── README.md
├── gui/
│   ├── workflow_app.py
│   ├── keyframe_gallery.py
│   └── app.py
├── wheels/
│   └── scenedetect_core-0.7.2-py3-none-any.whl
├── run_workflow_gui.py
├── run_diagnostics.py
├── requirements.txt
├── README.md
└── .gitignore
```

Fișierele `__init__.py` ale pachetelor sunt omise din schemă.

| Componentă | Responsabilitate |
|---|---|
| `extraction` | Detectarea scenelor, extragerea cadrelor și rapoartele |
| `interpretation` | Apelul VLM, validarea observațiilor, configurația și încărcarea ontologiei |
| `workflow` | Sesiunea, selecția, procesarea imaginilor și exportul JSON-LD |
| `gui/workflow_app.py` | Interfața unificată și coordonarea operațiilor din fundal |
| `gui/keyframe_gallery.py` | Miniaturi, paginare, selecție și previzualizare |
| `gui/app.py` | Interfața de extragere păstrată pentru diagnosticare |

Serviciile sunt separate de interfață pentru a putea fi reutilizate ulterior prin endpointuri API. API-ul și frontendul separat nu sunt încă implementate.

Pentru extrageri simultane într-un viitor API, modificarea configurației globale Katna va necesita izolare sau sincronizare.

## Întreținerea wheelului PySceneDetect

Wheelul inclus folosește sursa corespunzătoare commitului:

```text
7cd1005e8349d8e913d0930fc1750363eb4ddc51
```

Reconstruire din rădăcina proiectului:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir .\wheels "https://github.com/Breakthrough/PySceneDetect/archive/7cd1005e8349d8e913d0930fc1750363eb4ddc51.zip"
```

Operația necesită internet și nu este necesară pentru instalarea obișnuită dacă wheelul există deja.

La actualizare trebuie reverificate metadatele, compatibilitatea cu OpenCV contrib și rezultatele extragerii. Actualizează și numele wheelului din `requirements.txt`, dacă se schimbă.

## Fișiere locale

`.gitignore` exclude mediile virtuale, `.env`, rezultatele din `output/`, videoclipurile locale de test, fișierele temporare Katna și configurația PyCharm.

Exporturile salvate în alte directoare nu sunt automat excluse de regula pentru `output/`.

Wheelul necesar instalării este păstrat în repository. Sesiunile JSON-LD conțin referințe la fișierele locale, nu copiile imaginilor; păstrează imaginile împreună cu rezultatele necesare.

## Biblioteci principale

- PySceneDetect și FFmpeg — detectarea scenelor și exportul clipurilor.
- Katna și OpenCV — selecția și procesarea cadrelor.
- Pillow și Tkinter — imaginile și interfața grafică.
- HTTPX — comunicarea cu OpenRouter.
- Pydantic — validarea observațiilor și a sesiunii.
- RDFLib — încărcarea ontologiilor.
- python-dotenv — încărcarea configurației locale din `.env`.
