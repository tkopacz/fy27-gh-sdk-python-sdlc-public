# Fabryka agentów SDLC — od diagnozy do dokumentacji

Beancount #1048: zero jednostek z kosztem całkowitym powoduje dzielenie przez zero.
Poniżej skrót rzeczywistego przebiegu z logu: **około 12 minut na jednym slajdzie**.

```mermaid
%%{init: {"theme": "base", "fontFamily": "Arial", "flowchart": {"wrappingWidth": 360, "rankSpacing": 24, "nodeSpacing": 16}}}%%
flowchart LR
    subgraph P1["1. ANALIZA STATYCZNA"]
        direction TB
        A["analyst<br/>Narzędzie SDK: Ruff + Pyright"]
        B["Raport JSON<br/>Ruff: bez uwag<br/>Pyright: 600 diagnostyk"]
        C["static-reviewer<br/>Recenzja JSON; wyniki ucięte<br/>Brak potwierdzenia przyczyny"]
        A --> B --> C
    end

    subgraph P2["2. NAPRAWA I WERYFIKACJA"]
        direction TB
        D["analyst + architect<br/>Diagnoza dzielenia przez zero<br/>Projekt zabezpieczenia"]
        E["tester — RED<br/>23 przypadki regresyjne<br/>Błąd potwierdzony"]
        F["programmer<br/>Walidacja przed dzieleniem<br/>Odrzucenie wadliwej grupy"]
        G["tester — GREEN + reviewer<br/>23 nowe OK; cały plik: 141 OK<br/>20 pominiętych; review: akceptacja"]
        D --> E --> F --> G
    end

    subgraph P3["3. DOKUMENTACJA"]
        direction TB
        H["documentarian<br/>Podsumowanie zespołu<br/>+ odczyt poprawki i testów"]
        I["Notka w CHANGES<br/>Opis faktycznej korekty<br/>Bez ponownych testów"]
        H --> I
    end

    P1 -->|"Ta sama sesja"| P2
    P2 -->|"Nowa sesja SDK"| P3

    classDef analysis fill:#eaf2ff,stroke:#386cb0,color:#172b4d
    classDef repair fill:#eaf7ee,stroke:#34834a,color:#173b24
    classDef docs fill:#fff3df,stroke:#b7791f,color:#513510
    class A,B,C analysis
    class D,E,F,G repair
    class H,I docs
```

## Przebieg omawiania slajdu

1. **`DEFAULT_PROMPT` — diagnoza statyczna.** Orkiestrator deleguje przez
   `task`: analityk uruchamia narzędzie SDK `python_static_analysis`,
   potem recenzent dostaje cały
   zwrócony JSON. Raport ma uciętą listę diagnostyk Pyright; nie potwierdza
   przyczyny dzielenia przez zero. Na tym etapie nie ma edycji ani testów.
2. **`DEFAULT_REPAIR_PROMPT` — naprawa.** Druga tura tej samej sesji zachowuje
   kontekst. Specjaliści analizują kod, projektują zabezpieczenie, dodają testy
   RED, poprawiają kod i potwierdzają GREEN oraz akceptację review.
   Wynik: kontrolowany `InterpolationError: Amount is zero` zamiast wyjątku
   dzielenia przez zero, bez zmiany inventory przez wadliwą grupę.
3. **`DOCUMENTATION_PROMPT` — zamknięcie.** To nie kolejna delegacja `task`:
   Python tworzy osobną sesję z `agent="documentarian"` i przekazuje
   podsumowanie. Agent zmienia tylko `CHANGES`. Aplikacja zamyka sesję
   i klienta SDK; zmiany zostają do obejrzenia (`keep_changes=True`),
   bez commitowania ani wysyłania zmian przez demo.

## Na co zwrócić uwagę

- Trzy kolumny odpowiadają trzem promptom w [main.py](main.py), a nie trzem
  agentom; szczegółową kolejnością specjalistów steruje orkiestrator.
- Raport statyczny to dane z narzędzia, nie dowód odtworzenia błędu.
- RED → poprawka → GREEN to osobne przekazania pracy; końcowe review
  następuje po testach. 20 pominiętych testów nie oznacza 161 zaliczonych.
- Nowa sesja dokumentarzysty dostaje podsumowanie jawnie; nie dziedziczy
  automatycznie historii orkiestratora.

Źródło: [log przebiegu z 19.10.2026, 07:29:52–07:42:00 UTC](logs/summary20261019T072952.272306Z-4b13c439.log).
Diagram opisuje ten przebieg, nie gwarantuje identycznej sekwencji każdego uruchomienia.
