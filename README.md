# PS5 13.60 — booting the Prospero kernel under QEMU

Research notes, tooling and QEMU device models for running the PS5 Prospero
system software kernel outside of a console. Everything here is derived from a
**live kernel memory dump** — no decrypted firmware, no keys, no Sony
binaries are redistributed.

Goal: get as far as possible towards a usable PS5 research environment on
ordinary PC hardware.

## Status

| Area | State |
|---|---|
| Kernel boots in QEMU | **yes** — reaches `Device configuration finished`, 1436 log lines, no panic |
| PCI bus enumerated | 6 devices |
| PUP container format | **resolved and verified byte-for-byte** |
| PUP payload decryption | blocked (needs console-side key) |
| PKG container | two-layer scheme characterised |
| SBL / ICC driver chain | mapped, top to bottom |
| RAM above 2168 MiB | blocked by a fixed-address ACPI coupling, patch found |
| Hypervisor | out of scope here (needs hardware) |

## Reference material

Kernel dump used throughout:

```
kernel-13.60-live.bin   103,546,880 bytes
SHA-256                 c3f745e25dc25ee7afef89eb418b295b6334bbefe8aa17e6886483c35d78cddd
kernel text   0x0000000  13,369,344 bytes  @ 0xffffffff9e3f0000
kernel data   0x0cc0000  90,177,536 bytes  @ 0xffffffff9f0b0000
```

Publicly available from `terrafirma2021/ps5-13.60-kernel-dump`, captured
2026-10-13. Note that the capture contains **688 zero-filled unmapped
pages** and is not a decrypted nested PUP image.

All addresses in these documents refer to that dump.

## Findings

### PUP container format — resolved

The container is a `bls_header` (32 bytes) followed by an array of
`bls_entry` records (48 bytes each, starting at `0x20`). Field layout was
cross-checked against two independent size identities:

```
block_count @ 0x10 = 2,780,659
2,780,659 * 512    = 1,423,697,408   == file size, exact

sum of entry sizes = 1,423,695,674
overhead           = 1,734           (header + tables + 512-alignment)
```

Two errors are common in circulating documentation and are corrected in
`docs/PUP-FORMAT.md`: a claimed `BLS` magic at `0x24` is actually
`entry[0].size`, and `block_offset` is measured in 512-byte blocks, not
bytes.

Every segment begins with 16 cleartext bytes:

```
0x00  magic   0xEEF51454   ("54 14 f5 ee" on disk)
0x04  unk     0x32010110
0x08  u16 ...  variables
```

The payload after that header is uniformly encrypted — measured entropy
is 8.0000 bits/byte across every 64 MiB slice up to 1344 MiB, which rules
out sparse or partially-cleartext regions.

### SBL driver — attach path, not a mailbox

`0xffffffff9e8268b0` is often assumed to be a mailbox function. It is the
`attach` method of the newbus device `pci/sbl_driver`:

- 1624 bytes, `0x9e8268b0` – `0x9e826f07`
- calls `device_get_softc` (`0x9e6a2b10`), so `rdi` is a `device_t`
- creates `SblDrvTskQ`, allocates IRQ rid 3 and MEM rid 1, installs an interrupt
- stores the softc once, at `0x9e826ea8`

There is **no direct caller**. The only reference is a method pointer in
the driver record at `0xffffffff9feb1408`; dispatch is entirely newbus.

The sibling `probe` at `0x9e826740` requires `cmp $0x1022` then
`cmp $0x13ec` — a PCI device with vendor `0x1022`, device `0x13ec`, which
the kernel describes as `" Oberon PSP"`. Under QEMU that device does not
exist, so `probe` never runs and `attach` is never reached. Verified with
breakpoints: `probe` = 0 hits, `attach` = 0 hits, while
`sceSblDriverSendMsg` = 5 hits.

This is a missing PCI device, not a missing patch.

### RAM ceiling — fixed-address ACPI coupling

The kernel queries the RSDP at physical `0xf52b0`, an address **hardcoded
in the image** at `0xffffffffa1d93840` (`b0 52 0f 00 ...`). SeaBIOS moves
its SMBIOS copy depending on installed RAM:

- 3520 MiB → RSDP intact at `0xf52b0`, `memcmp` sees `RSDT`, ACPI works
- 3584 MiB → `_SM3_` overwrites it, `memcmp` sees `00 18 00 00`, failure

Zeroing the hardcoded address forces normal discovery via the `acpi.rsdp`
kenv and EBDA scan. Result: boots at 2G / 3G / 3520M / 3584M / 4G / 6G / 8G
with no behaviour change at the reference size.

Separately, the `0x877cc000` figure often quoted as a memory limit is not
a rule — it is `138739 << 14`, an arithmetic result of a page counter at
`0xffffffffa1925f10`. It is identical at every `-m` value, which proves
it is not derived from the VM configuration.

### PKG — two distinct layers

The PKG has two encryption layers that are frequently conflated:

- **type 3 entries** (metadata, SELF headers) use a **universal**
  RSA-3072 keyset — the same on every console
- **game content** uses a per-console derived key

Mechanism: seek `0x2580`, 0x180-byte RSA block; `entry_count` at `0x10`,
`file_table_offset` at `0x18`; `key_index = (flags2 & 0xF000) >> 12`;
`is_encrypted = flags1 & 0x80000000`; SHA3-256 over 0x40 bytes feeds
AES-128-CBC.

## Tooling

`scripts/ps5pup.py` — PUP container parser. Subcommands `info`, `list`,
`map`, `seg`. Reads and validates the header, walks the entry table,
verifies both size identities, and can extract a raw segment. It will
report encryption state accurately and does not pretend to decrypt.

`scripts/ps5pkg.py` — PKG header and entry table parser.

`scripts/ps5otp.py`, `scripts/otp_mailbox.py` — helpers for the OTP
controller model below.

All scripts are dependency-free Python 3 and take a file path; none embed
keys or contact the network.

## QEMU device models

`qemu-devices/` contains three device models written for this work:

| File | Purpose |
|---|---|
| `ps5_ec.c` | ACPI Embedded Controller (ports 0x62/0x66). Without it the kernel logs `cannot find EC device`. |
| `ps5_icc.c` | Internal Communication Controller. Without it the kernel loops on `ICC:handshake failed`. |
| `ps5_otpctrl.c` | OTP controller backing `sbl/otpctrl`. **Does not fabricate keys** — it serves fuse contents from a user-supplied file. |

`ps5_otpctrl.c` deliberately contains no key material. The fuse bank
belongs to the console that owns it; the model is a mechanism, not a
bypass.

Wiring: add the two `system_ss.add(...)` lines from
`qemu-devices/meson-fragment.txt` to `hw/misc/meson.build`. Built and
tested against QEMU 8.2.10.

## Documentation

Detailed write-ups live in `docs/`. They are currently written in French;
an English translation is in progress. Each one states, for every claim,
the measurement that supports it — and where a previous version of the
document was wrong, that is recorded too, because a correction is more
useful than a clean story.

- `docs/PUP-FORMAT.md` — container layout, verified
- `docs/sbl-driver-attach.md` — full disassembly of the SBL driver attach path
- `docs/MAILBOX-SBL.md` — SBL/ICC call chain from `sblServiceRequest` down
- `docs/MAILBOX-PATH.md` — message path tracing
- `docs/OTP-DEVICE.md` — OTP controller register model
- `docs/PKG-EXTRACTION.md` — PKG two-layer scheme
- `docs/RAM-LIMIT.md` — the memory ceiling analysis
- `docs/ram-alloc-path.md` — `kmem_alloc_contig` failure path

## What this is not

- Not a jailbreak, and not a path to one. It does not enable piracy or
  online cheating.
- Not a redistribution of Sony code. No firmware, no decrypted SELF, no
  keys are included or linked.
- Not an emulator that runs games. It boots a kernel.

## Scope and intent

Naming, since it trips people up (including an earlier revision of this
document):

| Name | What it is | Evidence in the 13.60 dump |
|---|---|---|
| **Prospero** | the PS5 platform — SDK, executables, application category | `Prospero SDK version`, `Prospero Native Game`, `prospero-llvm-readelf.exe` |
| **Orbis** | PS4 generation codename; the `orbis_*` filenames in the kernel are inherited PS4/FreeBSD legacy | `orbis_mdbg.c`, `orbis_pmc.c`, `orbis_vnode`, `Orbis Sflash` |
| **Oberon** | the APU / SoC | `" Oberon PSP"` — the PCI probe description |

Referring to a PS5 kernel as "Orbis" is easy to do because the internal
file names say so, but the platform is Prospero and that is what people
in the field say. Using the mixed-up name in a title is the fastest way
to look like an outsider, so it is corrected here rather than quietly
edited away.

The point is to make PS5 system software research possible on hardware
people actually own, using a memory image that is already public. If you
have corrections, especially if you have a dump from a different firmware
version to compare against, issues and PRs are welcome.
