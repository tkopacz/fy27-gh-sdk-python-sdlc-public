# Demo 009: własny klient webowy dla Copilot CLI przez ACP

Demo pokazuje, jak własny interfejs WWW może rozmawiać z GitHub Copilot CLI
bez używania jego interaktywnego terminala ani Python SDK. Pythonowy backend
używa oficjalnego pakietu `agent-client-protocol` jako klient ACP i uruchamia
osobny proces CLI w trybie serwera ACP. Wiadomości JSON-RPC płyną jako NDJSON
przez `stdin` i `stdout`; FastAPI udostępnia interfejs przeglądarce i przekazuje
aktualizacje do niej przez Server-Sent Events (SSE).

ACP Copilot CLI jest w public preview; opcje i kompatybilność mogą się zmieniać.
Szczegóły: [Copilot CLI ACP server](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server)
oraz [oficjalny Python SDK ACP](https://agentclientprotocol.github.io/python-sdk/).

## Wymagania i uruchomienie

Potrzebne są Python 3.10+, repozytoryjne `.venv` z `requirements.txt`, Copilot
CLI na `PATH`, sieć oraz aktywna subskrypcja Copilot uwierzytelniona przez
`copilot login` (albo skonfigurowany przez użytkownika provider BYOK). Logowanie
w rozszerzeniu VS Code nie zastępuje logowania CLI. Test integracyjny wysyła
prawdziwy prompt przez klienta HTTP, ACP i lokalny proces Copilot CLI; może
zużyć kredyty. Brak CLI, logowania, sieci lub dostępu do usługi powoduje
czytelne niepowodzenie, a nie pominięcie testu.

Z katalogu głównego repozytorium uruchom:

```bash
.venv/bin/python demos/009-acp-web/main.py
```

Otwórz adres wypisany przez program (domyślnie
`http://127.0.0.1:8765`). Kliknij **Start a session**, wyślij prompt, a potem
zamknij sesję przyciskiem **Close session**. Serwer wiąże się wyłącznie z
loopbackiem. Każda sesja to osobny proces `copilot --acp --stdio`, ograniczony
do narzędzi `view` i `grep`; demo nie dopuszcza narzędzi edycji, terminala ani
MCP. Maksymalnie dwie sesje mogą działać jednocześnie. Zakończenie serwera
zamyka wszystkie należące do niego procesy ACP.

Nie wystawiaj tego prototypu do sieci ani nie traktuj listy narzędzi jako
uwierzytelnienia użytkownika. Serwer lokalny nie ma logowania, autoryzacji
użytkowników, izolacji tenantów, trwałego magazynu sesji ani ochrony
produkcyjnej. Nie wpisuj sekretów ani prywatnych danych do promptów.

## Przebieg krok po kroku

0. Przygotuj [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\009-acp-web\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Oczekuj `Copilot CLI: <ścieżka>` przed adresem serwera. Przy tworzeniu sesji
   ACP ten sam resolver omija rozpoznany bootstrapper VS Code i uruchamia
   natywny CLI; punkt wejścia `.js` wymaga Node.js.

1. **Przygotuj środowisko:** utwórz `.venv`, zainstaluj `requirements.txt`, skonfiguruj dostęp do
   Copilot CLI, a następnie wykonaj `copilot login`. Uruchom w katalogu głównym:
   `.venv/bin/python demos/009-acp-web/main.py`.
2. Sprawdź komunikat z adresem `127.0.0.1:8765` i otwórz go w przeglądarce.
   Kliknięcie **Start a session** wywołuje `POST /api/sessions`; backend
   uruchamia osobny proces CLI z `--acp --stdio`, przekazując login CLI, ale nie
   wypisując tokenu.
3. Wskaż w `ACPSessionManager.create_session()` wywołanie
   `spawn_agent_process()`. ACP rezerwuje standardowe wyjście procesu na
   strumień protokołu, więc logi serwera trafiają na standardowe wyjście
   backendu, nie do stdout procesu CLI.
4. Backend wykonuje ACP `initialize`, a następnie `new_session` z katalogiem
   roboczym repozytorium i pustą listą MCP servers. Każde kliknięcie **Start**
   tworzy niezależny kontekst rozmowy, a sesji przypisywany jest własny proces.
5. Wyślij: `Reply with exactly ACP_OK. Do not use tools.` Przeglądarka otwiera
   `EventSource` dla `/events`, a następnie wysyła JSON przez
   `POST /messages`. Backend konwertuje prompt na blok ACP `text_block` i czeka
   na zakończenie tury.
6. Obserwuj zdarzenia SSE. Tekst agenta pojawia się jako `agent_message_chunk`;
   inne aktualizacje pokazują jedynie nazwę zdarzenia i bezpieczny tytuł
   wywołania narzędzia. Po `turn_complete` backend zwraca `stop_reason`.
7. Jeśli chcesz zobaczyć użycie narzędzia, wyślij krótką prośbę o odczyt
   istniejącego pliku z repozytorium, bez edycji. CLI ma allowlistę tylko
   `view,grep`, a backend zatwierdza wyłącznie jednorazowe żądania typu `read`
   lub `search`; każdą inną prośbę o uprawnienie odrzuca.
8. Kliknij **Close session**. ACP otrzymuje `session/close`, a kontekst
   `spawn_agent_process` zamyka proces. Następnie zatrzymaj serwer Ctrl+C;
   lifespan FastAPI sprząta pozostałe sesje. Nie są zapisywane pliki ani
   trwała historia wiadomości.

## Na co zwrócić uwagę

- **Wybór CLI:** `CopilotRuntime` jest wspólny z demami SDK, ale ten przykład
  nadal używa ACP, nie klienta SDK. Środowisko i polecenie procesu wskazują tę
  samą instalację; allowlista `view,grep` i cleanup sesji/serwera nie zmieniają się.

- **Klient i agent:** backend FastAPI/Python jest klientem ACP; Copilot CLI jest
  agentem ACP. To nie jest GitHub Copilot SDK i nie jest to samodzielny model
  przez REST.
- **Transport i lifecycle:** `spawn_agent_process` wiąże klienta z procesem
  `copilot --acp --stdio`; stdout dziecka przenosi NDJSON, a zamknięcie kontekstu
  kończy jego lifecycle. `initialize` negocjuje wersję protokołu, `new_session`
  izoluje rozmowę, `prompt` rozpoczyna turę, a `close_session` sprząta sesję.
- **Uprawnienia:** `--available-tools=view,grep` ogranicza wszystkie sesje
  uruchomionego procesu. `request_permission` przyznaje tylko dostęp
  jednorazowy dla typów `read`/`search`; shell, edycja, MCP i pozostałe
  uprawnienia nie są dopuszczane.
- **Zdarzenia i prywatność:** `session_update` streamuje treść odpowiedzi i
  nazwy zdarzeń. Surowe argumenty oraz wyniki narzędzi nie trafiają do UI;
  frontend używa `textContent`, a nie `innerHTML`.
- **Ograniczenia prototypu:** sesje są przechowywane w pamięci procesu, prompt
  ma limit 1200 znaków, a limit aktywnych procesów to dwa. Localhost nie jest
  ochroną dla usługi wystawionej w sieci.
- **Wynik i cleanup:** oczekuj odpowiedzi zawierającej `ACP_OK`, zdarzenia
  `agent_message_chunk` i `turn_complete`, a po zamknięciu braku aktywnej sesji.
  Nie pozostawiaj serwera ani sesji uruchomionej po prezentacji.

## Test integracyjny

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/009-acp-web/test_main.py -v
```

Testy obejmują walidację promptu, blokadę nie-loopback bindu, stronę WWW,
komunikaty błędów i **rzeczywisty** cykl HTTP → ACP SDK → Copilot CLI z
odpowiedzią modelu i sprzątnięciem procesu. Nie ma mocków ani automatycznego
skipowania testu live. Wymagane są działający CLI, autoryzacja CLI/BYOK, sieć
i dostęp do Copilot.

## Wzorzec dla zdalnego „Agent HQ”

Zdalny układ to coś więcej niż wystawienie portu ACP:

```text
Użytkownik → HTTPS + SSO → API / broker sesji
                           ├─ kolejka zadań + audyt
                           └─ izolowany worker / kontener / worktree
                                  └─ lokalny Copilot CLI --acp --stdio
                                     ↑ prywatny klient ACP
```

1. Uwierzytelnij użytkownika w warstwie HTTPS/API (SSO/OIDC), autoryzuj dostęp
   do repozytorium i sprawdzaj uprawnienia przy każdym poleceniu.
2. Broker przechowuje wyłącznie metadane i mapuje użytkownika na sesje.
   Właściwy worker powinien być efemeryczny, ograniczony zasobami i osobny dla
   użytkownika/zadania; przypnij mu własny worktree i zakres repozytorium.
3. Uruchamiaj Copilot CLI jako proces potomny w workerze, używając ACP przez
   stdio. W pierwszej wersji nie publikuj TCP ACP. Jeśli osobny host musi
   komunikować się po TCP, użyj sieci prywatnej lub uwierzytelnionego proxy,
   TLS/mTLS, listy dozwolonych klientów i limitów połączeń; nigdy nie zakładaj,
   że ACP sam zapewnia uwierzytelnianie transportu.
4. Przechowuj poświadczenia poza obrazem i logami, w zarządzanym magazynie
   sekretów. Dostarczaj je workerowi tylko na czas życia zadania i używaj
   najmniejszych uprawnień. Nie przekazuj sekretów w promptach, query stringach
   ani w logach zdarzeń.
5. Ograniczaj równoległe procesy, czas promptu, CPU/pamięć, wielkość workspace
   i limity API. Przy zamykaniu sesji zamykaj klienta ACP, CLI i worktree;
   po awarii czyść osierocone workery.
6. Traktuj odpowiedzi i eventy jako dane użytkownika. Redaguj logi, weryfikuj
   output przed publikacją oraz dodaj retencję, audyt, CSRF/origin protection,
   monitoring i politykę zgód na narzędzia.
7. Ustal trwałość sesji oddzielnie od procesu: jeśli potrzebna jest możliwość
   wznowienia, przechowuj minimalne metadane w kontrolowanym magazynie, nie
   udostępniaj identyfikatorów jako sekretów i odtwórz sesję w tym samym
   autoryzowanym środowisku.

ACP standaryzuje cykl i wiadomości klient–agent. Nie zapewnia kolejki,
uwierzytelniania użytkowników, separacji tenantów, polityki narzędzi,
zarządzania workerami ani bezpiecznej trwałości — te elementy pozostają
odpowiedzialnością aplikacji „Agent HQ”.
