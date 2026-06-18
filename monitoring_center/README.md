# Monitoring Center

Monitoring Center to lokalny dodatek Home Assistant do monitorowania urządzeń w sieci i stron WWW. Działa bez chmury, używa własnej bazy SQLite w `/data` i udostępnia panel przez Ingress w sidebarze Home Assistant.

## Funkcje

- monitorowanie urządzeń po IP albo hostname przez cykliczny ping,
- status online/offline, czas odpowiedzi, utrata pakietów i historia dostępności,
- monitorowanie URL przez HTTP/HTTPS, kod HTTP, czas odpowiedzi i hash treści,
- wykrywanie zmian HTML, selektor CSS, ignorowane regexy dla dynamicznych fragmentów,
- historia sprawdzeń z filtrami po monitorze, typie, statusie i dacie,
- retencja danych i czyszczenie starej historii,
- dashboard, zakładki Urządzenia, Strony WWW, Historia, Ustawienia i Diagnostyka,
- publikowanie encji `binary_sensor` oraz `sensor` do Home Assistant,
- eventy `monitor_online`, `monitor_offline`, `website_changed`, `website_error`,
- import i export konfiguracji monitorów do JSON.

## Encje Home Assistant

Jeżeli opcja `publish_home_assistant_entities` jest włączona, dodatek publikuje stany przez lokalne API Home Assistant:

- `binary_sensor.<prefix>_<id>_<name>_status`,
- `sensor.<prefix>_<id>_<name>_response_time`,
- `sensor.<prefix>_<id>_<name>_last_error`,
- dla stron WWW także `sensor.<prefix>_<id>_<name>_http_status`,
- dla stron WWW także `sensor.<prefix>_<id>_<name>_last_change`.

Domyślny prefix to `monitoring_center`.

## Bezpieczeństwo

Dodatek pobiera wyłącznie HTTP/HTTPS i nie wykonuje JavaScript. Limit rozmiaru strony, timeouty oraz blokada prywatnych adresów dla URL są konfigurowalne. Po włączeniu `block_private_networks` adres URL nie może rozwiązywać się do zakresów lokalnych, prywatnych, link-local, multicast, reserved ani unspecified.

## Dane

SQLite jest przechowywany domyślnie w `/data/monitoring_center.db`. Schemat zawiera tabele:

- `monitors`,
- `monitor_checks`,
- `website_snapshots`,
- `settings`,
- `events`.

Migracje są wykonywane automatycznie przy starcie.

## Instalacja

1. Skopiuj repozytorium do lokalnego źródła dodatków Home Assistant albo dodaj je jako repozytorium dodatków.
2. W Home Assistant przejdź do **Settings -> Add-ons -> Add-on Store**.
3. Wybierz repozytorium lokalne i zainstaluj **Monitoring Center**.
4. Uruchom dodatek.
5. Otwórz panel z sidebaru albo przyciskiem **Open Web UI**.

## Konfiguracja

Opcje startowe są w `config.yaml`, a przykładowy plik znajduje się w `options.example.json`. Monitorami zarządza się z poziomu UI dodatku.

Najważniejsze opcje:

- `retention_days` - retencja historii,
- `default_device_interval` - domyślny interwał ping,
- `default_website_interval` - domyślny interwał HTTP,
- `request_timeout_seconds` - timeout HTTP,
- `ping_timeout_seconds` - timeout ping,
- `max_page_size_kb` - limit pobieranej strony,
- `block_private_networks` - ochrona SSRF dla monitoringu URL,
- `publish_home_assistant_entities` - publikacja encji,
- `publish_home_assistant_events` - publikacja eventów.

## Automatyzacje

Przykłady automatyzacji znajdują się w `examples/automations.yaml`.

## Rozwój

Kod jest podzielony modułowo:

- `monitoring_center/main.py` - API i serwowanie UI,
- `monitoring_center/monitoring.py` - scheduler oraz logika ping/HTTP,
- `monitoring_center/database.py` - dostęp do SQLite,
- `monitoring_center/migrations.py` - migracje schematu,
- `monitoring_center/ha.py` - publikacja encji i eventów HA,
- `monitoring_center/validators.py` - walidacja wejścia i ochrona SSRF.

Architektura pozwala później dopisać kolejne typy monitorów, np. TCP port, DNS, certyfikat SSL, MQTT lub REST API.
