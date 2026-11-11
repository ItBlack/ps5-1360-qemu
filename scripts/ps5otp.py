#!/usr/bin/env python3
"""
ps5otp.py - fabrique un fichier de banque OTP pour le device QEMU ps5-otpctrl.

Ce script ne fabrique AUCUNE cle. Il assemble un conteneur "OTPK" a partir
de donnees que TU fournis (les tiennes, extraites de ta console, ou des
valeurs de test quand tu developpes le device).

Ce qu'il sert a faire :
  - construire un banc de test pour developper le device sans vraie console
  - packager des cles que tu possedes deja, pour les donner a QEMU

Usage:
    ps5otp.py new   <sortie.otpk>                  banc de test a zeros
    ps5otp.py add   <fichier.otpk> <off> <fichier> ajoute une region
    ps5otp.py list  <fichier.otpk>                 inventaire
    ps5otp.py dump  <fichier.otpk> <sortie.bin>    banque brute 4 Kio

Format (little endian):
    magic   "OTPK"
    version u32 = 1
    count   u32
    puis count fois: offset u32, size u32, data[size]
"""
import struct
import sys
import os

MAGIC = b"OTPK"
VERSION = 1
BANK_SIZE = 0x1000


def read_container(path):
    with open(path, "rb") as f:
        blob = f.read()
    if len(blob) < 12 or blob[:4] != MAGIC:
        raise ValueError("ce n'est pas un fichier OTPK")
    ver, count = struct.unpack_from("<II", blob, 4)
    if ver != VERSION:
        raise ValueError(f"version {ver} non supportee")
    pos = 12
    entries = []
    for _ in range(count):
        if pos + 8 > len(blob):
            break
        off, sz = struct.unpack_from("<II", blob, pos)
        pos += 8
        if pos + sz > len(blob):
            break
        entries.append((off, blob[pos:pos + sz]))
        pos += sz
    return entries


def write_container(path, entries):
    out = bytearray()
    out += MAGIC
    out += struct.pack("<II", VERSION, len(entries))
    for off, data in entries:
        out += struct.pack("<II", off, len(data))
        out += data
    with open(path, "wb") as f:
        f.write(out)


def cmd_new(argv):
    if len(argv) != 1:
        print("usage: ps5otp.py new <sortie.otpk>")
        return 1
    write_container(argv[0], [(0, bytes(BANK_SIZE))])
    print(f"banc de test cree : {argv[0]} ({BANK_SIZE} octets a zero)")
    print("ATTENTION : ce ne sont PAS de vraies cles, seulement")
    print("            un banc pour developper le device.")
    return 0


def cmd_add(argv):
    if len(argv) != 3:
        print("usage: ps5otp.py add <fichier.otpk> <offset> <fichier>")
        return 1
    container, off_s, src = argv
    off = int(off_s, 0)
    with open(src, "rb") as f:
        data = f.read()
    if off + len(data) > BANK_SIZE:
        print(f"erreur : {len(data)} octets a {off:#x} depasse la banque "
              f"({BANK_SIZE:#x} octets)")
        return 1
    entries = read_container(container)
    entries.append((off, data))
    write_container(container, entries)
    print(f"region ajoutee : {len(data)} octets a {off:#x} dans {container}")
    return 0


def cmd_list(argv):
    if len(argv) != 1:
        print("usage: ps5otp.py list <fichier.otpk>")
        return 1
    entries = read_container(argv[0])
    print(f"{argv[0]} : {len(entries)} region(s)")
    for off, data in entries:
        preview = data[:16].hex()
        print(f"  {off:#06x}  {len(data):5d} o  {preview}{'...' if len(data) > 16 else ''}")
    return 0


def cmd_dump(argv):
    if len(argv) != 2:
        print("usage: ps5otp.py dump <fichier.otpk> <sortie.bin>")
        return 1
    entries = read_container(argv[0])
    bank = bytearray(BANK_SIZE)
    for off, data in entries:
        bank[off:off + len(data)] = data[:BANK_SIZE - off]
    with open(argv[1], "wb") as f:
        f.write(bank)
    used = sum(len(d) for _, d in entries)
    print(f"banque {BANK_SIZE} octets ecrite dans {argv[1]} ({used} o renseignes)")
    return 0


COMMANDS = {"new": cmd_new, "add": cmd_add, "list": cmd_list, "dump": cmd_dump}


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
