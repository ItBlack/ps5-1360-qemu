#!/usr/bin/env python3
"""
ps5pup.py — inspecte un fichier de mise a jour PS5 (PUP).

Le format est un `bls_header` suivi d'une liste de `bls_entry`. Les
structures ci-dessous sont celles publiees par le projet
zecoxao/ps5-pup-decrypt (include/bls.h, include/pup.h) et ont ete
VERIFIEES contre PS5UPDATE_14.22_RECOVERY.PUP : la somme des tailles
declarees plus les remplissages tombe exactement sur la taille du
fichier (ecart 0 octet).

  bls_header (32 octets)
      0x00  u32  magic        "SLB2"
      0x04  u32  version      3 observe
      0x08  u32  flags        0x01010000 observe
      0x0C  u32  file_count   2 observe
      0x10  u32  block_count  0x2A6DF3 observe (= offset du segment 1 / 512)
      0x14  u8[12] unknown    tout a zero observe

  bls_entry (48 octets), a partir de 0x20
      0x00  u32  block_offset  offset du segment EN BLOCS DE 512 OCTETS
      0x04  u32  size          taille du segment en octets
      0x08  u8[8] reserved     tout a zero observe
      0x10  char[32] name      nom ASCII termine par NUL

  Donc : offset absolu du segment = block_offset * 512.
  Les blocs de 512 octets expliquent aussi le remplissage entre l'en-tete
  et les donnees, ainsi qu'entre deux segments.

EN-TETE INTERNE DE CHAQUE SEGMENT
---------------------------------
Chaque segment commence par 16 octets EN CLAIR, puis le reste est chiffre :

      +0x00  u32  magic          0xEEF51454 observe sur les deux segments
      +0x04  u32  0x32010110     identique sur les deux segments
      +0x08  u16  4              identique sur les deux segments
      +0x0A  u8   0
      +0x0B  u8   0
      +0x0C  u16  varie par segment (0x05B0, 0x0240 observes)
      +0x0E  u16  varie par segment (0x0DE0, 0x05A0 observes)

  Au-dela de 16 octets, l'entropie est maximale : c'est chiffre. Le
  `pup_header` complet fait 32 octets, donc `file_size`, `segment_count`
  et les champs suivants ne sont PAS lisibles sans la cle. C'est
  exactement ce que fait l'ioctl 0xC0184402 (`decrypt_header`) cote
  console : il dechiffre cet en-tete.

CHIFFREMENT
-----------
Tout le contenu des segments est chiffre. Mesure : entropie de Shannon
7.997 bits/octet a partir de l'offset 0x1000 et jusqu'a la fin, sur
43 echantillons de 64 Kio. Aucun magic interne (ELF, PFS, SCE, gzip)
n'est visible en clair.

Le dechiffrement se fait sur la console, via le service de chiffrement et
le noeud /dev/pup_update0 (voir zecoxao/ps5-pup-decrypt). Ce script ne
dechiffre rien et n'invente rien.

Usage:
    ps5pup.py info <fichier.PUP>
    ps5pup.py list <fichier.PUP>
    ps5pup.py map  <fichier.PUP>
    ps5pup.py seg  <fichier.PUP> <index>   # en-tete clair d'un segment
"""
import os
import struct
import sys

MAGIC = b"SLB2"
BLS_HEADER_SIZE = 0x20
BLS_ENTRY_SIZE = 0x30
MAX_ENTRIES = 64
BLOCK = 512
HEADER_BYTES = 0x1000


def parse(path):
    total = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(HEADER_BYTES)

    if len(head) < BLS_HEADER_SIZE or head[:4] != MAGIC:
        raise ValueError("ce n'est pas un PUP (magic SLB2 absent)")

    version, flags, file_count, block_count = struct.unpack_from("<IIII", head, 4)
    unknown = head[0x14:0x20]

    entries = []
    for i in range(min(file_count, MAX_ENTRIES)):
        base = BLS_HEADER_SIZE + i * BLS_ENTRY_SIZE
        if base + BLS_ENTRY_SIZE > len(head):
            break
        block_offset, size = struct.unpack_from("<II", head, base)
        reserved = head[base + 8:base + 16]
        name = head[base + 16:base + 48].split(b"\x00")[0].decode("ascii", "replace")
        absolute = block_offset * BLOCK
        entries.append({
            "name": name,
            "block_offset": block_offset,
            "offset": absolute,
            "size": size,
            "reserved": reserved,
            "fits": absolute + size <= total,
        })

    return {
        "version": version,
        "flags": flags,
        "file_count": file_count,
        "block_count": block_count,
        "unknown": unknown,
        "entries": entries,
        "total": total,
    }


def segment_header(path, entry):
    """Lit les 16 octets en clair au debut d'un segment."""
    with open(path, "rb") as fh:
        fh.seek(entry["offset"])
        raw = fh.read(16)
    if len(raw) < 16:
        return None
    magic, unk04, unk08 = struct.unpack_from("<IIH", raw, 0)
    flags, unk0b = struct.unpack_from("<BB", raw, 10)
    unk0c, unk0e = struct.unpack_from("<HH", raw, 12)
    return {
        "raw": raw,
        "magic": magic,
        "unk04": unk04,
        "unk08": unk08,
        "flags": flags,
        "unk0b": unk0b,
        "unk0c": unk0c,
        "unk0e": unk0e,
    }


def cmd_info(argv):
    if len(argv) != 1:
        print("usage: ps5pup.py info <fichier.PUP>")
        return 1
    info = parse(argv[0])
    mib = 1048576.0
    total = info["total"]

    print(f"fichier   : {argv[0]}")
    print(f"taille    : {total} o ({total/mib:.1f} Mio)")
    print(f"magic     : SLB2")
    print(f"version   : {info['version']}")
    print(f"flags     : {info['flags']:#010x}")
    print(f"entrees   : {info['file_count']}")
    print(f"block cnt : {info['block_count']} ({info['block_count']*BLOCK} o)")
    print(f"unknown   : {info['unknown'].hex(' ')}"
          f"{'  (tout a zero)' if not any(info['unknown']) else ''}")
    print()
    print(f"{'nom':<18} {'bloc':>10} {'offset':>12} {'taille':>12}  unite")
    print("-" * 62)
    for e in info["entries"]:
        warn = "" if e["fits"] else "  DEPASSE"
        print(f"{e['name']:<18} {e['block_offset']:>10} {e['offset']:>12}"
              f" {e['size']:>12}  {e['size']/mib:7.1f} Mio{warn}")
    print("-" * 62)

    # controle de coherence : somme + remplissages = taille du fichier
    if info["entries"]:
        data_end = max(e["offset"] + e["size"] for e in info["entries"])
        overhead = total - sum(e["size"] for e in info["entries"])
        print(f"somme des tailles : {sum(e['size'] for e in info['entries'])} o")
        print(f"fin des donnees   : {data_end:#x}")
        print(f"surcoute totale   : {overhead} o "
              f"(en-tete {BLS_HEADER_SIZE} + {info['file_count']}x{BLS_ENTRY_SIZE}"
              f" + remplissages a {BLOCK} o)")
        if data_end <= total:
            print(f"reste apres donnees : {total - data_end} o")
    print()
    for i, e in enumerate(info["entries"]):
        h = segment_header(argv[0], e)
        if h:
            print(f"  seg[{i}] {e['name']}: +0x00 {h['raw'][:12].hex(' ')}"
                  f" | unk0C={h['unk0c']:#06x} unk0E={h['unk0e']:#06x}")
    print()
    print("Contenu chiffre : l'inspection s'arrete aux en-tetes en clair.")
    return 0


def cmd_list(argv):
    if len(argv) != 1:
        print("usage: ps5pup.py list <fichier.PUP>")
        return 1
    for e in parse(argv[0])["entries"]:
        print(e["name"])
    return 0


def cmd_map(argv):
    if len(argv) != 1:
        print("usage: ps5pup.py map <fichier.PUP>")
        return 1
    info = parse(argv[0])
    mib = 1048576.0
    total = info["total"]

    regions = []
    cursor = 0
    for e in info["entries"]:
        if e["offset"] > cursor:
            regions.append((cursor, e["offset"], "remplissage"))
        regions.append((e["offset"], e["offset"] + e["size"], e["name"]))
        cursor = e["offset"] + e["size"]
    if cursor < total:
        regions.append((cursor, total, "remplissage final"))

    print(f"{'debut':>12}  {'fin':>12}  {'taille':>10}  region")
    print("-" * 66)
    for start, end, label in regions:
        if end <= start:
            continue
        print(f"{start:#012x}  {end:#012x}  {(end-start)/mib:8.3f} Mio  {label}")
    print("-" * 66)
    print(f"{'':>12}  {total:#012x}  {total/mib:8.1f} Mio  total")
    covered = sum(e["size"] for e in info["entries"])
    print(f"\ndonnees utiles : {covered} o ({covered/mib:.1f} Mio,"
          f" {100.0*covered/total:.2f} %)")
    return 0


def cmd_seg(argv):
    if len(argv) != 2:
        print("usage: ps5pup.py seg <fichier.PUP> <index>")
        return 1
    info = parse(argv[0])
    idx = int(argv[1], 0)
    if idx < 0 or idx >= len(info["entries"]):
        print(f"erreur : index {idx} hors plage (0..{len(info['entries'])-1})",
              file=sys.stderr)
        return 1
    e = info["entries"][idx]
    h = segment_header(argv[0], e)
    print(f"segment {idx} : {e['name']}")
    print(f"  offset {e['offset']:#x} (bloc {e['block_offset']}), taille {e['size']} o")
    print(f"  en-tete clair (16 o) : {h['raw'].hex(' ')}")
    print(f"  magic   {h['magic']:#010x}")
    print(f"  unk04   {h['unk04']:#010x}")
    print(f"  unk08   {h['unk08']}")
    print(f"  flags   {h['flags']:#04x}  unk0B {h['unk0b']:#04x}")
    print(f"  unk0C   {h['unk0c']:#06x} ({h['unk0c']})")
    print(f"  unk0E   {h['unk0e']:#06x} ({h['unk0e']})")
    print("  au-dela de 16 octets : chiffre")
    return 0


COMMANDS = {"info": cmd_info, "list": cmd_list, "map": cmd_map, "seg": cmd_seg}


def main(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    try:
        return COMMANDS[argv[1]](argv[2:])
    except (ValueError, OSError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
