# Home Assistant Monitoring

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

Historia zmian: [CHANGELOG.md](CHANGELOG.md).
