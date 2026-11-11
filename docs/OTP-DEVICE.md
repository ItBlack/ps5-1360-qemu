# Device QEMU `ps5-otpctrl` — état et usage

## Ce qui marche

Le device est écrit, compilé, enregistré dans QEMU et chargé au boot.

```
$ ./qemu-system-x86_64 -device help | grep ps5
name "ps5-ec", bus ISA
name "ps5-icc", desc "PS5 APU Internal Communication Controller"
name "ps5-otpctrl", bus ISA
```

Boot avec les 30 régions de clés :

```
qemu-system-x86_64: -device ps5-otpctrl,iobase=0x2000,keys=.../ps5-keys.otpk:
  info: ps5-otpctrl: 30 key region(s) loaded from .../ps5-keys.otpk
```

Résultat du boot : **1436 lignes, 11 erreurs SBL** — identique à un boot sans
le device. Le device n'introduit donc aucune régression.

## Correction importante : pas de nœud ACPI à écrire

J'ai annoncé qu'il fallait un nœud ACPI pour que le pilote s'attache. **C'est
faux**, et la mesure le montre.

Le device est instrumenté : chaque lecture et chaque écriture est journalisée.

```
$ ... -device ps5-otpctrl,iobase=0x2000,keys=... 2> probe.err
$ grep -c PS5OTP probe.err
0
```

**Zéro accès sur 1436 lignes de boot.** Le noyau ne touche jamais le device.

### Pourquoi : ce pilote n'est pas un pilote ACPI

Le désassemblage tranche. `otpctrl_ioctl_nolock` (`0xffffffff9ee44521`) appelle
trois accesseurs :

```
0xffffffff9e9836e0   lire OTP
0xffffffff9e983a30   écrire OTP
0xffffffff9e983710   statut OTP
```

Ces accesseurs n'émettent ni `in`/`out`, ni accès MMIO. Ils empilent un message
et appellent le corps d'envoi `0xffffffff9e994615`, dont le code est :

```
movabs rax, 0x80008000000006
```

avec les commandes OTP `0x800f150e`, `0x800f1516`, `0x800f1518`.

**Tout passe par la mailbox SBL.** Aucune ressource matérielle à déclarer,
donc aucun nœud ACPI à construire. Un nœud ACPI serait une porte sur une
maison sans sol.

### Et la mailbox est en amont du problème

```
module_register_init: MOD_LOAD (sbl_sm_service, 0xffffffff9e658728, 0) error 45
ERROR: sblServiceRequest(103) sceSblDriverSendMsg 1073774592
```

Le module parent `sbl_sm_service` échoue **avant** que le pilote OTP existe.
Même un device parfait ne serait jamais atteint. L'ordre réel est donc :

1. réparer la mailbox (donc l'hyperviseur : `vmmcall` → `#UD` sans lui)
2. seulement ensuite le pilote OTP pourra être joint
3. et alors un support matériel aura un sens

Le device reste utile comme échafaudage : il charge les clés, il est prêt, et
il documente le contrat. Mais il ne débloque rien tant que (1) n'est pas fait.

## Modèle de registres

| offset | nom     | accès | rôle                                     |
|--------|---------|-------|------------------------------------------|
| 0x00   | CONTROL | W     | 1 = lire (transfert), 2 = écrire         |
| 0x04   | ADDRESS | RW    | offset dans la banque                    |
| 0x08   | STATUS  | R     | bit0 PRÊT, bit1 ERREUR, bit2 ÉCRITURE_OK |
| 0x0C   | DATA    | RW    | octet/slot de données                    |
| 0x10   | SIZE    | R     | taille de la banque (64 Kio)             |

La banque fait 64 Kio, ce qui laisse de la place pour les 4934 octets de clés
publiées et pour des clés fournies par l'utilisateur.

Le bit PRÊT est **toujours** positionné après une lecture : le noyau sonde ce
bit en boucle au démarrage et bloque indéfiniment s'il ne le voit jamais.

Sans fichier de clés, le device annonce `ERREUR` : le noyau prend la branche
« pas de clés » au lieu d'utiliser des zéros silencieusement. Un zéro qui
passe pour une clé est bien pire qu'une erreur franche.

## Port I/O

⚠️ Piège rencontré : l'espace de ports x86 s'arrête à `0xFFFF`. J'ai d'abord
utilisé `0x10500` en croyant lire les offsets du dump — le device écrasait la
mémoire du BIOS et le trampoline n'était plus reconnu comme image bootable
(« No bootable device »).

Les offsets `0x105xx` vus dans le dump sont des offsets **dans** le bloc OTP,
pas des ports. La base réelle reste à confirmer sur matériel ; par défaut le
device écoute sur `0x2000`, qui ne conflicte avec rien.

## Fichier de clés

Format `OTPK`, little endian :

```
magic  "OTPK"   4 octets
version u32     = 1
count   u32
puis count fois : offset u32, size u32, data[size]
```

Fabriqué et inspecté avec `scripts/ps5otp.py` :

```bash
ps5otp.py new   banc.otpk                  # banc de test à zéros
ps5otp.py add   banc.otpk 0x100 cle.bin    # ajouter une région
ps5otp.py list  banc.otpk                  # inventaire
ps5otp.py dump  banc.otpk banque.bin       # banque brute
```

Ce script ne fabrique **aucune** clé. Il assemble un conteneur à partir de ce
qu'on lui donne.

## Fabrication / test

Après modification de `ps5_otpctrl.c` :

```bash
cd ~/qemu-src/build && ninja qemu-system-x86_64
```

Test fonctionnel :

```bash
cd /tmp/p5kq && timeout 110 ~/qemu-src/build/qemu-system-x86_64 \
  -L ./bios -M pc -cpu EPYC -m 2G -smp 8 \
  -kernel wp3_boot/trampoline.elf -initrd wp3_boot/kernel_raw.bin \
  -display none -serial null -monitor none \
  -chardev file,id=dbg,path=/tmp/p5kq/keys.log \
  -device isa-debugcon,iobase=0x402,chardev=dbg \
  -device ps5-otpctrl,iobase=0x2000,keys=../../keys/ps5-keys.otpk \
  -no-reboot
wc -l keys.log        # attendu : 1436
```

## Étape suivante

1. Nœud ACPI pour que le pilote `sbl/otpctrl` s'attache
2. Une fois attaché, observer les commandes `otpctrl_ioctl_nolock` réellement
   émises, et aligner le modèle de registres sur ce que le pilote demande
3. Alimenter la banque avec les clés publiées (`keys/`) ou les siennes
