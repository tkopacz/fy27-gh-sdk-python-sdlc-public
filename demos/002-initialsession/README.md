# Demo 002: od instalacji do działającej sesji

To demo pokazuje, że Python SDK uruchamia kompletny runtime GitHub Copilot:
utrzymuje sesję, pozwala agentowi czytać repozytorium przez wbudowane narzędzia,
czeka na zakończenie pętli i sprząta zasoby. Kod aplikacji podaje tylko model,
katalog roboczy, cel oraz sposób prezentacji wyniku.

## Przebieg krok po kroku

0. Sprawdź [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\002-initialsession\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Po walidacji checkoutu oczekuj `Copilot CLI: <ścieżka>` przed połączeniem SDK;
   wrapper VS Code zostanie jawnie rozwiązany do natywnego CLI.

1. Przygotuj Python 3.10+, GitHub Copilot CLI, dostęp do sieci i konto
   z aktywną subskrypcją Copilot. Z katalogu głównego tego repozytorium
   zainstaluj przypiętą wersję `github-copilot-sdk`:

   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

2. Sprawdź uwierzytelnienie osobnego runtime CLI:

   ```bash
   copilot -p "Reply with exactly: OK" --silent
   ```

   Oczekiwany wynik to `OK`, bez wyświetlania poświadczeń. Logowanie
   w rozszerzeniu VS Code nie jest współdzielone z runtime CLI. Jeżeli polecenie
   zgłasza brak uwierzytelnienia, wykonaj `copilot login`, a potem powtórz test.

3. Przygotuj dokładnie ten checkout, którego oczekuje `CONFIGURATION`:

   ```bash
   .venv/bin/python prepare_workspaces.py
   ```

   Skrypt tworzy osobny klon dla każdego dema (`demos/<demo>/workspace/`,
   ignorowany przez Git), więc w trakcie pokazu nie przełączasz tagów.
   Ten klon (`demos/002-initialsession/workspace/`) jest na tagu
   `demo-red-1048` (`1053b01f486b598c45a56f574ff3dfef64f20500`) to stan z
   dodanym, czerwonym testem `TestZeroUnitsWithTotalCost` i jeszcze bez
   poprawki. Przed uruchomieniem aplikacja sprawdzi pliki parsera i testów oraz
   pełny hash commita; inny stan kończy się
   komunikatem konfiguracyjnym, zanim wystartuje Copilot.

4. Uruchom demo z katalogu głównego:

   ```bash
   .venv/bin/python demos/002-initialsession/main.py
   ```

5. Najpierw zobaczysz `Model: auto`, bezwzględną ścieżkę katalogu roboczego
   i prompt zabraniający zmian. Następnie wejście do
   `CopilotClient(use_logged_in_user=True)` uruchamia runtime Copilot CLI,
   używa logowania zarządzanego przez CLI i zestawia połączenie. Potwierdza to:

   ```text
   [lifecycle] Copilot CLI runtime connected
   ```

   Podczas działania można w drugim terminalu wykonać
   `ps -ef | grep '[c]opilot'`, aby zobaczyć proces runtime bez odczytywania
   jego danych.

6. `create_session(model="auto", working_directory=...)` tworzy stanową sesję.
   `auto` deleguje wybór kwalifikującego się modelu do Copilot, a
   `working_directory` przypina wbudowane narzędzia plikowe do przygotowanego
   checkoutu. Przed tym krokiem program wypisuje listę MCP i przekazuje
   `disabled_mcp_servers`: SDK blokuje dokładne pasujące nazwy przed startem
   i uwierzytelnieniem serwerów w tej sesji, bez zmiany konfiguracji CLI.
   `on_event` zaczyna obserwować bezpieczne nazwy eventów, natomiast
   `PermissionHandler.approve_all` usuwa pytania interaktywne w tej
   kontrolowanej, tylko do odczytu demonstracji. Program wypisze identyfikator:

   ```text
   [lifecycle] Session created: <session-id>
   ```

7. Jedno `send_and_wait()` przekazuje prompt agentowi. Model dobiera wbudowane
   narzędzia, aby znaleźć `convert_costspec_to_cost` i test `TestZeroUnitsWithTotalCost`. Podczas pętli
   zobaczysz między innymi `session.start`, `tool.execution_start` i
   `tool.execution_complete`; callback celowo nie drukuje payloadów, argumentów
   poleceń ani treści plików.

8. Po zakończeniu tur runtime emituje `session.idle`. Dopiero wtedy
   `send_and_wait()` zwraca ostatnią wiadomość asystenta. Oczekiwany wynik to
   wyjaśnienie, dlaczego `0 HOOL {{20.00 USD}}` z issue #1048 rzuca `DivisionByZero`, bez
   zmian w checkoutcie, poprzedzone:

   ```text
   [lifecycle] Session idle

   Copilot response:
   ```

9. Po odpowiedzi sesja jest zamykana przed klientem. Finalne potwierdzenia to:

   ```text
   [lifecycle] Session closed
   [lifecycle] Copilot client closed
   ```

   Te same przejścia cleanup wykonują się również przy błędzie w środku sesji.

## Na co zwrócić uwagę

- **Wspólny kod** — denylista MCP i jej komunikat oraz wyświetlanie nazw
  eventów pochodzą z `copilot_runtime.py`; `show_event()` tylko deleguje
  bezpieczny output. Lista nadal trafia jawnie do `create_session()`.

- **Start** — `self.runtime.create_client()` przypina instalację CLI przez
  wspólny resolver i przekazuje środowisko klienta. Login, model, polityka
  tylko do odczytu, eventy oraz zamknięcie sesji i klienta pozostają bez zmian.

- **`DEFAULT_PROMPT` i `CONFIGURATION`** — cel jest tylko do odczytu, timeout
  wynosi 180 sekund, a oczekiwany commit gwarantuje powtarzalny kontekst.
- **`validate_configuration()`** — repozytorium i revision są sprawdzane przed
  startem klienta; błąd przygotowania nie zużywa żądania Copilot.
- **`CopilotClient(use_logged_in_user=True)`** — klient zarządza procesem CLI
  i połączeniem, korzystając z logowania CLI, a nie sesji VS Code.
- **`create_session()`** — sesja przechowuje historię i udostępnia wbudowane
  narzędzia agenta; `model="auto"` pozostawia wybór modelu usłudze, a
  `working_directory` wyznacza kontekst operacji plikowych.
- **Blokada MCP** — widoczna lista odpowiada `DISABLED_MCP_SERVERS`.
  `disabled_mcp_servers` dopasowuje dokładne nazwy i blokuje pasujące serwery
  tylko dla tej sesji; nie wyłącza wbudowanych narzędzi Copilot ani nie zmienia
  globalnej konfiguracji CLI.
- **Uprawnienia** — `PermissionHandler.approve_all` jest właściwe wyłącznie dla
  tej kontrolowanej prezentacji z jednoznacznym zakazem zmian. Produkcyjny host
  powinien oceniać każde żądanie uprawnień.
- **`show_event()`** — oczekuj przejścia `session.start` → eventy
  `tool.execution_*` → `session.idle`; drukowane są nazwy, nie potencjalnie
  wrażliwe payloady.
- **`send_and_wait()`** — eventy nadal docierają podczas oczekiwania, a wynik
  pojawia się dopiero po bezczynności sesji i musi być wiadomością asystenta.
- **Bezpieczny efekt** — odpowiedź może różnić się sformułowaniem, ale powinna
  wyjaśniać zachowanie na podstawie checkoutu. Demo nie powinno wypisywać
  poświadczeń ani pełnych payloadów eventów.
- **Cleanup** — kolejność to zamknięcie sesji, a potem klienta/runtime; oba
  potwierdzenia powinny pojawić się po poprawnej odpowiedzi.

Nie napisaliśmy transportu JSON-RPC, historii rozmowy, pętli wywołań narzędzi,
obsługi zdarzenia bezczynności ani procedury sprzątania. To różni runtime
agentowy Copilot od prostego wrappera na pojedynczy endpoint LLM.

## Test integracyjny

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/002-initialsession/test_main.py -v
```

Test nie mockuje klienta, sesji, poświadczeń, sieci ani repozytorium. Uruchamia
zainstalowany SDK i żywy runtime, wymaga przygotowanego wyżej klonu, sprawdza
zdarzenia narzędzi i `session.idle`, a po odpowiedzi porównuje `git status`.
Brak repozytorium, niewłaściwy commit lub problem z uwierzytelnieniem powoduje
czytelny błąd zamiast pominięcia testu.
