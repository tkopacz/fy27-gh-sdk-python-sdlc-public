# 010 — Rozszerzenie obserwujące sesję Copilot CLI i własne `/demo`

To **rozszerzenie istniejącej sesji CLI**, a nie aplikacja czatowa oparta na Python SDK.
Użytkownik pracuje w zwykłym Copilot CLI. CLI uruchamia
[extension.mjs](extension.mjs), dostarcza mu JavaScript SDK i przyłącza go
do swojej rozmowy. Python w [main.py](main.py) tylko przygotowuje tymczasowe
repozytorium i uruchamia interaktywny CLI.

Sprawdzone integracyjnie z CLI **1.0.97-2**, Node **24.20.0**, Python **3.14**
na Linux/WSL. Nie jest to deklaracja minimalnej obsługiwanej wersji CLI.
Mechanizm extensions i jego API nadal ewoluują.

## Co pokazujemy

| Operacja | Efekt |
|----------|-------|
| Uruchomienie | `[demo] READY /demo \| /demo stats \| /demo joke` w osi rozmowy |
| `/demo` | Własny handler wysyła stały prompt do **tej samej** sesji; model odpowiada `DEMO_OK` |
| `/demo stats` | Lokalny odczyt liczników; bez żądania do modelu |
| `/demo joke` | Dwie nowe sesje: czeski komik, następnie tłumacz na polski; główna rozmowa bez zmian |
| Ponowne `/demo joke` podczas pracy | `JOKE_BUSY`; bez uruchamiania drugiej pary sesji |
| `/demo invalid` | Jawne ostrzeżenie; bez żądania do modelu |
| Zwykły prompt | Obserwator również widzi zdarzenia, nie tylko własną komendę |
| Wywołanie narzędzia | `TOOL_START` i `TOOL_COMPLETE`, bez argumentów ani wyniku narzędzia |
| `/clear` | CLI zastępuje rozmowę i przeładowuje rozszerzenie; liczniki zaczynają od zera |
| `/exit` | CLI kończy proces rozszerzenia; launcher usuwa tymczasowe repozytorium |

Nie ma tu MCP, własnego status line ani animacji. Pokaz skupia się na kodzie
działającym obok agenta i obserwującym zdarzenia. Własne komunikaty używają
`session.log()` w natywnej osi CLI, a nie bezpośrednich zapisów do terminala.

## Wymagania

- Linux, WSL lub macOS z interaktywnym terminalem; test PTY nie obsługuje
  natywnego Windows i kończy się tam jawnym błędem, nie pominięciem.
- Repozytoryjne `.venv` z [requirements.txt](../../requirements.txt).
  Devcontainer i cloud-agent setup instalują ten plik. Do testów terminalowych
  używamy pytest, pexpect i pyte. Pyte odtwarza ekran, nie model ani SDK.
- `copilot`, `node` i `git` na `PATH`. Zalecany Node 22 lub nowszy.
  Przy instalacji przez nvm aktywuj swoją wersję Node w tym terminalu.
- CLI obsługujący `joinSession`, `commands`, `streaming`, `session.log`,
  `CopilotClient({ mode: "empty" })` i RPC metadanych narzędzi.
  Porównaj `copilot --version` z wersją widoczną po uruchomieniu.
- Lokalne uwierzytelnienie CLI, sieć i konto z dostępem do Copilot oraz
  wybranego modelu. Jeśli trzeba, uruchom `copilot login` i dokończ autoryzację.
  Logowanie do rozszerzenia VS Code nie zastępuje loginu CLI.
- Model wybierasz zwykłym `/model` w CLI. `/demo joke` odczytuje jego ID
  i używa go w obu nowych sesjach. Nie kopiuje konfiguracji providera BYOK
  ani ustawień reasoning/context: ten wariant wymaga modelu dostępnego przez
  lokalne uwierzytelnienie GitHub Copilot. Główna sesja nie zmienia ustawień.
  Rzeczywiste prompty mogą zużywać AI credits.
- Dla `/demo joke` potrzebny jest `COPILOT_CLI_PATH` z absolutną ścieżką do
  CLI. Launcher ustawia go automatycznie. To ścieżka programu, nie sekret.

Rozszerzenie nie odczytuje sekretów i nie prosi o `requestedEnvironmentVariables`.
Nie wykonuj `npm install @github/copilot-sdk` w jego katalogu: CLI dostarcza
SDK przez swój resolver. Samo `node extension.mjs` **nie** uruchamia dema:
brakuje wtedy sesji nadrzędnego CLI i transportu rozszerzenia.
`node --check extension.mjs` jest natomiast poprawnym sprawdzeniem składni.

## Instalacja i przebieg pokazu krok po kroku

0. Przygotuj [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\010-cli-extension\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Używaj terminala zintegrowanego, nie Debug Console. Oczekuj `Copilot CLI:`
   z natywną instalacją, a po jej starcie `[demo] READY`. Rozpoznany
   bootstrapper VS Code jest omijany; ten sam CLI trafia do SDK rozszerzenia.
   Zarówno stdin, jak i stdout muszą należeć do terminala; przechwytywanie
   wyjścia nie jest interaktywnym pokazem slash commands.

1. W katalogu głównym tego repozytorium sprawdź środowisko:

   ```bash
   copilot --version
   node --version
   git --version
   .venv/bin/python -m pytest --version
   ```

   Te polecenia nie wysyłają promptu. Jeśli w istniejącym `.venv` brakuje
   zależności testowych, zainstaluj zadeklarowany zestaw:

   ```bash
   .venv/bin/python -m pip install -r requirements.txt
   ```

2. Uruchom z **interaktywnego terminala**:

   ```bash
   .venv/bin/python demos/010-cli-extension/main.py
   ```

   Launcher tworzy nowe repozytorium Git w katalogu tymczasowym i kopiuje
   dokładnie jeden plik do `.github/extensions/demo-observer/extension.mjs`.
   Nie instaluje niczego w repozytorium źródłowym ani `~/.copilot/extensions`.
   Nie ma argumentów konfiguracyjnych; prompty są stałymi `DEMO_PROMPT`,
   `JOKE_SYSTEM` i `TRANSLATOR_SYSTEM` w kodzie.

3. Jeśli CLI pyta o zaufanie do wypisanego katalogu, wybierz **1. Yes** —
   zaufanie tylko na tę sesję. Nie wybieraj trwałego zapamiętania katalogu
   tymczasowego i nie włączaj `--yolo`.

4. Poczekaj na `[demo] READY /demo | /demo stats | /demo joke`. Wpisz `/env`, aby obejrzeć
   listę rozszerzeń. Powinien być widoczny `demo-observer`.
   Komenda `/demo` jest też dostępna w podpowiedziach slash commands.
   Launcher wyłącza ładowanie custom instructions i wbudowane MCP,
   przekazuje wielokrotne `--disable-mcp-server <nazwa>` dla znanych,
   skonfigurowanych serwerów i włącza `--screen-reader`, żeby łatwiej śledzić
   linie zdarzeń. Ta sama lista trafia do osobnego runtime SDK używanego przez
   `/demo joke`. Lista jest widoczna w terminalu i dotyczy tylko tych uruchomień.
   **To nie jest całkowicie izolowany profil:** globalne pluginy, hooki,
   rozszerzenia, ustawienia i autoryzacja użytkownika mogą nadal działać.
   Usuń konflikt nazwy `/demo` w swoim środowisku przed pokazem.

5. W razie potrzeby wybierz model przez `/model`, następnie wpisz:

   ```text
   /demo stats
   /demo invalid
   /demo stats
   ```

   Każdą komendę zatwierdź osobno. Zobaczysz liczniki zerowe, ostrzeżenie
   `INVALID_ARGUMENT`, a następnie nadal liczniki zerowe. To lokalny kod,
   nie rozmowa z modelem.

6. Wpisz `/demo` i poczekaj na odpowiedź oraz `IDLE`. Oczekuj:

   ```text
   [demo] COMMAND sending a prompt to this session
   [demo] TURN_START count=1
   DEMO_OK
   [demo] USAGE input=<liczba> output=<liczba>
   [demo] IDLE turns=1 chunks=<liczba> tools=0 usage_reports=1
   ```

   Liczby i kolejność wyświetlania odpowiedzi oraz metryk zależą od runtime.
   To schemat wyniku, nie obietnica konkretnej liczby tokenów.
   `COMMAND` oznacza rozpoczęcie handlera; dopiero zdarzenia i odpowiedź
   potwierdzają wykonanie żądania do modelu.

7. Ponownie wpisz `/demo stats`. Liczniki nie zmieniają się tylko dlatego,
   że je odczytujesz. Następnie wyślij zwykły prompt:

   ```text
   Odpowiedz jednym słowem: PYTHON. Nie używaj narzędzi.
   ```

   Nowe `TURN_START`, `USAGE` i `IDLE` pokazują, że extension obserwuje całą
   sesję od dołączenia, nie tylko wywołania `/demo`.

8. Pokaż narzędzia, wysyłając bezpieczne żądanie:

   ```text
   Use the view tool to read .github/extensions/demo-observer/extension.mjs.
   Do not edit files. Reply with the name of the registered slash command.
   ```

   Zatwierdź tylko zamierzony odczyt, jeśli CLI zapyta. Obserwator wypisze
   `TOOL_START` i `TOOL_COMPLETE`. Nie drukuje nazwy pliku, argumentów,
   tekstu odpowiedzi ani payloadu narzędzia. Sam CLI może oczywiście pokazać
   normalny wynik odczytu — do pokazu używamy niesensytywnego kodu.
   Jeśli model nie wykona narzędzia, nie uznawaj tej części pokazu za udaną.

9. Wpisz `/demo stats` i zapamiętaj liczniki. Następnie `/demo joke`:

   ```text
   [demo] JOKE_START model=<ID> mode=empty system=replace
   [demo] JOKE_STAGE language=cs tools=0
   [demo] JOKE_CS <krótki dowcip po czesku>
   [demo] JOKE_STAGE language=pl tools=0
   [demo] JOKE_PL <polskie tłumaczenie tego samego dowcipu>
   [demo] JOKE_DONE sessions_deleted=2 runtime_stopped=true
   ```

   Poczekaj na `JOKE_DONE`. To dwa rzeczywiste wywołania modelu, nie zapisany
   dowcip i słownik tłumaczeń. Drugie dostaje wyłącznie czeski tekst pierwszego.
   Kolejne `/demo joke` w trakcie pracy daje `JOKE_BUSY`. Po ukończeniu
   `/demo stats` ma te same liczniki co przed żartem: te dwa wywołania
   nie należą do foreground session. Ponowne `/demo` nadal daje `DEMO_OK`.
   Przy błędzie zobaczysz `JOKE_ERROR stage=...`, nigdy zastępczy gotowy dowcip.

10. Wpisz `/clear`, poczekaj na nowe `READY`, następnie `/demo stats`.
   Oczekuj zer: statystyki są w pamięci procesu rozszerzenia, nie odtwarzają
   historii ani poprzedniej rozmowy. To również sposób na ponowne załadowanie
   zmienionego rozszerzenia; `/clear` rozpoczyna nową rozmowę.

11. Zakończ przez `/exit`. Poczekaj na
    `CLI exited; temporary extension repository removed.`.
    CLI zarządza zamknięciem rozszerzenia, a Python usuwa wyłącznie utworzony
    przez siebie katalog tymczasowy. Historia i logi w konfiguracji CLI mogą
    pozostać; launcher nie kasuje konta, autoryzacji ani historii użytkownika.

## Własna orkiestracja: co zastępujemy, a czego nie wyłączamy

`JokePipeline` to mała, własna orkiestracja: utwórz klienta → wygeneruj
dowcip → sprawdź format → przetłumacz → pokaż wynik → posprzątaj.
Model nie decyduje o delegowaniu do tłumacza; robi to zwykły kod MJS.

Trzy ustawienia mają różne role:

1. **`CopilotClient({ mode: "empty" })`** wyłącza domyślnie opcjonalne
   funkcje coding agenta, m.in. discovery konfiguracji, skills, instrukcje
   projektu i operacje Git. Nie zmieniamy trybu klienta obsługującego CLI;
   tworzymy osobnego klienta tylko na czas polecenia.
2. **`systemMessage: { mode: "replace", content: ... }`** zastępuje
   SDK-managed system prompt kompletnymi instrukcjami komika/tłumacza,
   zamiast dopisywać „opowiedz dowcip” do instrukcji agenta programistycznego.
   Razem z promptem usuwamy też zawarte w nim wskazówki bezpieczeństwa:
   sami podajemy ograniczenia treści, nie udostępniamy narzędzi i walidujemy wynik.
3. **`availableTools: []`** udostępnia pusty zestaw narzędzi. Dodatkowy
   handler odmawia ewentualnych żądań uprawnień. Przed promptem odczytujemy
   faktycznie zainicjalizowaną listę z runtime; `tools=0` jest sprawdzeniem,
   a nie tylko wydrukiem konfiguracji.

**Nie wyłączamy całego runtime'u ani zabezpieczeń usługi.** Copilot nadal
obsługuje protokół, sesje, uwierzytelnienie, model i rozliczenie. To własna
orkiestracja na runtime Copilot, nie bezpośredni klient surowego API modelu.
Nie obiecujemy też bypassu polityk organizacji lub providera.

Każda rola ma własny session ID; nie otrzymuje historii głównej rozmowy.
`baseDirectory` wskazuje istniejący katalog danych CLI, żeby ponownie użyć
lokalnego logowania bez kopiowania tokenów. **Izolacja dotyczy kontekstu
sesji i narzędzi, nie osobnego konta, sandboxa czy katalogu poświadczeń.**
Stan własnych sesji usuwamy przez `deleteSession`; normalne logi runtime
mogą pozostać w profilu. `empty` nie oznacza całkowitego braku zapisów na dysku.

Odpowiedzi mają format JSON `{ "language": "cs" lub "pl", "text": "..." }`.
Kod sprawdza pola, etykietę języka, niepusty tekst, limit 500 znaków
i niebezpieczne znaki sterujące; formatowanie białych znaków normalizuje
do jednej linii. Nie analizuje automatycznie jakości dowcipu ani poprawności
tłumaczenia. Porównaj oba teksty podczas prezentacji.

## Instalacja ręczna w wybranym repozytorium

Użyj tego wariantu, jeśli chcesz rozszerzyć codzienną sesję CLI. Najpierw
przeczytaj [extension.mjs](extension.mjs): jest to lokalnie wykonywany kod.

1. Otwórz katalog główny docelowego repozytorium Git, nie podkatalog `demos`.
   Utwórz `.github/extensions/demo-observer/`.
2. Skopiuj [extension.mjs](extension.mjs) do
   `.github/extensions/demo-observer/extension.mjs`.
   Nie nadpisuj istniejącego rozszerzenia; rozwiąż konflikt nazw najpierw.
   `main.py`, testy i Python nie są potrzebne do takiej instalacji.
3. Uruchom CLI z jawną ścieżką dla własnego klienta rozszerzenia:

   ```bash
   COPILOT_CLI_PATH="$(command -v copilot)" copilot
   ```

   W typowej instalacji `command -v` zwraca absolutną ścieżkę; jeśli używasz
   aliasu/funkcji, wskaż rzeczywisty plik wykonywalny. Zatwierdź zaufanie po
   przeglądzie kodu i poczekaj na `READY`. Przejdź przez kroki 4–10 pokazu.
   Ścieżka SDK nie jest rozwiązywana przez `PATH`, dlatego samo `"copilot"`
   nie wystarczy. Brak tej zmiennej nie blokuje obserwatora ani `/demo stats`,
   ale `/demo joke` zgłasza `JOKE_ERROR stage=configuration`.
4. Po zmianie kodu wyjdź z CLI i uruchom go ponownie albo użyj `/clear`.
   Samo zapisanie pliku nie gwarantuje hot reload.
5. Aby odinstalować, zakończ CLI i usuń **tylko skopiowany**
   `.github/extensions/demo-observer/extension.mjs`; pusty katalog można
   potem usunąć. Po ponownym starcie `/demo` i `READY` powinny zniknąć.
   Nie usuwaj całego `.github/extensions` ani `~/.copilot`.

## Na co zwrócić uwagę — kod i cykl życia

- **Wspólny kod** — `DISABLED_MCP_SERVERS` i `show_disabled_mcp_servers(cli=True)`
  pochodzą z `copilot_runtime.py`. Launcher nadal zamienia każdą nazwę na
  flagę CLI; eventy rozszerzenia JavaScript pozostają w jego własnym kodzie.

- **Wybór CLI:** `validate()` używa wspólnego `CopilotRuntime`, a środowisko
  procesu przypina `COPILOT_CLI_PATH` także dla klienta SDK w rozszerzeniu.
  Nie uruchamiamy bootstrappera VS Code ani nie pobieramy innego runtime.
  `/exit` nadal kończy CLI i usuwa tymczasowy checkout. Pełne testy PTY
  wymagają Linux/WSL/macOS; kontrola natywnej ścieżki działa też na Windows.

- **`SessionObserver.run()` / `joinSession()`** — dołączenie do foreground
  session CLI, nie `createSession()`. Uwierzytelnienie i model należą do hosta.
- **Blokada MCP launchera** — `--disable-builtin-mcps` wyłącza wbudowane
  serwery, a każde `--disable-mcp-server <nazwa>` blokuje dokładnie wskazany
  serwer podczas tego uruchomienia CLI. `RuntimeConnection.forStdio()` ustawia
  te same opcje dla oddzielnego runtime dwóch sesji `/demo joke`; opcje głównego
  CLI nie są dziedziczone automatycznie przez ten proces. To nie wyłącza custom
  commands ani nie zastępuje polityki narzędzi; ustawienia globalne nie są
  zmieniane.
- **`commands: [{ name, description, handler }]`** — `name` nie ma `/`;
  CLI przekazuje `context.args` po nazwie komendy. To nie prompt z instrukcją
  „udawaj slash command”.
- **`streaming: true`** — konieczne, aby połączenie rozszerzenia odbierało
  nietrwałe `assistant.message_delta`, nawet gdy sam CLI już streamuje tekst.
- **`session.send()`** — przyjęcie wiadomości, nie oczekiwanie na odpowiedź.
  Dotyczy zwykłego `/demo`. Natomiast `/demo joke` celowo czeka przez
  `sendAndWait()` w dwóch własnych sesjach, z timeoutem 60 sekund na etap.
- **`JokePipeline.run()` / `stage()`** — deterministyczna kolejność dwóch
  ról, identyfikator modelu pobrany z CLI, osobne instrukcje i konteksty.
  Tylko niesensytywny, wygenerowany tekst dowcipu trafia do `JOKE_CS`/`JOKE_PL`.
  Te logi nie są przesyłane jako prompty do głównego agenta.
- **`session.on()` / `observe()`** — jawna lista obsługiwanych zdarzeń.
  Nie utrwalamy promptów, odpowiedzi, argumentów, tokenów autoryzacyjnych
  ani wewnętrznego toku rozumowania.
- **`turns`** liczy `assistant.turn_start`, nie prompty użytkownika;
  narzędzia i dalsze wywołania modelu mogą zwiększać liczbę zdarzeń.
  **`chunks` nie oznacza tokenów.** `tools` liczy rozpoczęcia wywołań.
- **`USAGE`** pokazuje liczbę input/output tokens z pojedynczego otrzymanego
  raportu. To nie suma od początku sesji, zajętość kontekstu ani cena.
  Brak wartości daje `unavailable`, nie fikcyjne zero.
  `usage_reports` liczy odebrane raporty, nie gwarantuje liczby płatnych żądań.
- **`TOOL_COMPLETE`** oznacza zakończenie wywołania, nie deklarację sukcesu
  jego wyniku. Dodatkowe zdarzenia subagentów mogą trafiać do tych samych
  liczników; demo ich nie rozdziela.
- **`session.log()`** — wyjście w natywnej osi CLI; własne zdarzenia logowania
  są ignorowane przez obserwator, więc nie powstaje pętla. Kolejka zachowuje
  kolejność logów bez drukowania każdego fragmentu odpowiedzi.
- **`stop()`** — odpięcie subskrypcji przy SIGTERM. Nie wywołujemy
  `session.destroy()`, bo główna rozmowa należy do CLI. Jeśli trwa dowcip,
  przerywamy jego aktywne żądanie. Sesje komika/tłumacza są nasze, więc
  usuwamy je w `finally`, a własny runtime zamykamy przez `client.stop()`.
  Nie pozostawiamy go celowo w tle po poleceniu.

## Testy — rzeczywisty CLI, SDK, model i narzędzie

Z głównego katalogu repozytorium:

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/010-cli-extension -v
```

[test_main.py](test_main.py) uruchamia prawdziwy launcher w pseudoterminalu:
potwierdza zaufanie tylko dla świeżo utworzonego repozytorium, sprawdza
lokalne komendy i błędny argument, wysyła `/demo`, potwierdza wyrenderowane
`DEMO_OK`, dodatnie input/output tokens i fragmenty streamu. Następnie
wykonuje rzeczywisty odczyt niesensytywnego pliku, sprawdza zdarzenia narzędzi,
przeładowanie przez `/clear`, reset liczników i cleanup po `/exit`.
Test sprawdza też oba etapy `/demo joke`, rzeczywiste puste zestawy narzędzi,
czeski i polski tekst z wymaganymi słowami, `JOKE_BUSY`, błąd dodatkowego
argumentu, niezmienione liczniki głównej sesji i późniejszy zwykły odczyt pliku.
Osobne uruchomienia prawdziwego CLI sprawdzają brak ścieżki oraz nieistniejący
plik runtime dla klienta dowcipu: błąd musi być widoczny, a obserwator nadal działać.

Nie mockujemy SDK, modelu, poświadczeń, sieci ani plików. Pyte interpretuje
kody sterujące terminala, ponieważ proste sklejenie fragmentów stdout nie
odtwarza ekranu CLI. Test nie zapisuje surowego transkryptu na dysku ani
nie dołącza go do komunikatu timeoutu. Nieznane dialogi, brak logowania,
Node, zależności lub wymaganych zdarzeń powodują błąd, nie skip.
Test dziedziczy konfigurację modelu użytkownika; rozszerzenia ingerujące
w prompty mogą zmienić wynik. Uporządkuj taki profil przed testowaniem.

Osobne testy sprawdzają brak programu/źródła, składnię MJS, rzeczywistą
instalację, cleanup po wyjątku oraz odmowę uruchomienia bez TTY.

Demo jest ostatnie w `DEMO_DIRECTORIES`:

- `run-all-tests.py` wykonuje również jego testy PTY bez ręcznej obsługi.
- `run-all-demos.py` uruchamia interaktywny launcher i **czeka na Twoje
  `/exit`**. Uruchamiaj ten runner w terminalu; w CI użyj runnera testów.

## Diagnostyka

| Objaw | Co sprawdzić |
|-------|-------------|
| Brak `READY` / nieznane `/demo` | `/env`, wersję CLI, Node na PATH, nazwę `extension.mjs`, Git root i konflikt nazw |
| `chunks=0` mimo widocznego streamu | Czy zainstalowana kopia ma `streaming: true` i została przeładowana |
| Brak `USAGE` | Dostęp do modelu, błędy CLI oraz zgodność wersji; nie zastępuj danych estymacją |
| Extension failed | Lokalne logi CLI; nie publikuj pełnych logów bez przeglądu i redakcji |
| `JOKE_ERROR stage=configuration` | Absolutną ścieżkę `COPILOT_CLI_PATH`; launcher ustawia ją automatycznie |
| `JOKE_ERROR stage=startup` | Istnienie pliku CLI i zgodność dostarczonego JS SDK |
| `JOKE_ERROR stage=cs` lub `pl` | Logowanie lokalnego klienta, dostęp do modelu, obsługę pustych narzędzi, timeout lub format JSON odpowiedzi |
| Inna wersja w oknie niż `--version` | Usuń z własnego polecenia `--no-auto-update`; może wybierać starszy wbudowany runtime zamiast aktywnego |
| Nie działa `copilot -p '/demo'` | Slash command wymaga interaktywnego dispatchera CLI, nie tekstowego promptu do modelu |
| Zmiana źródła nie wpływa na uruchomiony pokaz | Launcher kopiuje plik na starcie; zakończ i uruchom go ponownie |

Źródła: [extensions](https://github.com/github/copilot-sdk/blob/main/nodejs/docs/extensions.md),
[przykłady](https://github.com/github/copilot-sdk/blob/main/nodejs/docs/examples.md),
[typy komend](https://github.com/github/copilot-sdk/blob/main/nodejs/src/types.ts).
Gałąź `main` dokumentacji może wyprzedzać zainstalowany runtime.
