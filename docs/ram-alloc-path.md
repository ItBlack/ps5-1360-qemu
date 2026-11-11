# 09 — Allocateur : pourquoi `kmem_alloc_contig` renvoie ENOMEM (12)

Statut : **lane ALLOCATEUR**, complementaire de `02-ram.md` (qui cherche la table
de disposition). Les 4 points demandes sont traites. Le point 4 conclut
**`regle non trouvee`** : aucune correction minimale n'est prouvee. Les deux
sites candidats sont donnes avec octets exacts, mais etiquettes **non prouves**.

Conventions de preuve (identiques a `02-ram.md`) :

```
DUMP = /tmp/ps5-1360-dump/kernel-13.60-live.bin
       103 546 880 o
       sha256 c3f745e25dc25ee7afef89eb418b295b6334bbefe8aa17e6886483c35d78cddd
texte : base 0xffffffff9e3f0000, offset fichier 0        (13 369 344 o)
data  : base 0xffffffff9f0b0000, offset fichier 0xCC0000 (90 177 536 o)

objdump -D -b binary -m i386:x86-64 --adjust-vma=0xffffffff9e3f0000 \
        --start-address=ADDR --stop-address=ADDR2 DUMP

conversion offset data : off = VA - 0xffffffff9f0b0000 + 0xCC0000
```

Avertissement du dump lui-meme (`kernel-13.60-live.bin.json`) :

```
"unmapped_data_ranges": [{"start_page": 21328, "end_page": 22016}],
"unmapped_data_pages": 688,
"warning": "unmapped data pages are zero-filled; ..."
```

Ces 688 pages zero-fill couvrent les offsets fichier `0x5350000..0x5600000`
(page 21328 -> `0x5350000`, page 22016 -> `0x5600000`), soit les VA
data `0xffffffffa3740000..0xffffffffa39f0000`. **Aucune VA citee dans ce
document ne tombe dans cette plage** (la plus haute citee est
`0xffffffffa21cb478`, tres en dessous de `0xffffffffa3740000`) : tous les octets
lus ci-dessous sont des octets reels du dump, pas du zero-fill.

Faits deja mesures (non re-mesures ici, repris de la lane 2) : 7 modules en
ENOMEM (`SceIpmiMgr cam dce hdmi pcist pfsmgr sdma`), 14 `kthread_add error 12`,
2 `kproc_create error 12`, 1 `kmem_alloc_contig error`, `Flexible memory
(system)` = 2168 Mio a `-m 2G` comme a `-m 3520M`.

---

## 1. Qui imprime, quelle taille, quels flags

### 1.1 Localisation des chaines (mesure)

```
$ python3 -c "... find(b'%s kmem_alloc_contig error') ..."
gc_allocate_system_memory_for_dir              off 0x13b540a  VA 0xffffffff9f7a540a
%s kmem_alloc_contig error\n                   off 0x12f298c  VA 0xffffffff9f6e2989
kmem_alloc_contig error\n                      off 0x136bd2a  VA 0xffffffff9f75bd2a
ring allocation failed %d\n                    off 0x12ff195  VA 0xffffffff9f6ef195
%s can't allocate system memory for suspended_vm dir   VA 0xffffffff9f71233c
failed to init TEE Ring                        VA 0xffffffff9f692525
```

### 1.2 Site d'impression principal : `FUN_ffffffff9edd3950` (2169 o)

```
$ objdump ... --start-address=0xffffffff9edd3ee0 --stop-address=0xffffffff9edd3fc0

ffffffff9edd3f6a: 41 b8 ff ff ff ff   mov    $0xffffffff,%r8d
ffffffff9edd3f70: 41 b9 00 20 00 00   mov    $0x2000,%r9d
ffffffff9edd3f76: ba 02 01 00 00      mov    $0x102,%edx
ffffffff9edd3f7b: 31 c9               xor    %ecx,%ecx
ffffffff9edd3f7d: 48 8b 3e            mov    (%rsi),%rdi
ffffffff9edd3f80: be 00 10 00 00      mov    $0x1000,%esi
ffffffff9edd3f85: 6a 06               push   $0x6
ffffffff9edd3f87: 6a 00               push   $0x0
ffffffff9edd3f89: e8 62 fb b1 ff      call   0xffffffff9e8f3af0
ffffffff9edd3f8e: 48 83 c4 10         add    $0x10,%rsp
ffffffff9edd3f92: 48 85 c0            test   %rax,%rax
ffffffff9edd3f95: 74 13               je     0xffffffff9edd3faa      <-- echec
ffffffff9edd3faa: 48 8d 3d d8 e9 90 00 lea 0xffffffff9f6e2989,%rdi
ffffffff9edd3fb1: 48 8d 35 52 14 9d 00 lea 0xffffffff9f7a540a,%rsi
ffffffff9edd3fba: e8 51 94 87 ff      call   0xffffffff9e64d410      <-- printf
```

Donc `%s` = `"gc_allocate_system_memory_for_dir"` et le format =
`"%s kmem_alloc_contig error\n"`. La ligne 1256 du log est bien produite ici.

**Taille demandee : `0x1000` = 4096 octets (4 Kio).** Ce n'est pas une grosse
allocation. `9e8f3800` l'arrondit ensuite a `0x4000` (16 Kio) :

```
$ objdump ... --start-address=0xffffffff9e8f3883
ffffffff9e8f3883: 49 81 c6 ff 3f 00 00  add    $0x3fff,%r14
ffffffff9e8f3894: 49 81 e6 00 c0 ff ff  and    $0xffffffffffffc000,%r14
```

**Flags : `edx = 0x102`** = `M_WAITOK (0x2) | M_ZERO (0x100)`.
Autres parametres du site : `r9d = 0x2000`, `r8d = 0xffffffff` (borne haute de
l'allocation, donc 4 GiB-1), `ecx = 0` (borne basse), args de pile `6` et `0`.

### 1.3 Autres sites d'echec mesures

`FUN_ffffffff9ea8c820` (245 o) — imprime `ring allocation failed %d\n`, puis
`failed to init TEE Ring`, avec la chaine `mp3` :

```
ffffffff9ea8c840: c7 05 f4 6f 26 03 00 00 00 00   movl $0x0,0xffffffffa1926460
ffffffff9ea8c84a: be 00 80 00 00                  mov  $0x8000,%esi     <-- 32768 o
                  edx=0x101  (M_NOWAIT|M_ZERO)   ecx=0  r8d=0xffffffff
                  r9d=0x4000  push 6  push 0
```

`FUN_ffffffff9ee02ef0` (289 o) — meme wrapper, `esi=0x4000`, `edx=0x102`,
`r9d=0x4000`.

Difference de flags a retenir : le ring TEE demande `0x101` =
**`M_NOWAIT|M_ZERO`**. Une allocation `M_NOWAIT` ne peut ni dormir, ni
defragmenter, ni evincer : elle echoue des que le bloc contigu n'est pas
disponible immediatement, et renvoie `-12`. Le site `gc_allocate` est en
revanche `M_WAITOK`.

### 1.4 Chaine d'appel (mesuree)

```
FUN_ffffffff9edd3950  (imprime) 
   -> 0xffffffff9e8f3af0   wrapper : choisit l'arene puis appelle kmem_alloc_contig
      -> 0xffffffff9e8f3800  kmem_alloc_contig (738 o)
         -> 0xffffffff9e9d6730  seuil "petite allocation contigue"
            -> 0xffffffff9e9d67c0  chemin general (taille > seuil)
               -> 0xffffffff9ef7ad50  allocation contigue avec controle de plafond par domaine
                  -> 0xffffffff9ea06050  parcours vm_phys par domaine
                  -> 0xffffffff9e82b880  allocateur de pages (gate "minfree")
```

Selected arene : le wrapper `9e8f3af0` choisit entre 4 globales
(`0xffffffffa190e2b0`, `0xffffffffa190e640`, `0xffffffffa190e0e8`,
`0xffffffffa190e478`) puis passe `movzbl 0x150(%rdx),%esi` comme indice de
domaine. Mesure : `a190e0e8+0x150 = 0` et `a190e0e8+0x9d = 4` (donc le
selecteur `9e8551c0` retourne 0, pas 7) → **domaine 0**.

---

## 2. Memoire REELLE ou REGLE ? — reponse mesuree

### 2.1 Le pool « flexible » n'est pas epuise

Globales du pool, lues dans le dump :

```
0xffffffffa1925f10 = 138739   (0x21df3)  total pages du pool flexible
0xffffffffa1925f14 =    206   (0xce)     consomme A
0xffffffffa1925f18 =   2974
0xffffffffa1925f1c =    898
0xffffffffa1925f20 =  25960   (0x6568)   consomme C
0xffffffffa1925f24 =  24096   (0x5e20)   consomme B
0xffffffffa1925f2c =   4461
0xffffffffa1925f38 =     10
0xffffffffa1925f3c =      2
0xffffffffa1925f40 =    552
```

Arithmetique, avec page = 16 Kio (`arena+0x400 = 0xe`, `shl $0xe`) :

```
138739 * 16384 = 2273099776 = 0x877CC000   -> exactement la ligne 153 du log
206 + 24096 = 24302 pages = 379.7 Mio consommes
138739 - 24302 = 114437 pages = 1788.1 Mio libres
```

**Conclusion partielle : le pool flexible est libre a 1788 Mio sur 2168 Mio au
moment du dump. Une allocation de 4 Kio ne peut pas echouer par epuisement de
ce pool.** L'echec n'est donc pas, au premier niveau, une limite reelle de
memoire libre.

### 2.2 Mais un second shortage est mesure, independant du pool

Les 14 `kthread_add ... error 12` du log ne concernent pas le pool flexible :
`kthread_add` alloue une pile noyau + un `struct thread` dans l'espace noyau.
14 echecs consecutifs indiquent une pression sur l'arene noyau elle-meme, pas
sur le pool de pages flexible. Ce sont deux ressources distinctes et les deux
manquent.

Etat de l'arene pointee par `0xffffffff9fed8b10` :

```
*(0xffffffff9fed8b10) = 0xffffffffa1ab6800     (arene / vm_map)
*(0xffffffff9fed8b18) = 0xffffffffa1ab6f00     (comparee par le wrapper)

0xffffffffa1ab6800 + 0x3e0 = 0x800      (2048)
0xffffffffa1ab6800 + 0x3e8 = 0x0        <-- seuil "petite allocation contigue"
0xffffffffa1ab6800 + 0x3f0 = 0x3fff     (masque d'alignement)
0xffffffffa1ab6800 + 0x3f8 = 0x200000   (2 Mio)
0xffffffffa1ab6800 + 0x400 = 0xe        (shift page = 14 -> 16 Kio)
0xffffffffa1ab6800 + 0x408 = 0xffff8e7701dfd4c0
0xffffffffa1ab6800 + 0x410 = 0x4
```

Le seuil `+0x3e8` vaut **0**, et `9e9d6730` teste exactement ce champ :

```
ffffffff9e9d6746: 48 3b b7 e8 03 00 00   cmp 0x3e8(%rdi),%rsi
ffffffff9e9d674d: 76 2b                  jbe 0xffffffff9e9d677a   (chemin rapide)
   sinon -> 0xffffffff9e9d67c0 (chemin general, celui qui echoue)
```

Avec `+0x3e8 = 0`, **toute** allocation contigue, meme de 16 Kio, est detournee
vers le chemin general. C'est une regle de configuration, pas une mesure de
memoire libre.

Tables d'etat de l'allocateur de pages, mesurees :

```
tetes de freelist a arene+0xf8+i*8, fenetre utile i = 0..91 (92 tetes ; a
i = 92 la formule retombe sur arene+0x3d8, qui n'est plus une tete) :
**6 tetes non nulles sur 92**
   idx 0  = 0xffff8e7701dfdd40
   idx 34 = 0xffff8e7701da0780
   idx 37 = 0xffff8e7701da3b40
   idx 38 = 0xffff8e7777e02b00
   idx 90 = 0xffff8e770100a180
   idx 91 = 0xffff8e7777e02b00   (meme valeur qu'a idx 38, tel quel dans le dump)
   tous les autres idx = 0
   ATTENTION : idx 92..97 valent 0xffffff8008a1c000 / 0x800 / 0x3fff /
   0x200000 / 0xe mais ce ne sont PAS des tetes de freelist : a ces indices la
   formule retombe sur les champs scalaires arene+0x3d8/+0x3e0/+0x3f0/+0x3f8/
   +0x400. A ne pas lire comme des pointeurs.

compteurs par domaine @0xffffffffa2170604 + domaine*0x240
   dom 0 = 25960 pages (406 Mio)   dom 8 = 4096   dom 9 = 4096
   tous les autres = 0

compteurs par zone @0xffffffffa21704c0 + zone*4
   zones 0..15 = 0 ; zone 16..23 hors sujet (valeurs non-zone)

compteur d'echecs @0xffffffffa1cf2fa0 : idx 20 = 979
table de plafonds @0xffffffffa1cf2ff0 : dom 0 = 979 pages, dom 8 = 55, dom 9 = 55
```

### 2.3 Le test de plafond par domaine, lui, PASSE

`9ef7ad50` commence par un controle explicite avant tout parcours :

```
ffffffff9ef7adeb: 8b 54 0e 74            mov    0x74(%rsi,%rcx,1),%edx
ffffffff9ef7adf3: 8b 84 0e 94 00 00 00   mov    0x94(...),%eax
ffffffff9ef7adfa: 03 84 0e 80 00 00 00   add    0x80(...),%eax
ffffffff9ef7ae01: 4c 01 f2               add    %r14,%rdx        <-- r14 = nb pages demandees
ffffffff9ef7ae04: 48 39 c2               cmp    %rax,%rdx
ffffffff9ef7ae07: 76 2e                  jbe    0xffffffff9ef7ae37   (accepte)
   sinon -> 0xffffffff9ef7b009 : libere le verrou, `lock add %r14d` au compteur
            d'echec, `call 0xffffffff9ea828e0`, retourne 0  (ENOMEM)
```

Valeurs du domaine 0 (base `0xffffffffa1925ea0`, entree de 0x88) :

```
dom0 : +0x74 = 206   +0x78 = 2974   +0x7c = 898   +0x80 = 25960   +0x94 = 0
test : 206 + 1 = 207 <= 25960 + 0 = 25960   -> PASSE
```

Donc **le plafond par domaine n'est pas la cause**. Le refus vient plus bas,
dans le fournisseur de pages.

### 2.4 Ce qui refuse : le gate « minfree » de `9e82b880`

```
ffffffff9e82b95c: 41 0f b7 44 24 02   movzwl 0x2(%r12),%eax   ; nb pages libres
ffffffff9e82b962: 66 85 c0            test   %ax,%ax
ffffffff9e82b965: 0f 84 b5 00 00 00   je     ...  -> retourne NULL
ffffffff9e82b96b: 66 41 3b 44 24 04   cmp    0x4(%r12),%ax   ; vs seuil (lowat)
ffffffff9e82b971: 0f 82 a9 00 00 00   jb     ...  -> retourne NULL
```

C'est un **seuil (`lowat`) stocke par zone** : si `free_count < lowat`, l'appel
renvoie NULL meme s'il reste des pages. Le compteur de pages libres n'est pas
dans le dump (structures en memoire directe `0xffff8e77...`, hors des deux
sections reconstruites) : **la valeur exacte de `lowat` n'est donc pas etablie**.

### 2.5 Ce qui est etabli et ce qui ne l'est pas

| Affirmation | Statut |
|---|---|
| L'allocation qui echoue fait 4096 o (`0x1000`), arrondie a 16 Kio | **mesure** |
| Flags `0x102` = `M_WAITOK\|M_ZERO`, borne haute `0xffffffff`, domaine 0 | **mesure** |
| Le pool flexible a 1788 Mio libres sur 2168 Mio | **mesure** |
| L'echec n'est pas un epuisement du pool flexible | **mesure** (consequence directe) |
| Le plafond par domaine (`9ef7ad50`) passe pour 1 page | **mesure** |
| Le seuil `arene+0x3e8 = 0` detourne tout vers le chemin general | **mesure** |
| `kthread_add` echoue 14x : l'arene noyau est saturee separement | **faisceau d'indices**, cause non isolee |
| Le refus final vient du `lowat` de `9e82b880` | **plausible, non etabli** (compteur hors dump) |
| Il existe une zone/plage interdite codee en dur bloquant le contigu | **non etabli** |

---

## 3. Constantes suspectes : `0x877cc000`, `0x87800000`, `0x80000000`

### 3.1 `0x877cc000` — 3 occurrences, aucune n'est une regle de pool

Recherche little-endian, 8 octets :

| Offset | VA | Nature |
|---|---|---|
| `0x36c7320` | `0xffffffffa1ab7320` | donnee, qword `00 c0 7c 87 00 00 00 00` |
| `0x3ddb478` | `0xffffffffa21cb478` | donnee, qword idem (cache de taille flexible) |
| `0x9e9b9c0e` | `0xffffffff9e9b9c0e` | **faux positif** : `81 fb 00 00 00 c0` = `cmp $0xc0000000,%ebx` suivi de `jl` |

La seule imm32 `0x877cc000` du texte est ce `cmp $0xc0000000` : c'est un test de
signe, pas la constante de pool.

La vraie relation est arithmetique, pas litterale :

```
0x877cc000 = 2273099776 = 138739 * 16384 = (0xffffffffa1925f10) << 14
```

Le log confirme la provenance (`9edfecb2`) :

```
ffffffff9edfecb2: 8b 15 58 72 b2 02   mov 0xffffffffa1925f10,%edx
ffffffff9edfecc7: 48 c1 e2 0e         shl $0xe,%rdx
ffffffff9edfecd2: 48 c1 e9 14         shr $0x14,%rcx        ; -> Mio
```

et le meme calcul est refait a `9e93da89` (`mov 0xffffffffa1925f10,%eax`,
`shl $0x4`, clamp `0x180000`) puis a `9e67122e`
(`r14d = a1925f10 - (a1925f14 + a1925f24)`, `shl $0xe`).

### 3.2 `0x87800000` — absent du texte

Aucune imm32 `0x87800000` dans la section texte. **Non etabli** comme constante
de comparaison. (La valeur n'existe que comme approximation de `0x877cc000`.)

### 3.3 `0x80000000` — trop d'occurrences, non concluant

Nombreuses imm32 `0x80000000` dans le texte ; aucune ne peut etre reliee au
chemin d'allocation sans tracage supplementaire. **Non etabli.**

### 3.4 La valeur de dimensionnement, elle, est bien en dur

`FUN_ffffffff9edfd840` choisit la taille totale sur un index de mode pair/impair :

```
ffffffff9edfd865: 49 bd 00 00 00 00 04 00 00 00   movabs $0x400000000,%r13   ; 16 GiB
ffffffff9edfd8b3: 49 bd 00 00 00 00 08 00 00 00   movabs $0x800000000,%r13   ; 32 GiB
ffffffff9edfd87b / 9edfd8c5 : mov %..,0xffffffffa1fa5400   ; index de mode
```

Mode courant mesure : `0xffffffffa1fa5400 = 1` (PPR16, GDDR6 16 GiB), coherent
avec la ligne 145 du log. Table de modes a `0xffffffff9f280cd0`, entrees de
`0x60` ; entree 1 a `0xffffffff9f280d30` :

```
7f 2c 6f 9f ff ff ff ff  00 00 00 00 04 00 00 00
```

Globals de layout associees :

```
0xffffffffa1fa41b8 = 0x400000000   (16 GiB, taille totale)
0xffffffffa1fa41c8 = 0x3fc016000
0xffffffffa1fa41d0 = 0x944a000     (Kernel static size, = 149 Mio du log)
0xffffffffa1fa41d8 = 0x90c16000
```

`0xffffffffa1fa41d8` est ecrit par `9edf9648` a partir de la somme des plages
e820-like **plus** `0xffffffffa1fa54f0` (`add` a `9edf9636`). Ce terme ajoute
est ce qui rend la taille independante de `-m` : la valeur ne derive pas
directement de la memoire passee par l'hyperviseur.

---

## 4. Conclusion : correction minimale

### 4.1 Verdict

**`regle non trouvee`.**

Aucun site unique prouve ne transforme cet ENOMEM en succes. Ce qui est prouve :

1. la demande est minuscule (4 Kio, 16 Kio apres arrondi) ;
2. le pool flexible a 1788 Mio libres ;
3. le plafond par domaine passe (207 <= 25960) ;
4. le refus vient d'un gate de pages (`lowat` dans `9e82b880`) ou d'une
   defaillance de l'arene noyau, et **les compteurs correspondants ne sont pas
   dans le dump** (structures en memoire directe `0xffff8e77...`).

Il n'est donc pas possible, avec ce dump seul, de designer « l'octet a changer ».
Toute patch annoncee comme certaine serait une invention.

### 4.2 Sites candidats — octets exacts, **non prouves**

**Candidat A — seuil de contiguite `arene+0x3e8` (le plus probable).**
Champ a `0xffffffffa1ab6800 + 0x3e8` = `0xffffffffa1ab6be8`,
offset fichier `0x36C6BE8`.

```
avant : 00 00 00 00 00 00 00 00    (qword 0 : chemin rapide desactive)
apres : 00 40 00 00 00 00 00 00    (0x4000 = 16 Kio : reactive le chemin rapide)
```

Ce candidat ne change pas la quantite de memoire ; il change le chemin de code.
Il est **testable** et **reversible**. Il n'est **pas prouve** : rien ne dit que
le chemin rapide (`9e82b880` avec la freelist `arene+0x448+idx*8`) dispose de
pages, et la table `arene+0x448` est entierement nulle dans le dump.

**Candidat B — flag `M_NOWAIT` du ring TEE.**
Site `0xffffffff9ea8c84a` : `be 00 80 00 00` (taille `0x8000`), flags en `edx`.
Passer `0x101` (`M_NOWAIT|M_ZERO`) a `0x102` (`M_WAITOK|M_ZERO`) permettrait a
l'allocation du ring de dormir et de defragmenter au lieu d'echouer
immediatement. Cela ne corrigerait **pas** la ligne 1256 (`gc_allocate` est deja
en `M_WAITOK`) : c'est un correctif du symptome « ring allocation failed -12 »
et « failed to init TEE Ring », pas de la cause.

**Candidat C — mode memoire (hors perimetre de cette lane).**
Table `0xffffffff9f280cd0` entree 1 ou global `0xffffffffa1fa41b8`. Changer
16 GiB -> 32 GiB ne corrige pas un echec de 4 Kio : ecarte.

### 4.3 Ce qu'il faut mesurer pour conclure

Pour transformer « non etabli » en « prouve », il faut des compteurs runtime que
le dump ne contient pas :

1. la valeur de `lowat` et de `free_count` par zone (structure `0xffff8e77...`) ;
2. le retour exact de `9e82b880` pendant l'echec (NULL immediat ou apres
   parcours complet) ;
3. l'etat de l'arene noyau au moment des 14 `kthread_add error 12` — c'est le
   symptome le plus parlant : une arene noyau saturee expliquerait a la fois les
   threads et le contigu.

Instrumentation minimale suggeree (hors dump, a faire en émulation) : breakpoint
sur `0xffffffff9e82b879` et `0xffffffff9e9d67c0` avec lecture de `r12+0x2` et
`r12+0x4`.

---

## 5. Recapitulatif des adresses

| Objet | VA | Offset fichier |
|---|---|---|
| chaine `gc_allocate_system_memory_for_dir` | `0xffffffff9f7a540a` | `0x13b540a` |
| chaine `%s kmem_alloc_contig error` | `0xffffffff9f6e2989` | `0x12f298c` |
| chaine `ring allocation failed %d` | `0xffffffff9f6ef195` | `0x12ff195` |
| site d'appel fautif | `0xffffffff9edd3f89` | `0x9e3f89` |
| `FUN_9edd3950` (imprime) | `0xffffffff9edd3950` | `0x9e3950` |
| wrapper arene | `0xffffffff9e8f3af0` | `0x503af0` |
| `kmem_alloc_contig` | `0xffffffff9e8f3800` | `0x503800` |
| seuil petite alloc contigue | `0xffffffff9e9d6730` | `0x5e6730` |
| chemin general contigu | `0xffffffff9e9d67c0` | `0x5e67c0` |
| allocateur pages | `0xffffffff9e82b880` | `0x43b880` |
| plafond par domaine | `0xffffffff9ef7ad50` | `0xb8ad50` |
| parcours vm_phys | `0xffffffff9ea06050` | `0x616050` |
| selecteur de domaine | `0xffffffff9e8551c0` | `0x4651c0` |
| global pool flexible | `0xffffffffa1925f10` | `0x3535f10` |
| table de domaines | `0xffffffffa1925ea0` | `0x3535ea0` |
| cache taille flexible | `0xffffffffa21cb478` | `0x3ddb478` |
| 2e occurrence `0x877cc000` | `0xffffffffa1ab7320` | `0x36c7320` |
| arene (via `9fed8b10`) | `0xffffffffa1ab6800` | `0x36c6800` |
| seuil contigu `+0x3e8` (candidat A) | `0xffffffffa1ab6be8` | `0x36c6be8` |
| table de modes | `0xffffffff9f280cd0` | `0xe90cd0` |
| index de mode | `0xffffffffa1fa5400` | `0x3bb5400` |

Toutes ces valeurs sont relues dans le dump `kernel-13.60-live.bin` decrit en
tete. Aucune n'est deduite d'une source web.
