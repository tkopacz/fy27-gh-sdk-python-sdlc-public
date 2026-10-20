# Demo 007: GitHub MCP, historia i wznowienie

Demo czyta [beancount/beancount#1048](https://github.com/beancount/beancount/issues/1048)
i upstreamowy `CHANGES` przez GitHub MCP, proponuje dokumentację i wznawia
zapisaną sesję SDK przy kolejnym uruchomieniu. Opcjonalnie agent dokumentalista
edytuje lokalny `CHANGES`; osobny, zatwierdzony etap może utworzyć **draft PR
wyłącznie w forku**. Domyślny przebieg niczego nie edytuje ani nie publikuje.

## Wymagania i gotowa konfiguracja

- Repozytoryjne `.venv`, Python 3.10+, `github-copilot-sdk==1.0.14` i pytest
  z głównego `requirements.txt`. Nie instaluj Beancount do tego demo:
  nie wykonujemy jego kodu, tylko czytamy issue i edytujemy dokumentację.
- Natywny Copilot CLI, zapisane logowanie `copilot login`, aktywny dostęp do
  Copilot, sieć i dostęp do GitHub MCP. Logowanie `gh` nie zastępuje logowania
  Copilot; SDK korzysta z runtime CLI, nie z poświadczeń edytora.
- Istniejący fork `tkopacz/beancount` i niezależny checkout
  [workspace](./workspace), z `origin=https://github.com/tkopacz/beancount.git`,
  gałęzią `demo/beancount-1048` i bazą `master`.
  [CHANGES](./workspace/CHANGES) zawiera już przygotowaną przez SDK notatkę
  `Proposed documentation for issue #1048`, zatwierdzoną i wypchniętą do
  tej gałęzi forka. Nie trzeba ponownie uruchamiać etapu przygotowania.
- W [main.py](./main.py) `CONFIGURATION = DemoConfiguration()` ma gotowe
  ustawienia: `fork_owner="tkopacz"`, `resume=None`, `remote_mcp=False`,
  `prepare_draft=False`, `publish_draft=False`, model `auto`, limit 30 AI credits.
  Nie ma argumentów CLI. Zmieniaj nazwane pola konfiguracji w kodzie.
- `DEMO_007_FORK_OWNER` opcjonalnie nadpisuje właściciela. Nie trzeba go
  ustawiać dla przygotowanego forka. `DEMO_007_APPROVE_DRAFT_PR=yes` jest
  wymagane wyłącznie przy publikacji.

**Osobny `DEMO_007_GITHUB_MCP_TOKEN` nie jest potrzebny w domyślnym trybie.**
CLI zarządza połączeniem GitHub MCP i używa własnego logowania.
Zobacz też [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).

## Przebieg krok po kroku

Polecenia Windows uruchamiaj z głównego katalogu repozytorium.

1. Sprawdź checkout forka:

   ```powershell
   git -C demos\007-mcp-resume\workspace status --short
   git -C demos\007-mcp-resume\workspace branch --show-current
   git -C demos\007-mcp-resume\workspace remote -v
   ```

   Oczekuj czystego checkoutu, `demo/beancount-1048` i `origin` wskazującego
   fork, nie upstream. `upstream` może wskazywać `beancount/beancount`,
   ale demo nigdy do niego nie zapisuje. Istniejąca gałąź zawiera wcześniejszą
   poprawkę parsera; ten pokaz dotyczy MCP i dokumentacji, nie naprawy parsera.
   Sprawdzaj aktualny stan issue: nie zakładaj, że nadal jest otwarte.
2. Pozostaw domyślny `CONFIGURATION`. Uruchom:

   ```powershell
   .venv\Scripts\python.exe demos\007-mcp-resume\main.py
   ```

   Alternatywnie otwórz [main.py](./main.py) i naciśnij F5,
   **Python: Current File (.venv)**. Na Linux:
   `.venv/bin/python demos/007-mcp-resume/main.py`.
3. Sprawdź `Copilot CLI:`. Wspólny resolver wybiera natywne CLI także wtedy,
   gdy PATH wskazuje bootstrapper VS Code. `CopilotRuntime.create_client()`
   otwiera połączenie SDK stdio i używa zapisanego logowania CLI.
4. SDK `list_sessions()` sprawdza dokładny identyfikator `beancount-1048`.
   Dla nowej sesji zobaczysz `[session] created beancount-1048`;
   dla istniejącej `[session] resumed beancount-1048`. Domyślne `resume=None`
   nie nadpisuje historii i nie maskuje błędów wznowienia utworzeniem nowej sesji.
5. Przy pierwszej turze obserwuj `[mcp] github-mcp-server status=connected`,
   narzędzia `github-mcp-server-issue_read` i
   `github-mcp-server-get_file_contents`, `[tool] success=True` oraz
   `Copilot response:` z podsumowaniem. Agent może użyć `list_pull_requests`
   i `pull_request_read` wyłącznie w skonfigurowanym forku; brak PR jest
   poprawnym wynikiem. Wyjście `[fork]` wskazuje właściciela i gałąź.
6. Zaczekaj na zamknięcie kontekstów sesji i klienta. Uruchom to samo
   polecenie ponownie, bez zmiany kodu. Oczekuj `resumed`, niezerowego
   `events_before` i większego `events_after` po odpowiedzi. Wznowiona tura
   korzysta z wcześniejszego kontekstu i nie musi ponownie wywoływać MCP.
7. Zachowaj magazyn sesji CLI. Do ponownego pokazu pierwszej tury wybierz
   nowy `session_id` w konfiguracji i pozostaw `resume=None`.
   `resume=True` wymusza wznowienie istniejącej historii,
   `resume=False` jawnie tworzy nową sesję; używaj go z nowym identyfikatorem.

## Na co zwrócić uwagę

- **Cykl życia:** klient stdio -> lista zapisanych sesji -> create/resume ->
  odczyt historii -> tura modelu -> wzrost historii -> zamknięcie sesji i klienta.
  Historia na dysku pozostaje celowo dostępna do wznowienia w innym procesie.
- **Narzędzia i uprawnienia:** `READ_TOOLS`, `available_tools`, `tool_guard`
  i `permission` w [main.py](./main.py). Hook kontroluje argumenty także dla
  odczytów niewymagających monitu; powłoka, ogólny zapis i push są blokowane.
  `github_mcp_tool_config.additional_tools` włącza narzędzia zarządzane
  przez CLI, ale samo w sobie nie jest ograniczeniem argumentów po stronie serwera.
- **Zakres:** odczyt upstreamowego issue 1048 i `CHANGES`, odczyt PR w forku;
  lokalny zapis tylko przez `documentalist_update_versions` po opt-in;
  `create_pull_request` tylko przy zatwierdzonej publikacji.
- **Model i koszt:** `model="auto"`, timeout i `session_limits.max_ai_credits`.
  Limit 30 to wymagane minimum runtime; testy na żywo zużywają dostęp Copilot.
- **Zdarzenia:** `session.mcp_servers_loaded`, `tool.execution_start`,
  `tool.execution_complete`, `assistant.usage`, checkpointy użycia.
  Ewentualne metryki `subagent.completed` nie oznaczają, że subagent musi wystąpić.
  Callback pokazuje nazwy eventów i liczbowe metryki, nie argumenty/payloady.
  Końcowa odpowiedź modelu jest osobnym wynikiem dla operatora.
- **Sprzątanie:** konteksty SDK zamykają połączenia. Nie usuwamy sesji,
  checkoutu ani zmian dokumentalisty automatycznie. Program nigdy nie wysyła
  zmian Git i nie zapisuje surowej telemetrii.

## Gdzie wygenerować DEMO_007_GITHUB_MCP_TOKEN

**Nie generuj go dla domyślnego uruchomienia.** Jest potrzebny dopiero po
świadomym ustawieniu `remote_mcp=True`: jawne połączenie HTTP przez
SDK `mcp_servers` wymaga własnego nagłówka Authorization. Logowanie CLI
ani `gh auth login` nie wypełnia tego nagłówka.

1. Otwórz <https://github.com/settings/personal-access-tokens/new>
   (Settings -> Developer settings -> Personal access tokens ->
   Fine-grained tokens -> Generate new token).
2. Nazwij token `demo-007-github-mcp`, wybierz krótki termin ważności
   i **Resource owner: tkopacz**.
3. Do odczytu publicznych repozytoriów wybierz **Public repositories**,
   bez dodatkowych uprawnień zapisu. Token nie musi należeć do organizacji
   `beancount`, aby czytać jej publiczne issue i pliki.
4. Jeśli token ma też umożliwiać zatwierdzoną publikację draft PR, wybierz
   zamiast tego **Only select repositories -> tkopacz/beancount**.
   Ustaw **Pull requests: Read and write**, **Contents: Read-only**.
   **Metadata: Read-only** jest automatyczne. Publiczny upstream pozostaje
   dostępny do odczytu. Nie przyznawaj Contents write, Workflows,
   Administration ani dostępu do wszystkich repozytoriów.
5. Kliknij **Generate token** i zapisz wartość wyłącznie w globalnej zmiennej
   użytkownika `DEMO_007_GITHUB_MCP_TOKEN`, np. w Windows:
   **Edytuj zmienne środowiskowe dla konta -> Zmienne użytkownika -> Nowa**.
   Nie wklejaj sekretu do czatu, pliku, commita ani polecenia zachowanego w historii.
6. Zamknij wszystkie okna VS Code i uruchom edytor z nowego procesu,
   aby F5 i terminal odziedziczyły nową zmienną. Sprawdź tylko jej obecność:

   ```powershell
   Test-Path Env:DEMO_007_GITHUB_MCP_TOKEN
   ```

7. W konstruktorze `CONFIGURATION` ustaw `remote_mcp=True`, wybierz nowy
   `session_id` i pozostaw `resume=None`, `prepare_draft=False`,
   `publish_draft=False`. Uruchom zwykłe polecenie dema.
   Oczekuj `[mcp] github-remote status=connected`, udanych odczytów
   `github-remote-issue_read` i `github-remote-get_file_contents` oraz odpowiedzi.
   Nie zmieniaj transportu dla istniejącej sesji w trakcie prezentacji.
8. Po pokazie unieważnij zbędny token na
   <https://github.com/settings/personal-access-tokens> i usuń zmienną.

HTTP łączy się z `https://api.githubcopilot.com/mcp/`. `tools` i nagłówek
`X-MCP-Tools` ograniczają katalog do narzędzi tego etapu, a
`X-MCP-Readonly: true` dodatkowo blokuje zapis po stronie serwera
w etapach odczytu i przygotowania. Lokalna edycja dokumentalisty pozostaje
oddzielnym narzędziem SDK. Brak tokenu powoduje jawny błąd konfiguracji.
Ten tryb wymaga osobnej walidacji na żywo po dostarczeniu tokenu.

Źródła: [uwierzytelnianie GitHub Remote MCP](https://github.com/github/github-mcp-server/blob/main/docs/host-integration.md),
[konfiguracja serwera i trybu read-only](https://github.com/github/github-mcp-server/blob/main/docs/server-configuration.md).

## Kontrolowana edycja dokumentacji i draft PR

1. Zacznij od udanego przebiegu odczytu. Sprawdź czysty checkout i gałąź
   poleceniami z walkthrough. Jeśli `CHANGES` zawiera już proponowaną notatkę
   `issue #1048`, nie uruchamiaj przygotowania ponownie: dokument jest gotowy
   do przeglądu/publikacji. Powtórne wstawienie jest celowo odrzucane.
2. Dla nowego przygotowania ustaw w konstruktorze `CONFIGURATION`
   `prepare_draft=True`, `publish_draft=False`, `resume=None` i uruchom demo.
   Agent ponownie czyta issue i `CHANGES`, po czym wywołuje
   `documentalist_update_versions`. Narzędzie wstawia jeden akapit
   rozpoczynający się od `Proposed`, zawierający `DivisionByZero`,
   `0 HOOL {{20.00 USD}}` i `#1048`. Nie twierdzi, że bug został naprawiony.
   Oczekuj `[review]` i tylko zmiany `CHANGES`; SDK nie wykonuje commit/push.
3. Sprawdź dokument i zakres zmian:

   ```powershell
   git -C demos\007-mcp-resume\workspace diff -- CHANGES
   git -C demos\007-mcp-resume\workspace status --short
   ```

   Zweryfikuj treść względem issue i istniejącej poprawki na gałęzi.
   Dopiero po świadomym przeglądzie zatwierdź i wypchnij zmianę
   **do forka**, używając własnej tożsamości Git. Jeśli notatka jest już
   zatwierdzona, sprawdź ją przez `git log -1 -p -- CHANGES`.
4. Aby opublikować, ustaw `prepare_draft=False`, `publish_draft=True`,
   `resume=None`, a w środowisku procesu `DEMO_007_APPROVE_DRAFT_PR=yes`.
   Uruchom demo. Walidacja wymaga czystego checkoutu, notatki w `CHANGES`
   oraz identycznego SHA lokalnego HEAD i gałęzi wypchniętej do forka.
5. SDK udostępnia wtedy dodatkowo `create_pull_request`, ale zatwierdza
   wyłącznie `tkopacz/beancount`, head `demo/beancount-1048`,
   base `master`, `draft=True`. Sprawdź wynik w GitHub:
   <https://github.com/tkopacz/beancount/pulls>. Nie twórz duplikatu, jeśli
   taki draft już istnieje. Program nie scala PR ani nie oznacza go jako gotowego.
6. Po pokazie przywróć `prepare_draft=False`, `publish_draft=False`
   i usuń zmienną zatwierdzającą publikację. Nie usuwaj historii sesji,
   jeśli chcesz dalej demonstrować resume.

Nie ustawiaj właściciela forka na `beancount`. Zakres tokenu i ochrona gałęzi
są dodatkowymi zabezpieczeniami, nie zamiennikiem kontroli SDK.

## Testy na żywo

```powershell
.venv\Scripts\python.exe -m pytest --import-mode=importlib demos\007-mcp-resume\test_main.py -v
```

Na Linux użyj `.venv/bin/python -m pytest --import-mode=importlib demos/007-mcp-resume/test_main.py -v`.
Testy sprawdzają walidację, granice uprawnień i rzeczywiste SDK/CLI/GitHub MCP:
unikatowa sesja jest tworzona, klient zamykany i automatycznie wznawiany
w nowym procesie runtime. Drugi test live pobiera rzeczywisty bazowy commit
lokalnego forka do izolowanego checkoutu pytest i uruchamia dokumentalistę: sprawdza dokładną
notatkę, zachowanie całej pozostałej treści i zmianę wyłącznie `CHANGES`.
Bazą testu jest `origin/master`, więc działa także wtedy, gdy gałąź
prezentera zawiera już zatwierdzoną notatkę. Test nie tworzy commitów.

Testy nie podrabiają modelu, sesji, poświadczeń, sieci ani narzędzia edycji.
Nie zmieniają workspace prezentera, nie wysyłają zmian i nie tworzą PR.
Brak CLI, logowania, sieci, subskrypcji lub MCP powoduje błąd z instrukcją,
nie pominięcie testu. Testy domyślne weryfikują tryb zarządzany przez CLI;
tryb HTTP wymaga dodatkowo prawdziwego tokenu i osobnego przebiegu.
