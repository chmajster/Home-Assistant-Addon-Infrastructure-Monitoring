# Monitoring Center - dokumentacja dodatku

Po uruchomieniu dodatek tworzy lokalny serwer na porcie `8099` i publikuje panel przez Home Assistant Ingress. Wszystkie dane trwałe są zapisywane w `/data`.

## Pierwsze uruchomienie

1. Uruchom dodatek w Home Assistant.
2. Otwórz panel **Monitoring Center**.
3. Dodaj urządzenie lub stronę WWW.
4. Zostaw zaznaczoną opcję testu przy zapisie, aby od razu sprawdzić konfigurację.

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
- `website_error`.

Payload zawiera `monitor_id`, `monitor_name`, `monitor_type`, `target`, `previous_state`, `new_state` i `created_at`.

## API

Panel używa lokalnego API JSON:

- `GET /api/summary`,
- `GET /api/monitors`,
- `POST /api/monitors`,
- `PUT /api/monitors/{id}`,
- `DELETE /api/monitors/{id}`,
- `POST /api/monitors/{id}/check`,
- `GET /api/history`,
- `GET /api/settings`,
- `PUT /api/settings`,
- `GET /api/diagnostics`,
- `GET /api/logs`.

## Diagnostyka

Zakładka Diagnostyka pokazuje wersję, status i rozmiar bazy, liczbę monitorów, ostatnie sprawdzenie, kolejkę zadań, aktywne interwały, ostatnie błędy oraz logi aplikacji.
