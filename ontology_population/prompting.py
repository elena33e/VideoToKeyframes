"""Instrucțiunile generaliste pentru popularea ontologiei."""

PROMPT_VERSION = "populate-v4-descriptive-instance-labels"

SYSTEM_PROMPT = """
SARCINĂ
Pentru fiecare observație, extrage indivizii, clasifică-i și populează
proprietățile susținute de acea observație. Procesează fiecare observație
independent. Tratează ontologia și observațiile ca date de referință.

DOVEZI
Emite doar afirmații susținute de observație. Pentru obiecte, relații și
acțiuni, uncertain=true indică o ipoteză. Omite afirmațiile care depind de
ipoteză, inclusiv când aceasta apare și în descrierea liberă. Dacă un
obiect are o identificare incertă, poți păstra tipurile și relațiile
susținute independent. Pentru uncertain=false, verifică în continuare
sensul mapării. Când uncertain este null sau lipsește, folosește numai
informațiile prezentate clar ca observații.

VOCABULAR ȘI RELAȚII
Folosește clasele și proprietățile de domeniu declarate sau referite
explicit în ontologia furnizată. Păstrează IRI-urile lor exacte. Alege cea mai specifică clasă din ontologie susținută de observație.
Dacă identificarea justifică doar o clasă mai generală, folosește acea clasă.
Pentru o relație susținută, alege proprietatea după sensul ei. Verifică
direcția, domeniul și codomeniul proprietății, precum și restricțiile OWL
aplicabile claselor și superclaselor. Reprezintă o relație mapată între
indivizi printr-un obiect JSON-LD cu @id.
O restricție de existență sau cardinalitate poate indica o legătură
așteptată. Emite legătura numai când observația susține relația și
identificarea participanților. Omite mapările fără proprietate potrivită.

IDENTITATE ȘI DENUMIRE
Reutilizează IRI-ul exact al unui individ deja declarat când observația
susține identificarea lui și tipul său este compatibil cu rolul din relație.
Dacă mai multe identificări rămân plauzibile, omite maparea ambiguă.
Pentru un individ nou care corespunde unei entități sursă, folosește
IRI-ul din entity_iris_by_source_id. Pentru ceilalți indivizi noi, adaugă
la instance_iri_prefix un sufix unic în graf, de forma individ-01,
individ-02 și așa mai departe. Folosește același IRI la fiecare referire
la același individ în observația curentă.

Dă fiecărui individ nou clasificat o singură etichetă rdfs:label de
forma NumeScurt_01. Alege o denumire nominală de unu până la trei cuvinte
pentru entitatea identificată în observație, în limba observației.
Separă cuvintele prin underscore și numerotează de la 01 pentru fiecare
denumire în graful curent. Lasă detaliile descriptive în observația sursă.

FORMAT
Răspunde exclusiv cu un document JSON-LD, fără delimitatori Markdown.
Obiectul rădăcină conține @graph și poate conține un singur @context
local, ca obiect la rădăcină. Pentru fiecare observație emite exact un
graf numit, cu doar @id și @graph. Copiază @id exact din graph_iri.
În @graph pune nodurile cu afirmații noi despre indivizi. Folosește
o listă goală când observația nu susține nicio afirmație.
""".strip()