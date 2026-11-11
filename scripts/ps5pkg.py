#!/usr/bin/env python3
"""
ps5pkg.py - lecteur de packages PS5 (retail ET debug).

Extrait ce qui est lisible SANS AUCUNE CLE :
  - type de package (retail signe / debug non signe / meta)
  - le XML "package-configuration" present en fin de fichier
  - la liste des entrees declaree dans ce XML
  - les metadonnees : param.json, icon0.png, pic0.png, snd0.at9
  - le contenu non chiffre des packages debug

Ne tente JAMAIS de dechiffrer. Pour un package retail, le contenu des
entrees est chiffre par une cle derivee de la console : cet outil le dit
explicitement au lieu de produire des octets faux.

Format etabli en lisant PS5PKGReader (GPL-2.0), voir
docs/reference/ pour la trace.
"""
import os
import re
import sys
import json

MAGIC_META = b"uCNT"
MAGIC_FULL = b"uFIH"

CONFIG_START = b'<package-configuration version="1.0" type="package-info">'
CONFIG_END = b"</package-configuration>"

FLAG_RETAIL = 0x80
FLAG_DEBUG = 0x00


class PkgError(Exception):
    pass


def classify_magic(data):
    if data[:4] == MAGIC_META:
        return "meta"
    if data[:4] == MAGIC_FULL:
        flag = data[5] if len(data) > 5 else None
        if flag == FLAG_RETAIL:
            return "retail"
        if flag == FLAG_DEBUG:
            return "debug"
        return f"complet (drapeau {flag:#x} inconnu)"
    return None


def find_config_xml(data):
    """Le XML est en fin de fichier. Lecture par blocs depuis la fin."""
    end_i = data.rfind(CONFIG_END)
    if end_i < 0:
        return None, None
    start_i = data.rfind(CONFIG_START, 0, end_i)
    if start_i < 0:
        return None, None
    blob = data[start_i:end_i + len(CONFIG_END)]
    try:
        text = blob.decode("utf-8", "replace")
    except Exception:
        return None, None
    return text, (start_i, end_i + len(CONFIG_END))


def parse_config_entries(xml_text):
    """
    Le XML declare les entrees sous la forme :
      <entry><id>..</id><offset>..</offset><size>..</size><name>..</name></entry>
    On reste tolerant : on accepte plusieurs noms de balises.
    """
    entries = []
    for block in re.findall(r"<entry>(.*?)</entry>", xml_text, re.S):
        def grab(*tags):
            for t in tags:
                m = re.search(rf"<{t}>\s*([^<]*?)\s*</{t}>", block)
                if m:
                    return m.group(1)
            return None

        raw_id = grab("id", "entry-id")
        raw_off = grab("offset", "entry-offset", "container-offset")
        raw_size = grab("size", "entry-size")
        name = grab("name", "entry-name", "file")

        def as_int(v):
            if v is None:
                return None
            v = v.strip()
            try:
                return int(v, 0)
            except ValueError:
                try:
                    return int(v)
                except ValueError:
                    return None

        entries.append({
            "id": as_int(raw_id),
            "offset": as_int(raw_off),
            "size": as_int(raw_size),
            "name": name,
            "raw": block.strip(),
        })
    return entries


def get_container_offset(xml_text):
    m = re.search(r"<mount-image[^>]*>(.*?)</mount-image>", xml_text, re.S)
    if not m:
        return None
    inner = m.group(1)
    m2 = re.search(r"<container-offset>\s*([^<]*?)\s*</container-offset>", inner)
    if not m2:
        return None
    v = m2.group(1).strip()
    try:
        return int(v, 0)
    except ValueError:
        return int(v)


class Pkg:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        self.kind = classify_magic(self.data)
        if self.kind is None:
            raise PkgError(
                f"magic inconnu {self.data[:4]!r} : ce n'est pas un PKG PS5 "
                "(attendu 'uCNT' ou 'uFIH')"
            )
        self.xml, self.xml_span = find_config_xml(self.data)
        self.entries = parse_config_entries(self.xml) if self.xml else []
        self.container_offset = get_container_offset(self.xml) if self.xml else None

    def entry_names(self):
        return [e["name"] for e in self.entries if e["name"]]

    def summary(self):
        L = []
        L.append(f"fichier     : {self.path}")
        L.append(f"taille      : {len(self.data):,} octets")
        L.append(f"type        : {self.kind}")
        if self.kind == "retail":
            L.append("contenu     : CHIFFRE (cle derivee de la console)")
        elif self.kind == "debug":
            L.append("contenu     : lisible (package debug)")
        if self.xml_span:
            L.append(f"XML config  : octets {self.xml_span[0]:#x}..{self.xml_span[1]:#x} "
                     f"({self.xml_span[1]-self.xml_span[0]} o)")
        else:
            L.append("XML config  : absent")
        if self.container_offset is not None:
            L.append(f"container   : {self.container_offset:#x}")
        L.append(f"entrees     : {len(self.entries)}")
        if self.entries:
            L.append("")
            L.append(f"{'nom':32s} {'offset':>12s} {'taille':>12s}")
            L.append("-" * 58)
            for e in self.entries:
                nm = (e["name"] or "?")[:32]
                off = f"{e['offset']:#x}" if e["offset"] is not None else "?"
                sz = f"{e['size']:,}" if e["size"] is not None else "?"
                L.append(f"{nm:32s} {off:>12s} {sz:>12s}")
        return "\n".join(L)

    def extract(self, outdir):
        os.makedirs(outdir, exist_ok=True)
        rep = {"file": self.path, "kind": self.kind,
               "extracted": [], "skipped": []}

        if self.xml:
            p = os.path.join(outdir, "package-configuration.xml")
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.xml)
            rep["extracted"].append({"name": "package-configuration.xml",
                                     "size": len(self.xml), "path": p})

        base = self.container_offset or 0

        for e in self.entries:
            if not e["name"] or e["offset"] is None or e["size"] is None:
                continue
            abs_off = base + e["offset"]
            if abs_off + e["size"] > len(self.data) or e["size"] == 0:
                rep["skipped"].append({"name": e["name"], "reason": "hors fichier"})
                continue

            blob = self.data[abs_off:abs_off + e["size"]]

            if self.kind == "retail":
                rep["skipped"].append({
                    "name": e["name"],
                    "reason": "chiffre (retail) - extraction impossible sans console",
                })
                continue

            safe = os.path.basename(e["name"].replace("\\", "/")) or f"entry_{e['id']}"
            p = os.path.join(outdir, safe)
            with open(p, "wb") as f:
                f.write(blob)
            rep["extracted"].append({"name": e["name"], "size": len(blob), "path": p})

        with open(os.path.join(outdir, "_rapport.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2, ensure_ascii=False)
        return rep


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        print("usage: ps5pkg.py <fichier.pkg> [dossier_sortie]")
        return 1

    path = argv[1]
    outdir = argv[2] if len(argv) > 2 else None

    try:
        pkg = Pkg(path)
    except (PkgError, OSError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1

    print(pkg.summary())

    if outdir:
        rep = pkg.extract(outdir)
        print()
        print(f"extrait : {len(rep['extracted'])} fichier(s) -> {outdir}")
        for s in rep["skipped"]:
            print(f"  ignore {s['name']} : {s['reason']}")
        print(f"rapport : {os.path.join(outdir, '_rapport.json')}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
