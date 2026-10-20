# Demo 005: deterministyczna analiza i zespół SDLC

Demo łączy deterministyczne narzędzia do analizy Pythona z orkiestracją
agentów Copilot SDK. Główny agent używa `task`, a środowisko wykonawcze
przekazuje zadania agentom niestandardowym działającym w odizolowanych
kontekstach. Demo świadomie łączy dynamiczną delegację ze statyczną logiką:
**pierwszy prompt → Ruff, Pyright i static-reviewer; drugi prompt →
naprawa i review; kod Pythona → documentarian**. Analityk
uruchamia Ruff i Pyright za pomocą narzędzia SDK `python_static_analysis`,
a następnie główny agent przekazuje pełny raport JSON agentowi
`static-reviewer`. Recenzent nie może czytać ani edytować repozytorium:
przygotowuje ocenę wyłącznie na podstawie wyników analizy statycznej.
Dwa prompty trafiają do tej samej sesji SDK, więc etap naprawy zachowuje
kontekst analizy. Na końcu aplikacja tworzy osobną sesję z
`agent="documentarian"` i jawnie przekazuje jej podsumowanie naprawy.
Ta rola nie jest dostępna do delegowania w sesji orkiestratora.

Do omówienia kodu bez uruchamiania całego przykładu służy
[diagram na jeden slajd](flow.md): trzy fazy odpowiadające promptom,
z pogrupowanymi zadaniami i wynikami rzeczywistego przebiegu z logu.

## Przygotowanie

Potrzebne są: Python 3.11 lub nowszy, `github-copilot-sdk`, `pytest`, Ruff
i Pyright z `requirements.txt`, kompilator C, Node.js wymagany przez Pyright,
dostęp do sieci i modeli, aktywna subskrypcja GitHub Copilot oraz GitHub
Copilot CLI zalogowany na konto GitHub (zalogowanie w VS Code nie wystarcza).
Meson, Ninja oraz Flex i Bison są zależnościami środowiska Pythona.
Kontener deweloperski zawiera kompilator i Node.js 22.
Instaluj pakiety przez rejestr skonfigurowany w swoim środowisku; nie
zmieniaj jego adresu. W systemie Linux lub w kontenerze deweloperskim
wykonaj z katalogu głównego repozytorium:

```bash
.venv/bin/python -m pip install -r requirements.txt
export PATH="$PWD/.venv/bin:$PATH"
export COPILOT_CLI_PATH="$(command -v copilot)"
.venv/bin/python -m ruff --version
.venv/bin/python -m pyright --version
copilot -p "Reply with exactly: OK" --silent
# tylko demo 005: lokalne źródła, kompilacja parsera i instalacja w trybie edytowalnym
.venv/bin/python prepare_sdlc_team.py
git -C demos/005-sdlc-team/workspace status --short
```

Na Windows użyj **Developer PowerShell for Visual Studio** z narzędziami
kompilatora C/C++. Z katalogu głównego:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PATH = "$PWD\.venv\Scripts;$env:PATH"
$env:COPILOT_CLI_PATH = (Get-Command copilot).Source
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m ruff --version
.\.venv\Scripts\python.exe -m pyright --version
copilot -p "Reply with exactly: OK" --silent
.\demos\005-sdlc-team\prepare-beancount.ps1
git -C demos\005-sdlc-team\workspace status --short
.\.venv\Scripts\python.exe demos\005-sdlc-team\main.py
```

`prepare_sdlc_team.py` przygotowuje wyłącznie to demo: nie uruchamia SDK
ani nie pobiera źródeł z GitHuba. Oczekuj komunikatu `[ok]` (lub `[skip]`) oraz
`[setup] Checkout import verified; compiled parser loaded.` oraz czystego
stanu repozytorium Git. Instalacja zależności może wymagać dostępu do rejestru
pakietów.
Skrypt nie przywraca plików do poprzedniego stanu: nieprawidłowy HEAD lub
zmiany w śledzonych plikach powodują przerwanie przygotowania i wyświetlenie
wyjaśnienia. Instalacja w trybie edytowalnym wskazuje **katalog roboczy dema
005**, a nie `src-beancount` ani kopię innego dema. Przygotuj środowisko
ponownie po przełączeniu instalacji Beancount na inną kopię repozytorium.

W systemie Windows jeden skrypt
[prepare-beancount.ps1](prepare-beancount.ps1) odtwarza potrzebne źródła
z lokalnego pakietu, buduje parser C i instaluje kopię repozytorium w trybie
edytowalnym za pomocą interpretera z repozytorium. Nie pobiera najnowszej
wersji Beancount z PyPI ani nie zmienia instalacji używanych przez pozostałe
dema. Ten przykład wymaga dokładnie
`demo-base-1048` / `9747213802acb733ce53acc6e963f5961f47d6cd`.
Skrypt można uruchomić z dowolnego katalogu. Nie uruchamia Copilota, nie
zatwierdza ani nie wysyła zmian, nie przywraca poprzedniego stanu repozytorium
i nie zmienia skonfigurowanego rejestru pakietów. Wymagane narzędzia
i kompilator trzeba wcześniej przygotować zgodnie z poleceniami
powyżej. Błąd przygotowania przerywa skrypt zamiast wypisywać gotowość.

Kontrolne wywołanie `copilot -p` potwierdza, że lokalny interfejs wiersza
poleceń (CLI) jest zalogowany. SDK korzysta z tego samego konta przez
`CopilotClient(use_logged_in_user=True)`. Demo korzysta z kopii repozytorium
`tkopacz/beancount` utworzonej specjalnie na potrzeby tego pokazu:
`demos/005-sdlc-team/workspace` (zobacz `dema.md`). Odtwarza ją lokalny plik
[beancount-base.bundle](beancount-base.bundle). Tag `demo-base-1048` wskazuje
wersję bazową, w której błąd #1048 (`0 HOOL {{20.00 USD}}` →
`decimal.DivisionByZero`) nadal występuje. Tester dodaje test, który początkowo
nie przechodzi, a programista naprawia błąd. Demo sprawdza, czy HEAD wskazuje
ten commit (`9747213`); w przeciwnym razie kończy się błędem konfiguracji.
Agenci mogą edytować tylko pliki `beancount/parser/booking_full.py`,
`beancount/parser/booking_full_test.py` i `CHANGES`. Przed uruchomieniem SDK
aplikacja wymaga czystego drzewa roboczego Git, bez zmian w śledzonych
i nieśledzonych plikach (ignorowane pliki kompilacji nie przeszkadzają).
Przed pokazem zachowaj samodzielnie istniejące poprawki: aplikacja ich nie
usuwa. Domyślnie `CONFIGURATION.keep_changes=True`: po zatrzymaniu SDK
poprawki pozostają w katalogu roboczym do obejrzenia. Ustawienie
`keep_changes=False` automatycznie przywraca te trzy pliki do przypiętej
wersji bazowej i sprawdza stan repozytorium. Nie
zatwierdza ani nie wysyła zmian. Nie przywraca stanu całego repozytorium ani
nie usuwa innych plików. Między kolejnymi przebiegami nie trzeba ponownie
budować parsera.

### Ręczny reset po przerwanym pokazie

Gdy aplikacja zgłasza `requires a clean workspace before starting`,
użyj skryptu [reset-workspace.ps1](reset-workspace.ps1) w PowerShell 7
(`pwsh`). **Skrypt trwale odrzuca zmiany w śledzonych plikach (także
przygotowane do zatwierdzenia) oraz usuwa nieignorowane pliki i katalogi
nieśledzone — wyłącznie w katalogu roboczym dema 005.** Najpierw skopiuj
potrzebne poprawki poza ten katalog albo zachowaj je w inny sposób. Skrypt
nie tworzy kopii zapasowej ani schowka Git.

1. Zakończ demo i poczekaj, aż środowisko wykonawcze Copilot CLI się zatrzyma.
   Jeśli dziennik informuje, że zatrzymanie nie zostało potwierdzone, zatrzymaj
   to środowisko przed dalszymi działaniami: jego edytory nie mogą działać
   równolegle ze skryptem przywracającym pliki.
2. Z katalogu repozytorium uruchom:

   ```powershell
   pwsh -NoProfile -File .\demos\005-sdlc-team\reset-workspace.ps1
   ```

3. Sprawdź wyświetloną ścieżkę katalogu roboczego, stan repozytorium Git
   i listę plików przeznaczonych do usunięcia.
   Wpisz dokładnie `RESET`, aby potwierdzić; Enter lub inna odpowiedź anuluje
   bez zmian. Jeśli katalog roboczy jest czysty, skrypt kończy działanie bez
   pytania.
4. Oczekuj `[reset] Base restored; workspace clean. No commit or push.`
   Skrypt wymaga HEAD `9747213802acb733ce53acc6e963f5961f47d6cd`.
   Nie przełącza wersji, nie działa na nadrzędnym repozytorium ani na
   dowiązanym katalogu roboczym. Zachowuje ignorowane pliki kompilacji i logi
   dema. Nie usuwa zagnieżdżonych repozytoriów Git: jeśli po zakończeniu
   pozostaną zmiany, zgłasza błąd zamiast informować o gotowości. Pliki
   ignorowane przed przywróceniem pozostają na miejscu także wtedy, gdy
   przywrócony plik `.gitignore` przestanie je ignorować. W takiej sytuacji
   sprawdź pozostałe zmiany samodzielnie; skrypt ich nie usuwa.
5. Uruchom `.\.venv\Scripts\python.exe .\demos\005-sdlc-team\main.py`.
   Skrypt nie uruchamia CLI ani SDK, nie wymaga zalogowania i nie wysyła
   poleceń do modelu. Dopiero demo tworzy klienta i sesję SDK, korzystając
   z konta zalogowanego w CLI. Po pokazie domyślnie zachowywane są zmiany;
   automatyczne przywracanie trzech plików wymaga `keep_changes=False`.

Testy skryptu korzystają z rzeczywistych, tymczasowych kopii repozytorium
odtworzonych z lokalnego pakietu. Nie łączą się z Copilotem ani z siecią
i nie usuwają plików z bieżącego katalogu roboczego:

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\test_reset_sdlc_team.py -q
```

### Dołączone źródła i licencja

- [main.py](main.py) zawiera aplikację SDK, wszystkie role i polecenia,
  obsługę narzędzia Ruff/Pyright, ograniczony zakres różnic, funkcję
  zwrotną uprawnień i obsługę cyklu życia.
- [test_main.py](test_main.py) zawiera testy aplikacji oraz testy SDK
  wykonywane na żywo.
- [src-beancount](../../src-beancount/) zawiera wszystkie **340 plików**
  źródłowego drzewa bazowego, w tym parser C, gramatykę, testy, konfigurację
  Meson, przykłady i skrypty `bin`. Pochodzenie zapisuje
  [SOURCE.json](../../src-beancount/SOURCE.json). To czytelna migawka, bez `.git`.
- [beancount-base.bundle](beancount-base.bundle) zawiera oryginalny commit
  `9747213802acb733ce53acc6e963f5961f47d6cd` i całe jego drzewo. Przodkowie
  nie są dołączani: [prepare_workspaces.py](../../prepare_workspaces.py)
  odtwarza płytką kopię repozytorium (z ograniczoną historią) o wskazanym
  HEAD i z adresami `origin`/`upstream`. Nie zawiera ona pełnej historii projektu.
- [prepare_sdlc_team.py](../../prepare_sdlc_team.py) buduje parser i weryfikuje
  rzeczywisty import z tej kopii repozytorium.
- Beancount pozostaje na licencji **GPL-2.0-only**; zachowano oryginalne
  nagłówki, [COPYING](../../src-beancount/COPYING) i
  [CREDITS](../../src-beancount/CREDITS). Zależności SDK, CLI, Ruff, Pyright
  i narzędzia budowy instaluje się z ich dystrybucji; lokalny pakiet źródłowy nie zawiera ich
  kodu ani binariów.

## Przebieg krok po kroku

0. Przygotuj [wspólny start CLI i F5](../../README.md#wspolny-start-copilot-cli).
   Na Windows uruchom `.venv\Scripts\python.exe demos\005-sdlc-team\main.py`
   albo otwórz ten `main.py` i naciśnij F5 (**Python: Current File (.venv)**).
   Po walidacji toolchainu oczekuj `Copilot CLI: <ścieżka>`; rozpoznany
   bootstrapper VS Code jest omijany na rzecz natywnego CLI z PATH.

1. Zainstaluj wymagane składniki i sprawdź, czy CLI jest zalogowany,
   wykonując polecenia z sekcji **Przygotowanie**. W systemie Windows
   uruchom
   `.\demos\005-sdlc-team\prepare-beancount.ps1` w Developer PowerShell.
   `prepare_sdlc_team.py` odtwarza bazową kopię repozytorium i kompiluje
   parser, ale nie dodaje testu regresyjnego ani poprawki zgłoszenia #1048:
   robią to agenci podczas pokazu. Sprawdź, czy repozytorium Git jest czyste
   i czy pojawił się komunikat potwierdzający poprawny import.
   Jeśli poprzedni pokaz pozostawił zmiany, wykonaj kroki sekcji
   **Ręczny reset po przerwanym pokazie** przed startem SDK.
2. Z katalogu repozytorium uruchom:

   ```bash
   .venv/bin/python demos/005-sdlc-team/main.py
   ```

3. Przed uruchomieniem Copilot oczekuj `[setup] Toolchain verified: pytest ...,
   ruff ..., pyright ...`. Zarówno przygotowanie, jak i aplikacja uruchamiają
   rzeczywiste `python -m pytest --version`, `python -m ruff --version`
   i `python -m pyright --version` tym samym interpreterem w katalogu
   `workspace`. Brak modułu, awaria uruchomienia albo brak raportu wersji
   zatrzymuje demo przed otwarciem sesji SDK (kod 2), z listą błędów,
   ścieżką interpretera i poleceniem instalacji `requirements.txt`.
   Samo wykrycie pakietu przez import nie wystarcza. Na Windows napraw środowisko
   poleceniem `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
   przez skonfigurowany rejestr, ponów przygotowanie i start z kroku 2.
   Kontrola nie instaluje nic automatycznie ani nie wysyła promptu do Copilot.
   Dopiero po jej powodzeniu `CopilotClient(use_logged_in_user=True)` łączy aplikację ze środowiskiem
   wykonawczym Copilot CLI, a `create_session()` rejestruje agentów
   niestandardowych, narzędzie `git_diff`
   i narzędzie `python_static_analysis`. Każde wywołanie sesji wypisuje
   `MCP server names disabled for this session:` i ustawia
   `disabled_mcp_servers`; SDK blokuje dokładne dopasowania przed startem lub
   uwierzytelnieniem MCP tylko w danej sesji, bez zmiany ustawień CLI.
   Główny agent nie dostaje narzędzi
   edycji, powłoki ani skanera. `env` przekazuje środowisku wykonawczemu
   zmienne z katalogiem bieżącego interpretera na początku `PATH`, więc
   polecenie `python` testera korzysta z tego samego `.venv` i instalacji
   w trybie edytowalnym. Jeszcze przed sprawdzeniem kopii repozytorium
   pojawia się `[log] Activity log: ...`. Otwórz wskazany plik w edytorze
   obok terminala. Każde uruchomienie tworzy osobny plik
   `logs/sdlc-<czas-UTC>-<id>.log`; wpisy mają czas UTC, numer kolejny
   i wyróżnioną kategorię. Są zapisywane na bieżąco, a nie dopiero po
   zakończeniu sesji. `CONFIGURATION.log_directory` pozwala zmienić katalog
   bez używania argumentów CLI; nie może on wskazywać kopii repozytorium ani
   jej podkatalogu.
   Obok szczegółowego logu powstaje `logs/summary<czas-UTC>-<id>.log`,
   ze wspólnym znacznikiem czasu i identyfikatorem. Terminal wypisuje
   `[log] Summary log: ...`; otwórz ten plik jako widok przebiegu pokazu.
   Zawiera etapy cyklu SDK, przekazania `task`, start/koniec agentów,
   skróty promptów i publicznych odpowiedzi oraz wejścia/wyjścia narzędzi
   własnych. Wartości są skracane do 400 znaków z jawnym oznaczeniem;
   pełne dane pozostają w logu szczegółowym. Oba logi maskują sekrety
   i są zapisywane na bieżąco. Summary pomija strumień zdarzeń konsolowych
   i surowe wyniki procesów Ruff/Pyright.
4. Agent nadrzędny zleca zadanie agentowi `analyst` za pomocą wbudowanego narzędzia
   `task`; środowisko wykonawcze uruchamia analityka z jego własną listą
   narzędzi. Analityk wywołuje
   `python_static_analysis`. Obsługa tego narzędzia uruchamia ustalone polecenia
   `.venv/bin/python -m ruff check --output-format=json beancount` i
   `.venv/bin/python -m pyright --outputjson beancount` w kopii repozytorium,
   wyłącznie dla pakietu źródłowego. Kod wyjścia zero oznacza brak wyników,
   a kod jeden — zakończoną analizę, która wykryła problemy.
5. Obsługa narzędzia jest asynchroniczna: podczas działania lokalnych
   analizatorów SDK nadal obsługuje zdarzenia, uprawnienia i anulowanie.
   Każdy analizator ma limit 120 sekund; przekroczenie limitu czasu lub
   anulowanie
   zatrzymuje jego proces (w systemie POSIX także proces potomny Node.js
   uruchomiony przez Pyright). Narzędzie porządkuje białe znaki w komunikatach
   i usuwa bezwzględne ścieżki, sortuje wyniki według pliku, wiersza i reguły
   oraz zapisuje je w JSON-ie bez zbędnych
   odstępów. Raport zawiera liczby diagnostyk, maksymalnie 80 pozycji na
   analizator i nie więcej niż **6000 bajtów UTF-8 dla całego JSON-u**.
   Po przekroczeniu limitu obsługa narzędzia usuwa nadmiarowe wyniki z końca
   listy i zwiększa wartość `omitted_findings`; pole `filters.json_bytes_limit`
   opisuje przyjęty limit. Dzięki temu raport pozostaje w treści zadania,
   zamiast trafiać do pliku, którego recenzent bez narzędzi nie może otworzyć.
   Brak pliku wykonywalnego, przekroczenie limitu czasu lub niepoprawne dane
   wyjściowe oznaczają błąd, a nie „brak problemów”.
   Kod wyjścia inny niż 0 lub 1 jest sprawdzany **przed** odczytaniem JSON-u:
   raport błędu zawiera `exit_code` i komunikat z `stderr`, np. błędną
   konfigurację Ruff, zamiast mylącego `invalid JSON at character 0`.
   Przy kodzie 0 lub 1 brak danych wyjściowych oznacza `returned no JSON report`;
   uszkodzony JSON nadal jest odrzucany z podaniem pozycji i opisu błędu.
   W takim przypadku SDK otrzymuje `ToolResult(result_type="failure")`,
   a recenzent musi zaznaczyć, że analiza jest niekompletna.
6. Główny agent przekazuje pełny JSON z wynikami analityka agentowi
   `static-reviewer` za pomocą kolejnego zadania `task`. Recenzent nie ma
   narzędzi: ma ocenić wyłącznie raport, odróżnić zaobserwowane problemy od
   ich interpretacji i zaznaczyć, jeśli raport jest niekompletny. W terminalu
   zobaczysz nazwy analizatorów, liczbę ustaleń i zdarzenia delegowania,
   a nie surowe dane ani treść plików.
7. Po pierwszym `session.idle` Python wysyła `DEFAULT_REPAIR_PROMPT`
   do **tej samej sesji**; terminal pokazuje
   `[stage] orchestrator: prompt 2`. Pierwszy prompt (`DEFAULT_PROMPT`)
   kończy się na recenzji statycznej. Dopiero drugi zleca pozostałym
   specjalistom analizę problemu, projekt, testy, implementację i niezależną
   recenzję, bez ponownego uruchamiania skanerów. Kolejność zadań w tych
   etapach wybiera model przez `task`; Python ustala granicę między promptami.
   Zdarzenia `subagent.selected`,
   `subagent.started`, `subagent.completed` i `subagent.failed` pokazują cykl
   delegowania. Role edytujące pliki używają narzędzia środowiska wykonawczego
   `apply_patch` lub `edit`
   zależnie od palety narzędzi modelu;
   funkcja zwrotna SDK zatwierdza tylko plik przypisany danej roli. Tester ma
   najpierw dodać `TestZeroUnitsWithTotalCost` i
   wykazać, że test początkowo nie przechodzi (`DivisionByZero`), a po zmianie
   programisty uruchomić go ponownie i uzyskać wynik pomyślny. W wersji bazowej
   tej klasy jeszcze nie ma, więc samo uruchomienie testu przed jej dodaniem
   niczego nie dowodzi (pytest zwraca kod 5, gdy nie znajdzie wybranych testów).
   Nowe metody są zgodne ze stylem pytest i używają rzeczywistej funkcji
   `loader.load_string` z otwartymi kontami. Istotny jest zapis
   `{{20.00 USD}}`:
   `{# koszt}` nie odtwarza tego samego przypadku.
   Po pomyślnym teście regresyjnym tester uruchamia także dokładnie
   `python -m pytest beancount/parser/booking_full_test.py -q`. Cały moduł
   sprawdza m.in. istniejące zerowe wpisy FIFO/LIFO bez jawnego kosztu
   całkowitego; nie wolno odrzucać wszystkich zerowych wpisów z dowolnym
   kosztem. Niepowodzenia wracają do programisty, zanim zespół uzna poprawkę
   za gotową.
8. Po zakończeniu drugiej tury i zamknięciu sesji orkiestratora zobaczysz
   `[stage] Selecting SDK agent: documentarian`. To bezwarunkowy krok
   normalnego przebiegu zapisany w `execute_team`, nie decyzja modelu,
   `task` ani fallback. `ask(..., agent="documentarian")` tworzy nową sesję
   SDK. `DOCUMENTATION_PROMPT` przekazuje jej końcowe podsumowanie zespołu;
   dokumentalista czyta aktualną poprawkę i testy, a następnie edytuje tylko
   `CHANGES`. Nowa sesja nie dziedziczy historii poprzedniej: podsumowanie
   jest przekazane jawnie w prompcie. Funkcja uprawnień nadal sprawdza rolę
   i ścieżkę. Oczekuj `subagent.selected`, edycji `CHANGES`, końcowej
   odpowiedzi i zamknięcia tej sesji. Błąd sesji lub zdarzenie
   `subagent.failed` przerywa przebieg, zamiast uruchamiać kolejne etapy.
9. `send_and_wait()` czeka na `session.idle`. Długi etap `model.call_start`
   nie jest sam w sobie dowodem zawieszenia programu: co 15 sekund zobaczysz
   `[progress] Waiting for session.idle` z czasem przebiegu, ostatnim
   zdarzeniem i czasem, który upłynął od tego zdarzenia, bez treści poleceń
   ani odpowiedzi.
   `CONFIGURATION.timeout_seconds` ogranicza każde wysłanie i oczekiwanie
   do 900 sekund, a `progress_interval_seconds` ustawia odstęp komunikatów.
   Możesz przerwać działanie, naciskając Ctrl+C. Przekroczenie limitu czasu
   i Ctrl+C powodują jawne wywołanie przez SDK `session.abort()`, ponieważ
   samo przekroczenie limitu w `send_and_wait()` nie zatrzymuje środowiska
   wykonawczego. Anulowanie kończy proces kodem 130 i komunikatem
   `Cancelled.`; po przekroczeniu limitu czasu aplikacja kończy się kodem 1
   i wyświetla komunikat o ostatnim zdarzeniu.
10. SDK odłącza sesję i zatrzymuje klienta, przeznaczając na każdą z tych
   czynności najwyżej 10 sekund. Jeśli CLI zakończył już działanie po
   naciśnięciu Ctrl+C, błędy RPC są zgłaszane jako `[cleanup]` i nie
   zastępują pierwotnej przyczyny przerwania. Jeśli zatrzymanie klienta się
   nie powiedzie, SDK wywołuje `force_stop()` wyłącznie dla własnego
   środowiska wykonawczego. Po poprawnym zakończeniu zobaczysz `[lifecycle] Session closed`,
   `[lifecycle] Copilot client closed` i końcową odpowiedź.
11. Po wyświetleniu odpowiedzi i zatrzymaniu środowiska wykonawczego domyślne
    `keep_changes=True` pozostawia poprawki (także częściowe po błędzie lub
    anulowaniu). Oczekuj `[rollback] Disabled: workspace changes kept for inspection`.
    Obejrzyj je poleceniem `git -C demos/005-sdlc-team/workspace diff`.
    Zachowanie zmian nie oznacza ich zatwierdzenia ani wysłania.
    Przed kolejnym startem zachowaj potrzebne poprawki i wykonaj opisany
    wyżej ręczny reset: wymóg czystego drzewa pozostaje bez zmian.
    Przy `keep_changes=False` aplikacja przywraca trzy dozwolone pliki
    do wersji bazowej, także po błędzie,
    przekroczeniu limitu czasu lub naciśnięciu Ctrl+C.
    Oczekuj `[rollback] Base restored; workspace clean. No commit or push.`
    i pustego `git -C demos/005-sdlc-team/workspace status --short`.
    Na końcu sprawdź `[usage] AIC=...; status=...` w terminalu
    i `[USAGE] run total` w obu logach. To suma rozliczeń zgłoszonych
    przez SDK dla tego przebiegu, wraz z agentami i ewentualną sesją fallback.
    Przy `partial` odczytaj liczbę wywołań bez danych; `unavailable`
    oznacza brak danych, a nie darmowy przebieg.
    W trybie `keep_changes=False` uruchom demo ponownie: test regresyjny i poprawka nie pozostają w kopii
    repozytorium, więc pokaz zaczyna się od pierwotnego błędu. Jeśli nie udało
    się potwierdzić zatrzymania środowiska wykonawczego, aplikacja nie
    przywraca plików: komunikat `[rollback] Not attempted` oznacza, że trzeba
    najpierw zatrzymać to środowisko. `[rollback] Failed` oznacza błąd Git
    lub pozostałe zmiany; sprawdź je ręcznie. Program nie usuwa dodatkowych
    plików, aby wymusić czysty stan repozytorium.
12. W dzienniku znajdź `[ARTIFACT] diff before rollback`: zawiera rzeczywiste
    zmiany trzech dozwolonych plików, zapisane **przed** ich przywróceniem.
    Porównaj je z poleceniami edycji, wynikami testów i recenzją. Dziennik
    pozostaje po przywróceniu plików, także po błędzie, przekroczeniu limitu
    czasu i anulowaniu. `[RUN] completed` oznacza zakończenie aplikacji,
    a nie dowód poprawności naprawy; `subagent_failed` informuje o awarii
    agenta pomocniczego.
    `[RUN] failed` lub `[RUN] interrupted` podaje przyczynę przerwania.
    Przy nagłym zakończeniu procesu pozostaną już zapisane wpisy, ale może
    zabraknąć końcowego diffu i informacji o sprzątaniu.

### Odtwarzanie przebiegu z logu

Tekstowy dziennik można wyświetlić w edytorze. W systemie Windows możesz też
śledzić najnowszy przebieg w drugim oknie PowerShella, otwartym w katalogu
repozytorium:

```powershell
$log = Get-ChildItem .\demos\005-sdlc-team\logs\sdlc-*.log |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content -LiteralPath $log.FullName -Encoding utf8 -Tail 80 -Wait
```

Ctrl+C w **drugim terminalu** kończy tylko wyświetlanie dziennika, a nie sesję
SDK. W systemie Linux lub w kontenerze deweloperskim otwórz plik wskazany
przez `[log]` w edytorze albo użyj polecenia `tail -f` z pełną ścieżką do pliku.

- **`[AGENT]`**: rzeczywiste zdarzenia `subagent.selected/started/completed/failed`,
  nazwa roli, identyfikator agenta i delegacji; brak zdarzenia startu nie
  jest zastępowany wymyślonym etapem.
- **`[HANDOFF]`**: polecenie użytkownika, argumenty `task` i odczyty wyników przez
  `read_agent`, a następnie ich odpowiedzi z odbiorcą. Zadanie zawiera polecenie
  oraz kontekst faktycznie przekazany specjaliście przez orkiestratora.
  Łącz `tool_call_id`, `parent_tool_call_id`, `agent_id` i rolę; sąsiedztwo
  wpisów nie dowodzi zależności, bo zadania mogą działać równolegle.
  `returned` oznacza dostarczenie wyniku wywołującemu, **a nie jego akceptację**.
  Aprobaty lub kolejnego kroku szukaj w następnej publicznej wypowiedzi
  albo delegacji; program nie dopisuje intencji agenta.
- **`[AGENT OUTPUT]`**: widoczne wypowiedzi agentów i końcowa odpowiedź.
  Nie zapisujemy wewnętrznego rozumowania ani zakodowanego stanu modelu.
- **`[CUSTOM TOOL]`**: własne funkcje obsługujące `python_static_analysis`
  i `git_diff`,
  oddzielnie od **`[RUNTIME TOOL]`** (np. odczyt, edycja, powłoka).
  Ruff i Pyright mają osobne wpisy rozpoczęcia, pełnych danych `stdout`/
  `stderr`, kodu wyjścia i raportu. Pełne dane wyjściowe analizatora
  pozostają w pliku;
  przekazywany modelowi JSON nadal ma dotychczasowy limit 6000 bajtów.
  `[TOOL RESULT]` pokazuje wynik zwrócony przez środowisko wykonawcze,
  także wynik testów. Jeśli zwraca ono tylko odwołanie do wyniku zapisanego
  osobno, dziennik zachowuje to odwołanie i nie odczytuje samodzielnie
  dodatkowych plików.
- **`[PERMISSION]`**: decyzja funkcji zwrotnej SDK dla danego wywołania.
  To zgoda na operację, a nie akceptacja merytoryczna wygenerowanego kodu.
- **`[ARTIFACT]`**, **`[CONSOLE]`**, **`[ERROR]`**, **`[RUN]`**: zestaw zmian
  przed przywróceniem plików, etapy cyklu życia i postęp, błędy oraz wynik.

Pliki `*.log` są ignorowane przez Git i nie są uwzględniane przy przywracaniu
plików. Nie zapisujemy środowiska ani surowych danych SDK. Wartości znanych
zmiennych środowiskowych, których nazwy zawierają określenia `token`,
`secret`, `password` lub `API key`, a także rozpoznawalne tokeny GitHub,
są zastępowane oznaczeniem. Nie jest to uniwersalny skaner sekretów:
dziennik zawiera treść zadań, odpowiedzi, argumentów narzędzi i kod
demonstracyjnego repozytorium. Przed pokazaniem lub udostępnieniem przejrzyj
go; nie umieszczaj sekretów w poleceniach ani plikach dema. Po pokazie
świadomie usuń stare dzienniki — aplikacja ich nie nadpisuje ani nie usuwa
automatycznie. Błąd otwarcia lub zapisu dziennika jest błędem aplikacji,
a nie powodem do cichego wyłączenia rejestrowania.

Analityk ma narzędzia tylko do odczytu oraz skaner, `static-reviewer` nie ma
żadnych narzędzi, architekt ma wyłącznie dostęp do odczytu, a zwykły recenzent
ma dodatkowo ograniczone narzędzie SDK `git_diff`. Programista i dokumentalista
mogą edytować wyłącznie przypisane im pliki. Tester może też
uruchomić jedną z dwóch dokładnych komend:
`python -m pytest beancount/parser/booking_full_test.py -k TestZeroUnitsWithTotalCost -q`
albo `python -m pytest beancount/parser/booking_full_test.py -q`.
Tester dostaje natywne narzędzie powłoki środowiska wykonawczego: `bash`
w systemie POSIX albo `powershell` w Windows. Ponieważ jest to narzędzie
ogólnego przeznaczenia, funkcja zwrotna uprawnień SDK łączy identyfikator
wywołania z rolą agenta i zatwierdza wyłącznie przypisaną edycję albo jedno
z tych poleceń testowych uruchomione w katalogu kopii repozytorium. Jawna
zmiana katalogu na lokalizację poza tą kopią oraz inne operacje są odrzucane.
Uruchamiaj demo wyłącznie w zaufanej kopii repozytorium: testy mogą wykonać
znajdujący się w niej kod.

Główny agent nie ma narzędzi edycji ani powłoki, a `custom_agents` przypisuje
specjalistom ich własne zestawy narzędzi. `send_and_wait()` nie realizuje
pętli modelu: czeka, aż środowisko wykonawcze wykona zlecone zadania i prześle
zdarzenie `session.idle`. Zwykły przebieg **nie uruchamia trybu awaryjnego**.
Aby pokazać kontrolowany wariant bez automatycznego delegowania, ustaw
`fallback_agent="analyst"` w `CONFIGURATION` w pliku `main.py`. Jeśli pierwsza
sesja nie zleci żadnego zadania, demo wyświetli `[fallback]` i utworzy
**osobną sesję** z `agent="analyst"`, której zakres ogranicza się do odczytu.
To jawny wybór agenta przez SDK, a nie ponawianie całego procesu.
Niezależnie od tego opcjonalnego fallbacku normalny przebieg zawsze wybiera
dokumentalistę w kodzie po drugim prompcie. `repair_prompt=None` uruchamia
wyłącznie pierwszy prompt (oraz ewentualny fallback), bez naprawy i dokumentacji;
testy izolowanych interakcji SDK używają tego wariantu. Pusty tekst drugiego
promptu jest błędem konfiguracji.

## Na co zwrócić uwagę

- **Wspólny kod** — denylista MCP, jej komunikat i podstawowe nazwy eventów
  pochodzą z `copilot_runtime.py`. Korelacja agentów, metryki, stan timeoutu
  i log aktywności pozostają lokalne, bo są treścią tego przykładu.

- **Runtime** — `CopilotRuntime.create_client()` przypina wspólną instalację,
  zachowuje środowisko toolchainu i login CLI. Delegacja, role, polityki,
  eventy oraz istniejąca ścieżka `start()` / `stop()` nie zmieniają się.

- **Zachowanie zmian:** `DemoConfiguration.keep_changes` ma domyślnie
  wartość `True`. Obserwuj `[setup] Keep workspace changes: True` oraz
  `[rollback] Disabled`, a potem rzeczywisty diff. SDK nadal zamyka sesje
  i zatrzymuje własny runtime; wyłączone jest wyłącznie przywracanie plików.
  Przy `False` oczekuj `[rollback] Base restored` i czystego katalogu.
- **Hybrydowa orkiestracja:** w [main.py](main.py) porównaj
  `DEFAULT_PROMPT`, `DEFAULT_REPAIR_PROMPT` i końcowe
  `ask(..., agent="documentarian")` w `execute_team`. Dwa wpisy
  `[HANDOFF] user prompt sent` mają ten sam `session_id`; dokumentalista
  dostaje nowy. Przed drugim promptem powinny zakończyć się Ruff/Pyright
  i `static-reviewer`, a przed dokumentalistą — testy, poprawka i review.
  `custom_agents` sesji orkiestratora nie zawiera dokumentalisty.
  `[ARTIFACT] diff before rollback` powinien obejmować także `CHANGES`.
- **Ręczne przywracanie:** [reset-workspace.ps1](reset-workspace.ps1) pokazuje
  zakres zmian przed potwierdzeniem `RESET`. Usuwa także zmiany przygotowane
  do zatwierdzenia i pliki nieśledzone, ale zachowuje pliki ignorowane oraz
  dzienniki. Środowisko wykonawcze Copilot musi być zatrzymane. Gotowość
  potwierdza wyłącznie komunikat `Base restored; workspace clean`; samo
  przywrócenie nie tworzy sesji SDK ani nie zmienia stanu zalogowania CLI.
- **Pełna oś czasu:** w `ActivityLog` i `record_event` sprawdź wyróżnione
  kategorie, czas UTC oraz identyfikatory korelacji. W trakcie pokazu przejdź
  od `task requested`, przez start specjalisty i jego narzędzia, do
  `task returned` i następnego zadania. Nie myl dostarczenia wyniku ze zgodą
  recenzenta; obserwuj jego rzeczywistą wypowiedź.
- **Wyniki po pokazie:** `[ARTIFACT] diff before rollback` pozostaje
  w dzienniku w obu trybach (nazwa wpisu jest zachowana także bez rollbacku).
  Kopia repozytorium jest czysta tylko przy `keep_changes=False`. Sprawdź wyniki pytest
  i `git_diff`, a nie tylko opis końcowy. Wpisy trzech równoległych agentów
  rozróżniaj po ID, a nie po kolejności ich pojawienia się.
- **Deterministyczne analizatory:** narzędzie uruchamia przypięte wersje Ruff
  i Pyright dla `beancount/`; raport JSON zawiera także wykryte wersje
  narzędzi. Wersje wraz z regułami konfiguracji projektu determinują diagnostyki
  dla tej samej kopii repozytorium.
- **Gotowość narzędzi:** `verify_demo_tools` musi wypisać wersje pytest,
  Ruff i Pyright przed `[lifecycle] Copilot CLI runtime connected`.
- **Blokada MCP:** każda sesja SDK przekazuje tę samą listę nazw przez
  `disabled_mcp_servers`. To ograniczenie sesji, odrębne od allowlist
  `custom_agents` i niezależne od globalnej konfiguracji Copilot CLI.
  `No module named ...` nie jest wynikiem analizy. Przy błędzie kontroli
  nie powstaje sesja SDK, nie ma delegacji ani rollbacku, a dziennik startu
  zachowuje przyczynę i polecenie naprawy.
- **Skrót przebiegu:** w `summary<czas-UTC>-<id>.log` obserwuj kolejno
  `[RUN]`, `[SESSION]`, `[HANDOFF]`, `[AGENT]`, `[CUSTOM TOOL]`
  i `[AGENT OUTPUT]`. Identyfikatory agentów i wywołań łączą wejścia
  z wyjściami; numery wpisów odpowiadają szczegółowemu logowi, więc mogą
  mieć przerwy. Zakończenie sesji, zatrzymanie klienta i rollback też
  pozostają widoczne. Błąd zapisu któregokolwiek logu jest błędem przebiegu.
- **AIC całego przebiegu:** `RunUsage` zbiera zdarzenia SDK `assistant.usage`
  dla orkiestratora i agentów, również w dodatkowej sesji fallback.
  Sumuje wyłącznie `copilot_usage.total_nano_aiu` dla poszczególnych żądań:
  **AIC = suma nano-AIU / 1 000 000 000**. Nie dodaje ponownie `cost`,
  tokenów ani stanów limitów sesji; powtórzony identyfikator zdarzenia
  nie jest liczony drugi raz. Po zakończeniu lub przerwaniu, już po sprzątaniu,
  sprawdź `[USAGE] run total` w obu logach oraz `[usage] AIC=...` w terminalu.
  `reported` oznacza dane dla wszystkich zaobserwowanych zdarzeń usage;
  `partial` oznacza sumę znanych kosztów z brakami, a `unavailable` i `aic=null`
  brak danych rozliczeniowych (nie zero). Pola `reported_calls`,
  `calls_without_billing` i `usage_events` pokazują pokrycie.
  Przy przerwaniu runtime może nie wysłać ostatniego zdarzenia; to licznik
  danych otrzymanych przez SDK, nie faktura ani zużycie całego konta GitHub.
  Połączenie z modelem, subskrypcja i login CLI są potrzebne do testów live;
  brak danych AIC nie jest zastępowany estymacją z liczby tokenów.
- **Źródła i interpreter:** lokalny pakiet zapewnia pełne drzewo bazowe,
  ale nie gotową naprawę. `prepare_sdlc_team.py` sprawdza import i parser C.
  `env` klienta SDK zapewnia, że powłoka testera używa właściwego interpretera
  `python`. Nie instaluj w międzyczasie
  Beancount w trybie edytowalnym z innego katalogu.
- **Od testu nieudanego do pomyślnego:** obserwuj, jak tester dodaje test
  regresyjny, test wykrywa błąd w kodzie bazowym, programista zmienia
  `booking_full.py`, a pytest potwierdza poprawkę. Końcowy opis modelu nie
  zastępuje rzeczywistych testów ani sprawdzenia zestawu zmian.
  Kod wyjścia zero aplikacji oznacza zakończenie rozmowy i zamknięcie SDK,
  a nie automatyczne potwierdzenie naprawy zgłoszenia.
  Końcowy warunek obejmuje również przejście całego modułu booking, nie
  wyłącznie nowej klasy regresyjnej.
- **Granica SDK:** `python_static_analysis` jest niestandardowym narzędziem SDK
  zarejestrowanym dla analityka. Obserwuj `[tool] start`,
  `[analysis] Ruff/Pyright report` i `[tool] complete success=True`;
  `[event] tool.execution_start` / `tool.execution_complete` pokazują cykl
  narzędzia środowiska wykonawczego.
- **Filtr raportu:** komunikaty mają skompresowane białe znaki, ścieżki są
  względne, a JSON mieści się w 6000 bajtach i nie zawiera więcej niż
  80 diagnostyk na analizator. Sprawdź `finding_count`, `omitted_findings`
  i `json_bytes_limit`, aby nie pomylić niepełnego raportu z kompletnym.
- **Awaria analizatora:** sprawdź `status="failed"`, `exit_code` i `error`.
  Błąd konfiguracji lub uruchomienia nie jest błędem dekodowania JSON.
  Nie uznawaj pustej listy `findings` w nieudanym raporcie za czystą analizę;
  funkcja obsługująca narzędzie przekazuje informację o niepowodzeniu do SDK,
  nie zmieniając sposobu zamykania sesji ani klienta.
- **Przekazanie recenzji:** `static-reviewer` otrzymuje pełny raport w zadaniu
  `task`, ale nie ma dostępu do plików. Jego ocena powinna opierać się
  wyłącznie na wynikach Ruff i Pyright, a nie na przeglądzie zmian Git.
- **Delegacja i jawny wybór:** obserwuj `task` oraz zdarzenia `subagent.*`
  w dwóch turach orkiestratora. Porównaj je z końcowym
  `agent="documentarian"`: tę rolę wybiera Python, ale odpowiedź i edycja
  nadal przechodzą przez rzeczywisty SDK, model i funkcję uprawnień.
- **Uprawnienia i ograniczenia:** analityk ma skaner, recenzent `git_diff`,
  tester — powłokę z dwoma dozwolonymi poleceniami, a programista
  i dokumentalista — możliwość edycji przypisanych plików za pomocą
  `apply_patch` lub `edit`. Nie zatwierdzaj operacji spoza tych zakresów.
  Nazwy narzędzi muszą odpowiadać środowisku wykonawczemu i modelowi.
  W CLI 1.0.98 sesja wybrana jawnie i agent uruchomiony przez `task` mogą
  mieć różne zestawy edytorów. `str_replace_editor` nie wystarcza; role
  dopuszczają oba aktualne edytory. Sprawdzaj wpisy
  `[tool] start apply_patch` / `[tool] start edit` i rzeczywiste zmiany,
  a nie tylko deklarację roli.
- **Odpowiedź i sprzątanie:** po `session.idle` pojawia się końcowa odpowiedź,
  następnie zamykane są sesja i klient Copilot. Wyjście pokazuje nazwy
  narzędzi i wynik, nie argumenty ani surowe dane zdarzeń; szczegóły
  widocznych operacji znajdują się w lokalnym dzienniku. Przed przywróceniem
  plików zapisywany jest zestaw zmian.
- **Długie oczekiwanie:** `[progress]` pokazuje czas i ostatnie zdarzenie
  również podczas pracy analizatorów. Nie wypisuje odpowiedzi częściowych
  ani wrażliwych danych. Sprawdź limit w `CONFIGURATION`; po Ctrl+C oczekuj
  jawnego przerwania i komunikatu `Cancelled.`, a nie `Copilot session failed`.
- **Granica anulowania:** obserwuj `[lifecycle] Aborting active Copilot request`
  oraz ewentualne `[cleanup]`. Odłączenie sesji zachowuje historię SDK;
  `force_stop()` awaryjnie zatrzymuje klienta; nie ponawia polecenia.
- **Powtarzalność:** domyślnie obejrzyj zachowane zmiany i zresetuj katalog
  ręcznie przed kolejnym przebiegiem. Przy `keep_changes=False` po zatrzymaniu środowiska wykonawczego oczekuj
  `[rollback] Base restored`, czystego stanu repozytorium i tego samego HEAD.
  Funkcja zwrotna odrzuca zatwierdzanie i wysyłanie zmian; przywrócenie jest
  lokalnym działaniem aplikacji, a nie zadaniem zleconym modelowi. Skrypt nie
  używa `git clean` ani nie przywraca stanu całej kopii repozytorium.

## Testy

### Wybór zachowania zmian w kodzie i z zewnątrz

Bez argumentów CLI: w [main.py](main.py) ustaw
`CONFIGURATION = DemoConfiguration(keep_changes=False)`, aby przywrócić
automatyczny rollback. Kod wywołujący może zamiast tego przekazać konfigurację
do `main(configuration)` albo `SdlcTeamApplication().run(configuration)`:

```python
from dataclasses import replace

configuration = replace(demo.CONFIGURATION, keep_changes=False)
# SDK closes sessions and its CLI runtime before Python restores the three files.
exit_code = demo.main(configuration)
```

`demo` oznacza załadowany moduł dema. Pominięcie parametru zachowuje
`keep_changes=True`. Nieprawidłowa wartość (np. tekst `"false"` zamiast
`False`) kończy się błędem konfiguracji przed połączeniem z SDK.
Test edycji programisty sprawdza oba tryby po sukcesie i po anulowaniu
na rzeczywistych, tymczasowych repozytoriach i przez żywy SDK.

Test `test_live_hybrid_workflow_repairs_then_explicitly_documents` uruchamia
pełny domyślny scenariusz przez rzeczywisty SDK i lokalny login CLI.
Wymaga przygotowanego, czystego katalogu dema i skompilowanego parsera,
sieci oraz subskrypcji. Sprawdza rozdzielenie analizy i naprawy, dwa prompty
w sesji orkiestratora, jawną sesję dokumentalisty, wywołania testów i diff
wszystkich trzech plików przed rollbackiem.
Przed dokumentacją niezależnie wykonuje też pytest dla regresji i całego
modułu na rzeczywiście zmienionych plikach; samo powodzenie narzędzia SDK
nie wystarcza do uznania testów za poprawne. Nie uruchamiaj go równolegle
z pokazem w tym samym katalogu roboczym. Brak wymaganych składników
powoduje błąd, nie pominięcie testu.

### Ograniczenie zaobserwowane w środowisku wykonawczym

W CLI 1.0.98 niektóre zadania delegowane programiście zgłaszały brak edytora,
mimo że zarejestrowano `apply_patch` i `edit`. Samo ograniczenie nazw delegacji
nie rozwiązało tego problemu, dlatego demo nie wymusza takiego obejścia.
Nie traktuj deklaracji modelu o wykonaniu poprawki jako dowodu edycji:
sprawdź zdarzenia narzędzi, rzeczywiste zmiany i oba wyniki pytest.

Podczas weryfikacji poprawka przygotowana przez agentów przeszła cały moduł
booking: **120 passed, 20 skipped** (pominięcia są częścią testów projektu
źródłowego).
Ostatnia korekta wymagała jawnego wybrania `programmer` przez SDK (`agent=`);
nie był to w pełni automatyczny przebieg całego zespołu zakończony powodzeniem.
Poprawkę zachowano poza repozytorium, a katalog roboczy przywrócono do stanu
z pierwotnym błędem. Test automatycznej delegacji wykonywany na żywo pozostaje
w zestawie i ma zgłosić błąd, jeśli środowisko wykonawcze nie udostępni edytora.

```bash
.venv/bin/python -m pytest --import-mode=importlib demos/005-sdlc-team
.venv/bin/python -m pytest --import-mode=importlib tests/test_prepare_workspaces.py tests/test_prepare_sdlc_team.py
```

Test przygotowania kompiluje rzeczywisty parser w osobnym, tymczasowym
środowisku, sprawdza `DivisionByZero` na bazie i poprawny zakup 2 HOOL.
Testy przywracania korzystają z prawdziwego programu Git i tymczasowych kopii repozytorium
odtworzonych z pakietu. Sprawdzają zachowanie istniejących zmian,
przywrócenie trzech plików, niezmieniony HEAD oraz jawne błędy. Test
programisty wykonywany na żywo sprawdza edycję przed zatrzymaniem SDK i jej
brak po przywróceniu plików; wymaga sieci, subskrypcji i zalogowania w CLI.
Test przekroczenia limitu czasu sprawdza także komunikat
o przywróceniu plików. Test pakietu sprawdza SHA, kompletność wszystkich
340 plików względem migawki, `git fsck`, adresy zdalnych repozytoriów, brak
wymogu pobierania źródeł z sieci oraz zachowanie istniejących zmian.
Test programisty wykonywany na żywo korzysta z osobnej, tymczasowej kopii
repozytorium odtworzonej z pakietu. Sprawdza automatyczne delegowanie przez
`task`, rzeczywistą edycję za pomocą `apply_patch` lub `edit` oraz funkcję
zwrotną uprawnień; nie zmienia bazowego katalogu roboczego przeznaczonego
do pokazu. W systemie Windows testy budowy uruchamiaj w terminalu
deweloperskim Visual Studio;
test Ctrl+C przez PTY i kontrola PID przez `os.kill(pid, 0)` wymagają POSIX.
Natywny zestaw Windows (pozostałe testy, w tym żywy SDK):

```powershell
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib demos\005-sdlc-team -k "not ctrl_c and not local_tool_timeout"
.\.venv\Scripts\python.exe -m pytest --import-mode=importlib tests\test_prepare_workspaces.py tests\test_prepare_sdlc_team.py
```

`PYTHONUTF8=1` z sekcji przygotowania zachowuje polskie odpowiedzi także
podczas przekierowywania danych wyjściowych do pliku w Windows; nie zmienia
sposobu uwierzytelniania SDK. Instalacja Meson-Python w trybie edytowalnym
uruchamia narzędzia budowania także podczas importowania pakietu.
Przy ręcznym uruchamianiu poleceń zachowaj `.venv/bin` (Windows:
`.venv\Scripts`) na początku `PATH`, zgodnie z sekcją przygotowania.
Klient SDK dodaje ten katalog automatycznie do środowiska swojej powłoki.

Testy uruchamiają rzeczywiste pliki wykonywalne Ruff i Pyright, sprawdzają
skompresowany raport JSON i jego rozmiar w bajtach, jawny błąd przy braku
dostępu do kopii repozytorium, konfigurację ról oraz decyzje funkcji zwrotnej
dla dozwolonych i odrzuconych ścieżek i poleceń. Testy
obejmują też uruchomienie rzeczywistego Ruff z błędną konfiguracją i
potwierdzają zachowanie przyczyny z `stderr` oraz kodu wyjścia.
Testy parsera sprawdzają poprawny JSON przy kodach 0 i 1, brak danych
wyjściowych,
uszkodzony JSON i dodatkowy tekst po raporcie bez maskowania błędów.
Testy dziennika używają rzeczywistych plików: sprawdzają natychmiastowy zapis,
UTF-8, redakcję, osobne nazwy przebiegów, jawny błąd katalogu oraz zapis błędu
konfiguracji. Test przekazania zadania wykonywany na żywo sprawdza w dzienniku
obie role, zadania, wyniki analizatorów i kolejność względem przywrócenia
plików. Test programisty wykonywany na żywo potwierdza zachowanie lub wycofanie
rzeczywistych zmian zależnie od `keep_changes`, zarówno po sukcesie,
jak i po anulowaniu; test przekroczenia limitu
czasu wymaga wpisu o błędzie zamiast pozornego zakończenia.
Testy wykonywane na żywo korzystają z zainstalowanego SDK, rzeczywistego CLI,
sieci i uwierzytelnienia. Sprawdzają też działanie pętli podczas analizy,
przekroczenie limitu czasu i anulowanie lokalnych procesów, limit czasu
rzeczywistego żądania SDK oraz naciśnięcie Ctrl+C w terminalu PTY
(Linux/POSIX). Test Ctrl+C wysyła sygnał również do procesu CLI i wymaga
kodu wyjścia 130, nawet jeśli wystąpi błąd podczas sprzątania. Krótkie
polecenia używane w testach anulowania nie zmieniają kopii repozytorium.
Testy potwierdzają w szczególności, że środowisko wykonawcze deleguje zadanie
analitykowi, który uruchamia oba analizatory, a następnie agentowi
`static-reviewer`, oraz że tester za pomocą SDK wykona oba dozwolone
polecenia bez edycji plików.
Test przekazania raportu zleca jedno uruchomienie skanera bez czytania kodu
ani rozwiązywania zgłoszenia, a następnie prosi o recenzję liczącą najwyżej
pięć zdań. Sprawdza przekazanie JSON przez SDK, a nie cały proces naprawy.
Brak kopii repozytorium, dostępu, subskrypcji lub zalogowania **nie powoduje
pominięcia testu** — test kończy się błędem z instrukcją przygotowania
środowiska.
