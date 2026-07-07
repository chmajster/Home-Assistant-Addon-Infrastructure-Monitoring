# Monitoring Center

Monitoring Center to lokalny dodatek Home Assistant do wspólnego monitorowania urządzeń, usług i stron WWW. Monitoring WWW jest typem monitora w tym samym widoku `Monitoring`, korzysta z tej samej historii i tych samych akcji co pozostałe monitory. Dodatek działa bez chmury, używa własnej bazy SQLite w `/data` i udostępnia panel przez Ingress w sidebarze Home Assistant.

## Funkcje

- monitorowanie urządzeń po IP albo hostname przez cykliczny ping,
- predefiniowane typy monitorów i presety w UI,
- grupy monitorów z osobnymi statystykami,
- tryb serwisowy dla monitorów i grup,
- SLO / uptime dla 24h, 7 dni, 30 dni i 90 dni,
- monitoring portów TCP, DNS, SSL, REST API, encji Home Assistant i MQTT,
- status online/offline, czas odpowiedzi, utrata pakietów i historia dostępności,
- monitorowanie WWW jako typu monitora przez HTTP/HTTPS, kod HTTP, czas odpowiedzi i hash treści,
- wykrywanie zmian HTML, selektor CSS, ignorowane regexy dla dynamicznych fragmentów,
- historia sprawdzeń z filtrami po monitorze, typie, statusie i dacie,
- retencja danych i czyszczenie starej historii,
- dashboard oraz zakładki Monitory, Grupy, Historia, Ustawienia i Diagnostyka,
- publikowanie encji `binary_sensor` oraz `sensor` do Home Assistant,
- eventy `monitor_online`, `monitor_offline`, `website_changed`, `website_error`,
- eventy typów monitorów, np. `website_hash_changed`, `ssl_certificate_expiring`, `dns_record_changed`,
- import i export konfiguracji monitorów do JSON,
- self-check dodatku z aktywnymi testami schedulera, SQLite, `/data`, Home Assistant API i publikacji HA.

## Nowe typy systemowe i sieciowe

Wszystkie nowe kontrole sa typami monitora w istniejacym systemie pluginow `monitor_types` i pojawiaja sie w tym
samym widoku **Monitoring**. Korzystaja z tej samej historii, statusow, thresholdow, retry, maintenance mode,
eventow Home Assistant i encji HA co ping, TCP, DNS, SSL, REST API, HA entity, MQTT i WWW.

Dodane typy obejmuja `ssh_command`, `docker_container`, `docker_compose_service`, `docker_healthcheck`,
`linux_host`, `disk_usage`, `backup_age`, `backup_file`, `ha_backup`, `ha_health`, `pihole_health`,
`unifi_device`, `unifi_wan`, `snmp_oid`, `snmp_interface`, `ssh_log_regex`, `journald_regex`,
`docker_log_regex`, `file_exists`, `file_age`, `file_hash`, `directory_size` i `directory_file_count`.

Typy oparte o SSH wymagaja `asyncssh`. Sekrety (`password`, `private_key`, `private_key_passphrase`,
`api_token`, `community`) sa maskowane w API, historii i eventach jako `********`. Przy edycji monitora
pozostawienie pustego pola sekretu zachowuje poprzednia wartosc.

Przyklad SSH / Bash:

```json
{
  "type": "ssh_command",
  "name": "Docker service",
  "target": "192.168.1.10:22",
  "interval_seconds": 300,
  "config": {
    "host": "192.168.1.10",
    "port": 22,
    "username": "root",
    "auth_method": "private_key",
    "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----...",
    "command": "systemctl is-active docker",
    "success_exit_codes": [0],
    "warning_exit_codes": [3],
    "error_exit_codes": [1, 2, 4, 5],
    "max_output_chars": 4000,
    "store_output": true
  }
}
```

Kazdy monitor moze miec wspolne pola alertow w `config_json`: `severity`, `cooldown_minutes`,
`notify_on_recovery`, `repeat_every_minutes`, `max_repeats`, `deduplicate_alerts` i `alert_channels`.
Eventy alertowe to `monitor_alert`, `monitor_alert_recovered`, `monitor_alert_suppressed` i
`monitor_alert_repeated`; payload zawiera `severity` i bezpieczne `details`. Obslugiwane kanaly to
`home_assistant_event`, `persistent_notification` i opcjonalny `webhook` z polem `webhook_url`.

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

## Discovery monitorow

W widoku **Monitoring** przycisk **Wykryj monitory** uruchamia skan propozycji. Discovery nigdy nie tworzy
monitorow automatycznie: wyniki trafiaja do modala, gdzie mozna zaznaczyc wybrane pozycje, oznaczone
duplikaty odznaczyc oraz edytowac nazwe, typ, target i grupe przed importem.

Dostepne zrodla:

- **Home Assistant**: encje `binary_sensor`, `sensor`, `device_tracker`, `switch`, `light` i `update`,
- **Siec lokalna**: zakres CIDR podany przez uzytkownika, ping sweep oraz porty `22`, `53`, `80`, `443`,
  `8123`, `1883`, `8080`, `8443`,
- **Docker**: kontenery wykryte przez istniejaca konfiguracje SSH/Docker,
- **UniFi/SNMP**: propozycje dla urzadzen opartych o istniejace konfiguracje UniFi albo SNMP.

API discovery:

- `POST /api/discovery/scan` przyjmuje `sources`, opcjonalne `network_cidr`, `timeout_seconds` i `max_hosts`,
- `POST /api/discovery/import` tworzy tylko monitory przekazane przez UI albo klienta API.

## Mapa topologii

Widok **Topologia** pokazuje lokalna mape zaleznosci urzadzen i uslug, np. `Internet -> router -> switch ->
AP -> NAS / Home Assistant / Pi-hole / IoT`. Dane sa zapisywane lokalnie w SQLite w tabelach
`topology_nodes` i `topology_edges`.

Node moze byc typu `internet`, `router`, `switch`, `ap`, `server`, `iot`, `service` albo `other`. Po przypisaniu
`monitor_id` status node'a wynika z aktualnego statusu monitora; node bez monitora ma status neutralny.
Elementy mozna przeciagac po mapie, laczyc liniami w trybie **Polacz**, a klikniecie node'a z monitorem
otwiera szczegoly tego monitora. Przycisk **Auto-layout** uklada prosta instalacje warstwowo i potrafi
utworzyc startowa mape na podstawie istniejacych monitorow.

API topologii:

- `GET /api/topology`,
- `PUT /api/topology`,
- `POST /api/topology/auto-layout`.

## Dynamiczne progi i anomaly detection

Kazdy monitor moze wlaczyc dynamiczne progi w sekcji **Dynamiczne progi** formularza. System liczy baseline z
historii danego monitora w `monitor_checks`: srednia, mediana, p95 i standard deviation. Anomalia moze podniesc
status do `warning` albo `error`, dodaje event `monitor_anomaly_detected` i zapisuje w `details_json` pola
`baseline`, `current_value`, `anomaly_score` i `anomaly_reason`.

Wspolne pola konfiguracji:

- `anomaly_detection_enabled`,
- `anomaly_window_hours`,
- `anomaly_min_samples`,
- `anomaly_stddev_multiplier`,
- `anomaly_warn_percent_over_baseline`,
- `anomaly_error_percent_over_baseline`.

Obslugiwane metryki to `response_ms`, `packet_loss`, `dns_lookup_ms`, `disk_usage_percent`,
`directory_size_bytes` i `file_count`. Historia przyjmuje filtr statusu `anomaly`, a dashboard pokazuje liczbe
aktywnych anomalii z ostatnich wynikow monitorow.

## Self-check dodatku

Widok **Diagnostyka** zawiera sekcje **Self-check**. Przycisk **Uruchom self-check** wykonuje aktywne testy:
zapis/odczyt SQLite, zapis/odczyt katalogu `/data`, polaczenie z Home Assistant API oraz publikacje testowego
eventu albo encji, gdy odpowiednie opcje sa wlaczone. Wynik kazdego testu jest pokazany osobno i zapisywany jako
event `diagnostics_self_check` z payloadem bez sekretow.

Rozszerzone `GET /api/diagnostics/full` zwraca m.in. uptime procesu, wersje Pythona i dodatku, `schema_version`,
rozmiar SQLite/WAL, liczbe monitorow, checki z ostatnich 24h, sredni czas checkow, bledy schedulera, status HA API,
zapis do `/data`, status pliku logu oraz zuzycie RAM/CPU procesu, jesli system je udostepnia.

Dostepny jest tez typ monitora `monitoring_center_health`. W Diagnostyce przycisk **Utworz monitor health** tworzy
zwykly monitor **Monitoring Center Health**, ktory sprawdza lokalny endpoint diagnostyczny i pozwala monitorowac sam
dodatek tym samym mechanizmem co inne uslugi.

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

## Panel WWW

Nowy panel administracyjny ma zakladki **Dashboard**, **Monitoring**, **Grupy**, **Historia**, **Zdarzenia**,
**Ustawienia** i **Diagnostyka**. Widok **Monitoring** laczy wszystkie typy monitorow w jednym miejscu:
urzadzenia, TCP, DNS, SSL, REST, encje Home Assistant, MQTT oraz monitoring WWW. Strony WWW nie sa osobna
glowna sekcja - sa filtrowane jako typy `http_status`, `http_hash` i `rest_api`.

Panel obsluguje widok kart/tabeli, filtry, sortowanie, masowe akcje, maintenance mode, test monitora przed
zapisem, import/export JSON, motyw jasny/ciemny/auto oraz responsywna nawigacje dla Home Assistant Ingress.

## Konfiguracja

Opcje startowe są w `config.yaml`, a przykładowy plik znajduje się w `options.example.json`. Monitorami zarządza się z poziomu UI dodatku.

Najważniejsze opcje:

- `retention_days` - retencja historii,
- `default_interval_seconds` - domyślny interwał nowych monitorów w sekundach,
- `default_timeout_minutes` - domyślny timeout monitorów w minutach,
- `max_concurrent_checks` - limit równoległych sprawdzeń,
- `failure_threshold` - liczba kolejnych błędów wymagana do statusu awaryjnego,
- `recovery_threshold` - liczba kolejnych sukcesów wymagana do powrotu online,
- `retry_delay_seconds` - szybszy ponowny check podczas potwierdzania zmiany statusu,
- `max_page_size_mb` - limit pobieranej strony w MB,
- `block_private_networks` - ochrona SSRF dla monitoringu URL,
- `publish_home_assistant_entities` - publikacja encji,
- `publish_home_assistant_events` - publikacja eventów.

## Automatyzacje

Przykłady automatyzacji znajdują się w `examples/automations.yaml`.

## Grupy Monitorów

Dodatek tworzy domyślne grupy:

- `Sieć domowa`,
- `Serwery`,
- `Strony WWW`,
- `Home Assistant`,
- `NAS`.

Monitor można przypisać do grupy przy tworzeniu lub edycji. Grupa pokazuje status zbiorczy, liczbę monitorów, liczbę online/offline oraz własne statystyki SLO.

## Maintenance Mode

Tryb serwisowy można włączyć dla pojedynczego monitora albo całej grupy. Dostępne warianty w UI:

- 30 minut,
- 2 godziny,
- ręcznie do wyłączenia.

Podczas aktywnego maintenance mode sprawdzenia nadal są wykonywane i zapisywane w historii, ale eventy Home Assistant są wyciszone. Dzięki temu planowany restart NAS-a albo aktualizacja routera nie generuje fałszywych powiadomień.

## SLO / Uptime

Dashboard i karty grup pokazują statystyki dla okien:

- 24h,
- 7 dni,
- 30 dni,
- 90 dni.

Metryki obejmują:

- procent uptime,
- średni czas odpowiedzi,
- liczbę incydentów.

Incydent jest liczony, gdy monitor przechodzi ze stanu poprawnego lub `unknown` do stanu awaryjnego, np. `offline`, `error`, `closed` albo `timeout`.

## Przykłady Typów Monitorów

Ping hosta:

```json
{
  "type": "ping_host",
  "name": "Router",
  "target": "192.168.1.1",
  "interval_seconds": 60,
  "config": {}
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
    "port": 8123
  }
}
```

Monitor WWW - status i hash:

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
    "max_page_size_mb": 5
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
    "error_days": 7
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
    "alert_states": ["unavailable", "unknown", "off"]
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
