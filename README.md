# Home Assistant Monitoring

Aktualna wersja: **0.12.0**. Repozytorium: https://github.com/chmajster/Home-Assistant-Addon-Infrastructure-Monitoring

Aktualizacja z 0.11.0 jest migracją in-place. Przy pierwszym starcie powstaje spójny backup SQLite,
wykonywane są migracje 11–14 i jednorazowe szyfrowanie sekretów. Zachowaj razem bazę oraz plik klucza z `/data`.

Repozytorium lokalnego dodatku Home Assistant **Monitoring Center**.

Dodatek znajduje się w katalogu [monitoring_center](monitoring_center). Zawiera backend Python/FastAPI, panel WWW, SQLite z migracjami, przykładową konfigurację i przykłady automatyzacji Home Assistant.

Szybki start:

1. Dodaj to repozytorium jako lokalne repozytorium dodatków w Home Assistant.
2. Zainstaluj dodatek **Monitoring Center**.
3. Uruchom dodatek i otwórz panel z sidebaru.

Pełna dokumentacja: [monitoring_center/README.md](monitoring_center/README.md).

Nowe typy monitorow sa dodawane w istniejacym widoku **Monitoring** jako pluginy `monitor_types`.
Obejmuja m.in. SSH/Bash, Docker, Linux host health, dyski, backupy, Home Assistant health, Pi-hole,
UniFi/SNMP, log regex oraz pliki/katalogi. Nie sa tworzone osobne glowne sekcje dla SSH, Docker ani Backup.

Discovery w widoku **Monitoring** potrafi zaproponowac monitory z encji Home Assistant, zakresu sieci CIDR,
istniejacych hostow Docker oraz konfiguracji UniFi/SNMP. Propozycje nie sa zapisywane automatycznie; wymagaja
zaznaczenia i importu przez uzytkownika.

Widok **Topologia** pokazuje lokalna mape zaleznosci urzadzen i uslug. Node'y moga byc powiazane z monitorami,
dziedzicza ich status, mozna je przeciagac, laczyc liniami i zapisac uklad w SQLite.

Dynamiczne progi/anomaly detection licza baseline z historii monitora i wykrywaja nietypowe wzrosty czasu
odpowiedzi, packet loss, DNS latency, uzycia dysku, rozmiaru katalogu oraz liczby plikow.

Diagnostyka zawiera Self-check dodatku: aktywne testy SQLite, zapisu do `/data`, Home Assistant API,
publikacji HA oraz monitor typu `monitoring_center_health` do monitorowania samego Monitoring Center.

Historia zmian: [CHANGELOG.md](CHANGELOG.md).
