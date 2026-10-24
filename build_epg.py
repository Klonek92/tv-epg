"""Baut eine kleine EPG-Datei nur mit den Sendern aus kanaele.txt.

Laedt alle Quellen, behaelt nur die gesuchten Kanaele und schreibt
public/epg.xml.gz. Laeuft taeglich per GitHub Actions.

- Bereits gelaufene Sendungen fliegen raus.
- Liefern mehrere Quellen denselben Sender, gewinnt die Quelle, deren
  Programm am weitesten in die Zukunft reicht (keine doppelten Sendungen).
- Ist eine Quelle kaputt oder veraltet, landet ein Hinweis in
  warnungen.txt. Der Workflow markiert den Lauf dann nach dem
  Veroeffentlichen als fehlgeschlagen, damit GitHub eine Mail schickt.
"""
import gzip
import lzma
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

QUELLEN = [
    "https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_AT1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_US_LOCALS1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_BEIN1.xml.gz",
    "http://www.xmltvepg.nl/rytecDE_Basic.xz",
    "http://www.xmltvepg.nl/rytecUK_SportMovies.xz",
    "iptvorg.xml",  # lokal im Bau erzeugt aus iptvorg.channels.xml (US/UK/CA-Ersatz)
]

# Eine Quelle gilt als veraltet, wenn ihr Programm nicht mindestens
# so weit in die Zukunft reicht.
MINDEST_VORLAUF = timedelta(hours=12)
WARNDATEI = "warnungen.txt"


def zeit(text):
    """XMLTV-Zeit wie '20261024053000 +0200' in UTC umwandeln."""
    if not text:
        return None
    teile = text.strip().split()
    try:
        t = datetime.strptime(teile[0][:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    versatz = timedelta()
    if len(teile) > 1 and len(teile[1]) == 5 and teile[1][0] in "+-":
        v = teile[1]
        versatz = timedelta(hours=int(v[1:3]), minutes=int(v[3:5]))
        if v[0] == "-":
            versatz = -versatz
    return (t - versatz).replace(tzinfo=timezone.utc)


def oeffnen(pfad):
    with open(pfad, "rb") as f:
        kopf = f.read(6)
    if kopf.startswith(b"\x1f\x8b"):
        return gzip.open(pfad, "rb")
    if kopf.startswith(b"\xfd7zXZ"):
        return lzma.open(pfad, "rb")
    return open(pfad, "rb")


BERICHT = []


def melden(text):
    """Ausgabe ins Log und in public/status.txt (im Browser lesbar)."""
    print(text)
    BERICHT.append(text)


def main():
    jetzt = datetime.now(timezone.utc)
    melden("Stand: " + jetzt.strftime("%d.%m.%Y %H:%M UTC"))
    with open("kanaele.txt", encoding="utf-8") as f:
        gesucht = {z.strip() for z in f if z.strip()}

    kanaele = {}
    # je Kanal: Quelle -> (Liste der Sendungen, spaetestes Ende)
    je_kanal = {}
    warnungen = []

    for url in QUELLEN:
        lokal = not url.startswith("http")
        pfad = url if lokal else "quelle.tmp"
        treffer, aktuell, ende_max = 0, 0, None
        try:
            if not lokal:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=300) as r, open(pfad, "wb") as out:
                    out.write(r.read())
            with oeffnen(pfad) as f:
                for _, el in ET.iterparse(f, events=("end",)):
                    if el.tag == "channel":
                        cid = el.get("id")
                        if cid in gesucht and cid not in kanaele:
                            kanaele[cid] = ET.tostring(el, encoding="unicode")
                        el.clear()
                    elif el.tag == "programme":
                        cid = el.get("channel")
                        if cid in gesucht:
                            treffer += 1
                            ende = zeit(el.get("stop")) or zeit(el.get("start"))
                            if ende and (ende_max is None or ende > ende_max):
                                ende_max = ende
                            if ende is None or ende > jetzt:
                                aktuell += 1
                                liste, bis = je_kanal.setdefault(cid, {}).get(url, ([], None))
                                liste.append(ET.tostring(el, encoding="unicode"))
                                if ende and (bis is None or ende > bis):
                                    bis = ende
                                je_kanal[cid][url] = (liste, bis)
                        el.clear()
            bis_text = ende_max.strftime("%d.%m. %H:%M UTC") if ende_max else "-"
            melden(f"ok     {url}: {treffer} Sendungen, davon {aktuell} aktuell, Programm bis {bis_text}")
            if treffer and (ende_max is None or ende_max < jetzt + MINDEST_VORLAUF):
                warnungen.append(f"Quelle veraltet (Programm nur bis {bis_text}): {url}")
            if lokal and treffer == 0:
                warnungen.append(f"Quelle leer: {url}")
        except Exception as e:  # eine kaputte Quelle soll den Rest nicht verhindern
            melden(f"FEHLER {url}: {e}")
            warnungen.append(f"Quelle nicht lesbar: {url} ({e})")
        finally:
            if not lokal and os.path.exists(pfad):
                os.remove(pfad)

    # je Kanal die Quelle nehmen, deren Programm am weitesten reicht
    programme = []
    for cid, quellen in je_kanal.items():
        liste, _ = max(
            quellen.values(),
            key=lambda q: q[1] or datetime.min.replace(tzinfo=timezone.utc),
        )
        programme.extend(liste)

    gefunden = set(je_kanal)
    fehlen = sorted(gesucht - gefunden)
    melden(f"{len(gefunden)} von {len(gesucht)} Kanaelen mit aktuellem Programm, {len(programme)} Sendungen")
    for land in sorted({k.rsplit(".", 1)[-1] for k in gesucht}):
        alle = [k for k in gesucht if k.rsplit(".", 1)[-1] == land]
        mit = [k for k in alle if k in gefunden]
        melden(f"  .{land}: {len(mit)} von {len(alle)}")
    if fehlen:
        melden("ohne Programm: " + ", ".join(fehlen))
    for w in warnungen:
        melden("WARNUNG " + w)

    if warnungen:
        with open(WARNDATEI, "w", encoding="utf-8") as f:
            f.write("\n".join(warnungen) + "\n")
            if fehlen:
                f.write("Kanaele ohne aktuelles Programm: " + ", ".join(fehlen) + "\n")
        for w in warnungen:
            print(f"::warning::{w}")

    if len(gefunden) < len(gesucht) * 0.5:
        sys.exit("Zu wenige Kanaele gefunden, alte Datei bleibt.")

    os.makedirs("public", exist_ok=True)
    with open("public/status.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(BERICHT) + "\n")
    with gzip.open("public/epg.xml.gz", "wt", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="Jan EPG">\n')
        for k in kanaele.values():
            out.write(k.strip() + "\n")
        for p in programme:
            out.write(p.strip() + "\n")
        out.write("</tv>\n")


if __name__ == "__main__":
    main()
