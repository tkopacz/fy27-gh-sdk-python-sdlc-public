# Demo 004: bezpieczne narzędzie niestandardowe z hookiem przed użyciem

To demo kopiuje wzorzec własnego toola z Demo 003 i dodaje kontrolę ścieżek
przed jego wykonaniem. Agent dostaje wyłącznie `read_project_file(path)`.
Programowy `on_pre_tool_use` rozwiązuje ścieżkę względem przypiętego workspace,
śledzi symlinki i zezwala tylko na zwykłe pliki wewnątrz jawnie dozwolonych
katalogów. Próba odczytu kontrolowanego pliku obok workspace zostaje odrzucona,
a następny odczyt projektowego `README.rst` przechodzi.

## Przebieg krok po kroku

0. Przygotuj [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\004-custom-tool-secure\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Po walidacji checkoutu oczekuj `Copilot CLI: <ścieżka>` przed eventami;
   komunikat o wrapperze VS Code wskazuje wybraną natywną instalację.

1. Przygotuj Python 3.10+, GitHub Copilot CLI, dostęp do sieci i konto z aktywną
   subskrypcją. Z katalogu głównego repozytorium zainstaluj przypięte zależności:

   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

2. Sprawdź uwierzytelnienie runtime CLI:

   ```bash
   copilot -p "Reply with exactly: OK" --silent
   ```

   Oczekiwany wynik to `OK`. Logowanie rozszerzenia VS Code nie jest
   współdzielone z CLI. W razie braku sesji wykonaj `copilot login`; nie pokazuj
   ani nie kopiuj tokenu podczas prezentacji.

3. Przygotuj własny klon tego dema (`demos/004-custom-tool-secure/workspace`, tag `demo-red-1048`):

   ```bash
   .venv/bin/python prepare_workspaces.py
   ```

   Skrypt tworzy osobny klon dla każdego dema (`demos/<demo>/workspace/`,
   ignorowany przez Git), więc w trakcie pokazu nie przełączasz tagów.

   Aplikacja sprawdza katalog i pełny hash przed uruchomieniem Copilot. Jedynym
   dozwolonym rootem jest ten checkout. Kontrolowany plik
   `fixtures/outside-workspace.txt` leży poza nim i służy wyłącznie do pokazania
   odmowy; jego zawartość nie powinna pojawić się w odpowiedzi modelu.

4. Uruchom demo z katalogu głównego:

   ```bash
   .venv/bin/python demos/004-custom-tool-secure/main.py
   ```

5. Program waliduje konfigurację, buduje `WorkspaceReadPolicy`, a następnie
   drukuje dozwolony katalog i JSON Schema wygenerowany przez SDK z
   `ReadFileParams`. Pole `path` jest wymaganym, niepustym stringiem. To kontrakt
   argumentów toola, ale nie zastępuje autoryzacji rozstrzygniętej ścieżki.
   `defer="never"` udostępnia ten schemat modelowi od początku sesji, a
   `is_terminal=False` oddaje wynik odczytu agentowi do dalszego przetwarzania.

6. `CopilotClient(use_logged_in_user=True)` łączy się z uwierzytelnionym runtime
   CLI. `create_session()` przypina katalog roboczy, przez `tools` rejestruje
   `read_project_file`, ogranicza `available_tools` tylko do tego toola i
   przekazuje `hooks={"on_pre_tool_use": guard.check}`. Wypisana lista
   `MCP server names disabled for this session:` jest przekazana jako
   `disabled_mcp_servers`; pasujące dokładne nazwy nie startują ani nie
   uwierzytelniają się w tej sesji. `skip_permission=True`
   wyłącza standardowe pytanie o zgodę na tool; w tym demo jest to bezpieczne
   wyłącznie dlatego, że programowy hook rozstrzyga każdą próbę przed handlerem,
   a handler ponawia kontrolę. `enable_file_hooks=False` wyłącza odkrywanie
   hooków z plików, lecz pozostawia aktywny programowy hook demonstracyjny.

7. Jeden `send_and_wait()` prosi model o dwa odczyty. Pierwsze wywołanie używa
   `../fixtures/outside-workspace.txt`. Runtime
   wywołuje pre-tool hook przed handlerem. Polityka rozwiązuje `..` do ścieżki
   kanonicznej, wykrywa wyjście poza root i zwraca
   `permissionDecision="deny"`. Zobaczysz:

   ```text
   [hook] deny tool=read_project_file path=../fixtures/outside-workspace.txt
   [event] tool.execution_complete tool=read_project_file success=False
   ```

   Nie pojawi się odpowiadający wpis `[tool] read ...`, co pokazuje, że handler
   nie dostał dostępu do pliku.

8. Wynik odmowy wraca do pętli agenta. Model wykonuje drugi odczyt dla
   `README.rst`. Hook rozwiązuje ścieżkę wewnątrz workspace, zwraca `allow` i
   dopiero wtedy SDK uruchamia handler:

   ```text
   [hook] allow tool=read_project_file path=README.rst
   [tool] read path=README.rst
   [event] tool.execution_complete tool=read_project_file success=True
   ```

   Handler ponownie stosuje tę samą politykę jako defense in depth. Dzięki
   `is_terminal=False` zawartość wraca do kolejnej tury modelu.

9. Po `session.idle` odpowiedź potwierdza blokadę pierwszej ścieżki i podaje
   tytuł `Double-Entry Accounting` z dozwolonego pliku. Program nie drukuje pełnych
   payloadów eventów ani zawartości kontrolowanego pliku. Na końcu oczekuj:

   ```text
   [lifecycle] Session closed
   [lifecycle] Copilot client closed
   ```

   Cleanup sesji i runtime odbywa się również po błędzie.

## Na co zwrócić uwagę

- **Wspólny kod** — denylista MCP, jej komunikat i drukowanie nazwy `session.idle`
  pochodzą z `copilot_runtime.py`. Własny callback nadal selekcjonuje eventy
  i bezpieczne pola związane z odmową/odczytem, zamiast drukować cały payload.

- **Start** — `self.runtime.create_client()` współdzieli wybór CLI z innymi
  demami. Hooki, dozwolone ścieżki i odmowy pozostają bez zmian; konteksty
  klienta i sesji nadal zamykają połączenie i proces po błędzie lub sukcesie.

- **`WorkspaceReadPolicy.authorize()`** — ścieżki względne są liczone od
  workspace, a `resolve(strict=True)` normalizuje `..` i śledzi symlinki przed
  porównaniem z dozwolonym rootem.
- **Fail closed** — brak ścieżki, nieistniejący plik, katalog, plik poza rootem,
  symlink wychodzący poza root, inny tool lub inny katalog roboczy oznacza
  odmowę, nie domyślne zezwolenie.
- **`ProjectReadGuard.check()`** — ten callback jest właściwym pre-tool hookiem.
  `deny` zatrzymuje wywołanie przed handlerem; `permissionDecisionReason` wraca
  do runtime i pozwala agentowi bezpiecznie kontynuować.
- **`build_read_tool()`** — Pydantic generuje schemat argumentów, ale walidacja
  typu nie rozstrzyga bezpieczeństwa ścieżki. Handler ponawia kontrolę, aby
  bezpośrednie wywołanie poza pętlą również było bezpieczne.
- **Rejestracja i wybór toola** — `tools=[read_tool]` rejestruje własny handler,
  `defer="never"` pokazuje jego schemat modelowi od początku, a
  `available_tools=["read_project_file"]` usuwa możliwość obejścia polityki
  innym wbudowanym narzędziem odczytu lub shellem.
- **Blokada MCP** — `disabled_mcp_servers` blokuje dokładne nazwy serwerów
  przed ich uruchomieniem/uwierzytelnieniem tylko w tej sesji. Nie zmienia
  allowlisty tooli, hooka ścieżek ani ustawień CLI.
- **Uprawnienia i wynik toola** — `skip_permission=True` pomija standardowe
  pytanie tylko dlatego, że hook i handler wymuszają tę samą politykę.
  `is_terminal=False` zwraca dozwoloną zawartość do pętli agenta zamiast kończyć
  sesję wynikiem toola.
- **Hooki programowe i plikowe** — `hooks=...` włącza callback SDK, natomiast
  `enable_file_hooks=False` gwarantuje, że demo nie ładuje przypadkowych hooków
  z checkoutu.
- **Eventy** — `tool.execution_start/complete` pokazują obie próby, ale terminal
  ujawnia tylko nazwę toola, żądaną ścieżkę i status, nie zawartość plików.
- **Model** — `model="auto"` pozostawia wybór kwalifikującego się modelu usłudze
  Copilot; demo nie używa BYOK ani własnego providera.
- **Cleanup** — konteksty asynchroniczne zamykają najpierw sesję, a potem klienta
  i zarządzany runtime CLI.

## Testy

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/004-custom-tool-secure/test_main.py -v
```

Testy polityki wykonują prawdziwe odczyty lokalne i obejmują poprawny plik,
wyjście przez `..`, ścieżkę absolutną, brak pliku i symlink uciekający z rootu.
Testy kontraktu przechodzą przez wrapper zainstalowanego `@define_tool` i
sprawdzają walidację schematu oraz defense in depth.

Test integracyjny nie mockuje klienta, sesji, modelu, hooka, poświadczeń, sieci
ani checkoutu. Prawdziwy Copilot runtime musi spróbować obu wywołań; test
potwierdza odmowę przed handlerem, dozwolony odczyt, finalną odpowiedź, cleanup
i niezmieniony worktree. Brak logowania, sieci, subskrypcji lub przypiętego
checkoutu kończy test czytelnym błędem zamiast pominięcia integracji.
