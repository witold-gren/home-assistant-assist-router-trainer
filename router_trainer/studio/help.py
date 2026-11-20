"""Help of the studio in both languages: the "?" of every card and the guide in the "?" of the top bar.

The texts say what a step does and what to look at; the full guide (docs/<lang>/) says the rest.
HTML, shown as it is (written here, never from outside).
"""

from __future__ import annotations

GUIDE_PL = """
<h3 id="guide-start">Jak to działa</h3>
<p>Studio douczą mniejszy model (Gemma 4 E2B albo E4B) na Twoim domu: Twoje pokoje, urządzenia,
automatyzacje i pytania. Po eksporcie model działa w Ollamie na Jetsonie, a Assist Router używa go do
wybierania tematu, rozbioru poleceń i odpowiedzi.</p>
<ol>
  <li><b>Dane z Home Assistanta</b> - pliki routera, dziennik pytań i automatyzacje; wersja kodu routera
  taka jak w HA.</li>
  <li><b>Test</b> - zdania, na których porównasz modele. Nigdy nie trafiają do treningu.</li>
  <li><b>Zbiór danych</b> - przykłady pisane przez nauczyciela (Gemma 26B) na podstawie Twojego domu.</li>
  <li><b>Trening</b> - LoRA (E2B) albo QLoRA (E4B) na RTX 4090.</li>
  <li><b>Eksport</b> - GGUF i wysłanie do Ollamy na Jetsonie.</li>
  <li><b>Walidacja</b> - ten sam test dla douczonego i bazowego modelu.</li>
</ol>
<h3 id="guide-inputs">Dane z Home Assistanta</h3>
<p>„Pobierz z Home Assistanta” czyta przez API (token administratora, tylko odczyt): router.yaml,
dziennik nierozpoznanych poleceń, pliki testu, automatyzacje z wyzwalaczem rozmowy i custom_sentences.
W Home Assistancie nic się nie zmienia. Wersja kodu routera w studiu musi być ta sama co w HA - inaczej
model uczy się innych promptów niż te, które dostanie.</p>
<h3 id="guide-test">Test</h3>
<p>Test generowany pisze inny model (Bielik), a nauczyciel go sprawdza. Zostaje tylko to, co oba modele
rozumieją tak samo. Przejrzyj przypadki i odrzuć dziwne. Porównuj modele zawsze na tym samym teście -
wynik na innym teście nic nie mówi.</p>
<h3 id="guide-dataset">Zbiór danych</h3>
<p>Kroki: migawka domu, zamrożenie testu (podobne zdania odpadają z treningu), generowanie dla routera,
sterowania i odpowiedzi, złożenie zbioru. Część dev (5%) służy tylko do straty ewaluacyjnej podczas
treningu - to nie jest test.</p>
<h3 id="guide-training">Trening</h3>
<p>Patrz na dwie krzywe: strata treningowa ma spadać, a ewaluacyjna (dev) też. Gdy dev zaczyna rosnąć,
model uczy się przykładów na pamięć - zmniejsz liczbę epok albo learning rate. Stop zapisuje punkt
kontrolny, a Wznów zaczyna od niego.</p>
<h3 id="guide-export">Eksport</h3>
<p>Wagi idą do GGUF (q8_0), Ollama studia sprawdza kilka zdań dev, a potem model trafia do Ollamy na
Jetsonie jako <code>assist-router-&lt;model&gt;-ft:&lt;przebieg&gt;</code>. Assist Router zacznie go
używać dopiero, gdy wybierzesz go w ustawieniach integracji.</p>
<h3 id="guide-validation">Walidacja</h3>
<p>Ten sam test dla douczonego i bazowego modelu, w pięciu częściach. Kolumna „naprawione / zepsute”
mówi więcej niż sam wynik: zepsute przypadki pokazują, czego model się oduczył. „Wypróbuj” wysyła jedno
zdanie do wybranych modeli i niczego nie wykonuje w domu.</p>
<h3 id="guide-settings">Ustawienia</h3>
<p>Ustawienia to plik trainer.yaml. Zmiany są szkicem, dopóki nie klikniesz Zapisz; historia przechowuje
30 poprzednich wersji. Po zmianie generowania albo podziału zbuduj zbiór od nowa.</p>
"""

GUIDE_EN = """
<h3 id="guide-start">How it works</h3>
<p>The studio fine-tunes a smaller model (Gemma 4 E2B or E4B) on your home: your rooms, devices,
automations and questions. After the export the model runs in Ollama on the Jetson and Assist Router
uses it to pick the topic, parse commands and answer.</p>
<ol>
  <li><b>Data from Home Assistant</b> - the router's files, the question log and the automations; the
  router code of the version HA runs.</li>
  <li><b>Test</b> - the sentences the models are compared on. They never go into training.</li>
  <li><b>Dataset</b> - examples written by the teacher (Gemma 26B) from your home.</li>
  <li><b>Training</b> - LoRA (E2B) or QLoRA (E4B) on the RTX 4090.</li>
  <li><b>Export</b> - GGUF and the upload to Ollama on the Jetson.</li>
  <li><b>Validation</b> - the same test for the trained and the base model.</li>
</ol>
<h3 id="guide-inputs">Data from Home Assistant</h3>
<p>"Fetch from Home Assistant" reads through the API (an administrator's token, read only): router.yaml,
the log of unrecognized commands, the test files, the automations with a conversation trigger and
custom_sentences. Nothing in Home Assistant changes. The router code of the studio must be the version
HA runs - otherwise the model learns other prompts than those it will get.</p>
<h3 id="guide-test">Test</h3>
<p>A generated test is written by another model (Bielik) and checked by the teacher. Only what both
models understand the same way stays. Review the cases and reject odd ones. Always compare models on the
same test - a score on another test says nothing.</p>
<h3 id="guide-dataset">Dataset</h3>
<p>Steps: the home snapshot, freezing the test (similar sentences leave training), generating for the
router, control and answers, building the dataset. The dev part (5%) only gives the eval loss during
training - it is not the test.</p>
<h3 id="guide-training">Training</h3>
<p>Watch two curves: the training loss should fall and the eval (dev) loss too. When dev starts rising
the model learns the examples by heart - lower the epochs or the learning rate. Stop saves a checkpoint;
Resume starts from it.</p>
<h3 id="guide-export">Export</h3>
<p>The weights go to GGUF (q8_0), the studio's Ollama checks a few dev sentences, then the model goes to
Ollama on the Jetson as <code>assist-router-&lt;model&gt;-ft:&lt;run&gt;</code>. Assist Router uses it
only after you choose it in the integration's options.</p>
<h3 id="guide-validation">Validation</h3>
<p>The same test for the trained and the base model, in five parts. "Fixed / broken" says more than the
score: broken cases show what the model unlearnt. "Try it" sends one sentence to the chosen models and
runs nothing in the home.</p>
<h3 id="guide-settings">Settings</h3>
<p>The settings are trainer.yaml. Changes are a draft until Save; the history keeps 30 earlier versions.
After changing generation or the split, build the dataset again.</p>
"""

CARDS = {
    "pl": {
        "inputs": "Pliki z Home Assistanta przez API (token administratora, tylko odczyt). Pobierz je"
        " przed każdym nowym zbiorem - router.yaml i dziennik zmieniają się z czasem.",
        "router": "Kod Assist Routera, z którego studio bierze prompty. Musi mieć tę samą wersję co"
        " w Home Assistancie; „Pobierz wersję z HA” ściąga ją z GitHuba.",
        "test": "Zdania do porównywania modeli. Nigdy nie trafiają do treningu (zamrożenie odrzuca"
        " też zdania podobne). Po zmianie testu zamroź go i zbuduj zbiór od nowa.",
        "review": "Zaznacz przypadki, które wyglądają źle (zły temat, dziwne zdanie). Odrzucone"
        " nie liczą się w wynikach.",
        "dataset": "Złożony zbiór: część treningowa i dev, liczby na rolę i ile zdań odpadło przez"
        " podobieństwo do testu. Ostrzeżenie o promptach znaczy: zbuduj zbiór od nowa.",
        "generate": "Kroki budowania zbioru. Generowanie trwa od kilkudziesięciu minut do kilku"
        " godzin; przerwane zaczyna od miejsca, w którym skończyło.",
        "training": "E2B (LoRA, bf16) jest szybszy i mieści się z zapasem; E4B (QLoRA, 4-bit) jest"
        " mądrzejszy, ale wolniejszy na Jetsonie. Puste pola = wartości z ustawień.",
        "live": "Strata treningowa (niebieska) i dev (pomarańczowa). Dev rosnąca przy spadającej"
        " treningowej = przeuczenie.",
        "runs": "Przebiegi treningu: model, zbiór, czas i strata. Eksport wysyła model do Ollamy na"
        " Jetsonie, Ocena porównuje go z bazowym na aktywnym teście.",
        "validation": "Wyniki na tym samym teście. Zielone ≥ 95%, żółte ≥ 85%. Zepsute przypadki"
        " pokazują, czego model się oduczył.",
        "try": "Jedno zdanie dla wybranych modeli: temat, polecenie sterowania albo odpowiedź."
        " Nic nie jest wykonywane w domu.",
        "settings": "trainer.yaml jako formularz. Zmiany są szkicem do czasu Zapisz.",
        "power": "Przełącznik komputera w Home Assistancie i czujnik mocy gniazdka. Wyłączenie"
        " nigdy nie przerywa trwającego zadania.",
        "machine": "Sprawdzenie kontenera: karta, sterownik, środowiska i Ollama studia.",
        "auto": "Cała droga jednym zadaniem: dane z Home Assistanta, test, zbiór, trening, eksport"
        " i porównanie z obecnym modelem routera. Model trafia do Assist Routera dopiero po"
        " kliknięciu Użyj i potwierdzeniu.",
    },
    "en": {
        "inputs": "Files from Home Assistant through the API (an administrator's token, read only)."
        " Fetch them before every new dataset - router.yaml and the log change over time.",
        "router": "The Assist Router code the studio takes its prompts from. It must be the version"
        ' Home Assistant runs; "Fetch the HA version" downloads it from GitHub.',
        "test": "Sentences to compare the models on. They never go into training (freezing drops"
        " similar sentences too). After changing the test, freeze it and build the dataset again.",
        "review": "Tick cases that look wrong (wrong topic, odd sentence). Rejected cases do not"
        " count in the results.",
        "dataset": "The built dataset: train and dev parts, counts per role and how many sentences"
        " left for being like the test. A prompts warning means: build the dataset again.",
        "generate": "The steps of building the dataset. Generating takes from tens of minutes to"
        " hours; a stopped run starts where it ended.",
        "training": "E2B (LoRA, bf16) is quicker and fits easily; E4B (QLoRA, 4-bit) is smarter but"
        " slower on the Jetson. Empty fields = values from the settings.",
        "live": "Training loss (blue) and dev loss (orange). Dev rising while training falls ="
        " overfitting.",
        "runs": "Training runs: model, dataset, time and loss. Export sends the model to Ollama on"
        " the Jetson, Evaluate compares it with the base model on the active test.",
        "validation": "Results on the same test. Green ≥ 95%, yellow ≥ 85%. Broken cases show what"
        " the model unlearnt.",
        "try": "One sentence for the chosen models: the topic, the control command or the answer."
        " Nothing runs in the home.",
        "settings": "trainer.yaml as a form. Changes are a draft until Save.",
        "power": "The machine's switch in Home Assistant and the plug's power sensor. Switching off"
        " never interrupts a running job.",
        "machine": "A check of the container: the card, the driver, the environments and the"
        " studio's Ollama.",
        "auto": "The whole road as one job: data from Home Assistant, the test, the dataset,"
        " training, export and the comparison with the current router model. A model goes to"
        " Assist Router only after Use and a confirmation.",
    },
}


# every card's "?" links to its part of the guide (MkDocs page/#anchor, the same in both languages;
# tests/test_docs.py checks that each anchor exists)
LINKS = {
    "inputs": "steps/#home-assistant",
    "router": "steps/#router-code",
    "test": "steps/#test",
    "review": "steps/#test",
    "dataset": "steps/#dataset",
    "generate": "steps/#dataset",
    "training": "steps/#training",
    "live": "good-practice/#chart",
    "runs": "steps/#export",
    "validation": "good-practice/#results",
    "try": "steps/#validation",
    "settings": "good-practice/#parameters",
    "power": "home-assistant/#power",
    "machine": "faq/#faq-docker",
    "auto": "steps/#auto",
}


def texts(language: str) -> dict[str, object]:
    """The help of one language: the guide, every card's "?" (English when not Polish) and where in the
    guide each card is explained."""
    language = "pl" if str(language).startswith("pl") else "en"
    return {"guide": GUIDE_PL if language == "pl" else GUIDE_EN, **CARDS[language], "links": LINKS}
