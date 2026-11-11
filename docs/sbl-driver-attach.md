# Lane 1 — Mailbox : qui remplit `[0xffffffffa18e9fd0]` ?

Statut : **cause racine trouvée et mesurée**. Le point 4 donne un patch d'octets
exact, et dit honnêtement ce qu'il ne résout pas.

Toutes les adresses sont des adresses virtuelles du dump
`/tmp/ps5-1360-dump/kernel-13.60-live.bin`
(`kernel_text @ 0xffffffff9e3f0000` offset 0, `kernel_data @ 0xffffffff9f0b0000`
offset `0xCC0000`). Les offsets fichier de `wp3_boot/kernel_raw.bin` sont
identiques (vérifié plus bas, §4.1).

---

## Résumé en cinq lignes

1. `0xffffffff9e8268b0` n'est pas une fonction de la mailbox : c'est la méthode
   **`attach` du pilote newbus `pci/sbl_driver`** (`FUN_ffffffff9e8268b0`,
   1624 octets, `0xffffffff9e8268b0`→`0xffffffff9e826f07`).
2. Elle n'est joignable que par **un pointeur de méthode dans un device tree**,
   jamais par un `call rel32` : son unique référence est
   `[0xffffffff9feb1408] = 0xffffffff9e658550` (thunk `jmp 0x9e8268b0`), dans
   l'enregistrement `pci/sbl_driver` du device tree noyau.
3. Le device parent de ce noeud est un device **PCI** (`device_type = "pci"`,
   `pci/sbl_driver`, `sbl_driver_pci`). Le pilote exige le couple
   **vendor `0x1022` / device `0x13ec`** (AMD "Oberon PSP"), lu dans l'espace de
   configuration PCI.
4. Mesure : sous GDB, sur un boot identique (1436 lignes), le point d'arrêt sur
   `0x9e826740` (**le `probe` du même pilote, juste avant dans la table**) fait
   **0 hit**, et `0x9e8268b0` **0 hit**, alors que le point de contrôle
   `0x9e642a90` fait 1 hit et `sceSblDriverSendMsg` 5 hits. Le noyau ne parcourt
   donc jamais ce pilote : soit le device n'existe pas sur le bus, soit le bus
   lui-même n'existe pas.
5. Le device n'existe pas : le log guest n'énumère que
   `8086:1237, 8086:7000, 8086:7010, 8086:7113, 1234:1111, 8086:100e`.
   Aucun `1022:13ec`, aucune chaîne `Oberon PSP` / `sbl_driver` / `13ec`.

---

## 1. Désassemblage complet de `0xffffffff9e8268b0`

### 1.1 Identité et taille

```
$ grep -n "9e8268b0" /tmp/sblre/kernel-13.60-text_symbols.tsv
4726:ffffffff9e8268b0	FUN_ffffffff9e8268b0	1624	[[ffffffff9e8268b0, ffffffff9e826f07]]
```

Taille réelle **1624 octets**, plage `0xffffffff9e8268b0`–`0xffffffff9e826f07`,
suivie de `nop` (`90`) jusqu'à `0xffffffff9e826f0f` puis de la fonction suivante
`0xffffffff9e826f10`. Voisins dans la table :

```
4724:ffffffff9e826720	FUN_ffffffff9e826720	20
4725:ffffffff9e826740	FUN_ffffffff9e826740	353
4726:ffffffff9e8268b0	FUN_ffffffff9e8268b0	1624
4727:ffffffff9e826f10	FUN_ffffffff9e826f10	316
4728:ffffffff9e827050	FUN_ffffffff9e827050	8
```

### 1.2 Prologue (octets du dump)

```
ffffffff9e8268b0: 55                    push   %rbp
ffffffff9e8268b1: 48 89 e5              mov    %rsp,%rbp
ffffffff9e8268b4: 41 57                 push   %r15
ffffffff9e8268b6: 41 56                 push   %r14
ffffffff9e8268b8: 41 55                 push   %r13
ffffffff9e8268ba: 41 54                 push   %r12
ffffffff9e8268bc: 53                    push   %rbx
ffffffff9e8268bd: 48 83 ec 18           sub    $0x18,%rsp
ffffffff9e8268c1: 4c 8d 3d 48 5a 4e 03  lea    0x34e5a48(%rip),%r15   # 0xffffffffa1d0c310 (stack canary)
ffffffff9e8268c8: 49 89 fe              mov    %rdi,%r14             # r14 = device_t
ffffffff9e8268cb: 49 8b 07              mov    (%r15),%rax
ffffffff9e8268ce: 48 89 45 d0           mov    %rax,-0x30(%rbp)
ffffffff9e8268d2: e8 39 c2 e7 ff        call   0xffffffff9e6a2b10   # device_get_softc
```

`device_get_softc` est confirmé par le corps du callee :

```
ffffffff9e6a2b10: 55              push   %rbp
ffffffff9e6a2b11: 48 89 e5        mov    %rsp,%rbp
ffffffff9e6a2b14: 48 8b 87 88 00 00 00  mov 0x88(%rdi),%rax
ffffffff9e6a2b1c: c3              ret
```

Donc **`rdi` = `device_t`** et **`rbx` = softc** (`0x9e8268d7: mov %rax,%rbx`).
C'est la signature `attach(device_t)`, pas celle d'une fonction mailbox.

### 1.3 Ce que la fonction construit

Les chaînes référencées par les `lea` du corps identifient sans ambiguïté le
sous-système (lecture directe des octets) :

| Adresse | Chaîne |
|---|---|
| `0xffffffff9f6f724b` | `SblDrvInHdlrMtx` |
| `0xffffffff9f67b0b2` | `SblDrvRcvdBmpSx` |
| `0xffffffff9f789d39` | `SblDrvHdlrSx` |
| `0xffffffff9f774f47` | `SblDrvSendSx` |
| `0xffffffff9f72b4f1` | `SblDrvTskQ` |
| `0xffffffff9f67b0c2` | `sbldrvtaskq` |
| `0xffffffff9f65de8f` | `sbl_initialize` |
| `0xffffffff9f6b8f22` | `ERROR: %s(%d) failed to allocate task queue\n` |

Séquence (adresses exactes) :

```
0x9e8268da  call 0x9e826240                  # allocateur/registre des Sx
0x9e8268e6  SblDrvInHdlrMtx
0x9e8268f4  call 0x9e8b7dd0                  # sx_init(&a18ea1c8, "SblDrvInHdlrMtx", ...)
0x9e826909  call 0x9e8b7dd0                  # sx_init(&a18ea018, "SblDrvRcvdBmpSx")
0x9e826920  call 0x9f03b290                  # &a18e9fd8, "SblDrvHdlrSx"
0x9e826935  call 0x9f03b290                  # &a18ea028, "SblDrvSendSx"
0x9e826946  call 0x9e648ff0                  # init &a18ea600, 0xc0
0x9e826965  call 0x9e8da760                  # taskqueue_create("SblDrvTskQ", ...)
0x9e82696a  mov  %rax,0xa18ea6c0             # -> [0xffffffffa18ea6c0]
0x9e826974  je   0x9e826b5b                 # echec -> "failed to allocate task queue", retour 0xc
0x9e826994  call 0x9e8db820                  # taskqueue_set_callback(..,"sbldrvtaskq",..,0x3f)
```

Puis il installe 3 groupes de callbacks (`c7 05 .. =0`, `mov %rax,..=0x9e65a850`,
`mov %rcx,..` à `0x9e8269aa`, `0x9e8269b4`, `0x9e8269bb`), et appelle un
dispatcher sur un objet du device :

```
0x9e8269c2  call 0x9e6a3af0                  # device_get_devclass/ivars
0x9e826a12  ja   0x9e826eb8                 # borne de table -> panic "bad entry"
0x9e826a1e  call *%r12                       # methode #0 : config/lecture
0x9e826a4d  call 0x9e6a7700                  # bus_alloc_resource(dev,3,...)
0x9e826a52  mov  %rax,0x10(%rbx)             # softc+0x10 = ressource
0x9e826a59  je   0x9e826baf                 # echec -> error 6
0x9e826aa6  call *%r12                       # methode #1
0x9e826acb  je   0x9e826c2d                 # -> poursuite (cf. §1.4)
```

Deux `bus_alloc_resource` : `0x9e826a4d` avec `esi=3` (SYS_RES_IRQ) et
`0x9e826c56` avec `esi=1` (SYS_RES_MEMORY, stockée en `softc+0x20` après
`0x9e826c46: c7 43 18 01 00 00 00` = `rid 1`).

### 1.4 La séquence exacte qui écrit `[0xffffffffa18e9fd0]`

Cinq instructions, à la toute fin :

```
ffffffff9e826ea6: 31 c0                 xor    %eax,%eax
ffffffff9e826ea8: 48 89 1d 21 31 0c 03  mov    %rbx,0x30c3121(%rip)   # 0xffffffffa18e9fd0
ffffffff9e826eaf: eb c5                 jmp    0xffffffff9e826e76
ffffffff9e826e76: 49 8b 0f              mov    (%r15),%rcx           # canary
...
ffffffff9e826e8d: c3                    ret
```

`rbx` = **softc du device PCI**, et l'épilogue retourne **0** (succès).
Donc `[0xa18e9fd0]` = « le softc du device `sbl_driver` PCI », publié comme
handle global du contrôleur de mailbox.

Chemin d'accès unique vers ce store (vérifié : `grep -n "9e826ea8\|9e826e8e\|9e826e66"` ne
donne qu'une occurrence de chaque, et aucun autre saut ne cible `0x9e826ea8`) :

```
0x9e826c8a  call 0x9e6a78e0        # bus_setup_intr / config (ressource IRQ)
0x9e826c91  je   0x9e826e66        # si retour == 0
0x9e826e66  call 0x9e827220        # <- gate A
0x9e826e6b  test %eax,%eax
0x9e826e6d  je   0x9e826e8e        # si gate A == 0
0x9e826e8e  mov  %rbx,%rdi
0x9e826e91  call 0x9e8272f0        # <- gate B (PCI AER / device_ids)
0x9e826e96  call 0x9e827730        # <- gate C (OTP)
0x9e826ea2  test %eax,%eax
0x9e826ea4  jne  0x9e826e76        # si gate C != 0 : PAS de publication, retour != 0
0x9e826ea6  xor  %eax,%eax
0x9e826ea8  mov  %rbx,[0xa18e9fd0] # publication
```

Deux conditions d'entrée **indépendantes** avant l'écriture :

* **gate C** (`0x9e827730`) : cinq appels `vmmcall` (hyperviseur) sur les IDs
  `0x14, 0x16, 0x17, 0x19, 0x1a` ; tout échec ⇒ `hv_restore_pt_tmr[%d] failed: %d`,
  retour ≠ 0, pas de publication. Code : `0x9e827737`–`0x9e827794`.
* **gate A** (`0x9e827220`) : lecture de deux valeurs par `0x9f0a5a50`
  (table `[0xa0ff93c0]`/`[0xa0ff93d8]`) puis `0x9f006f10` (`vmmcall` id 0x1e/0x1f).

---

## 2. Tous les appelants de `0xffffffff9e8268b0`

### 2.1 Le motif demandé (`b0 68 82 9e ff ff ff ff`) donne **0 hit**

```
$ python3 ... search b'\xb0\x68\x82\x9e\xff\xff\xff\xff'
raw 8-byte hits: 0
```

Normal : un pointeur de méthode dans une table **n'est pas** un `call rel32`.

### 2.2 Balayage `E8`/`E9` sur tout le dump : **un seul** hit, et c'est un thunk

```
$ python3 ... scan e8/e9 rel32 -> target 0xffffffff9e8268b0
== target 0xffffffff9e8268b0: 1 hits
   call at off=0x25dc30 va=0xffffffff9e64dc30 op=e9 rel=0x1d8c7b bytes=e97b8c1d00
```

Désassemblage autour (c'est une **table de thunks** de 8 octets : `E9 rel32`
puis 3× `cc`) :

```
ffffffff9e64dc28: e9 13 8b 1d 00   jmp 0xffffffff9e826740
ffffffff9e64dc2d: cc cc cc
ffffffff9e64dc30: e9 7b 8c 1d 00   jmp 0xffffffff9e8268b0   <-- notre entree
ffffffff9e64dc35: cc cc cc
ffffffff9e64dc38: e9 d3 92 1d 00   jmp 0xffffffff9e826f10
ffffffff9e64dc40: e9 0b 94 1d 00   jmp 0xffffffff9e827050
ffffffff9e64dc48: e9 13 94 1d 00   jmp 0xffffffff9e827060
```

Table complète : `0xffffffff9e64d410` → `0xffffffff9e6552d8`, **4057 entrées**,
index de notre thunk = **260**. Aucune référence (aucun `qword`, aucun
`lea rel32`) à la base `0x9e64d410` : cette table est atteinte par un autre
mécanisme (les thunks sont appelés par leur adresse, cf. 2.3).

### 2.3 La vraie référence : un pointeur de méthode dans un device tree

Recherche de l'adresse du **thunk** `0xffffffff9e64dc30` en `qword` :

```
abs 8-byte refs to 0xffffffff9e64dc30: 1
  off=0xe764c8 va=0xffffffff9f2664c8 ctx=...30dc649effffffff
```

Voisinage de `0xffffffff9f2664b8` (structure à paires `{clé, valeur}`) :

```
0xffffffff9f2664b0: 0xffffffff9fec7e58  (-> id 0x17 = 23)
0xffffffff9f2664b8: 0xffffffff9e64dc28  (= thunk de 0x9e826740)
0xffffffff9f2664c0: 0xffffffff9fec7e88  (-> id 0x18 = 24)
0xffffffff9f2664c8: 0xffffffff9e64dc30  (= thunk de 0x9e8268b0)
0xffffffff9f2664d0: 0xffffffff9fec7ea0  (-> id 0x19 = 25)
0xffffffff9f2664d8: 0xffffffff9e64dc38  (= thunk de 0x9e826f10)
```

C'est une **table de méthodes indexée par ID** (0x17,0x18,0x19,0x0e,0x0f,0x10…),
dont `0xffffffff9feb1220` détient la copie « driver » :

```
0xffffffff9feb1218: 0xffffffff9f699bc7  "sbl"
0xffffffff9feb1220: 0xffffffff9f2664b0  <- la table ci-dessus
0xffffffff9feb1228: 0x0000000000000030  (0x30 entrees)
```

Et le noeud qui porte les **méthodes du device** :

```
0xffffffff9feb1400: 0xffffffff9f789d6a   "pci/sbl_driver"
0xffffffff9feb1408: 0xffffffff9e658550   -> jmp 0xffffffff9e6a8180
0xffffffff9feb1410: 0xffffffff9feb1418
```

Le thunk `0x9e658550` mène à `0x9e6a8180`, de forme **modevent**
(`(devclass, event, arg)` avec test `esi==3 / esi==1 / esi==0`), et `esi==0`
appelle **`*%r12`** = `[arg]` = la méthode du device :

```
ffffffff9e6a81c8: 4c 8b 23        mov  (%rbx),%r12
ffffffff9e6a81ce: 74 2d           je   0xffffffff9e6a81fd
ffffffff9e6a81d0: 48 8d 0d e1 0a fb ff  lea -0x4f51f(%rip),%rcx  # 0xffffffff9e658cb8
ffffffff9e6a81f7: 41 ff d4        call *%r12
```

Autour de l'enregistrement, les noeuds frères nomment le pilote :

```
0xffffffff9feb1270: "sbl_driver_pci"
0xffffffff9feb12b0: "sbl_driver"
0xffffffff9feb1428: "pci"                  <- parent de bus
0xffffffff9feb12c0: "SblUnitSendMtx"
0xffffffff9feb12d8: "SblMsgBufMtx"
```

**Conclusion 2** : il n'y a aucun appel direct. `0x9e8268b0` est la méthode
`attach` du noeud `pci/sbl_driver`, invoquée par le newbus **seulement si un
device PCI correspondant s'attache**.

---

## 3. Pourquoi elle n'est pas appelée — mesuré, pas déduit

### 3.1 Le pilote exige vendor `0x1022` / device `0x13ec`

`0xffffffff9e826740` (le `probe`, 19 octets avant notre `attach` dans la table
de thunks, donc le même pilote) lit la config PCI via `bus_read_ivar` et teste :

```
ffffffff9e8267c2: ba 02 00 00 00      mov    $0x2,%edx      # ivar 2 = PCI vendor
ffffffff9e8267c7: 41 ff d7            call   *%r15
ffffffff9e8267ca: 0f b7 45 c8         movzwl -0x38(%rbp),%eax
ffffffff9e826820: ba 03 00 00 00      mov    $0x3,%edx      # ivar 3 = PCI device
ffffffff9e826825: 41 ff d7            call   *%r15
ffffffff9e826828: 81 7d c0 22 10 00 00  cmpl $0x1022,-0x40(%rbp)
ffffffff9e82682f: b8 06 00 00 00      mov    $0x6,%eax
ffffffff9e826834: 75 1d                 jne    0xffffffff9e826853   # pas AMD -> ENXIO
ffffffff9e826836: 0f b7 4d c8           movzwl -0x38(%rbp),%ecx
ffffffff9e82683a: 81 f9 ec 13 00 00     cmp    $0x13ec,%ecx
ffffffff9e826840: 75 11                 jne    0xffffffff9e826853   # pas 0x13ec -> ENXIO
ffffffff9e826842: 48 8d 35 d2 97 e6 00  lea    0xe697d2(%rip),%rsi  # 0xffffffff9f69001b
ffffffff9e826849: 48 89 df              mov    %rbx,%rdi
ffffffff9e82684c: e8 df d4 e7 ff        call   0xffffffff9e6a3d30   # device_set_desc
```

et la chaîne `0xffffffff9f69001b` est :

```
$ python3 ... read 0xffffffff9f69001b
' Oberon PSP'
```

« Oberon » = nom de code du PSP de la PS5. C'est **le** device de la mailbox SBL.

### 3.2 Mesure GDB : probe = 0 hit, attach = 0 hit, contrôles OK

Boot lancé avec le noyau et les options **exacts** de `bootkit/run.sh`
(`-M pc -cpu EPYC -m 3520M -smp 8`, même trampoline, même `kernel_raw.bin`,
md5 `520808c90b58241f454baeae0db0c8cc`), log redirigé vers `/tmp` (aucune
écriture dans le dépôt), breakpoints GDB :

```
$ gdb -q -batch -x /tmp/gdbcmds2.txt   # target remote 127.0.0.1:12399
$ grep -c HIT_CTRL_BTEXT /tmp/gdb2.out   -> 1
$ grep -c HIT_SENDMSG     /tmp/gdb2.out   -> 5
$ grep -c HIT_PROBE       /tmp/gdb2.out   -> 0
$ grep -c HIT_ATTACH      /tmp/gdb2.out   -> 0
$ wc -l /tmp/serial.gdb2.log              -> 1436
```

* `HIT_CTRL_BTEXT` (`0x9e642a90`, point de contrôle : il touche à coup sûr)
  = **1** ⇒ **les breakpoints sont bien armés**, la mesure est valide.
* `HIT_SENDMSG` (`0x9e825aa0`) = **5** ⇒ reproduit l'état déjà connu.
* `HIT_PROBE` (`0x9e826740`) = **0** ⇒ **le `probe` du pilote ne tourne jamais**.
* `HIT_ATTACH` (`0x9e8268b0`) = **0**.

C'est le point clé : ce n'est pas « l'attach est appelé mais échoue », c'est
**le pilote n'est jamais consulté**. Donc la condition manquante est en amont
de `probe`, c'est-à-dire dans l'**existence du device sur le bus**.

Un premier passage GDB avait donné 0 hit *sans* point de contrôle ; il ne
prouvait rien (breakpoints peut-être non armés). Le passage ci-dessus, avec
contrôle à 1 hit, est celui qui fait foi.

### 3.3 Le device n'existe pas dans la machine invitée

Le noyau énumère le bus PCI (c'est SeaBIOS qui parle, puis le noyau reprend) :

```
$ grep -oE "id=[0-9a-f]{4}:[0-9a-f]{4}" /tmp/serial.gdb2.log | sort -u
id=1234:1111
id=8086:100e
id=8086:1237
id=8086:7000
id=8086:7010
id=8086:7113
```

Et :

```
$ grep -c "Oberon PSP" /tmp/serial.gdb2.log   -> 0
$ grep -c "sbl_driver" /tmp/serial.gdb2.log   -> 0
$ grep -c "13ec"       /tmp/serial.gdb2.log   -> 0
```

Aucun `1022:13ec`. Le pilote ne peut donc pas matcher : `probe` n'est jamais
appelé, `attach` jamais, `[0xa18e9fd0]` jamais écrit, et
`sceSblDriverSendMsg` reçoit `rdi=[0xa18e9fd0]=NULL` → `0x40008000` (ENOMEM).
C'est cohérent avec les 18 lectures / 1 écriture déjà mesurées.

### 3.4 Second verrou, mesuré mais non établi comme bloquant

Le log contient, avant les erreurs SBL :

```
1232: The ACPI driver cannot be loaded after boot.
```

Le code correspondant (`0xffffffff9efe4fc0`, chemin `MOD_LOAD` `esi==0`) :

```
ffffffff9efe4fcd: 83 3d 8c 0a 97 01 00  cmpl $0x0,0xffffffffa0955a60
ffffffff9efe4fd4: 75 2f                 jne  0xffffffff9efe5005
ffffffff9efe4fd6: 48 8d 3d 27 97 68 00  lea  0xffffffff9f66e704  # le message
ffffffff9efe4fdf: e8 2c 84 66 ff        call 0xffffffff9e64d410
ffffffff9efe4fe4: b8 01 00 00 00        mov  $0x1,%eax        # retour 1 = echec
```

Le flag `[0xffffffffa0955a60]` vaut 0 au moment du `MOD_LOAD` (sa seule
écriture « en clair » est `0xffffffff9e7c3f10: movl $0x0,...`), et n'est armé
que par le modevent `esi==1` (post-boot).

Conséquence plausible : pas de bus ACPI ⇒ pas de `pcib`/`pci` newbus côté
noyau. **Mais je n'ai pas mesuré l'arbre newbus** : le noyau n'imprime pas ses
attaches (`grep -cE "^[a-z0-9]+[0-9]*: <"` = 4 lignes, toutes triviales :
`mem`, `null`, `io`, `acm`). Le lien de causalité ACPI → absence de bus PCI est
donc **non établi**. C'est la mesure suivante à faire (cf. §4.4).

---

## 4. Conclusion : condition d'entrée manquante et correction minimale

### 4.1 Condition d'entrée manquante (établie)

> Un device PCI avec **vendor ID `0x1022`, device ID `0x13ec`**, présent sur un
> bus PCI **du noyau invité** (pas seulement dans SeaBIOS), pour que le noeud
> `pci/sbl_driver` du device tree s'attache et publie son softc dans
> `[0xffffffffa18e9fd0]` à `0xffffffff9e826ea8`.

Tant que ce device n'existe pas, **aucun patch de la mailbox ne peut aider** :
le code d'envoi est correct, c'est le contrôleur qui n'est jamais instancié.

### 4.2 Pourquoi le patch « sauter gate C » ne suffit pas — mesuré

Gate C (`0x9e827730`) est une suite de `vmmcall` (`0x9f006f30` =
`mov $0x15,%eax; vmmcall`). Sous QEMU/TCG ce sont des `#UD`. Le noyau les
patche déjà en `mov $1,%eax; nop` (676 patches de `wp3_boot/patches.inc`,
entrées `db 15,1,217` → `db 49,192,144`). Donc gate C renvoie 0.

Mais le vrai mur est **avant** : `0x9e826c8a call 0x9e6a78e0` (mise en place de
l'interruption) et `0x9e826a4d call 0x9e6a7700` (`bus_alloc_resource`,
`0x9e6a7711: mov 0x28(%rdi),%r14; test; je 0xffffffff9e6a77b4` → échec si le
parent n'a pas de `rman`). Sans device PCI réel, pas de parent PCI, donc
`bus_alloc_resource` échoue, donc la fonction retourne par `0x9e826baf`
(`error 6`) sans jamais atteindre `0x9e826ea8`.

Sauter le contrôle de taille sans device ne produirait qu'un softc vide sans
ressource : `[0xa18e9fd0]` serait non-NULL mais `softc+0x10` (la ressource)
serait absurde, et `sceSblDriverSendMsg` (`0x9e825aae: mov 0x10(%rdi),%rcx`)
déréférencerait n'importe quoi. **À ne pas faire.**

### 4.3 Correction proposée — étape 1 (QEMU, obligatoire)

Il faut un device PCI `1022:13ec` sur le bus de la machine `pc`. Vérifié : le
QEMU 8.2.10 du projet n'expose **aucune** propriété `x-pci-vendor-id` sur les
devices PCI génériques, donc on ne peut pas réutiliser un device existant :

```
$ qemu-system-x86_64 -device edu,help | grep -i x-pci
  x-pcie-ari-nextfn-1=<bool> ...
  x-pcie-err-unc-mask=<bool> ...
  x-pcie-extcap-init=<bool> ...
  x-pcie-lnksta-dllla=<bool> ...
$ qemu-system-x86_64 -device pci-testdev,help | grep -i "x-pci-vendor"  -> (rien)
```

Donc : petit device stub dans `qemu-src`, du type de `hw/misc/ps5_otpmailbox.c`
déjà présent, avec

```c
.vendor_id = PCI_VENDOR_ID_AMD,   /* 0x1022 */
.device_id = 0x13ec,
.class_id  = PCI_CLASS_SYSTEM_OTHER,
```

un BAR mémoire de `0x20000` (taille mesurée dans le pilote : la ressource
`rid 1` est allouée puis mappée par `0x9e827301`… ; `0x9e82764e` écrit à
l'offset `0x10558` de la base — cohérent avec une fenêtre ≥ `0x11000`), et
l'ajout dans `hw/misc/meson.build`. **Non testé** : je n'ai pas compilé ce
device, et je ne modifie pas `qemu-src` depuis cette lane.

Note importante : le device doit être présent **avant** le boot du noyau pour
que le bus PCI invité l'énumère ; un device ajouté par `-device` sur `-M pc`
apparaît bien dans SeaBIOS (mesure : 6 devices listés ligne 18).

### 4.4 Correction proposée — étape 2 (noyau), seulement si nécessaire

Une fois le device présent, deux issues possibles, et une seule est acceptable :

* Si le noyau crée son bus PCI et attache `pci/sbl_driver` : `[0xa18e9fd0]`
  est rempli par le code d'origine. **Aucun patch noyau.** C'est l'objectif.
* Si le noyau ne crée pas de bus (cf. §3.4, ACPI), il faut d'abord traiter
  `[0xffffffffa0955a60]`, pas la mailbox.

Le seul patch noyau que je propose, **uniquement** pour rendre l'attach
tolérant à un softc de taille réduite si l'on veut tester sans le device réel,
porte sur le contrôle de taille de la table de méthodes :

```
Adresse virtuelle : 0xffffffff9e826f9f
Offset fichier    : 0x00436f9f      (= 0x9e826f9f - 0x9e3f0000)
Octets actuels    : 48 3d a5 03 00 00      (cmp $0x3a5,%rax)
Octets attendus   : 48 3d 01 00 00 00      (cmp $0x1,%rax)
```

Vérification des octets sur le noyau réellement booté :

```
$ python3 ... kernel_raw.bin @0x436f9f
cmp $0x3a5 at 0x9e826f9f: off=0x436f9f bytes=48 3d a5 03 00 00
ja  at 0x9e826fa5:        off=0x436fa5 bytes=0f 87 8d 00 00 00
store at 0x9e826ea8:      off=0x436ea8 bytes=48 89 1d 21 31 0c 03
```

Entrée correspondante au format de `wp3_boot/patches.inc`
(`dd phys ; dd len ; db bytes`, avec `phys = va - 0x9e3f0000`, comme le montre
l'exemple existant `dd 0x00c16a19 ; phys 0x1f006a19 — vmmcall@0xffffffff9f006a19`) :

```asm
    dd 0x00436f9f          ; phys 0x436f9f — cmp $0x3a5,%rax @0xffffffff9e826f9f
    dd 6
    db 0x48,0x3d,0x01,0x00,0x00,0x00
```

**Ce patch est un instrument de diagnostic, pas un correctif** : il permet de
voir si l'attach va plus loin, mais il ne remplace pas le device PCI (§4.3).
Je ne l'ai pas appliqué et je ne modifie pas `wp3_boot/kernel_raw.bin`.

### 4.5 Ce que cette lane change dans le diagnostic global

`docs/MAILBOX-PATH.md` concluait « le chemin qui écrit `0xa18e9fd0` n'est jamais
exécuté ; l'attach SPM `0x9e827730` n'a ni appelant ni référence — ce n'est pas
le chemin ». C'est **à corriger sur un point** : `0x9e827730` n'a en effet aucun
appelant direct, mais son appelant est **`0x9e8268b0` lui-même**, à
`0x9e826e96` (`call 0xffffffff9e827730`). C'est bien le chemin, mais un chemin
qui ne démarre jamais parce que le device PCI `1022:13ec` est absent.

---

## Annexe — commandes reproductibles

```bash
# 1. taille / entrée de fonction
grep -n "9e8268b0" /tmp/sblre/kernel-13.60-text_symbols.tsv

# 2. désassemblage complet
objdump -D -b binary -m i386:x86-64 --adjust-vma=0xffffffff9e3f0000 \
  --start-address=0xffffffff9e8268b0 --stop-address=0xffffffff9e826f10 \
  /tmp/ps5-1360-dump/kernel-13.60-live.bin

# 3. recherche du motif demandé (0 hit) puis balayage E8/E9 (1 hit = thunk)
python3 -c "import struct;d=open('/tmp/ps5-1360-dump/kernel-13.60-live.bin','rb').read();print(d.find(struct.pack('<Q',0xffffffff9e8268b0)))"

# 4. mesure des breakpoints (log hors dépôt)
cd bootkit && qemu-system-x86_64 -L ./bios -M pc -cpu EPYC -m 3520M -smp 8 \
  -kernel wp3_boot/trampoline.elf -initrd wp3_boot/kernel_raw.bin \
  -display none -serial null -monitor none \
  -chardev file,id=dbg,path=/tmp/serial.gdb2.log \
  -device isa-debugcon,iobase=0x402,chardev=dbg -no-reboot -S -gdb tcp:127.0.0.1:12399
```
