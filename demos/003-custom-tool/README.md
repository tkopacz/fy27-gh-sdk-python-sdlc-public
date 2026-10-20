# Demo 003: własne narzędzie w gotowej pętli agenta

To demo pokazuje, że dodajemy logikę domenową, a GitHub Copilot SDK wykonuje
całą pętlę wywołań narzędzi. Aplikacja definiuje model Pydantic, handler
czytający lokalny snapshot issue oraz sposób prezentacji zdarzeń. Runtime
wybiera tool, waliduje argumenty, uruchamia handler i kontynuuje pracę.

## Przebieg krok po kroku

0. Przygotuj [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\003-custom-tool\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Oczekuj `Copilot CLI: <ścieżka>` przed eventami SDK. Bootstrapper VS Code
   jest rozpoznawany i zastępowany natywnym CLI z jawnym komunikatem.

1. Przygotuj zależności i uwierzytelnienie CLI według poleceń poniżej.
2. Uruchom `.venv/bin/python demos/003-custom-tool/main.py` z katalogu repozytorium.
3. Obserwuj listę `MCP server names disabled for this session:`. Sesja SDK
   blokuje dokładnie pasujące serwery przed ich startem/uwierzytelnieniem;
   ograniczenie jest lokalne dla sesji i nie zmienia globalnej konfiguracji CLI.
   Następnie obserwuj schemat `IssueParams` oraz utworzenie klienta i sesji SDK.
4. Model wybierze `get_requirement(number=1048)`, a handler odczyta lokalny
   snapshot. Eventy narzędzia potwierdzą prawdziwe wywołanie przez runtime.
5. Wynik wróci do następnej tury modelu. Po `session.idle` zobaczysz odpowiedź
   opartą na snapshotcie oraz zamknięcie sesji i klienta.

### Przygotowanie

Wymagane są Python 3.11+, pakiet `github-copilot-sdk`, GitHub Copilot CLI,
dostęp do sieci, aktywna subskrypcja Copilot i uwierzytelnienie CLI. Logowanie
w rozszerzeniu VS Code nie jest współdzielone z runtime CLI.

Z katalogu głównego tego repozytorium:

```bash
.venv/bin/pip install -r requirements.txt
copilot -p "Reply with exactly: OK" --silent
```

Drugie polecenie sprawdza prawdziwe uwierzytelnienie bez wyświetlania
poświadczeń. Jeżeli zgłasza brak logowania, uruchom `copilot login`. Snapshot
issue `beancount#1048` jest zapisany w `fixtures/beancount-1048.json`,
więc Demo 003 nie potrzebuje sieci do odczytu wymagania.

## Uruchomienie

```bash
.venv/bin/python demos/003-custom-tool/main.py
```

Program powinien kolejno pokazać model `auto`, schemat JSON wygenerowany z
`IssueParams`, identyfikator sesji, zdarzenia `assistant.turn_start`,
`tool.execution_start` i `tool.execution_complete`, argument `1048` wybrany
przez model, `session.idle`, odpowiedź korzystającą z fixture oraz komunikaty
o zamknięciu sesji i klienta.

Jedno `session.send_and_wait()` wystarcza, żeby runtime wykonał kilka tur
modelu: najpierw wywołanie `get_requirement`, potem odpowiedź na podstawie
zwróconych danych.

## Na co zwrócić uwagę

- **Wspólny kod** — denylista MCP, jej komunikat i `print_event()` mieszkają
  w `copilot_runtime.py`. W callbacku dema pozostają licznik tur, schema
  argumentu issue i wyniki własnego narzędzia; ich format się nie zmienia.

- **Start** — `self.runtime.create_client()` używa tego samego resolvera co
  pozostałe dema. Zmienia wybór procesu CLI, nie schema `get_requirement`,
  model ani politykę uprawnień. Konteksty sesji i klienta zamykają runtime.

1. `IssueParams` jest kontraktem argumentów. SDK zamienia typ Pydantic na
   schemat widziany przez model.
2. `@define_tool` rejestruje `get_requirement`. `defer="never"` trzyma tool w
   pierwszej turze, zamiast chować go za tool search.
3. `create_session(tools=[get_requirement], available_tools=["get_requirement"])`
   dodaje handler domenowy i ogranicza katalog narzędzi do tej jednej funkcji.
   `disabled_mcp_servers` niezależnie blokuje dokładnie nazwane serwery MCP
   przed ich startem; nie zmienia allowlisty custom toola.
4. Nie wywołujemy handlera ręcznie. Model wybiera tool, SDK waliduje `number`
   przed handlerem i odsyła wynik do kolejnej tury.
5. Callback loguje `assistant.turn_start`, `tool.execution_start` i
   `tool.execution_complete` bez wypisywania wrażliwych payloadów.

Kod po naszej stronie to typ danych i odczyt lokalnego snapshotu. Kod
dostarczony przez SDK to wybór toola, walidacja protokołu, wykonanie handlera,
przekazanie wyniku i kontynuacja pętli. Piszemy funkcję domenową, nie
framework do function calling.

`PermissionHandler.approve_all` oraz `skip_permission=True` upraszczają tę
kontrolowaną, tylko do odczytu demonstrację. W aplikacji produkcyjnej należy
oceniać każde żądanie uprawnień, a `skip_permission` zostawić wyłącznie dla
narzędzi, które nie zmieniają stanu.

## Test integracyjny

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/003-custom-tool/test_main.py -v
```

Test nie mockuje klienta, sesji, poświadczeń, sieci ani fixture. Sprawdza
schemat wygenerowany przez `@define_tool`, odrzucenie brakującego snapshotu i
nieznanego numeru issue, a następnie uruchamia zainstalowany SDK i żywy
runtime. Żywa sesja musi wywołać `get_requirement`, zalogować tury narzędzi i
odpowiedzieć na podstawie fixture. Brak snapshotu albo problem z
uwierzytelnieniem powoduje czytelny błąd zamiast pominięcia testu.
