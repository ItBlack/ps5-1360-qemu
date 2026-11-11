# SBL / ICC — chaîne complète établie (mesurée)

Trois versions successives de ce document se sont trompées. Voici l'état actuel,
avec pour chaque affirmation la mesure qui la soutient.

## La chaîne, de haut en bas

```
sblServiceRequest                       message "ERROR" ligne 103 du log
  └─ sceSblDriverSendMsg
       └─ 0xffffffff9e825840            "envoi SBL"  ← reçoit des messages valides
            └─ 0xffffffff9e825aa0       accès device
                 └─ rdi = [0xa18e9fd0]  handle de device
                      out dx, eax → base 0 → perdu
                      retourne 0x40008000
```

## Ce qui est mesuré et solide

| Fait | Mesure |
|---|---|
| Messages bien formés | type 6 (`len 0x80`), type 5 (`len 0x08/0x28`), séquence croissante |
| Drapeau prêt | `[0xa18e9ff8] = 1` |
| Canaux libres | `[0x9feb1210] = 0x7fff` (15) |
| Handle device **nul** | `[0xa18e9fd0] = 0` à chaque envoi |
| Statut d'échec | retour exact de `0x9e825aa0` = `0x40008000` |
| Transport en port I/O | `out dx, eax` avec registres `0x1054c`…`0x1056c` |

## D'où vient le handle

Une seule écriture existe dans tout le binaire, à `0xffffffff9e826ea8` :

```asm
call 0xffffffff9e8272f0      ; attache device
call 0xffffffff9e827730      ; ← doit retourner 0
test eax,eax
jne  .skip                   ; échec → handle PAS écrit
xor  eax,eax
mov  QWORD PTR [rip+...], rbx   ; handle = rbx
```

### `0x9e827730` = acquisition de ressources SPM

```asm
mov edi, 0x14 ; mov ebx, 0x14 ; call 0x9f006f30   ; ressource 0x14
mov edi, 0x16 ; ...            call 0x9f006f30   ; 0x16
mov edi, 0x17 ; ...            call 0x9f006f30   ; 0x17
mov edi, 0x19 ; ...            call 0x9f006f30   ; 0x19
mov edi, 0x1a ; ...            call 0x9f006f30   ; 0x1a
```

et `0x9f006f30` est un hypercall :

```asm
mov eax, 0x15      ; hypercall 21
mov ebx, edi       ; numéro de ressource
vmmcall
ret
```

## Deux erreurs corrigées ici

1. **J'ai cru que `0x9f006f30` n'était pas patché.** Faux : `patches.inc:92`
   patche le VMMCALL à `0xc16f3c`, qui est exactement celui-ci, en
   `xor eax,eax` → succès. Le kit l'a déjà réglé.

2. **J'ai cru qu'un ring mémoire à `phys 0x40000000` servait de canal.** Faux :
   c'est du port I/O. Toutes mes lectures de cette zone étaient hors sujet.

3. **Mensonge apparent dans le trampoline.** Le message
   `patch mismatch at 1F000402` est **faux** : la routine `puts` écrase `edx`
   avant l'affichage. L'adresse affichée n'est pas l'adresse fautive. Il faut
   patcher via `patches.inc`, jamais dans `kernel_raw.bin` — le trampoline
   vérifie l'image vierge avant d'appliquer ses patchs.

## Le vrai point bloquant restant

Le log contient, ligne 602 :

```
can't re-use a leaf (is_spmem_available)!
```

C'est un **sysctl** : le noyau teste si la mémoire SPM est disponible, et la
réponse est négative. C'est cohérent avec un hyperviseur absent : les hypercalls
sont neutralisés par le kit (ils retournent 0), mais **rien ne simule l'état
réel** que l'hyperviseur maintiendrait. Le noyau voit « pas de SPM » et
n'attache pas le device.

Ensuite, `0x9e827730` n'est **jamais appelée** (breakpoint jamais touché) : la
sonde de device ne se déclenche pas non plus.

## Conclusion honnête

Le blocage n'est pas « un format de réponse inconnu ». C'est plus profond :
**le noyau croit qu'aucun matériel SBL/ICC n'est présent**, et aucun patch
logiciel ponctuel ne peut le convaincre du contraire. Il faudrait fournir l'état
matériel complet que le noyau attend — c'est-à-dire écrire l'émulation de l'ICC
ET le chemin par lequel le noyau le découvre.

C'est faisable, mais ce n'est pas une case à cocher : c'est le cœur du travail
d'émulation.

## Ce que ça ne débloquerait pas

Même avec un ICC complet : clés PFS dans les fuses, 18 partitions sans image,
userland jamais fuité. Le SBL est nécessaire, pas suffisant.
