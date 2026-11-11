# Plafond de RAM du boot PS5 13.60 sous QEMU

Mesuré le 2026-11-10, kit `ps5-kernel-qemu` (trampoline + `kernel_raw.bin`),
QEMU maison (`~/qemu-src/build/qemu-system-x86_64`), `-cpu EPYC -smp 8`.

## Résultat

| `-m` | RAM au-dessus de 4 Gio | lignes de log | `Failed to map RSDT` | boot |
|------|------------------------|---------------|----------------------|------|
| 2G (défaut d'origine) | non | 1436 | non | OK |
| 3G | non | 1436 | non | OK |
| 3500M | non | 1436 | non | OK |
| **3520M** | non | **1436** | **non** | **OK** |
| 3584M | oui | 126 | oui | panic |
| 3600M | oui | 126 | oui | panic |
| 3.8G / 3968M / 4G | oui | 126 | oui | panic |
| 8G (défaut QEMU) | oui | 126 | oui | panic |

**Plafond utile : un peu moins de 3,5 Gio** (`3520M` validé, `3584M` échoue).
Cause exacte : dès que l'e820 contient une entrée RAM au-dessus de `0x100000000`,
le noyau échoue `ACPI: Failed to map RSDT` → `APIC: Could not find any APICs`
→ `panic: running without device atpic requires a local APIC`.

`max-ram-below-4g` ne sauve pas la mise : à `-m 8G,max-ram-below-4g=3584M`
il reste de la RAM au-dessus de 4 Gio et le boot échoue pareil. Seule une
configuration **sans aucune** RAM au-dessus de 4 Gio passe.

## Aucune régression

À `3520M`, le log est identique à la baseline `2G` : 1436 lignes,
15 `error 12` (tous dans le registre de modules PS5, pas dans le mapping),
1 `sm_service_initialize -12`, 0 panic, 0 échec RSDT. Le diff ne contient que
des adresses (e820, ACPI, relocations), pas de comportement.

## Ce que le noyau annonce — et pourquoi ce n'est pas la RAM invitée

```
Flexible memory (system) : 0x877cc000 (2168 MiB)
BIOS memory size         : 0x380012000 (14337 MiB)
```

Ces deux lignes sont **identiques à 2 Gio et à 3.5 Gio**. Le noyau PS5 ne taille
pas sa mémoire sur l'e820 : il lit une table de disposition figée (les valeurs
`0x877cc000` et `0x380012000` sont présentes en dur dans `kernel_raw.bin` aux
offsets `0x36c7320`, `0x3ddb478`). Augmenter `-m` rend donc la RAM disponible au
matériel mais ne change pas la comptabilité du noyau : elle reste à 2168 Mio.

**Conséquence honnête : passer de 2 Gio à 3.4 Gio ne débloque rien de plus dans
le noyau aujourd'hui.** Le vrai levier serait de patcher cette table de
disposition (site patché → doit passer par `patches.inc`), pas `-m`.

## Ce que ça débloque quand même

Les `15 error 12` (ENOMEM du registre de modules) persistent à 3.4 Gio, donc ce
n'était pas un manque de RAM mais un manque de mémoire noyau allouable dans la
zone que le noyau considère comme sienne (2168 Mio fixes).

## Utilisation

```bash
PS5_RAM=3520M bash run.sh          # défaut retenu
PS5_RAM=2G     bash run.sh         # baseline d'origine
```

`run.sh` a été modifié pour lire `PS5_RAM` (défaut `3520M`) ; sauvegarde dans
`run.sh.bak-*`.
