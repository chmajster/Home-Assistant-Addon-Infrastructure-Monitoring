# Changelog

Wszystkie istotne zmiany w projekcie **Home Assistant Monitoring / Monitoring Center** będą dokumentowane w tym pliku.

Format opiera się na konwencji Keep a Changelog, a wersjonowanie dodatku powinno podążać za SemVer tam, gdzie ma to zastosowanie.

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
