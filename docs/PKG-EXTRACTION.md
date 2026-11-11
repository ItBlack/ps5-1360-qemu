# Extraction de packages PS5 — ce qui est possible

## Réponse directe

Sur un PKG **signé (retail)**, tu peux extraire **sans aucune clé** :

- ✅ toute la structure du fichier (taille, entrées, offsets)
- ✅ le XML `package-configuration` (titre, version, liste des fichiers)
- ✅ les métadonnées de contenu présentes en clair

Tu ne peux **pas** extraire le contenu chiffré (l'`eboot.bin`, les assets).

Sur un PKG **debug (non signé)**, tu peux extraire **tout**.

## Outil fourni

`scripts/ps5pkg.py` — lecteur autonome, Python 3, sans dépendance.

```bash
python3 scripts/ps5pkg.py jeu.pkg              # inventaire
python3 scripts/ps5pkg.py jeu.pkg ./sortie     # extraction
```

Tests de non-régression : `scripts/tests/run_tests.sh`

## Le format, vérifié

Établi en lisant `SvenGDK/PS5PKGReader` (GPL-2.0), pas deviné.

```
offset 0x00   magic     "uCNT" = meta   /   "uFIH" = package complet
offset 0x05   drapeau   0x80 = retail signé   /   0x00 = debug non signé
fin de fichier          XML <package-configuration version="1.0"
                            type="package-info"> ... </package-configuration>
```

Le XML contient :

```xml
<mount-image>
  <container-offset>0x...</container-offset>   ← base des offsets d'entrées
</mount-image>
<entries>
  <entry><id/><offset/><size/><name/></entry>
</entries>
```

Donc : **offset absolu = container-offset + offset de l'entrée**.

## Pourquoi le contenu retail reste inaccessible

La clé de déchiffrement est dérivée de secrets stockés dans les **fuses OTP de
la console**, pas d'une clé Sony universelle. Ces fuses :

- sont propres à chaque machine
- sont conçus pour être illisibles par logiciel
- ne figurent pas dans le dump du noyau (103 Mo, vérifié)

Aucun outil ne peut les deviner. Aucun émulateur non plus.

## Le pilote OTP du noyau — piste pour la suite

Le dump contient un vrai pilote OTP :

```
sbl/otpctrl        otpctrl_init        otpctrl_ioctl_nolock
sbl/manuauth       sbl/discid          sbl/ddd
sbl/devact         sbl/driveauth       sbl/pltauth    sbl/idata
```

Code à `0xffffffff9ee44200`–`0xffffffff9ee44767`.

Émuler ce device donnerait au noyau un OTP qui **répond**, avec le contenu
qu'on y met. Ça ne fabrique pas de clés Sony — ça fournit le mécanisme.

## Les noms de commandes SBL (via kstuff)

`kstuff/prosper0gdb/offsets/13_60.h` nomme les points d'entrée SBL, et leurs
offsets sont **valides pour notre noyau** (base implicite `0xffffffff9f0b0000`
= notre segment DATA, vérifié) :

```
sceSblServiceMailbox_lr_verifyHeader
sceSblServiceMailbox_lr_loadSelfSegment
sceSblServiceMailbox_lr_decryptSelfBlock
sceSblServiceMailbox_lr_decryptMultipleSelfBlocks
sceSblServiceMailbox_lr_sceSblAuthMgrSmFinalize
sceSblServiceMailbox_lr_verifySuperBlock
sceSblServiceMailbox_lr_sceSblPfsClearKey_1 / _2
sceSblServiceMailbox_lr_npdrm_cmd_5 / _6
sceSblServiceMailbox_lr_verifyImage
```

## Limite honnête

Extraire d'un PKG retail signé son contenu chiffré demande la console qui l'a
acheté. Ce n'est pas une limite de code, c'est une limite cryptographique.
Tout outil qui prétendrait le contraire mentirait.
