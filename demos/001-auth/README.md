# Demo 001: uwierzytelnianie

Demo wysyła to samo żądanie jedną z dwóch ścieżek uwierzytelniania obsługiwanych
przez GitHub Copilot SDK:

1. poświadczenia zapisane przez `copilot login` (wymagana subskrypcja Copilot);
2. własny dostawca modelu, czyli BYOK (koszt żądania rozlicza dostawca).

Sekrety są pobierane ze zmiennych środowiskowych i nigdy nie są drukowane.
Domyślna `CONFIGURATION` w `main.py` używa zapisanego logowania, modelu `auto`
i wykonuje prawdziwe żądanie.

## Przebieg krok po kroku

0. Start jest wspólny dla wszystkich dem: [wybór CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\001-auth\main.py`
   albo otwórz `main.py` i użyj **Python: Current File (.venv)** / F5.
   Przy prawdziwym żądaniu oczekuj `Copilot CLI: <ścieżka>` przed eventami.
   Rozpoznany wrapper VS Code daje dodatkowy komunikat z natywnym CLI.

1. Z katalogu głównego repozytorium zainstaluj przypięte zależności:

   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

2. Upewnij się, że GitHub Copilot CLI jest dostępny, konto ma aktywną
   subskrypcję, a runtime CLI jest uwierzytelniony:

   ```bash
   copilot -p "Reply with exactly: OK" --silent
   ```

   To polecenie sprawdza logowanie bez ujawniania poświadczeń. Logowanie
   w rozszerzeniu VS Code nie uwierzytelnia osobnego runtime CLI. Jeśli pojawi
   się `No authentication information found`, wykonaj `copilot login` i ponów
   sprawdzenie. W devcontainerze token może być przekazany przez mechanizm
   opisany w [konfiguracji przekazania poświadczeń](../../README.md#kontener-deweloperski);
   wtedy osobne `copilot login` nie jest potrzebne.

3. Opcjonalnie, przed żądaniem ustaw w `CONFIGURATION`
   `operation="status"` i uruchom:

   ```bash
   .venv/bin/python demos/001-auth/main.py
   ```

   Aplikacja tylko sprawdzi, czy znaleziono CLI, zapisane logowanie i wskazane
   zmienne. Nie uruchomi sesji i pokaże wyłącznie stany `set`/`not set` oraz
   `detected`/`not detected`, nigdy wartości sekretów. Ten status jest
   diagnostyką dostępnych źródeł, a nie dowodem, którego źródła runtime użyje
   podczas kolejnego żądania.

4. Przywróć domyślną konfigurację żądania:

   ```python
   CONFIGURATION = DemoConfiguration(
       operation="request",
       authentication="logged-in",
       model="auto",
       prompt=DEFAULT_PROMPT,
       dry_run=False,
   )
   ```

5. Uruchom demo z katalogu głównego:

   ```bash
   .venv/bin/python demos/001-auth/main.py
   ```

   Alternatywnie z katalogu `demos/001-auth` wykonaj:

   ```bash
   ../../.venv/bin/python main.py
   ```

6. Obserwuj kolejno `Authentication: saved GitHub login`, `Model: auto`,
   listę `MCP server names disabled for this session:` i dokładny prompt.
   `CopilotClient(use_logged_in_user=True)` uruchamia i łączy runtime CLI,
   pozwalając mu użyć poświadczeń GitHub zarządzanych przez CLI.
   `create_session()` tworzy sesję z modelem `auto`, callbackiem eventów,
   polityką `PermissionHandler.approve_all` i listą nazw MCP zablokowanych
   przed uruchomieniem.

7. Lista blokady zawiera dokładne nazwy z lokalnego
   `~/.copilot/mcp-config.json` (`azure-devops`,
   `io.github.github/github-mcp-server`, `microsoft/playwright-mcp`,
   `microsoftdocs/mcp`, `playwright`, `tavily`) oraz popularne nazwy/aliasy,
   m.in. `github`, `azure`, `azure-mcp-server`, `azure-devops-mcp-server`
   i `workiq`. `disabled_mcp_servers` dopasowuje serwery po dokładnej nazwie:
   runtime nie uruchamia ani nie uwierzytelnia pasujących serwerów dla tej
   sesji. Jeśli konfiguracja doda serwer pod nową nazwą, dopisz ją do
   `DISABLED_MCP_SERVERS` w `main.py`. Opcja nie zmienia globalnej konfiguracji
   CLI; pozostałe odkrywane ustawienia, instrukcje i agenty pozostają dostępne.

8. `session.send_and_wait()` wysyła prompt. W trakcie oczekiwania callback
   pokazuje tylko bezpieczne nazwy eventów, na przykład:

   ```text
   [event] SESSION_START -> session.start
   [event] ASSISTANT_TURN_START -> assistant.turn_start
   [event] ASSISTANT_MESSAGE -> assistant.message
   [event] SESSION_IDLE -> session.idle
   ```

   Payloady nie są wyświetlane, ponieważ mogą zawierać prompt, dane narzędzi
   lub błędy. Po `session.idle` metoda zwraca ostatnią wiadomość asystenta.

9. Końcowym wynikiem jest nagłówek `Copilot response:` i odpowiedź na
   `DEFAULT_PROMPT` (`Authentication works.`). Jeżeli runtime zakończy sesję
   bez wiadomości asystenta, zobaczysz bezpieczny komunikat
   `Copilot completed without an assistant message.`. Wyjście z obu bloków
   zarządzających cyklem życia zamyka sesję, połączenie i runtime także przy
   błędzie; demo nie wypisuje osobnych komunikatów cleanup.

### Wariant BYOK

1. Ustaw klucz dostawcy wyłącznie w zmiennej środowiskowej — nie wpisuj go do
   `main.py`, README ani outputu:

   ```bash
   export COPILOT_BYOK_API_KEY="..."
   ```

2. Ustaw konfigurację zgodną z endpointem, na przykład dla OpenAI:

   ```python
   CONFIGURATION = DemoConfiguration(
       operation="request",
       authentication="byok",
       provider_type="openai",
       provider_base_url="https://api.openai.com/v1",
       provider_wire_api="completions",
       model="gpt-4.1",
       api_key_variable="COPILOT_BYOK_API_KEY",
       dry_run=False,
   )
   ```

3. Uruchom to samo polecenie. `build_byok_provider()` odczyta sekret ze
   wskazanej zmiennej, a `CopilotClient(use_logged_in_user=False)` zablokuje
   cichy fallback do zapisanych poświadczeń GitHub. `create_session(provider=…)`
   skieruje wywołania modelu do podanego dostawcy. Output pokaże typ i URL
   dostawcy, wire API oraz tylko stan `API key: configured`, a następnie eventy
   i finalną odpowiedź.

Microsoft Foundry z kompatybilnym endpointem `/openai/v1/` również używa
`provider_type="openai"`; wdrożenia rodziny GPT-5 zwykle wymagają
`provider_wire_api="responses"`. Natywny Azure OpenAI używa
`provider_type="azure"`, bazowego URL zasobu i na przykład
`azure_api_version="2024-10-21"`. Lokalny, kompatybilny dostawca taki jak
Ollama może używać `provider_base_url="http://localhost:11434/v1"` oraz
`api_key_variable=None`. Dla każdego custom providera model jest obowiązkowy.

### Katalog eventów bez uruchamiania sesji

Ustaw `operation="events"` i uruchom demo. Aplikacja odczyta
`SessionEventType` z zainstalowanej wersji SDK oraz wypisze nazwy symboliczne
i wire wszystkich obsługiwanych eventów. Nie tworzy klienta ani sesji; jest to
katalog możliwości, a nie zapis konkretnego wykonania. Domyślne
`operation="request"` rejestruje ten sam bezpieczny callback i pokazuje tylko
eventy rzeczywiście wyemitowane podczas żądania.

## Na co zwracać uwagę

- **Wspólny kod** — `copilot_runtime.py` zawiera denylistę MCP, jej komunikat
  i `print_event(..., symbolic=True)`; callback dema zachowuje tylko
  dodatkową obserwację statusów serwerów. Dopisuj nazwy MCP w module wspólnym.

- **Runtime** — `CopilotSdkAdapter` używa wspólnego `CopilotRuntime.create_client()`;
  jawna ścieżka stdio i środowisko klienta omijają bootstrapper VS Code, ale
  nie zmieniają `use_logged_in_user=False` w BYOK. `status`, `events` i dry-run
  nie uruchamiają runtime. Konteksty klienta i sesji nadal zapewniają cleanup.

- **`CONFIGURATION` i `execute()`** — `status` i `events` kończą się bez sesji;
  dopiero `request` wybiera ścieżkę `logged-in` albo `byok`. `dry_run=True`
  pokazuje konfigurację, ale nie tworzy klienta ani nie wysyła promptu.
- **Wybór poświadczeń** — `use_logged_in_user=True` zezwala runtime CLI na
  użycie konta GitHub; w BYOK wartość `False` celowo uniemożliwia fallback.
- **Model i provider** — `auto` deleguje wybór kwalifikującego się modelu do
  Copilot. BYOK przekazuje jawne `model`, `type`, `base_url` i `wire_api`;
  provider rozlicza takie wywołanie.
- **`create_session()`** — sesja przechowuje stan rozmowy i koordynuje tury
  modelu, narzędzia, prośby o uprawnienia oraz strumień eventów.
- **Uprawnienia** — `PermissionHandler.approve_all` usuwa interaktywne pytania
  w tym jednorazowym demo. Host produkcyjny powinien oceniać każde żądanie.
- **Serwery MCP** — `DISABLED_MCP_SERVERS` przekazuje do `create_session()`
  dokładne identyfikatory z konfiguracji Copilot oraz popularne aliasy.
  Runtime nie startuje i nie uwierzytelnia pasujących serwerów w tej sesji;
  denylista nie jest wildcardem ani zmianą globalnych ustawień. Dodaj nazwę,
  jeśli nowy serwer pojawi się w konfiguracji pod innym identyfikatorem.
- **Eventy i bezpieczny output** — `print_event_placeholder()` wypisuje tylko
  nazwę eventu; nie pokazuj pełnych payloadów ani wartości tokenów/kluczy.
- **Przejścia cyklu życia** — klient łączy runtime, sesja przechodzi od
  `session.start` przez tury do `session.idle`, po czym najpierw zamykana jest
  sesja, a następnie klient.
- **Końcowy efekt** — spodziewaj się odpowiedzi asystenta, nie konkretnej listy
  eventów: zestaw pośrednich eventów może zależeć od runtime i modelu.

## Test integracyjny

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/001-auth/test_main.py -v
```

Testy wymagają uwierzytelnionego runtime Copilot CLI, subskrypcji Copilot,
sieci i dostępu do modelu `auto`. Test wysyła prawdziwy, deterministyczny prompt
i weryfikuje ukończenie sesji, odpowiedź oraz statusy serwerów z denylisty
zgłoszone przez event SDK. Brak wymaganego dostępu powoduje czytelny błąd testu,
a nie ciche pominięcie.

albo z katalogu tego dema:

```bash
python main.py
```

Program wypisuje wybrany sposób uwierzytelniania i model, dokładny prompt
przekazany do `session.send_and_wait()`, każdy event SDK wyemitowany przez
runtime oraz końcową odpowiedź Copilot. Ustaw `operation` na `status` lub
`events` tylko wtedy, gdy zamiast domyślnego żądania na żywo chcesz wyświetlić
jeden z tych widoków diagnostycznych.

Ustawienia niebędące sekretami, takie jak model i adres URL providera,
znajdują się w tym obiekcie konfiguracji. `api_key_variable` zawiera wyłącznie
nazwę zmiennej środowiskowej, z której aplikacja pobiera klucz BYOK.

## Sprawdzanie środowiska

Ustaw `operation="status"` i uruchom demo.

Polecenie informuje wyłącznie, czy dostępne jest każde źródło poświadczeń.
Runtime wybiera poświadczenia GitHub w następującej kolejności:
`COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, zapisane logowanie
Copilot, a następnie poświadczenia GitHub CLI.

## Eventy sesji

Wyświetl wszystkie typy eventów udostępniane przez zainstalowany SDK:

```python
CONFIGURATION = DemoConfiguration(operation="events")
```

Oba uwierzytelnione przebiegi rejestrują ten sam ogólny callback-placeholder
przed utworzeniem sesji. Wypisuje on symboliczne i protokołowe nazwy każdego
eventu faktycznie wyemitowanego przez runtime, nie ujawniając potencjalnie
wrażliwego payloadu:

```text
[event] SESSION_START -> session.start
[event] ASSISTANT_TURN_START -> assistant.turn_start
[event] ASSISTANT_MESSAGE -> assistant.message
[event] SESSION_IDLE -> session.idle
```

Katalog jest generowany z `SessionEventType`, dlatego pozostaje zgodny
z zainstalowaną wersją SDK i nie wymaga utrzymywania drugiej, zakodowanej
na stałe listy.

Domyślne `operation="request"` również rejestruje callback eventów, więc
pokazuje eventy faktycznie emitowane przez sesję na żywo, zamiast jedynie
wymieniać typy obsługiwane przez zainstalowany SDK.

## Zapisane logowanie GitHub

Zaloguj się raz, a następnie pozwól SDK ponownie używać zapisanych poświadczeń:

```bash
copilot login
```

```python
CONFIGURATION = DemoConfiguration(
  operation="request",
  authentication="logged-in",
  model="auto",
  dry_run=False,
)
```

`CopilotClient(use_logged_in_user=True)` jawnie określa tę intencję. Jest to
również domyślne ustawienie SDK, jeśli nie podano jawnie tokenu GitHub.

## Własny provider (BYOK)

Dla endpointu zgodnego z OpenAI przechowuj klucz w zmiennej środowiskowej:

```bash
export COPILOT_BYOK_API_KEY="..."
```

```python
CONFIGURATION = DemoConfiguration(
    operation="request",
    authentication="byok",
    provider_type="openai",
    provider_base_url="https://api.openai.com/v1",
    model="gpt-4.1",
    api_key_variable="COPILOT_BYOK_API_KEY",
    dry_run=False,
)
```

Endpoint `/openai/v1/` Microsoft Foundry zgodny z OpenAI również używa
`provider_type="openai"`; wdrożenia z rodziny GPT-5 zazwyczaj wymagają
`provider_wire_api="responses"`.

Dla natywnego endpointu Azure OpenAI użyj typu providera Azure:

```python
CONFIGURATION = DemoConfiguration(
    operation="request",
    authentication="byok",
    provider_type="azure",
    provider_base_url="https://RESOURCE.openai.azure.com",
    model="DEPLOYMENT_NAME",
    api_key_variable="COPILOT_BYOK_API_KEY",
    azure_api_version="2024-10-21",
    dry_run=False,
)
```

Dla lokalnego providera zgodnego z OpenAI, takiego jak Ollama, klucz nie jest wymagany:

```python
CONFIGURATION = DemoConfiguration(
    operation="request",
    authentication="byok",
    provider_type="openai",
    provider_base_url="http://localhost:11434/v1",
    model="qwen2.5-coder",
    api_key_variable=None,
    dry_run=False,
)
```

BYOK ustawia `use_logged_in_user=False`, więc przykład nie może po cichu
przełączyć się na zapisane poświadczenia GitHub. Przy własnym providerze
podanie modelu jest obowiązkowe.

## Testy integracyjne

Zestaw testów używa zainstalowanego SDK Pythona, uruchamia prawdziwy runtime
Copilot i wysyła deterministyczne żądanie z uwierzytelnieniem GitHub. Nie
stosuje atrap klientów, sesji, poświadczeń, providerów ani wywołań sieciowych.

Logowanie do rozszerzenia GitHub Copilot w VS Code nie uwierzytelnia
oddzielnego runtime Copilot CLI używanego przez SDK. W przepływie kontenera
deweloperskiego WSL skrypt hosta przygotowuje token, który kontener dziedziczy
po przebudowaniu; zobacz [konfigurację przekazywania poświadczeń](../../README.md#kontener-deweloperski).
Po przekazaniu tego tokenu osobne `copilot login` nie jest wymagane.
Najpierw sprawdź sesję CLI:

```bash
copilot -p "Reply with exactly: OK" --silent
```

Jeśli polecenie zgłosi `No authentication information found`, uruchom
`copilot login`. Konto musi mieć aktywną subskrypcję Copilot, a test wymaga
dostępu do sieci. Następnie uruchom:

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/001-auth/test_main.py -v
```

Brak lub nieprawidłowe uwierzytelnienie kończy test na żywo błędem z instrukcją
konfiguracji; test nigdy nie jest po cichu pomijany. Zaliczenie zestawu
potwierdza więc, że żądanie i odpowiedź przeszły przez rzeczywiste granice
SDK i GitHub Copilot.
