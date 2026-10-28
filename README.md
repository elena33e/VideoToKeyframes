# VideoToKeyframes

Aplicație desktop pentru extragerea cadrelor reprezentative din videoclipuri, folosind **PySceneDetect** pentru detectarea scenelor și **Katna** pentru selectarea keyframe-urilor.

Scopul aplicației este obținerea unor imagini reprezentative pentru scenele unui videoclip, cu un număr de cadre adaptat duratei fiecărei scene.

Interfața permite configurarea procesării, urmărirea progresului și previzualizarea imaginilor obținute.

## Funcționalități

- Detectarea automată a schimbărilor de scenă.
- Comasarea fragmentelor foarte scurte cu o scenă vecină.
- Calcularea numărului de cadre solicitate în funcție de durata scenei.
- Selectarea keyframe-urilor prin algoritmii Katna.
- Limitarea opțională a numărului total de cadre.
- Configurarea numărului de procese utilizate de Katna.
- Păstrarea rezultatelor valide când extragerea eșuează pentru unele scene.
- Anularea procesării între operațiile principale.
- Previzualizarea cadrelor extrase.
- Generarea unui raport al rulării și, opțional, a unui raport de performanță.

## Fluxul de procesare

1. PySceneDetect analizează videoclipul și identifică intervalele scenelor folosind `ContentDetector`.
2. Aplicația unește fragmentele mai scurte de 0,5 secunde cu o scenă vecină.
3. Pentru fiecare scenă rezultată, aplicația calculează numărul de cadre solicitate.
4. Dacă este activată limita globală, planul este ajustat pentru respectarea acesteia.
5. Scenele selectate sunt exportate folosind funcția `split_video_ffmpeg` din PySceneDetect.
6. Katna analizează fiecare clip și selectează cadrele reprezentative.
7. Imaginile sunt salvate pe scene, iar aplicația generează raportul rulării.

Dacă rezultă o singură scenă, videoclipul original este transmis direct către Katna, fără exportul unui clip separat.

Scenele sunt procesate succesiv. Katna folosește intern procesare paralelă; numărul de procese se configurează din interfață.

## Cerințe

Configurația folosită la testare:

- Windows;
- Python 3.11.11, pe 64 de biți;
- Tkinter disponibil în instalarea Python;
- pachetele din `requirements.txt`;
- FFmpeg disponibil pentru bibliotecile utilizate.

Interfața folosește `os.startfile` pentru deschiderea folderului cu rezultate. Prin urmare, versiunea actuală este destinată Windows.

FFmpeg poate fi furnizat de pachetul `imageio-ffmpeg`, instalat ca dependență a Katna. PySceneDetect poate folosi și un executabil FFmpeg disponibil în `PATH`.

## Instalare

Comenzile următoare se execută în PowerShell.

### 1. Obținerea proiectului

```powershell
git clone https://github.com/elena33e/VideoToKeyframes.git
cd VideoToKeyframes
```

Alternativ, descarcă arhiva repository-ului și deschide un terminal în folderul extras.

### 2. Crearea unui mediu virtual

```powershell
py -3.11 -m venv .venv
```

Dacă Python Launcher (`py`) nu este disponibil, folosește executabilul instalării Python 3.11.

Se recomandă un mediu virtual nou, fără pachete preluate din alte proiecte.

### 3. Instalarea dependențelor

Verifică existența fișierului:

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

`pip check` verifică cerințele declarate de pachete. Nu detectează toate conflictele posibile dintre fișierele instalate.

### 4. Verificarea componentelor

Verificarea Tkinter:

```powershell
.\.venv\Scripts\python.exe -m tkinter
```

Comanda trebuie să deschidă o fereastră de test.

Verificarea disponibilității FFmpeg pentru PySceneDetect:

```powershell
.\.venv\Scripts\python.exe -c "from scenedetect import is_ffmpeg_available; print(is_ffmpeg_available())"
```

Rezultatul așteptat este `True`.

## Particularități ale dependențelor

### De ce este folosit un wheel local pentru PySceneDetect?

Distribuția standard PySceneDetect 0.7.2 declară o dependență de `opencv-python`, în timp ce Katna solicită `opencv-contrib-python`.

Cele două pachete OpenCV furnizează același modul `cv2` și pot instala fișiere în aceleași locații.

Proiectul folosește un wheel construit din configurația `scenedetect-core` a sursei oficiale PySceneDetect 0.7.2. Aceasta permite utilizarea unui singur pachet OpenCV: `opencv-contrib-python`.

Wheelul este construit local; nu reprezintă un pachet `scenedetect-core` 0.7.2 descărcat de pe PyPI. Importurile din aplicație rămân `scenedetect`.

Nu instala suplimentar `scenedetect[opencv]`, `opencv-python` sau variantele OpenCV headless în acest mediu.

### De ce apare `--only-binary katna`?

Această opțiune solicită instalarea Katna dintr-un wheel și împiedică revenirea automată la instalarea din surse.

Pentru Katna 0.9.2 există o neconcordanță între metadatele wheelului și restricția de versiune Python din scriptul de instalare din surse. Configurația proiectului a fost testată cu Python 3.11.11 și wheelul Katna 0.9.2.

Această verificare locală nu constituie o garanție de compatibilitate pentru alte versiuni Python.

Fișierul `requirements.txt` fixează dependențele principale. Dependențele tranzitive nu sunt toate fixate individual.

## Pornirea aplicației

### Rulare obișnuită

```powershell
.\.venv\Scripts\python.exe run_gui.py
```

Aplicația procesează videoclipul fără monitorizarea detaliată a performanței. Raportul `manifest.json` este generat în continuare.

### Rulare cu diagnostic

```powershell
.\.venv\Scripts\python.exe run_diagnostics.py
```

Se deschide aceeași interfață și se folosește același flux de procesare. Suplimentar, monitorul încearcă să genereze `performance.json`.

Monitorizarea poate introduce un cost suplimentar de execuție. Pentru utilizarea obișnuită, folosește `run_gui.py`.

Dacă diagnosticul nu poate porni sau raportul său nu poate fi salvat, aplicația afișează un avertisment în consolă și continuă procesarea atunci când este posibil.

### Rulare din PyCharm

Selectează drept interpret:

```text
.venv/Scripts/python.exe
```

Pornește `run_gui.py` sau `run_diagnostics.py` cu **Run**.

Pentru diagnostic, evită rularea simultană cu un alt profiler.

## Utilizarea interfeței

1. Selectează videoclipul.
2. Alege folderul pentru rezultate.
3. Configurează opțiunile.
4. Apasă **Start procesare**.
5. La final, folosește **Deschide rezultatele** sau **Vezi cadrele**.

| Opțiune | Rol |
| --- | --- |
| Secunde de scenă / keyframe | Controlează numărul de cadre solicitate în funcție de durata scenei. |
| Prag detectare scene | Controlează sensibilitatea detectorului la schimbările vizuale. |
| Procese Katna | Stabilește numărul de procese folosite intern de Katna. |
| Limitează numărul total de cadre | Activează un plafon global pentru planul de extragere. |

### Numărul de cadre pe scenă

În absența limitei globale, calculul este:

```text
cadre solicitate = max(1, ceil(durata scenei / secunde per keyframe))
```

Pentru un interval de 15 secunde:

| Durata scenei | Cadre solicitate |
| --- | ---: |
| 5 secunde | 1 |
| 15 secunde | 1 |
| 16 secunde | 2 |
| 40 de secunde | 3 |

Valoarea reprezintă numărul de cadre solicitate către Katna. Nu înseamnă extragerea unei imagini exact la fiecare 15 secunde; pozițiile cadrelor sunt stabilite prin selecția Katna.

Katna poate furniza mai puține imagini decât cele solicitate.

### Limita globală

Când limita este dezactivată, sunt planificate toate scenele rezultate după comasare.

Când limita este activată:

- dacă permite cel puțin un cadru pentru fiecare scenă, aplicația rezervă câte unul și distribuie cadrele suplimentare proporțional cu cererea;
- dacă este mai mică decât numărul scenelor, aplicația selectează scene distribuite pe durata videoclipului și solicită câte un cadru pentru fiecare.

Limita reprezintă un plafon, nu un număr de imagini garantat.

### Pragul de detectare

Un prag mai mic produce, în general, mai multe delimitări de scene. Un prag mai mare produce mai puține delimitări.

Detectarea se bazează pe schimbări vizuale și nu identifică automat toate schimbările de acțiune sau de semnificație.

### Numărul de procese

Creșterea numărului de procese nu garantează reducerea timpului de procesare. Rezultatul depinde de procesor, memorie, rezoluția videoclipului și costul pornirii proceselor.

### Anularea

Butonul **Anulează** solicită oprirea între operațiile principale.

O operație PySceneDetect, FFmpeg sau Katna aflată deja în desfășurare poate trebui să se încheie înainte de oprire. Rezultatele salvate sunt păstrate.

## Organizarea rezultatelor

Fiecare rulare creează un folder separat, cu numele videoclipului, data, ora și un identificator unic.

Exemplu orientativ:

```text
output/
└── videoclip_DATA_ORA_ID/
    ├── scenes/
    │   ├── scene_0001/
    │   │   └── scene-0001.mp4
    │   └── scene_0002/
    │       └── scene-0002.mp4
    ├── keyframes/
    │   ├── scene_0001/
    │   │   └── scene-0001_0.jpeg
    │   └── scene_0002/
    │       └── scene-0002_0.jpeg
    ├── manifest.json
    └── performance.json
```

`performance.json` este prezent numai dacă monitorizarea a fost activată și raportul a putut fi salvat.

Pentru o singură scenă, folderul `scenes/` poate lipsi, deoarece este utilizat videoclipul original.

Indicii scenelor pot avea întreruperi după comasare sau selecția impusă de limita globală.

Numerotarea imaginilor indică ordinea în care sunt furnizate de Katna. Nu garantează ordinea lor cronologică în scenă.

### `manifest.json`

Raportul conține:

- setările rulării;
- intervalele scenelor;
- numărul scenelor detectate, selectate, procesate și cu imagini;
- numărul cadrelor solicitate și salvate;
- căile imaginilor;
- starea fiecărei scene;
- erorile întâlnite;
- starea finală a procesării.

Intervalele temporale descriu scenele din videoclipul original. Momentul exact al fiecărui keyframe nu este disponibil în implementarea actuală.

Manifestul este scris la încheierea controlată a rulării. O închidere forțată a procesului poate lăsa rezultate fără raport final.

### `performance.json`

Raportul de diagnostic include timpi pentru detectare, export și extragere, precum și observații despre selecția Katna și crearea grupurilor de procese.

Unele măsurători sunt incluse în altele: selecția și filtrarea fac parte din extragere. Timpii nu trebuie însumați ca etape independente.

Raportul nu reprezintă o măsurare completă a utilizării CPU sau RAM.

## Interpretarea rezultatului

| Stare | Semnificație |
| --- | --- |
| `success` | Toate scenele selectate au produs cel puțin o imagine validă. |
| `partial` | Au fost salvate imagini, dar unele scene au eșuat. |
| `failed` | A apărut o eroare critică sau nu s-a extras nicio imagine. |
| `cancelled` | Procesarea a fost anulată; rezultatele deja salvate sunt păstrate. |

O rulare poate fi raportată ca reușită chiar dacă anumite scene au fost omise intenționat prin limita globală. Numărul acestora este afișat separat.

Succesul tehnic confirmă salvarea imaginilor, nu și relevanța lor pentru orice utilizare ulterioară. Calitatea se verifică prin previzualizare.

Mesajul „Katna nu a generat imagini valide” nu demonstrează că scena nu conține cadre relevante. Poate indica faptul că selecția internă nu a furnizat candidați acceptați.

## Structura proiectului

```text
VideoToKeyframes/
├── gui/
│   ├── __init__.py
│   └── app.py
├── wheels/
│   └── scenedetect_core-0.7.2-py3-none-any.whl
├── interfaces.py
├── scene_detector.py
├── keyframe_extractor.py
├── pipeline.py
├── performance_monitor.py
├── run_gui.py
├── run_diagnostics.py
├── requirements.txt
├── README.md
└── .gitignore
```

| Fișier                   | Responsabilitate |
|--------------------------| --- |
| `gui/app.py`             | Interfața, validarea opțiunilor, progresul și previzualizarea. |
| `interfaces.py`          | Modelul unei scene și contractele serviciilor. |
| `scene_detector.py`      | Detectarea scenelor și exportul clipurilor prin PySceneDetect. |
| `keyframe_extractor.py`  | Configurarea Katna, extragerea și salvarea verificată a imaginilor. |
| `pipeline.py`            | Comasarea scenelor, planificarea cadrelor și coordonarea procesării. |
| `performance_monitor.py` | Monitorizarea opțională și raportul de performanță. |
| `run_gui.py`             | Pornirea obișnuită. |
| `run_diagnostics.py`     | Pornirea cu monitorizare. |

## Parametri interni

În versiunea actuală:

- pragul pentru comasarea scenelor foarte scurte este de **0,5 secunde**, stabilit în `main.py`;
- fereastra Katna este de **15 cadre**, stabilită prin `KATNA_WINDOW_FRAMES` în `keyframe_extractor.py`.

Acești parametri nu sunt configurați din interfață.

Fereastra Katna se aplică prin configurația bibliotecii înainte de extragere. Proiectul nu modifică fișierele sursă instalate ale Katna.

## Întreținerea wheelului PySceneDetect

Wheelul folosește sursa oficială PySceneDetect corespunzătoare commitului:

```text
7cd1005e8349d8e913d0930fc1750363eb4ddc51
```

Pentru reconstruirea lui, din rădăcina proiectului:

```powershell
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir .\wheels "https://github.com/Breakthrough/PySceneDetect/archive/7cd1005e8349d8e913d0930fc1750363eb4ddc51.zip"
```

Operația necesită acces la internet. Nu este necesară pentru instalarea obișnuită dacă wheelul este inclus în repository.

La actualizarea PySceneDetect trebuie verificate din nou metadatele pachetului, compatibilitatea cu OpenCV contrib și rezultatele procesării. Numele wheelului din `requirements.txt` trebuie actualizat corespunzător.

## Fișiere locale excluse din Git

Repository-ul exclude mediul virtual, rezultatele, videoclipurile locale de test, fișierele temporare Katna și configurarea locală PyCharm.

Fișierul wheel necesar instalării trebuie inclus în Git.

Folderele unei rulări din `output/` pot fi șterse după ce rezultatele necesare au fost păstrate. Ștergerea clipurilor din `scenes/` împiedică inspectarea lor ulterioară, dar nu șterge imaginile din `keyframes/`.

## Biblioteci utilizate

- [PySceneDetect](https://www.scenedetect.com/) — detectarea scenelor și exportul clipurilor.
- [Katna](https://katna.readthedocs.io/) — selectarea keyframe-urilor.
- [OpenCV](https://opencv.org/) — operații asupra imaginilor și suport video.
- [FFmpeg](https://ffmpeg.org/) — procesarea și exportul video.
- [Pillow](https://python-pillow.org/) — previzualizarea imaginilor.
- [Tkinter](https://docs.python.org/3/library/tkinter.html) — interfața grafică.