# Befundbericht H6630 – Stand 2026-11-21

Getrennt nach **beobachteten Fakten**, **aus Quellen abgeleiteten Vermutungen** und **offenen Fragen**.
Negative Ergebnisse bedeuten „nicht beobachtet", nicht „unmöglich".

## 1. Am echten H6630 bestätigt (beobachtet)

Gerät: `Govee_H6630_0F99`, BLE `CC:B8:5E:BE:0F:99`, Pact `1,2`, Werbung meldet **`encrypted=false`**.

| Was | Befehl | Antwort vom Gerät | Ergebnis |
|---|---|---|---|
| Firmware (soft) | `aa 06` | `1.00.45` | quittiert ✅ |
| Hardware (hard) | `aa 07 03` | `5.01.00` | quittiert ✅ |
| WLAN-Firmware | `aa 21` | `1.00.45` | quittiert ✅ |
| WLAN-Hardware | `aa 20` | `5.01.00` | quittiert ✅ |
| WLAN-MAC | `aa 14` | `CC:B8:5E:B3:F2:37` | quittiert ✅ |
| Ein/Aus-Status | `aa 01` | `on=true` | quittiert ✅ |
| Helligkeit | `aa 04` | `level=50` | quittiert ✅ |
| **Einschalten** | `33 01 01` | `33 01 00` (ok) | quittiert ✅ |
| **Ausschalten** | `33 01 00` | `33 01 00` (ok) + Push `ee 30 0f` | quittiert ✅ |
| **Helligkeit setzen** | `33 04 NN` | `33 04 00` (ok) | quittiert ✅ (20 % und 50 % getestet) |

**Wichtigste neue Erkenntnisse gegenüber dem Ausgangsstand:**

1. **Der Kanal ist unverschlüsselt (plaintext).** Der frühere „handshake timed out" entstand, weil das alte
   Skript pauschal den AES-RC4-Handshake erzwang. Die Werbung des Geräts meldet `encrypted=false`; ohne
   Handshake (reiner Klartext) antwortet das Gerät sofort. Dadurch sind **alle** obigen Lesebefehle lesbar –
   auch die zuvor „nur ein Byte"-Reads waren in Wahrheit Klartext-Frames, nur falsch interpretiert.
2. **Firmware-Version ist per BLE direkt abrufbar:** `1.00.45` (passt zur Govee-Home-Anzeige), Hardware `5.01.00`.
3. **Ein/Aus ist jetzt bestätigt** (vorher nur implementiert): beide Richtungen werden mit `status=ok` quittiert;
   das Ausschalten löst zusätzlich einen Geräte-Push `ee 30` aus (Schalt-/Zonen-Push, Payload noch nicht modelliert).
4. **Gerät im LAN lokalisiert:** WLAN-MAC `CC:B8:5E:B3:F2:37` → per ARP **192.168.178.115** (antwortet auf Ping).
5. **Offener TCP-Port 23 (Telnet):** Das Gerät zeigt einen `Govee login:`-Prompt. **Es wurde kein Login-Versuch,
   kein Brute-Force und keine Eingabe gesendet** – nur das Banner gelesen. Das ist ein Diagnose-/Service-Zugang,
   dessen Zweck unbekannt ist.

> Hinweis zur sichtbaren Wirkung: Die Quittungen (`status=ok`) sind bestätigt. Die *optische* Wirkung von
> Ein/Aus und Helligkeit am Display bitte beim nächsten Lauf kurz gegenprüfen und im Protokoll vermerken.

## 2. Aus Quellen abgeleitet (Vermutung, nicht am Gerät bewiesen)

Quellen: Bibliothek `govee-ble-local 1.10.0` (aus der Govee-App dekompiliert, teils hardwaregeprüft) und die
lesbaren Ressourcen/Strings des APK `GoveeHome_V7.7.21.apk`.

- **H6630-Profil (govee-ble-local, goodsType 285):** Capabilities nur `power` + `brightness`,
  `session: per_command` (jede App-Karte baut pro Befehl eine eigene BLE-Sitzung auf), `encryption:
  secret_key_pairing` im Profil – am Gerät verhält es sich jedoch als **plaintext** (siehe oben; das Profil
  beschreibt den verschlüsselten Fall, der hier nicht greift). `account_lock: false`, Helligkeit 1–100,
  IC-Zahl 1024 (= 32×32 Matrix). Scene-Dialekt „untraced".
- **Zeit/Zeitzone:** Die App sendet `33 09` (`datetime_epoch`) als Verbindungs-Zeit-Sync. Enthält lokale
  Wanduhr + Zeitzone (aus der **Telefon-Zeitzone**, `TimeZoneUtil.getTimeOffset`). Das erklärt, warum die
  iPhone-Zeitzonenänderung die Geräteuhr nicht stellte, solange die App sich nicht neu verband.
- **Auto-Upgrade:** Nur als UI-Text belegt („Automatisches OTA-Upgrade 02:00–06:00"). Ein BLE/LAN-Befehl zum
  **Steuern** des Zeitfensters ist in der Bibliothek nicht vorhanden.
- **LAN-Steuerung:** Strings bestätigen die dokumentierte LAN-API (UDP, „local API, Govee Desktop, Razer
  Chroma"). Freischaltung erfolgt laut App über den LAN-Schalter; ein von diesem Schalter unabhängiger
  Freischaltbefehl ist in den lesbaren Quellen nicht belegt.
- **Pixel-Ausgabe (32×32):** Belegt sind Graffiti/DIY/GIF/WatchFace-Funktionen und Upload-Mechanismen (`0xA3`
  Scene-Upload in der Bibliothek). Ein *fertiger* Streaming-Pfad für beliebige Pixelbilder ist für den H6630
  aber **„untraced"** (nicht nachgebaut) – d. h. nicht einsatzbereit belegt.

## 3. Offene Fragen (ehrlich: ungelöst)

| Frage | Stand |
|---|---|
| Befehl zum **Prüfen/Starten** eines Firmware-Updates | Kein BLE/LAN-Befehl in den Quellen gefunden. Versionen sind lesbar (`aa 06`), ein Update-Trigger nicht. |
| **Auto-Upgrade** direkt steuerbar? | Nur UI-Text, kein Steuerbefehl belegt. |
| Wie werden **Gerätezeit/Zeitzone** synchronisiert? | Hypothese `33 09` (s. o.). Als Experiment in der Software vorhanden, am H6630 **noch nicht gesendet/geprüft**. |
| **LAN unabhängig vom App-Schalter** aktivierbar? | Nicht belegt. LAN-API antwortete nicht (s. u.). |
| **Streaming/Upload** eigener Pixelbilder/Texte | Für H6630 „untraced"; Mechanismus existiert (`0xA3`), Dialekt für dieses Modell nicht nachgebaut. |

### LAN-API: aktueller Negativbefund
Multicast-Scan (auf allen Schnittstellen) und Unicast an `192.168.178.115:4001` sowie `devStatus` an `:4003`
brachten **keine Antwort**, obwohl das Gerät auf Ping antwortet und Port 23 offen ist. Gegenprobe mit zwei
anderen Govee-Geräten im Netz: ebenfalls keine Antwort. Wahrscheinlichste Ursache (nicht bewiesen): LAN-Steuerung
ist an den Geräten nicht aktiv (beim H6630 verlangt die App dafür das Firmware-Update), oder eine
eingehende-UDP-Blockade. Das ist **kein Beweis**, dass LAN nicht geht.

### APK-Analyse: Einschränkung
Die `classes.dex` ist mit **virbox StubApp** gepackt; jadx konnte nur den Packer-Stub und `R.java` dekompilieren,
nicht die eigentliche Protokolllogik (die liegt verschlüsselt in `libl68ae1757.so` und wird erst zur Laufzeit
geladen). Statische Dekompilierung des App-Codes aus diesem APK ist damit nicht möglich. Die belastbare
Protokollquelle ist deshalb `govee-ble-local` plus die Live-Reads am Gerät. Die Android-App ist zudem kein
Beweis für identisches Verhalten der iPhone-App.

## 4. Nächste evidenzbasierte Schritte

1. **Sichtbare Wirkung** von Ein/Aus + Helligkeit am Display gegenprüfen (Quittung ist bestätigt, Optik noch nicht vermerkt).
2. **Zeit-Sync-Experiment** `33 09` einmalig senden (Reiter „Experimente", mit Bestätigung) und beobachten, ob
   die Geräteuhr/Anzeige folgt → klärt die Zeitquelle.
3. **Push `ee 30`** beim Schalten gezielt mitschneiden und Payload entschlüsseln (Zonen-/Schaltzustand).
4. **LAN** erneut testen, sobald die LAN-Steuerung in der App aktiv ist (ggf. nach Firmware-Update).
5. **Cloud-Capabilities** mit einem Developer-API-Key abfragen (Reiter „Cloud") – zeigt, was Govee offiziell für
   den H6630 anbietet, ohne Funktionen zu erfinden.
6. Für **Pixel-Streaming**: den `0xA3`-Upload-Dialekt des H6630 erst aus einem echten App-Mitschnitt (btsnoop
   HCI-Log vom Android-Gerät) belegen, bevor etwas gesendet wird. Kein blindes Schreiben.

Discord-Integration erst, wenn ein bestätigter Pixel-Ausgabekanal existiert (aktuell: nur Ein/Aus + Helligkeit bestätigt).

## 5. Pixel-Streaming (Ziel: Spotify + Discord aufs Display)

**Stand: Es gibt noch keinen bestätigten Weg, eigene Pixel aufs H6630 zu schreiben.** Belegt sind nur Ein/Aus
und Helligkeit. Recherche-Ergebnis:

- **govee-ble-local** modelliert nur Strip-/Bar-Uploads (H60A6, H6052, Bulbs). Für den H6630 ist der
  Szenen-/Pixel-Dialekt ausdrücklich **„untraced"** – die Bibliothek kann also keine Pixelbilder bauen.
- Das Pixel-Display nutzt die Upload-Transporte **0xA3 / 0xA4** (Multi-Paket). Das *Rahmenformat* ist bekannt
  und im Werkzeug implementiert (Zusammensetzen/Zerlegen). Unbekannt ist der **Inhalt** (`value`): wie ein
  32×32-Bild, Text oder eine Animation kodiert wird (Palette, Layer, comm_byte).
- **pixeld** (Ersatz-Firmware) existiert, aber nur für das **H6631** (52×32), per Gehäuseöffnen + Serial-Flash,
  mit Brick-Risiko. Für den H6630 **nicht** verfügbar – und Firmware-Flashen ist hier ohnehin ausgeschlossen.
  Repos: `github.com/SamWiIIiams/pixeld-h6631`, `.../pixel2mqtt`.
- Das Gerät hat einen offenen **Telnet-Port (23, „Govee login:")** – Service-Zugang unbekannten Zwecks, nicht
  angetastet.

**Regelkonformer Weg zum Ziel (ohne blindes Schreiben, ohne Firmware):**
1. Einmal einen **Android-BLE-Mitschnitt** aufnehmen: Entwickleroptionen → „Bluetooth-HCI-Snoop-Log" an, im
   Govee-Home ein Bild/Text/GIF aufs Display schicken, `btsnoop_hci.log` exportieren.
2. `govee_lab btsnoop <log>` zerlegt den Mitschnitt (nur lesen) und rekonstruiert die 0xA3/0xA4-`value`-Ströme
   → damit wird das echte Pixelformat des H6630 belegt.
3. Erst dann einen **Spotify**- (Now-Playing/Cover) und **Discord**- (Sprachkanal/Sprecher) Renderer bauen, der
   32×32-Frames erzeugt und über den belegten Kanal sendet.

Ohne Schritt 1 lässt sich Schritt 3 nur erraten – das wäre blindes Schreiben und ist ausgeschlossen.
Alternative, falls kein Android-Gerät vorhanden: Hardware-BLE-Sniffer (nRF52840 + Wireshark) oder iPhone-Mitschnitt
über macOS PacketLogger; beide liefern denselben `value`-Strom für das Werkzeug.

### BEFUND (2026-11-21): Die Pixel laufen NICHT über Bluetooth

Ein iPhone-BLE-Mitschnitt (sysdiagnose → `bluetoothd-hci-latest.pklg`, ~10-Minuten-Fenster) wurde ausgewertet,
während im Govee-Home nacheinander Rot/Grün/Text/Bild aufs Display geschickt wurden. Ergebnis mit `govee_lab
capture`: 49 ATT-Pakete, aber **0 Govee-Frames** – kein `aa`/`33`/`a3`/`a4` im gesamten Mitschnitt, auch roh
nicht. Die einzigen BLE-Writes waren Standard-GATT (Notification-Enable `0200` u. Ä.).

**Schlussfolgerung (belegt):** Der H6630 ist ein reines Netzwerkgerät (App-Text: „This product only supports
network use"). Bluetooth überträgt nur Einrichtung + An/Aus + Helligkeit. **Die DIY-/Pixel-/Bilddaten gehen
über WLAN** – entweder Govee-Cloud (IoT/MQTT, was die App nutzt) oder die lokale LAN-API, wenn aktiviert.
Ein BLE-Mitschnitt kann das Pixelformat daher prinzipiell nicht zeigen.

**Folgen für Spotify/Discord aufs Display:**
- BLE-Pixel-Weg ist damit **ausgeschlossen** (nicht nur unbelegt – widerlegt).
- Verbleibende Wege, alle schwieriger:
  1. **Govee-Cloud/IoT** (WLAN) reversen – die App-Methode. Braucht WLAN-/HTTPS-Mitschnitt; der frühere
     Fiddler-Versuch scheiterte vermutlich an Certificate-Pinning. Konto-/verschlüsselungsgebunden.
  2. **Lokale LAN-API** – nur lokal, aber (a) LAN-Steuerung am Gerät nötig (hängt am blockierten Firmware-Update)
     und (b) DIY-Bild-Format über LAN ist überall ungelöst.
  3. **Offizielle Govee-Developer-API** – bietet für den H6630 nur Power/Helligkeit/Szenen, keine freien Pixel
     (mit API-Key im Reiter „Cloud" verifizierbar).
- Firmware-Ersatz (pixeld) nur für H6631, hier ausgeschlossen.

Der iPhone-Mitschnitt war trotzdem nützlich: Er hat den BLE-Weg **definitiv ausgeschlossen** und zeigt, dass der
nächste Schritt auf der **WLAN-/Cloud-Seite** liegen muss.
