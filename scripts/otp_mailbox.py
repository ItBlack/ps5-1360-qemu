#!/usr/bin/env python3
"""
otp_mailbox.py — documente et decode les commandes OTP que le noyau envoie
au SBL par la mailbox (sceSblDriverSendMsg).

Contexte etabli par desassemblage du dump 13.60 :

  sbl/otpctrl          pilote noyau (code 0xffffffff9ee44200..0xffffffff9ee44767)
  otpctrl_ioctl_nolock point d'entree ioctl
  0xffffffff9e9836e0   accesseur "lire OTP"   -> empile un message
  0xffffffff9e983a30   accesseur "ecrire OTP"
  0xffffffff9e983710   accesseur "statut OTP"
  0xffffffff9e994615   corps d'envoi : movabs 0x80008000000006 puis message

Le pilote n'est PAS un pilote ACPI : il ne lit aucun registre MMIO ni port.
Il n'y a donc pas de noeud ACPI a creer, et pas de device a adresser
directement. Tout passe par la mailbox, et la mailbox est morte sans
hyperviseur (vmmcall -> #UD).

Codes de message OTP observes dans le pilote :
  0x800f150e   0x800f1516   0x800f1518
  decompose en (0x8000_0000 | canal << 16 | commande)

Ce script sert a :
  - verifier la coherence des codes
  - produire un journal lisible depuis une trace de mailbox
  - documenter le contrat attendu par le pilote, pour qui voudra implementer
    le repondeur (cote hyperviseur ou cote SBL emule)

Aucune cle n'est fabriquee ici.
"""
import struct
import sys

# Bits communs aux messages SBL (etablis par desassemblage)
MSG_FLAG = 0x80000000

# Commandes OTP identifiees dans le pilote noyau
OTP_COMMANDS = {
    0x800F150E: "otp_status   (lecture d'etat du controleur)",
    0x800F1516: "otp_read     (lecture d'une region)",
    0x800F1518: "otp_write    (ecriture d'une region, en general refusee)",
}

# Autres commandes SBL rencontrees ailleurs dans le noyau, pour contexte
SBL_COMMANDS = {
    0x80000006: "attente/ack generique",
    0x00800080: "type 6 observe au boot",
    0x00000008: "type 5 observe au boot",
}


def decode(code):
    """Decompose un code de message SBL en champs lisibles."""
    known = OTP_COMMANDS.get(code) or SBL_COMMANDS.get(code)
    return {
        "code": f"0x{code:08x}",
        "flag": bool(code & MSG_FLAG),
        "channel": (code >> 16) & 0x7FFF,
        "command": code & 0xFFFF,
        "meaning": known or "inconnue",
    }


def cmd_decode(argv):
    if not argv:
        print("usage: otp_mailbox.py decode <code_hex> [...]")
        print("\ncommandes OTP connues :")
        for c, d in sorted(OTP_COMMANDS.items()):
            print(f"  {c:#010x}  {d}")
        return 1
    for a in argv:
        code = int(a, 0)
        d = decode(code)
        print(f"{d['code']}  canal={d['channel']:#06x}  cmd={d['command']:#06x}  {d['meaning']}")
    return 0


def cmd_parse(argv):
    """Lit une trace : lignes '<code_hex> <payload_hex>' et les decode."""
    if len(argv) != 1:
        print("usage: otp_mailbox.py parse <trace.txt>")
        return 1
    try:
        lines = open(argv[0]).read().splitlines()
    except OSError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        try:
            code = int(parts[0], 16)
        except ValueError:
            print(f"  ignore : {line}")
            continue
        d = decode(code)
        print(f"{d['code']}  {d['meaning']}")
        if len(parts) > 1:
            try:
                raw = bytes.fromhex("".join(parts[1:]))
            except ValueError:
                continue
            print(f"    payload {len(raw)} o : {raw[:32].hex()}")
            if len(raw) >= 8:
                w = struct.unpack_from("<II", raw, 0)
                print(f"    comme 2 x u32 : {w[0]:#x} {w[1]:#x}")
    return 0


def cmd_doc(argv):
    print(__doc__)
    print("Contrat attendu par le pilote (a implementer cote repondeur) :")
    print()
    for c, d in sorted(OTP_COMMANDS.items()):
        print(f"  {c:#010x}  {d}")
    print()
    print("Le corps d'envoi (0xffffffff9e994615) utilise :")
    print("  movabs rax, 0x80008000000006")
    print("  ... puis empile le message et appelle sceSblDriverSendMsg")
    print()
    print("Donc un repondeur doit :")
    print("  1. recevoir le message dans la structure de l'appelant ([rsi+0] WORD)")
    print("  2. ecrire le statut DWORD a [rsi+4]")
    print("  3. renvoyer le code retour dans eax")
    return 0


COMMANDS = {"decode": cmd_decode, "parse": cmd_parse, "doc": cmd_doc}


def main(argv):
    if len(argv) < 2 or argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    return COMMANDS[argv[1]](argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
