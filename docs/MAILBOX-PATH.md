# Chemin réel de l'init SBL — mesuré au GDB (13.60)

Base du dump (corrigée) : `kernel_text @ 0xffffffff9e3f0000`, offset 0,
`kernel_data @ 0xffffffff9f0b0000`, offset `0xCC0000`.

`kernel_raw.bin` (le noyau qui tourne) et le dump ont **les mêmes octets** aux mêmes
offsets : les adresses du dump sont valides pour le noyau émulé.

## Ce qui est réellement exécuté

Mesuré avec `-gdb tcp:: -S` et un point de contrôle sur `btext` (qui touche à coup sûr) :

| Adresse | Rôle | Atteint |
|---|---|---|
| `0xffffffff9e642a90` | btext (contrôle) | **oui** |
| `0xffffffff9e9946f0` | `sbl_init` (chemin SBL) | **oui, 2 fois** (`esi=0` puis `esi=1`) |
| `0xffffffff9e825aa0` | `sceSblDriverSendMsg` | **oui, 5 fois** |
| `0xffffffff9e78d3f0` | `sceSblSysVeriInitialize` | **non** |
| `0xffffffff9e994761` | site d'erreur `sceSblSysVeriInitialize` | **non** |
| `0xffffffff9e826e96` | appelsite *attach SPM* | **non** |
| `0xffffffff9e8268b0` | « entrée » du chemin attach | **non** |

## Corrections apportées aux notes précédentes

1. **La base du dump était fausse.** `kernel-13.60-live.bin.json` donne
   `kernel_text_base = 0xffffffff9e3f0000`, pas `0x9e000000`. Toute lecture à
   `vaddr - 0x9e000000` était décalée de `0x3f0000`. Avec la bonne base,
   `0x9e825aa0` se décode en `push rbp; mov rbp,rsp; ...` (prologue valide).

2. **« attach SPM `0x9e827730` jamais appelé » n'est pas la cause racine.**
   La fonction conteneur `0x9e8268b0` n'est jamais exécutée du tout, et
   `0x9e827730` n'a **aucun appelant** (`call rel32`) ni **aucune référence**
   (`qword`) dans le dump. Ce n'est pas un chemin que le boot emprunte puis
   abandonne : ce n'est pas le chemin du tout.

3. **`sm_service_initialize` n'est pas la fonction qui échoue.** La chaîne
   `sm_service_initialize` (`0xffffffff9f68731c`) est référencée par un
   `ERROR: %s(%d) sceSblSysVeriInitialize %d` à `0xffffffff9f78b4ed` : c'est le
   **nom du module passé en `%s`**, pas le nom de la fonction fautive. La fonction
   qui échoue est `sceSblSysVeriInitialize` (`0xffffffff9e78d3f0`).

4. **`sceSblSysVeriInitialize` n'est pas appelée depuis son seul appelsite
   statique** (`0xffffffff9e99474d`). Le log imprime pourtant le message d'échec :
   l'appel vient donc d'un autre chemin (probablement indirect). Ce point reste
   ouvert et demande une mesure, pas une déduction.

## Architecture complète de la mailbox (mesurée)

La chaîne est établie de bout en bout :

```
sceSblAuthMgrSmIsLoadable2  @0x9e727da0   (jamais atteinte au boot)
  └─ sceSblServiceMailbox   @0x9e994610   rdi=[0xffffffff9fe8bfd0], esi=msg
       └─ transport         @0x9eba0c70   dispatcher sur ecx
            ├─ ecx=0 -> 0x9eba0ca0   allocateur de canal
            ├─ ecx=1 -> 0x9e826300
            └─ ecx=2 -> 0x9e826020

allocateur de canal @0x9eba0ca0
  ├─ porte   [0xffffffffa18e9ff8]  (doit etre != 0)
  ├─ bitmap canaux [0xffffffff9feb1210] (bsf, < 0xf)
  ├─ ring     [0xffffffffa18ea020] + (canal|0x10)<<0xb
  └─ 0x9e825840  (copie du message puis envoi)
       └─ sceSblDriverSendMsg @0x9e825aa0  rdi=[0xffffffffa18e9fd0]
```

`sceSblDriverSendMsg` attend un **double indirection** :
`rdi -> [+0x10] -> [+0x10] = base`, et `[+8]` choisit le mode
(`0` = port I/O via `out`, sinon MMIO).

## Mesure : forcer la structure a un effet réel

En fabriquant la structure à chaud (`rdi -> [+0x10] -> base=0x10500`) :

| métrique | avant | après |
|---|---|---|
| `sceSblDriverSendMsg` en erreur | 5 | **3** |
| `error 12` (ENOMEM) | 15 | **12** |
| panic | 0 | 0 |

**Deux erreurs SBL disparaîssent.** La structure est donc bien le bon levier :
une partie du chemin accepte la structure fabriquée et va plus loin.
Il ne reste que 3 échecs, sur d'autres canaux.

## Cause racine mesurée : le pointeur du contrôleur est NULL

`sceSblDriverSendMsg` est appelée 5 fois, toujours avec **`rdi = 0`** :

```
9e825a1d  mov  0x30c45ac(%rip),%r15   # r15 = [0xffffffffa18e9fd0]
9e825a24  movzbl (%rsi),%r12d
9e825a28  call 0xffffffff9ecce330
9e825a2d  mov  %r15,%rdi            # <-- rdi = 0 (le global n'est jamais ecrit)
9e825a30  mov  %r12d,%esi
9e825a33  mov  %rax,%rdx
9e825a36  call 0xffffffff9e825aa0   # sceSblDriverSendMsg(0, chan, msg)
```

Retour mesuré de chaque appel : `0x40008000` (ENOMEM), identique aux 5.

### Qui devrait écrire ce global

`0xffffffffa18e9fd0` a **19 références** dans le texte du noyau :
**18 lectures**, **1 seule écriture**.

| | adresse | rôle |
|---|---|---|
| écriture unique | `0xffffffff9e826ea8` | `mov %rax,0xffffffffa18e9fd0` |
| fonction conteneur | **`0xffffffff9e8268b0`** | prologue valide (précédé de `0x90`) |
| cette fonction pendant le boot | — | **jamais exécutée** (breakpoint validé par témoin `btext`) |

Les 18 lectures sont à `0x9e825a1d`, `0x9e825c28`, `0x9e8264a9`, `0x9e8265b0`…`0x9e8266cc`,
`0x9e8270b7`, `0x9e8270e4`, `0x9e827142`, `0x9e8271aa`, `0x9e8271de`, `0x9e827900`.
Toutes lisent donc `NULL`.

### Nature du chemin manquant

`0x9e8268b0` n'a **aucun appelant `call rel32`** et **aucun pointeur `qword`**
dans le dump. Ce n'est pas une fonction oubliée par hasard : elle est résolue
par nom (table de symboles de module), ce qui est cohérent avec son placement
dans le cluster `sbl` (juste après `sceSblDriverSendMsg`).

## Modèle matériel déduit (exploitable)

La région montre tous les registres, en accès port (`out dx,eax`) quand
`[rcx+8] == 0`, en MMIO (`mov %eax,(%rdx)`) sinon, avec
`rcx = [rdi+0x10]` et `rdx = 0x105xx + [rcx+0x10]` :

| offset | usage observé |
|---|---|
| `0x1054c` | canal (16 bits, `movzwl %bx,%eax`) |
| `0x10550` | mot bas du message |
| `0x10554` | mot haut du message |
| `0x10564` | `channel << 8` à l'envoi ; **bit 0 = PRÊT** (pollé) |
| `0x10568` | donnée basse 32 bits |
| `0x1056c` | donnée haute 32 bits |

C'est une spécification complète pour un device de port à `0x10500`.
Mais il ne servira à rien tant que `rdi` vaut `NULL` : le transport n'est même
pas atteint avec un pointeur valide.

## Le mur, tel qu'il est maintenant mesuré

Les 5 `sceSblDriverSendMsg` s'exécutent et échouent tous en `0x40008000` (ENOMEM
côté noyau, `1073774592`). Le transport est atteint ; c'est la **structure du
contrôleur** qu'il lit qui n'est pas initialisée.

Prochaine mesure utile (pas encore faite) : poser un point d'arrêt sur les
**retours** des 5 appels (`sceSblDriverSendMsg+0x...`) et lire `rdi` au moment de
l'échec, pour savoir quelle valeur est nulle dans la structure. C'est la seule
information qui manque pour écrire le modèle.

## Leçon de méthode

Un point d'arrêt qui ne se déclenche jamais ne prouve pas « la fonction n'est pas
appelée » avant d'avoir validé que les points d'arrêt sur adresses noyau
fonctionnent. Le point de contrôle sur `btext` est obligatoire : QEMU + trampoline
peut très bien ne jamais exposer les KVA au debugger si l'attache est tardive
(`-S` est requis).
