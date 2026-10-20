# fy27-gh-sdk-python-sdlc

## Materiały dla uczestników

[Prezentacja](github-cli-sdk-python.pptx) jest utrzymywana ręcznie. Repozytorium
nie zawiera jej generatora ani zależności potrzebnych do jej budowania.
Instrukcje uruchamiania i obserwacji poszczególnych przykładów znajdują się
w README każdego dema.

## Kontener deweloperski

To repozytorium zawiera kontener deweloperski (`.devcontainer/`) z Pythonem
3.12, Node.js 22, GitHub CLI (`gh`), GitHub Copilot CLI (`@github/copilot`)
i pakietem Pythona `github-copilot-sdk`. Polecenie wykonywane po utworzeniu
kontenera zawsze tworzy repozytoryjne `.venv`, instaluje w nim SDK i zależności
pytest z `requirements.txt` oraz konfiguruje VS Code tak, aby aktywował ten
interpreter. Dzięki temu aktywne `.venv` nie ukrywa SDK zainstalowanego
wyłącznie w pakietach witryny użytkownika kontenera.

### Wykrywanie testów Pythona

VS Code wykrywa testy pytest w katalogach `tests/` i `demos/`, w tym we
wszystkich ponumerowanych katalogach dem, takich jak `demos/001-auth/` czy
`demos/002-initialsession/`. Tryb importlib zapobiega kolizjom powtarzających
się nazw `test_main.py`. Zbieranie testów nie wysyła żądań do Copilot; testy
integracyjne uruchamiają prawdziwy SDK i runtime, wymagają dostępu do sieci,
uwierzytelnienia CLI (lub providera skonfigurowanego dla danego dema) oraz
dostępu do Copilot albo poświadczeń providera. Dodatkowe wymagania opisuje
README każdego dema. Brak wymagań powoduje błąd, a nie ciche pominięcie testu
integracyjnego.

Aby naprawić istniejący kontener bez ponownej instalacji Copilot CLI:

```bash
source .devcontainer/python-environment.sh
create_python_environment "$PWD"
.venv/bin/python -m pytest --collect-only --import-mode=importlib tests demos
```

Następnie uruchom w VS Code polecenie **Python: Discover Tests**. W widoku
Test Explorer powinny pojawić się testy repozytorium i wszystkie pliki testowe
ponumerowanych dem. Nowe kontenery instalują pytest podczas konfiguracji po
utworzeniu; przebudowanie stosuje również domyślne ustawienia kontenera.
Ostrzeżenie o brakującym obserwatorze `.pixi/envs` nie ma związku z projektem:
to repozytorium korzysta z `.venv`, a nie z Pixi.

### Ustawienia VS Code i sesje Copilot

Na hoście VS Code otwórz **Accounts → Backup and Sync Settings**, wybierz
**Sign in with GitHub** i włącz ustawienia, które chcesz synchronizować.
Logowanie wymaga interaktywnego zatwierdzenia w przeglądarce, dlatego nie
można bezpiecznie włączyć go w `devcontainer.json`. Synchronizacja ustawień
VS Code obejmuje preferencje użytkownika, skróty, fragmenty kodu, zadania,
stan interfejsu, rozszerzenia i profile, ale nie kopiuje rozszerzeń do zdalnych
okien. Dlatego kontener jawnie deklaruje wymagane rozszerzenia Python, Python
Debugger i Copilot. Obszar roboczy dodatkowo poleca Python Debugger, aby był
dostępny po otwarciu repozytorium poza kontenerem.
Aby debugować bieżący plik Pythona, w sekcji **Run and Debug** wybierz
**Python: Current File (.venv)** (lub naciśnij F5). Ta konfiguracja uruchamia
`${file}` repozytoryjnym interpreterem (`.venv\Scripts\python.exe` w Windows,
`.venv/bin/python` w Linux/macOS), a bieżącym katalogiem ustawia
`${fileDirname}`. Jedna konfiguracja obsługuje wszystkie dema, w tym Human
Policy: otwórz jego `main.py` i naciśnij F5. Wybory człowieka i polecenia
slash CLI wpisuj w zintegrowanym terminalu, nie w Debug Console. Zamrożone
moduły są wyłączone, aby breakpointy Pythona działały niezawodnie. Poczekaj,
aż demo zakończy sprzątanie; długie zatrzymanie na breakpoincie może
przekroczyć skonfigurowany limit czasu żądania.
Automatyczne debugowanie podprocesów jest wyłączone: narzędzia Pythona CLI,
procesy potomne pytest i runnera działają normalnie, bez wstrzykiwania
debugpy. Breakpointy dotyczą procesu Pythona obsługującego demo, nie jego
procesów potomnych.

<a id="shared-copilot-cli-startup"></a>

### Wspólny start Copilot CLI

Wszystkie dziesięć dem i sekwencyjne runnery korzystają z
[copilot_runtime.py](copilot_runtime.py), który wybiera zainstalowane CLI.
Moduł zawiera również `DISABLED_MCP_SERVERS`, `show_disabled_mcp_servers()`
i pomocniczą funkcję `print_event()`, która nie wypisuje payloadów.
Przykłady SDK nadal jawnie przekazują wspólną listę do `create_session`;
demo 007 zachowuje celowy dostęp do GitHub MCP, a ACP ma odrębną politykę
protokołu. Szczegóły narzędzi, elicitation, użycia i subagentów pozostają
w poszczególnych demach. Nie trzeba tworzyć osobnego profilu debugowania ani
eksportować ustawień terminala dla każdego dema.

1. Przygotuj repozytoryjne `.venv`, zainstaluj `requirements.txt` przez
   skonfigurowany rejestr pakietów i sprawdź `copilot --version` oraz
   `copilot login`. Testy modeli na żywo wymagają sieci, aktywnej subskrypcji
   i dostępu do wybranych modeli; BYOK wymaga ponadto skonfigurowanego
   providera i zmiennej środowiskowej z sekretem.
2. Otwórz `main.py` wybranego dema i naciśnij F5 z konfiguracją
   **Python: Current File (.venv)** albo uruchom z katalogu głównego
   `.venv\Scripts\python.exe demos\<demo>\main.py` w Windows
   (`.venv/bin/python demos/<demo>/main.py` w Linux/macOS).
3. Resolver respektuje `COPILOT_CLI_PATH`, a w przeciwnym razie wyszukuje
   `copilot` w PATH. W Windows VS Code może wstrzyknąć bootstrapper Copilot
   Chat z `globalStorage\github.copilot-chat\copilotCli`. Resolver rozpoznaje
   ten wrapper, szuka `copilot.exe` poza jego katalogiem i wypisuje
   `VS Code Copilot launcher: ...; using installed CLI: ...`, a następnie
   `Copilot CLI: ...`. Nie usuwa instalacji, nie zmienia trwałych ustawień,
   nie uruchamia bootstrappera ani nie pobiera zapasowego runtime SDK.
   Nieprawidłowa jawna ścieżka, nierozpoznany wrapper Windows lub brak
   natywnego CLI powoduje widoczny błąd.
4. Przykłady SDK używają `RuntimeConnection.for_stdio(path=...)` i przekazują
   środowisko klienta, dzięki czemu procesy potomne SDK korzystają z tej samej
   natywnej ścieżki. Logowanie CLI pozostaje włączone, poza przypadkiem, gdy
   demo 001 wybiera BYOK. ACP używa tego samego wyboru dla `--acp --stdio`;
   demo 010 przekazuje natywną ścieżkę również rozszerzeniu. Punkt wejścia
   `.js` wymaga Node.js w PATH.
5. Postępuj według instrukcji danego dema, aby wybrać model i narzędzia,
   obserwować eventy oraz sprawdzić oczekiwaną odpowiedź. Konteksty sesji
   i zamknięcie klienta odpowiadają za sprzątanie; ACP zamyka się przy
   zakończeniu sesji/serwera, a demo 010 usuwa tymczasowe repozytorium po
   poleceniu `/exit`.

Zwracaj uwagę na wypisaną ścieżkę pliku wykonywalnego, a nie tylko na wynik
polecenia w terminalu PowerShell. F5 dziedziczy środowisko procesu VS Code,
nie zmienne wyeksportowane później w innym terminalu. Wybór runtime nie zmienia
polityk MCP, list dozwolonych narzędzi ani wyboru providera. Pełne testy
terminalowe dema 010 nadal wymagają Linux/WSL/macOS (PTY); walidacja natywna
w Windows obejmuje rzeczywistą ścieżkę uruchomienia CLI i instalację
rozszerzenia, ale nie interaktywne wykonywanie poleceń slash.

Kontener deweloperski włącza listę sesji VS Code i pokazuje wszystkie ostatnie
zewnętrzne sesje Copilot CLI powiązane z tym repozytorium. Otwórz widok Chat
lub okno Agents, aby wznowić widoczną sesję. Lokalna historia Copilot pozostaje
w lokalnym magazynie sesji VS Code i nie jest przesyłana przez synchronizację
ustawień.

W przypadku sesji synchronizowanych przez GitHub.com wybierz cel sesji
**Cloud** w oknie Agents w VS Code po zalogowaniu do GitHub na to samo konto.
Sesje w chmurze są sesjami agenta kodującego GitHub Copilot powiązanymi
z repozytorium, więc ich status i pull requesty są dostępne zarówno w GitHub.com,
jak i w VS Code. Są niezależne od lokalnej historii czatu.

Repozytorium zawiera także
`.github/workflows/copilot-setup-steps.yml`. Zanim agent GitHub Copilot
w chmurze rozpocznie pracę, GitHub uruchamia specjalnie nazwane zadanie
konfiguracyjne, które tworzy `.venv`, instaluje `requirements.txt` i umieszcza
to środowisko na początku `PATH`. Workflow zaczyna obowiązywać dla nowych
sesji w chmurze dopiero po scaleniu go z domyślną gałęzią repozytorium.

**GitHub Codespaces:** otwórz repozytorium → *Code* → *Codespaces* →
*Create codespace*.

**Lokalnie, z Podmanem:**

```bash
npm install -g @devcontainers/cli   # once
devcontainer up --workspace-folder . --docker-path podman
devcontainer exec --workspace-folder . --docker-path podman bash
```

**WSL:** przechowuj checkout w systemie plików Linux WSL (na przykład
w `~/src`, a nie w `/mnt/c`, gdzie uprawnienia właściciela mogą nie być
egzekwowane). Uwierzytelnij GitHub CLI w WSL, a następnie uruchom VS Code
skryptem repozytorium, aby przygotować token dla kontenera deweloperskiego:

```bash
gh auth login --hostname github.com
./start-code-wsl.sh
```

Do skryptu można przekazać dodatkowe argumenty VS Code, na przykład
`./start-code-wsl.sh --reuse-window`. **Następnie uruchom w VS Code polecenie
Dev Containers: Rebuild Container.** Po zmianie poświadczeń ponowne otwarcie
istniejącego kontenera lub terminala nie wystarczy.

Program uruchamiający wybiera kolejno `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`,
`GITHUB_TOKEN`, a następnie `gh auth token --hostname github.com`. Obsługiwane
są tokeny OAuth; token fine-grained PAT wymaga uprawnienia konta
**Copilot Requests**. Klasyczne tokeny PAT (`ghp_`) nie są obsługiwane przez
Copilot CLI.

Wybrany token jest zapisywany lokalnie w `.devcontainer/copilot.env`
z uprawnieniami tylko dla właściciela (`0600`). Ten plik i tymczasowe pliki
pośrednie są ignorowane przez Git i wyłączone z kontekstu budowania obrazu
Docker/Podman. Nie zatwierdzaj ich ani nikomu nie udostępniaj. Docker/Podman
odczytuje plik podczas tworzenia kontenera, więc poświadczenie trafia zarówno
do procesów Copilot CLI, jak i SDK, nawet gdy VS Code ponownie używa istniejącego
serwera WSL. Token nie jest przekazywany w wierszu poleceń ani wypisywany.
Jak każda zmienna środowiskowa kontenera, jest widoczny dla użytkowników
mających dostęp do silnika kontenerów; lokalny plik jest tekstem jawnym,
a nie magazynem sekretów.

Przy lokalnym Podmanie bez VS Code przygotuj ten sam plik w terminalu hosta
przed poleceniem `devcontainer up`:

```bash
source .devcontainer/copilot-credentials.sh
write_copilot_env "$PWD/.devcontainer/copilot.env"
```

Przy świeżym checkoutcie bez przygotowanego poświadczenia inicjalizacja tworzy
plik zawierający wyłącznie komentarz, zamiast zastępować pustą wartością token
przekazany przez Codespaces. W razie potrzeby uruchom `copilot login` wewnątrz
kontenera (lub skonfiguruj BYOK). Logowanie do rozszerzenia Copilot w VS Code
jest niezależne od uwierzytelnienia CLI.

W przebudowanym kontenerze sprawdź rzeczywiste żądanie SDK. Oczekuj nazw
eventów SDK, a następnie końcowej odpowiedzi `Authentication works.`:

```bash
.venv/bin/python demos/001-auth/main.py
```

Aby zmienić token, ponownie uruchom skrypt WSL i przebuduj kontener. Aby
zatrzymać jego przekazywanie, usuń wyłącznie `.devcontainer/copilot.env`
i przebuduj kontener; istniejące kontenery zachowują poprzednie środowisko
do czasu ich ponownego utworzenia.

### Testy przekazywania poświadczeń

```bash
.venv/bin/python -m pytest tests/test_devcontainer_credentials.py -v
```

Testy korzystają z rzeczywistych plików lokalnych i funkcji powłoki; sprawdzają
między innymi uprawnienia, inicjalizację, nieprawidłowe lub brakujące
poświadczenia, kolejność wyboru tokenu i wykluczenia. Test na żywo przygotowuje
prawdziwe poświadczenie hosta i przekazuje wynikowe środowisko zainstalowanemu
SDK Pythona oraz działającemu runtime Copilot dla deterministycznego żądania
bez narzędzi. Wymaga `github-copilot-sdk`, dostępu do pobrania runtime/sieci,
obsługiwanego tokenu lub uwierzytelnionego `gh` oraz konta z dostępem do Copilot.
Brak wymagań jawnie kończy test błędem, nigdy pominięciem. Zestaw nie uruchamia
Docker/Podman ani VS Code; aby sprawdzić faktyczne przekazanie poświadczenia
WSL do kontenera, uruchom powyższe demo wewnątrz przebudowanego kontenera.

## Dema

Demo 005 zawiera pełne, przypięte źródła Beancount w
[src-beancount](src-beancount/), wraz z informacją o pochodzeniu i oryginalną
licencją. Lokalny [pakiet źródłowy](demos/005-sdlc-team/beancount-base.bundle)
odtwarza oryginalny commit bazowy bez pobierania danych z GitHub.
Po zainstalowaniu [requirements.txt](requirements.txt) uruchom
`.venv/bin/python prepare_sdlc_team.py` (Windows:
`.\.venv\Scripts\python.exe prepare_sdlc_team.py` w terminalu deweloperskim
Visual Studio). [Skrypt przygotowujący](prepare_sdlc_team.py) buduje
rzeczywisty parser C i instaluje checkout dema w trybie edytowalnym, dzięki
czemu tester Copilot sprawdza te same źródła, które modyfikuje zespół.
Baza nadal zawiera błąd z issue #1048; agenci dodają test regresyjny i poprawkę
podczas pokazu. Wymagania uwierzytelniania, przebieg, oczekiwane wyniki
od niepowodzenia do sukcesu i sprzątanie opisuje
[instrukcja z checklistą](demos/005-sdlc-team/README.md).

### Indeks dem

Katalogi dem mają kolejne, niepowtarzające się numery w kolejności indeksu.
Uruchamiaj każdy `main.py` z katalogu głównego repozytorium
poleceniem `.venv/bin/python`; powiązane README opisuje wymagania, obserwowalne
zachowanie Copilot i sprzątanie. Zmiana numeracji nie usuwa klonów
`workspace/` ani historii sesji poszczególnych dem.

| Numer | Demo | Na co zwrócić uwagę |
| --- | --- | --- |
| 001 | [Uwierzytelnianie](demos/001-auth/README.md) | Logowanie CLI lub BYOK, bezpieczne nazwy eventów i rzeczywista odpowiedź modelu. |
| 002 | [Sesja początkowa](demos/002-initialsession/README.md) | Wbudowane narzędzia odczytu, `session.idle` i zamknięcie sesji/klienta. |
| 003 | [Własne narzędzie](demos/003-custom-tool/README.md) | Schemat Pydantic, `get_requirement` i kontynuacja pętli agenta. |
| 004 | [Bezpieczne narzędzie](demos/004-custom-tool-secure/README.md) | Odmowa odczytu spoza workspace, a następnie dozwolony odczyt. |
| 005 | [Zespół SDLC](demos/005-sdlc-team/README.md) | Analiza statyczna, delegowanie do agentów niestandardowych i uprawnienia ról. |
| 006 | [Polityka z udziałem człowieka](demos/006-human-policy/README.md) | Decyzje człowieka, ograniczenia powłoki/zapisu i informacja zwrotna po błędzie testu. |
| 007 | [MCP i wznawianie](demos/007-mcp-resume/README.md) | Ograniczony odczyt GitHub, trwałe eventy oraz ponowne uruchomienie/wznowienie. |
| 008 | [Wybór modelu](demos/008-model-choice/README.md) | To samo zadanie tylko do odczytu w czterech sesjach wybranych modeli przez jeden runtime. |
| 009 | [Klient WWW ACP](demos/009-acp-web/README.md) | Strumieniowanie do przeglądarki przez ACP, osobne procesy CLI i jawne zamknięcie. |
| 010 | [Rozszerzenie CLI](demos/010-cli-extension/README.md) | Natywne polecenia slash, eventy sesji głównej i odizolowane sesje dowcipu/tłumaczenia. |

Demo 007 używa teraz zmiennych `DEMO_007_GITHUB_MCP_TOKEN`,
`DEMO_007_FORK_OWNER` i `DEMO_007_APPROVE_DRAFT_PR`. Zaktualizuj lokalnie
skonfigurowane nazwy ze starego prefiksu `DEMO_005_`; nie kopiuj wartości
sekretów do kodu ani dokumentacji.

#### Ustawienie zmiennych Demo 007

`DEMO_007_GITHUB_MCP_TOKEN` jest potrzebny tylko dla opcjonalnego połączenia
zdalnym serwerem HTTP MCP (`CONFIGURATION.remote_mcp=True`). Domyślny serwer
GitHub MCP korzysta z logowania Copilot CLI (`copilot login`) i nie wymaga tej
zmiennej.

1. Jeśli jeszcze nie masz forka, utwórz na GitHubie własny fork
   `beancount/beancount`. Następnie otwórz **Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token**. Wybierz swoje konto jako
   **Resource owner** i ogranicz **Repository access** do swojego forka
   `beancount`. Nadaj tylko uprawnienia potrzebne do operacji dema: odczyt
   metadanych, Issues, Contents i Pull requests. Jeśli zamierzasz użyć
   opcjonalnego etapu tworzenia draft PR, ustaw **Pull requests** na
   **Read and write** dla forka. Nie używaj tokenu Copilot CLI jako tokenu MCP,
   chyba że ma te same wymagane uprawnienia. Wybierz **Generate token** i
   skopiuj go od razu — GitHub nie pokaże go ponownie.
2. W terminalu PowerShell, w którym uruchomisz demo, ustaw token bez wpisywania
   go jawnie w poleceniu ani zapisywania w repozytorium:

   ```powershell
   $secure = Read-Host "Wklej fine-grained GitHub token" -AsSecureString
   $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
   try {
       $env:DEMO_007_GITHUB_MCP_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
   } finally {
       [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
       $secure.Dispose()
   }
   ```

   Ta zmienna obowiązuje tylko w bieżącym procesie PowerShell i jego procesach
   potomnych. Uruchom demo z tego terminala. Aby użyć F5, zamknij wszystkie
   uruchomione okna VS Code i uruchom `code .` z tego terminala; F5 dziedziczy
   środowisko procesu VS Code. Po zakończeniu usuń ją poleceniem
   `Remove-Item Env:DEMO_007_GITHUB_MCP_TOKEN`. Nie zapisuj tokenu w kodzie,
   README, historii poleceń ani pliku śledzonym przez Git.
3. `DEMO_007_FORK_OWNER` to login konta albo organizacji będącej właścicielem
   Twojego forka `beancount`; odczytasz go z właściciela w adresie
   `https://github.com/<właściciel>/beancount`. Fork utwórz na GitHubie z
   `tkopacz/beancount`, którego klon przygotowuje `prepare_workspaces.py`.
   Ustaw właściciela w PowerShellu jako jego login, bez nazwy repozytorium:

   ```powershell
   $env:DEMO_007_FORK_OWNER = "<login-właściciela-forka>"
   ```

   Nie wpisuj tu `beancount` — to właściciel repozytorium upstream, a demo
   dopuszcza operacje tylko w Twoim forku.
4. `DEMO_007_APPROVE_DRAFT_PR` nie pochodzi z GitHuba i nie jest tokenem.
   To jawna, ręcznie ustawiana zgoda dema. Pozostaw ją nieustawioną podczas
   odczytu i przygotowywania zmian. Dopiero po sprawdzeniu zmiany `CHANGES`,
   ręcznym commicie i wypchnięciu zatwierdzonego brancha forka ustaw:

   ```powershell
   $env:DEMO_007_APPROVE_DRAFT_PR = "yes"
   ```

   Wartość musi być dokładnie `yes`. Sama zmienna nie publikuje PR: etap
   publikacji wymaga także `CONFIGURATION.publish_draft=True`,
   `CONFIGURATION.resume=True` i poprawnie przygotowanego, czystego checkoutu
   forka. Demo może wtedy utworzyć wyłącznie draft PR w Twoim forku — nigdy w
   upstreamie. Po uruchomieniu usuń zgodę poleceniem
   `Remove-Item Env:DEMO_007_APPROVE_DRAFT_PR`. Szczegółowy, krok po kroku
   opis przygotowania i publikacji znajduje się w
   [README dema 007](demos/007-mcp-resume/README.md#kontrolowany-proces-tworzenia-draft-pr).

### Rozszerzanie Copilot CLI

[Demo 010](demo2.md) oraz wykonywalne demo
[010-cli-extension](demos/010-cli-extension/README.md) pokazują natywne
rozszerzenie CLI: dołączanie do aktywnej sesji, obserwowanie eventów
i rejestrowanie poleceń `/demo`, `/demo stats` oraz `/demo joke`. Ostatnie
polecenie uruchamia dwie odizolowane sesje bez narzędzi i z własnymi promptami
systemowymi: najpierw czeskiego komika, a potem polskiego tłumacza; główna
rozmowa pozostaje bez zmian. CLI udostępnia JavaScript SDK rozszerzeń;
Python jedynie uruchamia tymczasowe repozytorium dema.

[Demo 009](demos/009-acp-web/README.md) buduje lokalnego klienta WWW w Pythonie
dla Copilot CLI, używając Agent Client Protocol (ACP) przez stdio. FastAPI
strumieniuje aktualizacje ACP do przeglądarki, a każda rozmowa dostaje osobny
proces CLI z dostępem wyłącznie do narzędzi odczytu/wyszukiwania. Demo wyjaśnia
również dodatkowe warstwy bezpieczeństwa i izolacji potrzebne w zdalnym,
wieloużytkownikowym „Agent HQ”.

### Uruchamianie testów i przykładów wszystkich dem

Dwa skrypty repozytorium korzystają ze wspólnego rejestru kolejności dem
w [demo_runner.py](demo_runner.py):

```bash
.venv/bin/python run-all-tests.py
.venv/bin/python run-all-demos.py
```

W Windows PowerShell użyj:

```powershell
.venv\Scripts\python.exe run-all-tests.py
.venv\Scripts\python.exe run-all-demos.py
```

Oba runnery wybierają repozytoryjny interpreter dla danej platformy oraz
wspólny resolver natywnego CLI; bootstrapper VS Code nie jest przekazywany
procesom potomnym SDK. Pełne testy PTY dema 010 wymagają Linux/WSL/macOS
i w natywnym Windows kończą się jawnym błędem, zamiast zaliczać
nieprzetestowaną integrację interaktywną.

#### Przebieg krok po kroku

1. Przygotuj repozytoryjne `.venv` z `requirements.txt` (kontener robi to
   automatycznie). Umieść `copilot` w PATH i wykonaj `copilot login` w tym
   samym środowisku lokalnym. Samo logowanie do rozszerzenia VS Code nie
   wystarczy. Dziedziczone są również obsługiwane zmienne tokenów CLI;
   żaden ze skryptów nie odczytuje, nie kopiuje ani nie wypisuje poświadczeń.
2. Zapewnij dostęp do sieci, aktywną subskrypcję Copilot, dostęp do każdego
   skonfigurowanego modelu oraz autoryzację GitHub MCP dla dema 007. Demo 009
   wymaga lokalnego logowania CLI (lub skonfigurowanego BYOK) i uruchamia
   lokalny serwer WWW; po przejściu demonstracji w przeglądarce zatrzymaj go
   przez Ctrl+C. Przygotuj przypięty checkout opisany w
   [demie 002](demos/002-initialsession/README.md) i przeczytaj README każdego
   dema przed uruchomieniem. Brak wymagań powoduje błąd, nigdy ciche pominięcie
   testu.
3. Z katalogu głównego repozytorium uruchom jedno z powyższych poleceń. Możesz
   też użyć `python run-all-tests.py` albo `python run-all-demos.py`; program
   uruchamia się ponownie z użyciem repozytoryjnego interpretera. Ścieżki
   i katalogi robocze procesów potomnych nie zależą od bieżącego katalogu
   wywołującego.
4. Runner sprawdza rejestr i wybiera lokalny plik wykonywalny `copilot`.
   `COPILOT_CLI_PATH` wymusza użycie tego pliku przez klientów SDK w procesach
   potomnych zamiast pobierania innego runtime. Rzeczywiste uzgodnienie
   `get_auth_status()` z SDK sprawdza uwierzytelnienie bez wysyłania promptu
   do modelu, a następnie zamyka klienta kontrolnego przed uruchomieniem dema.
5. `run-all-tests.py` uruchamia osobny proces pytest dla każdego dema,
   z opcjami `--import-mode=importlib -v`. Zbierane są wszystkie testy danego
   dema poza klonem `workspace/`, którego testy upstreamu nie są testami
   integracyjnymi dema. Testy na żywo wysyłają rzeczywiste żądania przez
   SDK/CLI i mogą zużywać AI credits. Testy dotyczące wyłącznie repozytorium
   w `tests/` nie są częścią tego polecenia.
6. `run-all-demos.py` uruchamia kolejno każdy `main.py` i czeka na jego
   zakończenie przed startem następnego. Bieżąca konfiguracja, prompty, modele,
   uprawnienia, output eventów i sprzątanie dem pozostają bez zmian. **Demo
   [005-sdlc-team](demos/005-sdlc-team/README.md) modyfikuje własny, przypięty
   checkout.** Sprawdź jego zmiany; runner nigdy ich nie resetuje ani nie
   usuwa. Kolejne dema lub testy mogą odrzucić zmodyfikowany checkout. Demo 007
   zachowuje skonfigurowany identyfikator sesji; kolejne uruchomienia stosują
   opisane tam ustawienia tworzenia/wznawiania, których runner nie zmienia.
   Za opcjonalne ustawienia zapisu/publikacji w każdym demie odpowiadasz
   samodzielnie. Demo 010 otwiera prawdziwe interaktywne CLI w tymczasowym
   repozytorium: poczekaj na `READY`, wypróbuj `/demo`, `/demo stats`
   i `/demo joke`, a potem wpisz `/exit`, aby runner mógł zakończyć działanie.
   Wymaga Node.js w PATH i TTY; w razie braku interaktywnego terminala zgłasza
   błąd zamiast udawać, że zwykły prompt uruchamia polecenie slash.
7. Każdy proces potomny przekazuje standardowy output; błąd jednego dema nie
   zatrzymuje pozostałych. Na końcu oczekuj jednego wiersza `PASS` lub `FAIL`
   z kodem wyjścia procesu dla każdego dema. Runner zwraca `0` tylko wtedy,
   gdy wszystkie procesy zakończą się powodzeniem, `1` przy dowolnym błędzie
   dema, `2` przy błędzie konfiguracji lub `130` po przerwaniu. Ctrl+C
   zatrzymuje sekwencję; przerwane uruchomienie może pozostawić historię sesji
   lub zmiany dema, dlatego przed ponowną próbą sprawdź ich stan.

#### Na co zwrócić uwagę

- **Rejestr:** `DEMO_DIRECTORIES` obejmuje wszystkie dziesięć dem, ponumerowanych
  od 001 do 010. Niezarejestrowane nowe demo, brak `main.py` lub brak pliku
  testowego powoduje błąd konfiguracji, a nie ciche pominięcie przykładu.
- **Uwierzytelnianie:** `verify_authentication()` korzysta z zainstalowanego
  SDK i lokalnego logowania CLI; wypisywane są wyłącznie ścieżka pliku
  wykonywalnego i stan powodzenia.
- **Cykl życia:** runtime kontroli wstępnej jest zamykany jako pierwszy;
  każdy kolejny proces potomny sam sprząta swoją sesję/runtime. Klient SDK ani
  sesja modelu nie są współdzielone.
- **Testy:** tryb importlib pytest obsługuje powtarzające się nazwy plików.
  Brak sieci, logowania, dostępu do modelu, autoryzacji MCP lub checkoutu
  powoduje rzeczywisty błąd. Demo 010 używa ponadto pexpect i pyte w systemach
  Linux/WSL/macOS do testowania prawdziwych poleceń slash CLI, renderowania
  terminala, eventów narzędzi i ponownego wczytywania rozszerzenia.
- **Przykłady:** prompty mogą wywoływać narzędzia i zużywać kredyty. Przed
  kolejnym ponumerowanym nagłówkiem zwróć uwagę na `session.idle` i komunikaty
  o sprzątaniu danego dema.
- **Stan:** runner zachowuje konfigurację, historię sesji CLI i zmiany
  w workspace; nie czyści ani nie resetuje stanu dema bez wiedzy użytkownika.
- **Wynik:** sprawdź końcowe podsumowanie każdego dema i kod wyjścia runnera,
  zamiast zakładać, że powodzenie ostatniego procesu oznacza sukces całego zestawu.

Testy runnera, w tym rzeczywiste uwierzytelnienie CLI i żądanie SDK przez
demo 001, wymagają dostępu do sieci, logowania i aktywnej subskrypcji:

```bash
.venv/bin/python -m pytest --import-mode=importlib tests/test_demo_runner.py -v
```

- [001-auth](demos/001-auth/README.md) porównuje poświadczenia zapisane przez
	`copilot login` z własnym providerem BYOK. Domyślna `CONFIGURATION`
	wysyła rzeczywisty prompt i wypisuje każdy event SDK:

	```bash
	python demos/001-auth/main.py
	```

	Test integracyjny używa prawdziwego SDK i usługi GitHub Copilot. Wymaga
	poprawnego uwierzytelnienia CLI przez przekazany token lub `copilot login`;
	logowanie do rozszerzenia VS Code nie jest używane przez runtime CLI.

- [002-initialsession](demos/002-initialsession/README.md) uruchamia kompletną
	sesję agenta Copilot w przypiętym klonie Beancount
	(`demos/002-initialsession/workspace`, tag `demo-red-1048`; każde demo ma
	własny klon utworzony przez `prepare_workspaces.py`). Agent odczytuje kod
	księgowania i testy za pomocą wbudowanych narzędzi, wyjaśnia issue #1048
	(`0 HOOL {{20.00 USD}}` powoduje `DivisionByZero`) i nie zmienia repozytorium:

	```bash
	.venv/bin/python demos/002-initialsession/main.py
	```

	Test integracyjny na żywo wymaga przygotowanego checkoutu, dostępu do sieci,
	uwierzytelnienia CLI i aktywnej subskrypcji Copilot. Sprawdza pętlę narzędzi,
	`session.idle`, sprzątanie zasobów i czysty katalog roboczy.

- [003-custom-tool](demos/003-custom-tool/README.md) rejestruje narzędzie
	Pydantic `get_requirement`, które odczytuje lokalny fixture issue #1048
	Beancount (`fixtures/beancount-1048.json`). SDK wybiera narzędzie, waliduje
	jego argumenty i kontynuuje pętlę agenta w ramach jednego
	`session.send_and_wait()`:

	```bash
	.venv/bin/python demos/003-custom-tool/main.py
	```

	Test integracyjny na żywo wymaga dostępu do sieci, uwierzytelnienia CLI
	i aktywnej subskrypcji Copilot. Sprawdza wygenerowany schemat, wywołanie
	`get_requirement`, eventy tur i wykonania narzędzia oraz końcową odpowiedź
	opartą na fixture.

- [004-custom-tool-secure](demos/004-custom-tool-secure/README.md) dodaje
  hook przed użyciem narzędzia i walidację ścieżki w handlerze własnego
  narzędzia odczytu. Obserwuj odmowę odczytu spoza workspace, późniejszy
  udany odczyt pliku projektu oraz zamknięcie sesji i klienta.

- [005-sdlc-team](demos/005-sdlc-team/README.md) łączy siedmiu specjalistów
  z uprawnieniami narzędzi przypisanymi do ról. Dwa prompty w jednej sesji
  uruchamiają analizę statyczną/recenzję, a następnie poprawkę kodu; Python
  jawnie wybiera `agent="documentarian"` w końcowej sesji. README opisuje
  przygotowanie przypiętej kopii roboczej, eventy cyklu życia i kontrolowany
  fallback z jawnym wyborem agenta.

- [006-human-policy](demos/006-human-policy/README.md) obsługuje blokowanie
  poleceń, ludzką akceptację zapisów, semantykę `maxlen` i informację
  zwrotną po błędzie testu w jednej sesji SDK. README wyjaśnia wymagany
  checkout roboczy i starszy fallback wejścia, gdy runtime CLI nie udostępnia
  elicitation formularza.

- [007-mcp-resume](demos/007-mcp-resume/README.md) używa ograniczonego dostępu
  GitHub MCP, limitów sesji i zapisanej historii eventów, a po restarcie
  wznawia tę samą sesję. Publikacja draft PR ma osobną bramkę; przed włączeniem
  zapisu przeczytaj README tego dema.

- [008-model-choice](demos/008-model-choice/README.md) uruchamia to samo
  zadanie tylko do odczytu na dostępnych modelach przez ten sam runtime
  GitHub Copilot SDK, dzięki czemu wybór modelu jest widoczny bez porównywania
  osobnych harnessów.

- [009-acp-web](demos/009-acp-web/README.md) uruchamia interfejs przeglądarkowy
  dostępny wyłącznie przez loopback. Każda rozmowa korzysta z osobnego procesu
  Copilot CLI przez ACP, a nie z Python Copilot SDK; po demo zamknij sesję
  i zatrzymaj serwer.

- [010-cli-extension](demos/010-cli-extension/README.md) dołącza rozszerzenie
  MJS do interaktywnej sesji CLI użytkownika. Obserwuje eventy tur,
  strumieniowania, narzędzi i użycia, dodaje `/demo`, lokalne `/demo stats`
  oraz odizolowane sesje czeskiego dowcipu i polskiego tłumaczenia przez
  `/demo joke`. Pokazuje sprzątanie cyklu życia. Uruchom
  `.venv/bin/python demos/010-cli-extension/main.py` w terminalu; tymczasowa
  instalacja jest usuwana po `/exit`.
