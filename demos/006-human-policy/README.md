# Demo 006: człowiek i polityka w pętli SDK

Do uruchomienia potrzebne są Python 3.11+, `requirements.txt`, Copilot CLI,
sieć, aktywna subskrypcja i `copilot login` (logowanie w VS Code nie wystarczy).
Przygotuj własny klon Beancount (`demos/006-human-policy/workspace`, tag
`demo-red-1048`; uruchom `.venv/bin/python prepare_workspaces.py`). Dozwolone zapisy: `beancount/parser/booking_full.py`,
`beancount/parser/booking_full_test.py` i `CHANGES`. Nie uruchamiaj demo na gałęzi produkcyjnej.
Sprawdź uwierzytelnienie przez `copilot -p 'Reply with OK' --silent`.

Demo wymaga runtime obsługującego strukturalne elicitation; zweryfikowano
Copilot CLI 1.0.98 z SDK 1.0.14. Sam SDK domyślnie wybiera własny runtime,
niekoniecznie `copilot` z PATH. W tym środowisku jego runtime 1.0.85 nie
przekazywał formularza do callbacku. Dlatego demo wybiera `COPILOT_CLI_PATH`,
jeżeli ustawiono tę zmienną, albo `copilot` z PATH. Przekazuje tę ścieżkę
jawnie przez wspólny `CopilotRuntime.create_client()` do
`RuntimeConnection.for_stdio(path=...)` i wypisuje `Copilot CLI:`.
Nie pobiera zastępczego runtime i nie ignoruje błędnej ścieżki. Opcjonalne
`COPILOT_CLI_PATH` ustaw w tej samej powłoce, w której uruchamiasz demo
i testy; sprawdź wersję dokładnie tej instalacji.

```bash
export COPILOT_CLI_PATH="$(command -v copilot)"
.venv/bin/python demos/006-human-policy/main.py
.venv/bin/python -m pytest --import-mode=importlib demos/006-human-policy/test_main.py -q
```

W PowerShell na Windows:

```powershell
$env:COPILOT_CLI_PATH = (Get-Command copilot).Source
& $env:COPILOT_CLI_PATH --version
.venv\Scripts\python.exe demos\006-human-policy\main.py
.venv\Scripts\python.exe -m pytest --import-mode=importlib demos\006-human-policy\test_main.py -q
```

Na Windows wskaż natywny `copilot.exe` dla architektury komputera albo
punkt wejścia CLI `.js` (wtedy wymagany jest Node.js na PATH), nie dowolny wrapper
`.cmd`, `.bat`, `.ps1` ani plik z instalacji Linux/WSL. SDK uruchamia proces
bez powłoki PowerShell; działający alias lub wrapper w terminalu nie oznacza,
że można uruchomić go przez Windows CreateProcess. `WinError 193` oznacza
odrzucenie pliku wykonywalnego przez Windows, przed logowaniem i sesją.
Sprawdź wypisaną ścieżkę i uruchom
`& $env:COPILOT_CLI_PATH --version`. Usuń nieaktualny override przez
`Remove-Item Env:COPILOT_CLI_PATH -ErrorAction SilentlyContinue`, aby demo
ponownie wybrało CLI z PATH. Nie trzeba zmieniać ustawień MCP.

Wyjątkiem jest rozpoznany bootstrapper rozszerzenia VS Code w
`globalStorage\github.copilot-chat\copilotCli`: `copilot.ps1`, `copilot.bat`
lub `copilot`. VS Code może automatycznie ustawić override na ten plik.
Demo pomija jego katalog przy wyszukiwaniu `copilot.exe` na PATH,
tak jak bootstrapper wyszukuje właściwą instalację. Wypisuje
`VS Code Copilot launcher: ...; using installed CLI: ...`, a następnie
`Copilot CLI:` ze ścieżką natywnego programu. Nie uruchamia bootstrappera,
nie instaluje pakietów i nie usuwa żadnej instalacji. Brak natywnego CLI
powoduje jawny błąd konfiguracji. Inne wrappery nadal nie są obsługiwane.

### Debugowanie w VS Code (F5)

1. Zainstaluj zalecane rozszerzenie Python Debugger i przygotuj `.venv`,
   checkout oraz logowanie CLI zgodnie z wymaganiami powyżej.
2. Otwórz `demos/006-human-policy/main.py`. W **Run and Debug** wybierz
   **Python: Current File (.venv)** — tę samą konfigurację co dla innych dem.
   Uruchamia ona aktualny plik z repozytoryjnym interpreterem
   (`.venv\Scripts\python.exe` na Windows) i jego katalogiem jako cwd.
   Opcja `-Xfrozen_modules=off` zapobiega ostrzeżeniu debuggera o pomijaniu
   breakpointów w zamrożonych modułach Pythona.
   `subProcess=false` pozostawia procesy testów uruchamiane przez CLI bez
   wstrzykiwania debuggera; breakpointy obejmują hosta dema.
3. Ustaw breakpoint przy `resolve_cli()` lub `client.create_session()` i
   naciśnij F5. W terminalu zintegrowanym oczekuj `Copilot CLI: <ścieżka>`
   oraz listy wyłączonych serwerów MCP. Kontynuuj wykonanie (F5).
4. Przy `[elicitation] zero-units semantics:` wpisz `reject` w terminalu
   zintegrowanym, nie w Debug Console. Oczekuj eventów narzędzi,
   `session.idle` i końcowej odpowiedzi.
5. Pozwól programowi wyjść normalnie, aby zamknął konteksty sesji i klienta.
   Po długiej pauzie na breakpoincie żądanie może przekroczyć timeout;
   uruchom demo ponownie, zamiast pomijać callbacki.

Nie trzeba eksportować `COPILOT_CLI_PATH` w terminalu przed F5: demo samo
wybiera instalację z PATH środowiska debuggera. Eksport w osobnym terminalu
nie zmienia środowiska już działającego VS Code. Override wskazujący
bootstrapper Copilot Chat jest rozpoznawany automatycznie, również gdy
jego katalog jest pierwszy na PATH. Jeśli debugger dziedziczy
inny nieaktualny override lub PATH sprzed instalacji CLI, popraw środowisko procesu
VS Code i uruchom go ponownie. Nie ma fallbacku ukrywającego błędny override.

`hooks` jest przekazywane do `create_session`: odczyt i dokładna komenda
`python -m pytest beancount/parser/booking_full_test.py -k TestZeroUnitsWithTotalCost -q` przechodzą automatycznie;
pozostałe polecenia shell są blokowane z informacją widoczną dla modelu
(w tym push, release i publikacja). Zapis do trzech plików roboczych jest
dozwolony, inne zapisy wymagają potwierdzenia człowieka; odmowa zatrzymuje
operację. Hook błędu testu zwraca dodatkowy kontekst dla modelu. Model
wywołuje `ask_user`, `ask_user_variant="elicitation"` kieruje formularz
do callbacku, a decyzja wraca do tej samej sesji przed kolejnymi toolami.
Callback ma typy SDK `ElicitationContext` i `ElicitationResult`: zwraca
`{"action": "accept", "content": {"<pole formularza>": "reject"}}`,
a nie starsze `answer` / `wasFreeform`. Nie rejestrujemy
`on_user_input_request`, ponieważ włącza on także protokół
`requestUserInput`. Nie ma fallbacku do starszego API; niepoprawny wybór
lub brak pól formularza powoduje jawny komunikat i `action="decline"`.

To demonstracja polityki żądań narzędzi SDK, **nie sandbox dla kodu Pythona**:
uruchomiony test może uruchomić własne subprocessy, których hook nie widzi.
Uruchamiaj wyłącznie zaufane, przejrzane testy w izolowanej kopii, bez
uprawnień publikowania; przy nieufnym kodzie ogranicz sieć i poświadczenia
na poziomie środowiska wykonawczego.
Wybierz `reject` (kontrolowany `InterpolationError`); `zero_cost` i
`keep_raising` pokazują alternatywne decyzje. Aplikacja nie tworzy osobnej
pętli modelu.

Test sprawdza reguły odmowy, trzy wybory formularza, błędną odpowiedź i brak
pól, brak CLI i niedozwolony launcher Windows oraz uruchamia prawdziwe sesje SDK z wąskim,
bezpiecznym promptem pytającym o decyzję; nie używa mocków poświadczeń,
SDK ani providera. Brak sieci, runtime, subskrypcji albo logowania powoduje
czytelny błąd, nie pominięcie testu. Test integracyjny wymaga rzeczywistego
`[elicitation]`; samo zakończenie sesji lub odpowiedź tekstowa bez callbacku
nie wystarcza do zaliczenia.

## Przebieg krok po kroku

1. Z katalogu głównego przygotuj checkout i sprawdź prawdziwe logowanie
   Copilot CLI, zgodnie z wymaganiami powyżej. Demo wymaga aktywnej
   subskrypcji, dostępu do sieci i gotowego `workspace` na oczekiwanym tagu.
   Sprawdź `copilot --version`; zweryfikowana wersja to 1.0.98.
   Opcjonalnie ustaw `COPILOT_CLI_PATH` zgodnie z poleceniami dla swojej
   powłoki i sprawdź wersję wybranego runtime.
2. Uruchom `.venv/bin/python demos/006-human-policy/main.py`. Aplikacja
   waliduje checkout, wypisuje `MCP server names disabled for this session:`,
   a wspólny helper waliduje ścieżkę i wypisuje `Copilot CLI: <ścieżka>`
   przed startem runtime (porównaj ją z instalacją sprawdzoną w kroku 1).
   Lista z `DISABLED_MCP_SERVERS`
   trafia do `create_session(disabled_mcp_servers=...)`; SDK blokuje dokładne
   dopasowania na poziomie tej sesji, przed startem i uwierzytelnieniem.
3. `CopilotRuntime(environment=self.environment, output=self.output).create_client()`
   tworzy klienta z jawnym transportem stdio i uruchamia wybrany CLI z jego
   logowaniem. `create_session()` wiąże workspace z jedną sesją i rejestruje
   callbacki uprawnień, pre/post-tool hooki, eventy oraz `ask_user_variant`.
   Lista MCP nie zmienia uprawnień, hooków ani dostępności funkcji `ask_user`.
4. Wyślij prompt demonstracyjny. Agent wywołuje narzędzia, a przed każdą
   operacją uruchamia się polityka hooka. Pytanie o zachowanie błędu trafia
   przez SDK wyłącznie do `elicit(context: ElicitationContext)`.
   Gdy pojawi się `[elicitation] zero-units semantics:`, wpisz `reject`
   i naciśnij Enter. Wynik `ElicitationResult` z `action="accept"` oraz
   `content` wraca do tej samej pętli agenta.
5. Obserwuj nazwy eventów narzędzi i komunikat `[elicitation]`.
   Agent kontynuuje pracę nad wskazanym błędem i uruchamia testy objęte
   polityką. Po `session.idle` pojawia się końcowa odpowiedź.
   Zamknięcie kontekstu sesji i klienta zwalnia sesję oraz proces runtime,
   także gdy operacja zakończy się wyjątkiem.
6. Uruchom podane wyżej polecenie pytest w tej samej powłoce.
   Testy integracyjne sprawdzają wybór CLI z PATH oraz przez jawny override.
   Same odpowiadają `reject`, nie modyfikują checkoutu i wymagają callbacku
   strukturalnego. Test konfiguracji debuggera sprawdza program, cwd i
   interpreter. Na Windows testy wymagają też zainstalowanych trzech
   bootstrapperów rozszerzenia Copilot Chat w domyślnym profilu VS Code:
   sprawdzają ich rzeczywiste pliki i prawdziwe sesje SDK, bez mocków.
   Oczekuj `19 passed` na Windows; pięć testów specyficznych dla Windows
   jest pomijanych na innych systemach (`14 passed, 5 skipped`).

## Na co zwrócić uwagę

- **Wspólny kod** — `copilot_runtime.py` zawiera denylistę MCP, jej komunikat
  i `print_event()`. Demo zachowuje własny wybór trzech typów eventów,
  podsumowanie narzędzi, permission i callback elicitation.

- **`DISABLED_MCP_SERVERS` / `disabled_mcp_servers`** — terminal pokazuje listę,
  a SDK blokuje zgodne, dokładne nazwy tylko dla tej sesji. Nie jest to
  wildcard, nie zmienia ustawień CLI i nie wpływa na tool allowlist.
- **`create_session()`** — sprawdź, że blokada MCP współistnieje z
  `hooks`, decyzjami permission, `ask_user_variant="elicitation"` i
  `on_elicitation_request`; nie zastępuje żadnej z tych kontroli.
- **Hooki i uprawnienia** — pre-tool hook pozwala jedynie na wskazane testy
  i odczyt; permission callback wymaga akceptacji człowieka dla pozostałych
  zapisów. Odrzucenie nie jest zgodą domyślną.
- **Elicitation** — oczekuj formularza `[elicitation]` i odpowiedzi `reject`
  przekazanej ponownie do agenta w tej samej sesji przez `content`.
  `on_user_input_request` i `legacy_input` nie są używane; starszy runtime
  nie jest obsługiwany przez fallback.
- **Runtime** — wspólny `CopilotRuntime.resolve_cli()` wybiera `COPILOT_CLI_PATH` albo CLI z PATH;
  `RuntimeConnection.for_stdio(path=cli)` przypina tę instalację dla SDK.
  Oczekuj `Copilot CLI:` przed komunikatem MCP i żadnego pobierania runtime.
  Błędna ścieżka lub launcher daje jawny błąd, bez cichego fallbacku.
  Rozpoznany bootstrapper VS Code daje dodatkowy komunikat z obiema
  ścieżkami; SDK uruchamia natywny `copilot.exe`, nie skrypt powłoki.
- **F5** — konfiguracja **Python: Current File (.venv)** używa tej samej
  ścieżki startowej SDK co terminal; wybór człowieka wpisuj w terminalu
  zintegrowanym. Breakpoint nie powinien przetrzymywać aktywnego żądania
  dłużej niż `timeout_seconds`.
  Gdy brakuje `[elicitation]`, test integracyjny ma zakończyć się błędem,
  zamiast zaliczyć zwykłą odpowiedź modelu.
- **Eventy / wynik** — logowane są wybrane eventy narzędzi, nie surowe
  payloady. Końcowa odpowiedź pojawia się dopiero po bezczynności sesji.
- **Cleanup** — po pokazie nie pozostaje uruchomiony klient Copilot SDK.
