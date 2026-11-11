# Format PUP — établi et vérifié

Statut : **format du conteneur résolu et vérifié**. Le déchiffrement du
contenu reste bloqué, voir la fin.

Fichier de référence : `PS5UPDATE_14.22_RECOVERY.PUP`,
1 423 697 408 octets, SHA-256 à recalculer si besoin.

## Le conteneur est un `bls_header`

Les structures ont été reprises du projet `zecoxao/ps5-pup-decrypt`
(`include/bls.h`, `include/pup.h`) puis **vérifiées octet par octet**
contre notre fichier. La vérification est concluante sans ambiguïté :

```
block_count (0x10) = 2 780 659
2 780 659 * 512     = 1 423 697 408
taille du fichier   = 1 423 697 408      -> égalité exacte
```

Et indépendamment :

```
somme des tailles déclarées = 1 423 695 674
surcoute (en-tête + tables + remplissages 512) = 1 734
1 423 695 674 + 1 734 = 1 423 697 408    -> égalité exacte
```

Deux chemins de calcul indépendants qui tombent sur la taille exacte du
fichier : le format est juste.

### `bls_header` — 32 octets, offset 0

| Offset | Type | Valeur observée | Rôle |
|---|---|---|---|
| 0x00 | u32 | `SLB2` | magic |
| 0x04 | u32 | 3 | version |
| 0x08 | u32 | `0x01010000` | flags |
| 0x0C | u32 | 2 | `file_count` |
| 0x10 | u32 | `0x2A6DF3` = 2 780 659 | `block_count` — nombre total de blocs de 512 o du fichier |
| 0x14 | u8[12] | tout à zéro | inconnu |

### `bls_entry` — 48 octets, à partir de 0x20

| Offset | Type | Rôle |
|---|---|---|
| +0x00 | u32 | `block_offset` — **en blocs de 512 octets** |
| +0x04 | u32 | `size` — taille du segment en octets |
| +0x08 | u8[8] | réservé, tout à zéro |
| +0x10 | char[32] | nom ASCII terminé par NUL |

**Offset absolu = `block_offset * 512`.**

Les entrées de notre fichier :

| Nom | bloc | offset absolu | taille | part |
|---|---|---|---|---|
| `PS5UPDATE1.PUP` | 2 | `0x400` | 1 266 089 597 | 1207.4 Mio |
| `PS5UPDATE2.PUP` | 2 472 834 | `0x4B770400` | 157 606 077 | 150.3 Mio |

Carte du fichier :

```
0x0000000000  0x0000000400       1 Kio   en-tête + table (remplissage à 512)
0x0000000400  0x004B77027D   1207.4 Mio   PS5UPDATE1.PUP
0x004B77027D  0x004B770400     387 o     remplissage à 512
0x004B770400  0x0054DBE4BD    150.3 Mio   PS5UPDATE2.PUP
0x0054DBE4BD  0x0054DBE600     323 o     remplissage final
0x0054DBE600                 1357.7 Mio   total
```

Les remplissages ne sont pas du gaspillage : ils alignent chaque segment
sur une frontière de 512 octets, ce que `block_count` et `block_offset`
supposent.

## En-tête interne de chaque segment — 16 octets en clair

Les deux segments commencent par **le même motif en clair** :

```
seg[0] @0x400       : 54 14 f5 ee 10 01 01 32 04 00 00 00 b0 05 e0 0d
seg[1] @0x4B770400  : 54 14 f5 ee 10 01 01 32 04 00 00 00 40 02 a0 05
```

| Offset | Type | seg[0] | seg[1] | Rôle |
|---|---|---|---|---|
| +0x00 | u32 | `0xEEF51454` | `0xEEF51454` | magic de segment |
| +0x04 | u32 | `0x32010110` | `0x32010110` | identique |
| +0x08 | u16 | 4 | 4 | identique |
| +0x0A | u8 | 0 | 0 | — |
| +0x0B | u8 | 0 | 0 | — |
| +0x0C | u16 | `0x05B0` | `0x0240` | varie par segment |
| +0x0E | u16 | `0x0DE0` | `0x05A0` | varie par segment |

**Au-delà de 16 octets, c'est chiffré.** Le `pup_header` complet fait 32
octets, donc `file_size`, `segment_count` et les champs suivants ne sont
pas lisibles sans la clé. Le `u32` à +0x10 de `seg[0]` vaut
`7778815604992573160`, ce qui est manifestement du chiffré et non une
taille.

## Ce que j'avais faux avant

Deux erreurs corrigées, gardées ici pour ne pas les refaire :

1. **Champs décalés.** Je lisais `version` à 0x20 et `ref_size` à 0x24.
   En réalité `file_count` est à 0x0C et `block_count` à 0x10, et
   l'offset 0x24 tombe **au milieu de `entry[0]`** — je lisais donc
   `entry[0].size` en croyant lire `ref_size`. D'où la croyance que
   `ref_size` ≈ 1207 Mio était une propriété globale du fichier.
2. **Offset traité comme absolu.** `entry[0].block_offset = 2` n'est pas
   l'octet 2, c'est le bloc 2, donc l'octet 1024. Traiter les offsets
   comme absolus faisait apparaître le segment 0 dans la zone d'en-tête,
   et la « seconde entrée vide » était le résultat d'un décalage de
   lecture d'une entrée.
3. **« La table ne décrit qu'un segment ».** Faux : elle en décrit deux,
   qui couvrent 100.00 % du fichier. L'ancien message
   `PS5UPDATE2.PUP (entree vide)` était un artefact du bug ci-dessus.

## Le déchiffrement — état réel

Le contenu est chiffré. Mesure : entropie de Shannon 7.997 bits/octet dès
l'offset `0x1000` jusqu'à la fin, sur 43 échantillons de 64 Kio. Aucun
magic interne (ELF, PFS, SCE, gzip) n'est visible en clair.

**Le déchiffrement ne se fait pas sur PC. Il se fait sur la console.**

Le projet `zecoxao/ps5-pup-decrypt` (mis à jour le 2026-10-19, 77
étoiles) ne contient aucun algorithme de déchiffrement. C'est un **payload
ELF qui s'exécute sur la PS5** (`Makefile` : `-nostdlib -fno-builtin`,
`linker.x`, `crt0.s`, cible `ps5_pup_decrypt.elf`). Il ouvre le noeud
`/dev/pup_update0` et demande au service de chiffrement de la console de
faire le travail à sa place. Sa propre description : *« ps5 pup decrypt
by asking nicely ps5 to do it »*.

Les ioctl utilisés, relevés dans `source/encryptsrv.c` :

| ioctl | Fonction | Rôle |
|---|---|---|
| `0xC0104401` | `verify_blsheader` | vérifie l'en-tête BLS |
| `0xC0184402` | `decrypt_header` | **déchiffre le `pup_header` de 32 o** |
| `0xC0184403` | `verify_segment` (additional ≠ 0) | `VerifyPupAdditionalSign` / `VerifyPupWatermark` |
| `0xC0184404` | `verify_segment` (additional = 0) | vérifie un segment |
| `0xC0184405` | `decrypt_segment` | déchiffre un segment entier |
| `0xC0284406` | `decrypt_segment_block` | déchiffre un bloc + sa table |

Structure des arguments (`encryptsrv_args.h`, tailles vérifiées par
`checkheaders.c`) :

```c
verify_blsheader_args       { void *buffer; ulong length; ulong unknown; }  // 24 o
decrypt_header_args         { void *buffer; size_t length; int type; }     // 24 o
verify_segment_args         { u16 index; void *buffer; size_t length; }    // 24 o
decrypt_segment_args        { u16 index; void *buffer; size_t length; }    // 24 o
decrypt_segment_block_args  { u16 entry_index; u16 block_index;
                              void *block_buffer; size_t block_length;
                              void *table_buffer; size_t table_length; }   // 40 o
```

Le `readbytes`/`writebytes` de `decryptio.c` travaille par tranches de
2 Mio (`#define chunksize 2097152`).

Contraintes d'usage documentées par le projet :

- il faut être sur la **même version** (5.00 sur un PUP 5.00) ou une
  version supérieure **du même `.XX`** (5.02 sur un PUP 5.50, mais pas
  6.00) ;
- ne fonctionne pas sur les fichiers `system`, `system_ex`, `wlan` ;
- « requires elevated privileges for most packages ».

## Conséquence pour notre projet

Notre émulateur ne peut pas déchiffrer un PUP sans le service de
chiffrement. Ce service, dans le noyau 13.60, est celui qu'on a déjà
identifié :

```
sceSblAuthMgrSmIsLoadable2  ->  sceSblServiceMailbox  ->  transport
                                                            |
                                              [0xffffffffa18e9fd0] = NULL
```

La structure `[0xa18e9fd0]` est remplie par l'`attach` du pilote
`pci/sbl_driver` (`0xffffffff9e8268b0`), qui exige un device PCI
`1022:13EC` (`probe` à `0xffffffff9e826740`, `cmp $0x1022` puis
`cmp $0x13ec`). Ce device n'existe pas dans notre QEMU, donc l'attach
n'est jamais appelé, donc la mailbox reste nulle, donc aucun déchiffrement
n'est possible.

**Le format PUP n'est plus le bloqueur. Le bloqueur est le device PCI
`1022:13EC`.**

## Outil

`scripts/ps5pup.py` implémente ce format :

```
ps5pup.py info <fichier.PUP>      # en-tête, entrées, contrôle de cohérence
ps5pup.py list <fichier.PUP>      # noms des segments
ps5pup.py map  <fichier.PUP>      # carte début/fin/taille par région
ps5pup.py seg  <fichier.PUP> <i>  # en-tête clair du segment i
```

`info` affiche `block_count * 512` à côté de la taille du fichier : c'est
le contrôle de cohérence qui valide le parse. Si ces deux nombres
diffèrent, le fichier n'est pas au format attendu.
