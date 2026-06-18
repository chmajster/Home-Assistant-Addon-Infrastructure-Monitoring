# Monitoring Center

Monitoring Center to lokalny dodatek Home Assistant do monitorowania urządzeń w sieci i stron WWW. Działa bez chmury, używa własnej bazy SQLite w `/data` i udostępnia panel przez Ingress w sidebarze Home Assistant.

## Funkcje

- monitorowanie urządzeń po IP albo hostname przez cykliczny ping,
- predefiniowane typy monitorów i presety w UI,
- monitoring portów TCP, DNS, SSL, REST API, encji Home Assistant i MQTT,
- status online/offline, czas odpowiedzi, utrata pakietów i historia dostępności,
- monitorowanie URL przez HTTP/HTTPS, kod HTTP, czas odpowiedzi i hash treści,
- wykrywanie zmian HTML, selektor CSS, ignorowane regexy dla dynamicznych fragmentów,
- historia sprawdzeń z filtrami po monitorze, typie, statusie i dacie,
- retencja danych i czyszczenie starej historii,
- dashboard, zakładki Urządzenia, Strony WWW, Historia, Ustawienia i Diagnostyka,
- publikowanie encji `binary_sensor` oraz `sensor` do Home Assistant,
- eventy `monitor_online`, `monitor_offline`, `website_changed`, `website_error`,
- eventy typów monitorów, np. `website_hash_changed`, `ssl_certificate_expiring`, `dns_record_changed`,
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

## Przykłady Typów Monitorów

Ping hosta:

```json
{
  "type": "ping_host",
  "name": "Router",
  "target": "192.168.1.1",
  "interval_seconds": 60,
  "config": {
    "timeout_seconds": 3
  }
}
```

Port TCP:

```json
{
  "type": "tcp_port",
  "name": "Home Assistant 8123",
  "target": "192.168.1.40:8123",
  "interval_seconds": 60,
  "config": {
    "host": "192.168.1.40",
    "port": 8123,
    "timeout_seconds": 5
  }
}
```

Hash strony WWW:

```json
{
  "type": "http_hash",
  "name": "Strona WWW",
  "target": "https://example.com",
  "interval_seconds": 300,
  "config": {
    "expected_status_codes": [200],
    "css_selector": "main",
    "ignore_patterns": ["\\\\d{4}-\\\\d{2}-\\\\d{2}"],
    "max_page_size_kb": 512,
    "timeout_seconds": 10
  }
}
```

Certyfikat SSL:

```json
{
  "type": "ssl_certificate",
  "name": "SSL example.com",
  "target": "example.com:443",
  "interval_seconds": 21600,
  "config": {
    "host": "example.com",
    "port": 443,
    "warning_days": 30,
    "error_days": 7,
    "timeout_seconds": 5
  }
}
```

Encja Home Assistant:

```json
{
  "type": "ha_entity",
  "name": "Czujnik salon",
  "target": "sensor.salon_temperature",
  "interval_seconds": 60,
  "config": {
    "alert_states": ["unavailable", "unknown", "off"],
    "timeout_seconds": 5
  }
}
```

## Przykłady Automatyzacji

Zmiana hasha strony:

```yaml
alias: Monitoring Center - hash strony zmieniony
trigger:
  - platform: event
    event_type: website_hash_changed
action:
  - service: persistent_notification.create
    data:
      title: "Zmiana strony"
      message: >
        {{ trigger.event.data.monitor_name }} zmieniła hash.
        Poprzedni: {{ trigger.event.data.details.previous_hash }},
        aktualny: {{ trigger.event.data.details.current_hash }}.
```

Wygasający certyfikat SSL:

```yaml
alias: Monitoring Center - SSL wygasa
trigger:
  - platform: event
    event_type: ssl_certificate_expiring
action:
  - service: persistent_notification.create
    data:
      title: "Certyfikat SSL wygasa"
      message: >
        {{ trigger.event.data.monitor_name }} wygasa za
        {{ trigger.event.data.details.days_left }} dni.
```

Niedostępna encja Home Assistant:

```yaml
alias: Monitoring Center - encja niedostępna
trigger:
  - platform: event
    event_type: ha_entity_state_changed
condition:
  - condition: template
    value_template: "{{ trigger.event.data.details.state in ['unavailable', 'unknown', 'off'] }}"
action:
  - service: persistent_notification.create
    data:
      title: "Encja HA w stanie alarmowym"
      message: >
        {{ trigger.event.data.monitor_name }} ma stan
        {{ trigger.event.data.details.state }}.
```

## Rozwój

Kod jest podzielony modułowo:

- `monitoring_center/main.py` - API i serwowanie UI,
- `monitoring_center/monitoring.py` - scheduler, zapis historii i eventy,
- `monitoring_center/monitor_types/` - pluginy typów monitoringu,
- `monitoring_center/database.py` - dostęp do SQLite,
- `monitoring_center/migrations.py` - migracje schematu,
- `monitoring_center/ha.py` - publikacja encji i eventów HA,
- `monitoring_center/validators.py` - walidacja wejścia i ochrona SSRF.

Architektura pozwala później dopisać kolejne typy monitorów, np. TCP port, DNS, certyfikat SSL, MQTT lub REST API.
