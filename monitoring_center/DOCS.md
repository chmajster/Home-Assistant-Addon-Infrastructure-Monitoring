# Monitoring Center - dokumentacja dodatku

## Nowy panel WWW

Panel ma sekcje: **Dashboard**, **Monitoring**, **Grupy**, **Historia**, **Zdarzenia**, **Ustawienia**
i **Diagnostyka**. Na desktopie dostepna jest boczna nawigacja, a na telefonie dolna nawigacja.

- **Dashboard** pokazuje KPI, globalny status, SLO, najgorsze monitory, ostatnie incydenty, zmiany WWW
  i certyfikaty SSL blisko wygasniecia.
- **Monitoring** jest glownym widokiem wszystkich monitorow. Monitoring WWW pozostaje typem monitora
  (`http_status`, `http_hash`, `rest_api`) i jest filtrowany w tym samym widoku, bez osobnej glownej zakladki.
- Widok **Monitoring** obsluguje karty i tabele, wyszukiwarke, filtry statusu, typu, grupy, maintenance
  i aktywnosci, sortowanie oraz masowe akcje.
- Kategorie frontendowe sa neutralne wobec starych zakladek: `network`, `website`, `home_assistant`,
  `protocol` i `other`. `website` jest tylko kategoria typu monitora, nie osobnym glownym widokiem.
- Formularz dodawania i edycji monitora jest drawerem z kafelkami typow, presetami, testem przed zapisem
  i podgladem JSON konfiguracji.
- **Historia** ma filtry monitora, grupy, typu, statusu, zakresu dat i szybkie zakresy 1h/24h/7d/30d.
- **Zdarzenia** pokazuja eventy aplikacji i Home Assistant z filtrem typu eventu.
- **Ustawienia** sa podzielone na sekcje: ogolne, retencja, interwaly i timeout, limity WWW,
  SSRF/Home Assistant, motyw i import/export.
- Motyw `auto`, jasny i ciemny oraz gestosc interfejsu sa zapisywane w `localStorage`.

Po uruchomieniu dodatek tworzy lokalny serwer na porcie `8099` i publikuje panel przez Home Assistant Ingress. Wszystkie dane trwałe są zapisywane w `/data`.

## Pierwsze uruchomienie

1. Uruchom dodatek w Home Assistant.
2. Otwórz panel **Monitoring Center**.
3. Dodaj urządzenie lub stronę WWW.
4. Zostaw zaznaczoną opcję testu przy zapisie, aby od razu sprawdzić konfigurację.

## Dane dostępowe

Widok **Dane dostępowe** pozwala utworzyć współdzielony profil login/hasło lub login/klucz prywatny SSH.
Profil wybiera się następnie w formularzu monitora. Login/hasło obsługuje MQTT i monitory SSH, natomiast
klucz prywatny wyłącznie typy SSH. Monitor bez profilu nadal używa danych wpisanych bezpośrednio.

Hasła, klucze i passphrase są przechowywane w `credential_secrets`, szyfrowane AES-256-GCM i nigdy nie są
zwracane przez API ani eksportowane jawnie. Klucz główny `/data/monitoring_center.key` musi być chroniony
i archiwizowany z bazą. Bez niego odzyskanie zaszyfrowanych poświadczeń nie jest możliwe.

## Ignorowanie dynamicznych fragmentów stron

W monitorze WWW można podać:

- selektor CSS, np. `main`, `.content`, `article`,
- regexy ignorowane, po jednym w linii.

Przykłady regexów:

```text
\d{4}-\d{2}-\d{2}
token=[A-Za-z0-9._-]+
Wyświetleń:\s*\d+
```

## Eventy

Dodatek może wysyłać eventy do Home Assistant:

- `monitor_online`,
- `monitor_offline`,
- `website_changed`,
- `website_error`,
- `monitor_status_changed`,
- `tcp_port_open`,
- `tcp_port_closed`,
- `website_hash_changed`,
- `ssl_certificate_expiring`,
- `dns_record_changed`,
- `rest_api_check_failed`,
- `ha_entity_state_changed`,
- `mqtt_monitor_timeout`.

Payload zawiera `monitor_id`, `monitor_name`, `monitor_type`, `target`, `previous_state`, `new_state` i `created_at`.

## API

Panel używa lokalnego API JSON:

- `GET /api/summary`,
- `GET /api/slo`,
- `GET /api/monitors`,
- `GET /api/monitor-types`,
- `GET /api/presets`,
- `GET /api/groups`,
- `POST /api/groups`,
- `PUT /api/groups/{id}`,
- `DELETE /api/groups/{id}`,
- `POST /api/groups/{id}/maintenance`,
- `DELETE /api/groups/{id}/maintenance`,
- `POST /api/monitors`,
- `PUT /api/monitors/{id}`,
- `DELETE /api/monitors/{id}`,
- `POST /api/monitors/{id}/check`,
- `POST /api/monitors/{id}/maintenance`,
- `DELETE /api/monitors/{id}/maintenance`,
- `GET /api/history`,
- `GET /api/settings`,
- `PUT /api/settings`,
- `GET /api/diagnostics`,
- `GET /api/logs`.

## Diagnostyka

Zakładka Diagnostyka pokazuje wersję, status i rozmiar bazy, liczbę monitorów, ostatnie sprawdzenie, kolejkę zadań, aktywne interwały, ostatnie błędy oraz logi aplikacji.
