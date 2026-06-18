# Changelog

Wszystkie istotne zmiany w projekcie **Home Assistant Monitoring / Monitoring Center** będą dokumentowane w tym pliku.

Format opiera się na konwencji Keep a Changelog, a wersjonowanie dodatku powinno podążać za SemVer tam, gdzie ma to zastosowanie.

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
