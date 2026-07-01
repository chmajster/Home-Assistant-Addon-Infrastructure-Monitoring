# Changelog

Wszystkie istotne zmiany w projekcie **Home Assistant Monitoring / Monitoring Center** będą dokumentowane w tym pliku.

Format opiera się na konwencji Keep a Changelog, a wersjonowanie dodatku powinno podążać za SemVer tam, gdzie ma to zastosowanie.

## [0.7.4] - 2026-07-02

### Changed

- Przebudowano wizualnie widok szczegółów monitora: uporządkowany toolbar, karty metryk, sekcje szczegółów i SLO oraz responsywny układ.
- Uspójniono topbar, kontrolki i zmienne UI dla jasnego i ciemnego motywu.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.7.4`.

## [0.7.3] - 2026-07-02

### Changed

- Doprecyzowano geometrię sidebaru: bezpieczny line-height, równe wysokości pozycji, lżejszy aktywny stan i stabilne wyrównanie ikon oraz tekstu.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.7.3`.

## [0.7.2] - 2026-07-02

### Changed

- Zastąpiono natywne potwierdzenie masowego usuwania własnym popupem z listą monitorów przeznaczonych do usunięcia.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.7.2`.

## [0.7.1] - 2026-07-02

### Changed

- Odświeżono UI sidebaru: spójne ikony SVG, lepszy aktywny stan, hover/focus oraz obsługa jasnego i ciemnego motywu.
- Dodano tryb `Zaznacz masowo`, w którym kliknięcie kafelka lub wiersza przełącza zaznaczenie monitora.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.7.1`.

## [0.7.0] - 2026-07-01

### Added

- Dodano osobne incydenty w bazie danych, API i UI, z czasem trwania, statusem, przyczyna i liczba checkow.
- Dodano dashboardowy status schedulera: dzialanie petli, ostatni tick, aktywne testy, kolejke i bledy.
- Dodano timeline monitora laczacy zdarzenia lifecycle, statusy, zmiany WWW, limity strony i incydenty.

### Changed

- Scheduler przechowuje taski checkow, usuwa zakonczone taski, anuluje je przy stopie i loguje wyjatki taskow.
- Podniesiono wersje dodatku i metadanych aplikacji do `0.7.0`.

## [0.6.0] - 2026-07-01

### Changed

- Przebudowano panel WWW jako responsywny panel administracyjny z boczna/mobilna nawigacja, rozbudowanym dashboardem, widokiem zdarzen, masowymi akcjami monitorow, formularzem typow jako kafelki, podgladem JSON oraz rozszerzona diagnostyka i ustawieniami.
- Timeout monitorow uzywa teraz globalnej wartosci z `Ustawien` jako domyslnej, ale honoruje tez per-monitor `timeout_minutes` albo `timeout_seconds` w konfiguracji monitora.
- Dodano globalny `default_interval_seconds` w ustawieniach jako domyslny interwal nowych monitorow.
- Dodano migracje `SCHEMA_VERSION = 7`, ktora przenosi stare ustawienia interwalu do `default_interval_seconds`.
- Dodano migracje `SCHEMA_VERSION = 8` dla licznikow runtime uzywanych przez ochrone przed flappingiem.
- Dodano limit rownoleglych sprawdzen, diagnostyke schedulera, progi failure/recovery i opoznienie retry.
- Dodano podstawowe testy pytest dla timeoutow, migracji, progow i limitu rownoleglosci oraz workflow GitHub Actions CI.
- Podniesiono wersje dodatku i metadanych aplikacji do `0.6.0`.

## [0.5.5] - 2026-06-30

### Added

- Dodano zgodne endpointy `GET /api/monitors/{id}`, `POST /api/monitors/{id}/enable` i `POST /api/monitors/{id}/disable`.
- Dodano alias typu `www` mapowany na wspolny checker `http_hash`.
- Dodano migracje `SCHEMA_VERSION = 6`, ktora przenosi stare typy `www`/`website` do wspolnego checkera WWW.

### Changed

- Zmieniono etykiety UI na ogolny widok `Monitoring` oraz etykiety typow WWW w formularzu monitorow.
- Przelaczanie monitora w UI korzysta teraz ze wspolnych endpointow enable/disable.
- Podniesiono wersje dodatku i metadanych aplikacji do `0.5.5`.

## [0.5.4] - 2026-06-30

### Added

- Dodano wspolne zrodlo wersji aplikacji w `monitoring_center.__version__`.
- Dodano endpoint `/ready` oraz rozszerzony endpoint `/api/diagnostics/full` z wersja, schematem bazy i statystykami SQLite.
- Dodano pragmy SQLite, bezpieczniejsze transakcje, transakcyjny import monitorow, kopie zapasowa bazy przed migracja oraz indeksy przyspieszajace historie i diagnostyke.
- Dodano `.gitignore`, `.dockerignore`, `.editorconfig` i bazowa konfiguracje narzedzi w `pyproject.toml`.

### Changed

- Ustawiono metadane repozytorium i add-onu na `https://github.com/chmajster/Home-Assistant-Monitoring`.
- Podniesiono wersje dodatku i metadanych aplikacji do `0.5.4`.

## [0.5.3] - 2026-06-30

### Fixed

- Dodano cache busting dla plików frontendu i wyłączono cache głównego HTML, żeby usunięta zakładka „Strony WWW” nie zostawała widoczna po aktualizacji dodatku.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.5.3`.

## [0.5.2] - 2026-06-30

### Changed

- Przeniesiono akcje konkretnego monitoringu z kafelków i wierszy tabeli do widoku szczegółów monitora.
- Dodano wyraźniejszy hover background dla klikalnych kafelków i wierszy monitoringu.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.5.2`.

## [0.5.1] - 2026-06-30

### Changed

- Doprecyzowano etykiety wyszukiwarki w widoku `Monitory`.
- Dodano wyszukiwarkę/przełącznik monitoringu na stronie szczegółów monitora.
- Upewniono się, że kliknięcie kafelka otwiera szczegóły monitoringu, a link celu działa niezależnie.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.5.1`.

## [0.5.0] - 2026-06-30

### Added

- Dodano odświeżony układ panelu administracyjnego z informacją o ostatnim odświeżeniu i pełniejszymi statystykami monitorów.
- Dodano wspólne filtry monitorów: typ, status, grupa, wyszukiwarka, sortowanie oraz tryb kart/tabeli.
- Dodano responsywny widok tabeli monitorów dla większych instalacji.

### Changed

- Usunięto osobną pozycję nawigacji „Strony WWW”; monitory WWW są teraz typem w widoku „Monitory”.
- Uporządkowano akcje kart monitorów w menu „Serwis” i „Więcej”.
- Poprawiono karty monitorów o pola zależne od typu, czytelne adresy, diagnostykę i badge statusów.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.5.0`.

## [0.4.1] - 2026-06-30

### Fixed

- Dodano changelog w katalogu add-onu `monitoring_center/CHANGELOG.md`, którego oczekuje Home Assistant Supervisor.
- Podniesiono wersję dodatku i metadanych aplikacji do `0.4.1`.

## [0.4.0] - 2026-06-30

### Added

- Dodano popupy/toasty sukcesu po operacjach na monitorach i ustawieniach.
- Dodano przełączanie jasnego i ciemnego motywu z zapisem wyboru lokalnie w przeglądarce.
- Dodano sterowanie głównymi akcjami z navbara.
- Dodano możliwość włączania i wyłączania monitorów bez ich usuwania.
- Dodano test monitora bez zapisu z poziomu formularza dodawania/edycji.
- Dodano prezentację daty sprawdzenia i sumy kontrolnej WWW na kartach, w szczegółach monitora, w historii oraz w wyniku testu formularza.
- Dodano endpoint `POST /api/monitors/test`.

### Changed

- Ustawiono domyślny timeout monitorów na 5 minut.
- Ujednolicono konfigurację timeoutów do pól `default_timeout_minutes` i `timeout_minutes`.
- Zmieniono limit pobieranej strony z KB na MB przez pole `max_page_size_mb`.
- Usunięto sztuczne maksymalne limity timeoutów i limitu pobieranej strony tam, gdzie użytkownik podaje własną wartość.
- Zaktualizowano konfigurację dodatku, przykładowe opcje, tłumaczenia i dokumentację do nowych pól timeoutu oraz limitu strony.

### Fixed

- Błędy walidacji/API nie zamykają już formularza monitora.
- Zachowano kompatybilność ze starymi polami `request_timeout_seconds`, `ping_timeout_seconds`, `timeout_seconds` i `max_page_size_kb`.

### Migration

- Dodano migrację konfiguracji do `SCHEMA_VERSION = 4`.
- Istniejące monitory bez pola aktywności pozostają domyślnie aktywne.
- Stare wartości timeoutów i limitów strony są konwertowane do minut oraz MB.

## [0.3.2] - 2026-06-30

### Added

- Dodano jasny motyw jako domyślny oraz przełącznik motywu w UI.
- Dodano filtr i ukrywanie duplikatów URL w sekcji Strony WWW.
- Dodano widok szczegółów monitora WWW z historią odpowiedzi, SLO i snapshotami zmian.

### Fixed

- Dodano blokadę zdublowanych monitorów URL dla typów HTTP/REST.

## [0.3.1] - 2026-06-18

### Fixed

- Removed the Alpine package install layer from the Docker build to avoid APK repository DNS failures.
- Replaced the external `ping` binary dependency with a Python ICMP implementation.
- Moved add-on build base image selection into `Dockerfile` and removed deprecated `build.yaml`.
- Vendored Python wheels so Supervisor can build the add-on without DNS access to PyPI.

## [0.3.0] - 2026-06-18

### Added

- Dodano grupy monitorów:
  - `Sieć domowa`,
  - `Serwery`,
  - `Strony WWW`,
  - `Home Assistant`,
  - `NAS`.
- Dodano zarządzanie grupami z poziomu UI.
- Dodano przypisywanie monitorów do grup.
- Dodano status grupy, liczbę monitorów, liczbę online/offline i osobne statystyki SLO.
- Dodano maintenance mode dla monitora:
  - 30 minut,
  - 2 godziny,
  - ręcznie do wyłączenia.
- Dodano maintenance mode dla grupy z takimi samymi wariantami.
- Dodano wyciszanie eventów Home Assistant podczas aktywnego maintenance mode monitora albo jego grupy.
- Dodano statystyki SLO / uptime dla okien:
  - 24h,
  - 7 dni,
  - 30 dni,
  - 90 dni.
- Dodano metryki SLO:
  - procent uptime,
  - średni czas odpowiedzi,
  - liczba incydentów.
- Dodano endpointy:
  - `GET /api/groups`,
  - `POST /api/groups`,
  - `PUT /api/groups/{group_id}`,
  - `DELETE /api/groups/{group_id}`,
  - `POST /api/groups/{group_id}/maintenance`,
  - `DELETE /api/groups/{group_id}/maintenance`,
  - `POST /api/monitors/{monitor_id}/maintenance`,
  - `DELETE /api/monitors/{monitor_id}/maintenance`,
  - `GET /api/slo`.

### Changed

- Dashboard pokazuje teraz globalne SLO / uptime.
- Eksport konfiguracji obejmuje również grupy monitorów.

## [0.2.0] - 2026-06-18

### Added

- Dodano architekturę pluginową typów monitoringu w `monitoring_center/monitor_types`.
- Dodano endpointy API:
  - `GET /api/monitor-types`,
  - `GET /api/presets`.
- Dodano predefiniowane typy monitoringu:
  - Ping hosta,
  - Port TCP,
  - HTTP/HTTPS status,
  - HTTP/HTTPS hash zawartości,
  - DNS lookup,
  - Certyfikat SSL,
  - REST API,
  - Home Assistant entity monitor,
  - MQTT monitor.
- Dodano gotowe presety:
  - Router - ping gateway,
  - Home Assistant - port 8123,
  - NAS - ping,
  - NAS - SMB 445,
  - SSH server - port 22,
  - Strona WWW - status i hash,
  - SSL domeny - certyfikat HTTPS,
  - DNS domeny - rekord A/AAAA.
- Dodano dynamiczny formularz dodawania monitora w UI, pokazujący pola zależnie od wybranego typu.
- Dodano możliwość skopiowania presetu i dostosowania go przed zapisem.
- Dodano wspólny format szczegółów wyniku w historii:
  - `monitor_id`,
  - `monitor_type`,
  - `status`,
  - `response_time_ms`,
  - `checked_at`,
  - `error_message`,
  - dane specyficzne dla typu monitora.
- Dodano eventy Home Assistant:
  - `monitor_status_changed`,
  - `tcp_port_open`,
  - `tcp_port_closed`,
  - `website_hash_changed`,
  - `ssl_certificate_expiring`,
  - `dns_record_changed`,
  - `rest_api_check_failed`,
  - `ha_entity_state_changed`,
  - `mqtt_monitor_timeout`.
- Dodano sensory zależne od typu monitora:
  - `sensor.<monitor>_tcp_port`,
  - `sensor.<monitor>_last_hash`,
  - `sensor.<monitor>_ssl_days_left`,
  - `sensor.<monitor>_dns_result`.
- Dodano zależności `dnspython` i `paho-mqtt`.

### Changed

- Zmieniono schemat `monitors.type`, aby obsługiwał rozszerzalne typy monitorów zamiast starego ograniczenia `device` / `website`.
- Stare typy są mapowane kompatybilnie:
  - `device` -> `ping_host`,
  - `website` -> `http_hash`.

## [0.1.0] - 2026-06-18

### Added

- Dodano lokalny dodatek Home Assistant **Monitoring Center**.
- Dodano konfigurację repozytorium dodatków Home Assistant w `repository.yaml`.
- Dodano metadane add-onu w `monitoring_center/config.yaml`.
- Dodano obraz kontenera z `Dockerfile`, `build.yaml` i `run.sh`.
- Dodano backend Python/FastAPI z REST API JSON.
- Dodano lokalną bazę SQLite z automatycznymi migracjami.
- Dodano tabele:
  - `monitors`,
  - `monitor_checks`,
  - `website_snapshots`,
  - `settings`,
  - `events`.
- Dodano monitoring urządzeń przez `ping`.
- Dodano wykrywanie statusu urządzeń `online` / `offline`.
- Dodano zapis czasu odpowiedzi ping i utraty pakietów.
- Dodano monitoring stron WWW przez HTTP/HTTPS.
- Dodano zapis kodu HTTP i czasu odpowiedzi strony.
- Dodano wykrywanie zmian zawartości strony przez hash treści.
- Dodano obsługę selektora CSS dla monitoringu fragmentu strony.
- Dodano obsługę ignorowanych regexów dla dynamicznych fragmentów HTML.
- Dodano snapshoty stron WWW oraz diff poprzedniej i aktualnej wersji.
- Dodano scheduler cyklicznych sprawdzeń z osobnym interwałem per monitor.
- Dodano ręczne uruchamianie testu monitora.
- Dodano historię sprawdzeń z filtrami po monitorze, typie, statusie i dacie.
- Dodano retencję danych oraz czyszczenie starej historii.
- Dodano panel WWW z zakładkami:
  - Dashboard,
  - Urządzenia,
  - Strony WWW,
  - Historia,
  - Ustawienia,
  - Diagnostyka.
- Dodano dashboard z licznikami monitorów, stanami, zmianami WWW, awariami i średnim czasem odpowiedzi.
- Dodano import i export konfiguracji monitorów do JSON.
- Dodano publikowanie encji Home Assistant przez lokalne API:
  - `binary_sensor` statusu,
  - sensor czasu odpowiedzi,
  - sensor kodu HTTP,
  - sensor daty ostatniej zmiany,
  - sensor liczby zmian,
  - sensor ostatniego błędu.
- Dodano eventy Home Assistant:
  - `monitor_online`,
  - `monitor_offline`,
  - `website_changed`,
  - `website_error`.
- Dodano stronę diagnostyczną z informacjami o wersji, bazie danych, liczbie monitorów, kolejce zadań, błędach i logach.
- Dodano logowanie aplikacji do pliku z rotacją.
- Dodano walidację IP, hostname i URL.
- Dodano zabezpieczenia SSRF:
  - ograniczenie schematów do HTTP/HTTPS,
  - opcjonalna blokada prywatnych i lokalnych adresów,
  - limit rozmiaru pobieranej strony,
  - timeouty HTTP,
  - brak wykonywania JavaScript.
- Dodano przykładowy plik `options.example.json`.
- Dodano przykłady automatyzacji Home Assistant w `monitoring_center/examples/automations.yaml`.
- Dodano dokumentację instalacji i rozwoju w `README.md`, `monitoring_center/README.md` i `monitoring_center/DOCS.md`.
- Dodano tłumaczenia konfiguracji w `monitoring_center/translations/pl.yaml` i `monitoring_center/translations/en.yaml`.

### Notes

- Pierwsza wersja jest przygotowana jako baza do dalszej rozbudowy o kolejne typy monitorów, np. TCP port, DNS, certyfikat SSL, MQTT i REST API.
- Walidacja runtime wymaga środowiska z Pythonem/Dockerem albo uruchomienia builda dodatku w Home Assistant.
