"""Baut eine kleine EPG-Datei nur mit den Sendern aus kanaele.txt.

Laedt alle Quellen, behaelt nur die gesuchten Kanaele und schreibt
public/epg.xml.gz. Laeuft taeglich per GitHub Actions.
"""
import gzip
import lzma
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET

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
    "https://www.open-epg.com/files/unitedkingdom1.xml.gz",
    "iptvorg.xml",  # lokal im Bau erzeugt aus iptvorg.channels.xml
]


def oeffnen(pfad):
    with open(pfad, "rb") as f:
        kopf = f.read(6)
    if kopf.startswith(b"\x1f\x8b"):
        return gzip.open(pfad, "rb")
    if kopf.startswith(b"\xfd7zXZ"):
        return lzma.open(pfad, "rb")
    return open(pfad, "rb")


def main():
    with open("kanaele.txt", encoding="utf-8") as f:
        gesucht = {z.strip() for z in f if z.strip()}

    kanaele, programme, gefunden = {}, [], set()
    for url in QUELLEN:
        lokal = not url.startswith("http")
        pfad = url if lokal else "quelle.tmp"
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
                            programme.append(ET.tostring(el, encoding="unicode"))
                            gefunden.add(cid)
                        el.clear()
            print(f"ok   {url}")
        except Exception as e:  # eine kaputte Quelle soll den Rest nicht verhindern
            print(f"FEHLER {url}: {e}")
        finally:
            if not lokal and os.path.exists(pfad):
                os.remove(pfad)

    fehlen = sorted(gesucht - gefunden)
    print(f"{len(gefunden)} von {len(gesucht)} Kanaelen mit Programm, {len(programme)} Sendungen")
    if fehlen:
        print("ohne Programm: " + ", ".join(fehlen))
    if len(gefunden) < len(gesucht) * 0.5:
        sys.exit("Zu wenige Kanaele gefunden, alte Datei bleibt.")

    os.makedirs("public", exist_ok=True)
    with gzip.open("public/epg.xml.gz", "wt", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="Jan EPG">\n')
        for k in kanaele.values():
            out.write(k.strip() + "\n")
        for p in programme:
            out.write(p.strip() + "\n")
        out.write("</tv>\n")


if __name__ == "__main__":
    main()
