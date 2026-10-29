# Flux de interpretare a keyframe-urilor și mapare la o ontologie

Data: 29 octombrie 2026  
Stare: propunere de referință pentru implementare; etapele de interpretare nu sunt încă implementate.

## Scop

Transformarea imaginilor extrase dintr-un videoclip în observații structurate și asocierea acestora cu conceptele unei ontologii țintă. Fluxul trebuie să poată fi adaptat la ontologii diferite fără logică specifică domeniului în cod. Ontologia încondeierii ouălor reprezintă un studiu de caz.

Pregătirea ontologiei este separată de interpretarea imaginilor. Ontologia orientează detaliile urmărite, iar atribuirea conceptelor se face după observația vizuală.

## Privire de ansamblu

```text
Ontologie → catalog de concepte și index pentru căutare
                         ↓
Keyframe → observație structurată → concepte candidate → mapare
                ↑                                          ↓
                └── completare prin verificare vizuală, la nevoie
                                                           ↓
                              consolidare pe scenă → export
```

## Principii

- Separarea observației vizuale de interpretarea în termenii ontologiei.
- O schemă de observație de bază, stabilă, completată cu aspecte relevante derivate din ontologie.
- Dovezi și proveniență pentru fiecare asociere: observații, entități și cadre sursă.
- Posibilitatea de a alege un concept mai general sau de a răspunde `unmapped`.
- Separarea faptelor observate de ipoteze și de concluziile inferate.
- Salvarea rezultatelor intermediare pentru inspecție și reluarea independentă a etapelor.
- Fluxul de procesare nu presupune adnotarea manuală prealabilă a imaginilor. Evaluările automate nu sunt tratate drept măsurători certe ale corectitudinii.

## 1. Pregătirea ontologiei

Se execută o dată pentru fiecare versiune a ontologiei și a configurației de pregătire.

Se încarcă ontologia și se construiește un catalog cu:

- identificatorul fiecărui concept;
- denumirea și sinonimele;
- definiția;
- părinții și relațiile relevante;
- eventualele indicii vizuale susținute de informațiile disponibile.

Se disting conceptele recunoscibile vizual de cele care necesită context sau informații externe. Clasificarea automată a observabilității este orientativă și poate fi incertă.

Dacă informațiile nu permit definirea unor criterii vizuale, conceptul se marchează ca insuficient definit. Modelul nu trebuie să inventeze o descriere vizuală pentru a completa catalogul. Dacă se adaugă ulterior surse externe, acestea trebuie păstrate ca proveniență și diferențiate de informația din ontologie.

Din catalog se construiește indexul pentru căutarea candidaților. Se poate genera și o listă scurtă de aspecte de urmărit în imagini, precum forma, dispunerea elementelor sau uneltele folosite.

**Rezultat:** catalogul conceptelor, indexul de căutare și aspectele relevante pentru observație.

## 2. Descrierea structurată a fiecărui keyframe

Un model vizual primește imaginea și produce:

- obiectele vizibile, cu identificatori locali;
- forme, culori, texturi, configurații și poziții;
- relații între obiecte;
- acțiuni sugerate de imagine, cu incertitudinea aferentă;
- text vizibil;
- detalii neclare sau imposibil de stabilit;
- o descriere textuală scurtă.

Schema de bază rămâne aceeași indiferent de ontologie. Aspectele derivate din ontologie o completează fără să forțeze existența unor obiecte sau caracteristici. Denumirile uzuale nu sunt interzise doar pentru că apar și în ontologie; criteriul este susținerea vizuală a afirmației.

Exemplu de observație:

> Pe suprafața obiectului se observă o bandă de forme romboidale, dispusă în jurul zonei mediane.

În această etapă nu se atribuie automat numele unui motiv tradițional sau semnificația lui. Materialul, tehnica și acțiunea nu se prezintă ca certe dacă imaginea nu le susține suficient.

**Rezultat:** o observație structurată per cadru, legată de imaginea și scena sursă.

## 3. Recuperarea conceptelor candidate

Pentru fiecare obiect, configurație sau acțiune descrisă se caută concepte relevante în catalog.

Căutarea combină denumirile și sinonimele cu asemănarea semantică dintre observații și definiții. Pentru fiecare candidat se includ părintele și conceptele apropiate cu care poate fi confundat.

Ierarhia orientează căutarea, dar nu o limitează definitiv la o singură ramură. O clasificare preliminară greșită nu trebuie să excludă conceptul corect; se păstrează o căutare globală de rezervă.

**Rezultat:** candidați pentru fiecare element observat, cu definiții și alternative relevante.

## 4. Maparea observațiilor la concepte

Un model textual primește observația și candidații recuperați. Pentru fiecare asociere propusă precizează:

- conceptul ales;
- observațiile exacte care îl susțin;
- indiciile distinctive prezente;
- informațiile care lipsesc;
- eventualele alternative.

Rezultatul poate fi un concept specific, o clasă mai generală justificată de dovezi sau `unmapped`. Niciun obiect nu trebuie mapat obligatoriu.

Codul verifică dacă identificatorul există în ontologia încărcată și dacă dovezile invocate trimit la observații reale. Existența identificatorului nu demonstrează corectitudinea vizuală a asocierii.

**Rezultat:** mapări cu dovezi, alternative și incertitudini explicite.

## 5. Revenirea țintită la imagine

Se revine la imagine când:

- două concepte nu pot fi diferențiate din descriere;
- lipsește un indiciu necesar;
- observațiile sunt contradictorii;
- există un obiect relevant rămas nemapat.

Întrebarea urmărește diferența vizuală concretă, fără să presupună răspunsul:

> Formele din bandă sunt închise și romboidale sau sunt linii în zigzag?

Modelul poate primi cadrul complet și un decupaj al regiunii relevante. Răspunsul completează observația, apoi se reevaluează maparea. Dacă imaginea nu permite diferențierea, se păstrează rezultatul general sau necunoscut.

Numărul revenirilor se limitează pentru controlul costului și pentru a evita repetarea aceleiași incertitudini. Verificarea nu se declanșează exclusiv pe baza unui scor de încredere autodeclarat.

**Rezultat:** observații completate și mapări reevaluate, cu istoricul verificării păstrat.

## 6. Consolidarea rezultatelor pe scenă

Consolidarea se face după maparea pe cadre:

- se reunesc conceptele identificate;
- se păstrează cadrele care susțin fiecare afirmație;
- se semnalează contradicțiile;
- se unesc entități doar când există suficiente dovezi că reprezintă același obiect.

Apartenența la aceeași scenă și asemănarea descrierilor nu dovedesc singure identitatea obiectului. Un detaliu nevizibil într-un cadru nu este automat absent din scenă.

În implementarea actuală a extragerii sunt disponibile intervalele scenelor și imaginile asociate, dar nu momentul exact al fiecărui keyframe sau ordinea cronologică garantată în interiorul scenei. Prin urmare, consolidarea inițială produce un rezumat al observațiilor din scenă. Reconstrucția succesiunii acțiunilor necesită recuperarea pozițiilor temporale și dovezi temporale suficiente.

**Rezultat:** rezumat pe scenă, cu proveniență și conflicte păstrate.

## 7. Salvarea și evaluarea

Se salvează separat:

- observațiile per cadru;
- candidații și mapările;
- verificările vizuale;
- rezultatele consolidate pe scenă;
- metadatele rulării: modele, configurație, versiuni de prompt, ontologie, costuri și timpi disponibili.

JSON este suficient pentru prima versiune. Exportul RDF se poate adăuga ulterior. În acest caz se păstrează distincția dintre fapte observate, verificări și inferențe. Validarea condițiilor explicite asupra datelor și raționamentul ontologic reprezintă operații separate.

Evaluarea urmărește:

- afirmațiile nesusținute;
- detaliile relevante omise;
- mapările greșite;
- cazurile nemapate;
- costul și durata procesării.

Un model judecător poate ajuta la verificare, inclusiv pe un eșantion de rezultate declarate sigure. Verdictul său rămâne o evaluare automată. Acordul dintre modele și scorurile de încredere nu sunt echivalente cu precizia reală sau cu probabilități calibrate. Dacă se folosesc seturi publice etichetate, alinierea etichetelor la ontologia țintă trebuie verificată.

## Prima implementare propusă

Se folosesc direct imaginile și scenele din `manifest.json`, fără repetarea extragerii.

1. Încărcarea manifestului și păstrarea identificatorilor cadrelor și scenelor.
2. Încărcarea catalogului de concepte din ontologie.
3. Generarea observațiilor structurate per cadru.
4. Recuperarea candidaților și maparea cu dovezi sau `unmapped`.
5. Verificarea vizuală țintită, cu un număr limitat de reveniri.
6. Salvarea rezultatelor intermediare și finale în JSON.

Primul experiment se rulează pe 20–30 de cadre. Obiectivul este verificarea faptului că descrierile păstrează detaliile necesare pentru distingerea conceptelor și că asocierile sunt justificate de dovezi.

Consolidarea între cadre, profilarea ontologică avansată, îmbogățirea web, exportul RDF și evaluarea cu mai multe modele se adaugă după verificarea acestui nucleu.

## Contextul deciziei

Documentul păstrează fluxul propus și discutat în chat. Punctul de pornire al discuției a fost [planul Perplexity](https://www.perplexity.ai/computer/tasks/42a8aefc-4af2-482b-bcb5-99865c3aec5e?view=thread), ajustat pentru separarea observației de interpretare, mapare per cadru înaintea consolidării și tratarea explicită a dovezilor și incertitudinilor.
