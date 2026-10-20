# Demo 008: wybór modelu w jednym runtime

To demo uruchamia to samo zadanie w osobnych sesjach z GPT-6.1 Sol,
GPT-6 Astra, Claude Opus 5.5 oraz wyborem `auto`. Każda sesja korzysta z tego
samego GitHub Copilot CLI runtime, SDK, katalogu roboczego, promptu i zestawu
narzędzi tylko do odczytu. Przy każdej odpowiedzi wypisywane są zarówno wybór
sesji, jak i model rzeczywiście zgłoszony przez SDK. Jest to szczególnie
istotne dla `auto`, które samo w sobie nie identyfikuje modelu obsługującego
wywołanie.

Przykład nawiązuje do [analizy modeli i harnessu GitHub Copilot][benchmark]:
w opisanym benchmarku GPT dawał korzystny stosunek kosztu do rozwiązywania
zadań, a Claude Opus osiągał najwyższą skuteczność przy wyższym koszcie. Wpis
porównuje też harness Copilot z harnessami dostawców przy zachowaniu tego
samego modelu i zadania. Demo nie odtwarza tych benchmarków ani nie obiecuje,
że taki sam kompromis wystąpi w dowolnym zadaniu; pokazuje wybór modelu i
rzeczywiste przebiegi w jednym harnessie.

[benchmark]: https://github.blog/ai-and-ml/github-copilot/evaluating-performance-and-efficiency-of-the-github-copilot-agentic-harness-across-models-and-tasks/

## Przebieg krok po kroku

0. Przygotuj [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\008-model-choice\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Oczekuj `Copilot CLI: <ścieżka>` przed listą modeli; resolver jawnie omija
   rozpoznany bootstrapper VS Code, nie zmieniając wybranych modeli.

Wymagane są Python SDK, Copilot CLI, aktywna subskrypcja Copilot, sieć,
uwierzytelnienie CLI oraz dostęp do skonfigurowanych modeli. Logowanie do
rozszerzenia VS Code nie uwierzytelnia runtime CLI. Z katalogu głównego:

```bash
.venv/bin/python demos/008-model-choice/main.py
```

1. Przygotuj Python SDK, Copilot CLI, aktywną subskrypcję, sieć i
   uwierzytelnienie CLI oraz dostęp do skonfigurowanych modeli. Logowanie
   do rozszerzenia VS Code nie uwierzytelnia runtime CLI.
2. Z katalogu głównego uruchom `.venv/bin/python demos/008-model-choice/main.py`.
   Klient SDK łączy runtime i pobiera przez `client.list_models()` listę ID
   dozwolonych dla konta i polityki organizacji.
3. Jeśli skonfigurowane ID nie są dostępne, program wypisze dostępne ID
   i zakończy się czytelnym błędem. Zmień wtedy `MODEL_CHOICES` w `main.py`
   na dostępne modele.
4. Dla każdego modelu aplikacja wypisuje listę blokowanych serwerów MCP,
   po czym tworzy osobną sesję przez `create_session(model=...)`.
   `disabled_mcp_servers` przekazuje do SDK dokładne nazwy; pasujące serwery
   nie startują i nie uwierzytelniają się w tej sesji. Nie zmienia to globalnej
   konfiguracji CLI ani sesji porównywanego następnego modelu.
5. Wszystkie sesje dostają ten sam prompt, repozytorium i tylko do odczytu
   allowlistę `grep`, `view`. Każde zdarzenie `assistant.usage` pokazuje model
   faktycznie obsługujący wywołanie i AIU z `copilot_usage.total_nano_aiu`.
   Suma z całego przebiegu — od pierwszego wywołania do finalnej odpowiedzi —
   pojawia się w jej nagłówku. Przy `auto` faktyczny model może być inny niż
   wybór sesji. Oczekuj też eventów pracy agenta oraz zamknięcia każdej sesji
   i klienta. Nie trzeba przekazywać sekretów ani argumentów wiersza poleceń.
6. Przy `session.usage_checkpoint` obserwuj dodatkową linię
   `[usage checkpoint] session total nano_aiu=...; AIU=...`. Pokazuje ona
   skumulowany stan rozliczeń sesji zgłoszony przez CLI, oddzielnie od sumy
   per-call w nagłówku odpowiedzi. Kolejne checkpointy nie są dodawane do
   siebie ani do sumy odpowiedzi. Po zakończeniu konteksty SDK nadal zamykają
   sesję i klienta.

## Na co zwrócić uwagę

- **Wspólny kod** — denylista MCP, jej komunikat i nazwy eventów pochodzą
  z `copilot_runtime.py`; ten sam zestaw nadal jest jawnie podawany każdej
  sesji. W demo zostaje porównanie modeli, bez kopii konfiguracji wspólnej.

- **Runtime** — `self.runtime.create_client()` przypina wspólną instalację CLI.
  Obie sesje nadal używają tego samego klienta, loginu i allowlisty; cleanup
  zamyka sesje i runtime. Brak wybranego modelu nadal jest jawnym błędem.

1. `client.list_models()` pokazuje wybór faktycznie udostępniony przez Copilot
   w danym środowisku, zamiast zakładać, że każde konto ma identyczną ofertę.
2. `create_session(model=...)` kieruje przebiegi przez ten sam agentowy
   runtime; aplikacja nie implementuje osobnego transportu dla każdego modelu.
   `disabled_mcp_servers` blokuje dokładne nazwy MCP w każdej sesji, przed
   uruchomieniem i uwierzytelnieniem tych serwerów.
3. Obie sesje dostają ten sam prompt, repozytorium i narzędzia `grep` oraz
   `view`. Brak narzędzi do zapisu i shell sprawia, że analiza nie zmienia
   checkoutu.
4. `session.start`, eventy narzędzi i `session.idle` pozwalają obserwować
   rzeczywisty cykl pracy Copilot CLI, a nie tylko porównać dwa tekstowe API.
5. W `[response]` porównaj `requested` z `actual model` oraz `AIU` z sumą
   per-call widoczną w liniach `[usage]`. AIU pochodzi z
   `copilot_usage.total_nano_aiu` (nano-AIU przeliczone na AIU), nie z tokenów
   ani szacunku kosztu. Gdy brakuje danych dla choć jednego wywołania, suma
   jawnie informuje, że runtime nie podał pełnych danych.
6. `SESSION_USAGE_CHECKPOINT` i `SessionUsageCheckpointData` opisują trwały,
   skumulowany snapshot sesji. Po wznowieniu sesji może obejmować wcześniejsze
   tury; nie jest kosztem wyłącznie ostatniej odpowiedzi. Handler wypisuje tylko
   surowe nano-AIU i przeliczone AIU, bez payloadów i sekretów. Nie interpretuje
   samego przeliczenia jednostek jako AIC ani kwoty w dolarach.

Prompt każe każdemu modelowi przeczytać ten sam snapshot issue #1048 i
zaproponować przypadki brzegowe do testów wpisów z zerową ilością i kosztem całkowitym. Zwróć uwagę na
to, które inwarianty modele wyciągają z tych samych kryteriów akceptacji i jak
uzasadniają testy. Nie traktuj jednej odpowiedzi jako wyniku benchmarku.

## Test integracyjny

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/008-model-choice/test_main.py -v
```

Test wysyła prompt w prawdziwych sesjach SDK przez runtime Copilot CLI.
Wymaga sieci, uwierzytelnienia CLI, subskrypcji Copilot i dostępu do modeli
skonfigurowanych w `MODEL_CHOICES`, w tym `auto`. Brak któregoś z wymagań kończy test błędem z
wyjaśnieniem zamiast cichego pominięcia. Test nie mockuje klienta, sesji,
modeli, poświadczeń ani sieci.
Sprawdza też obecność checkpointów dla każdej sesji, przeliczenie nano-AIU na
AIU oraz to, że suma per-call odpowiedzi nie zawiera ponownie checkpointów.
