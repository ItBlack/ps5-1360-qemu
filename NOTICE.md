# NOTICE

## What is not in this repository

This repository contains analysis, tooling and QEMU device models only. It
does **not** contain, link to, or bundle:

- any PS5 firmware image, PUP file, or PKG file
- any decrypted SELF or PRX binary
- any key material, fuse contents, or OTP bank
- any dump of Sony copyrighted code
- any game data

The kernel dump referenced throughout the documentation is published
separately by a third party and is not redistributed here. Its hash is
recorded only so that addresses in the documentation can be verified
against a specific image.

## On the QEMU device models

`ps5_otpctrl.c` implements an OTP controller that serves fuse contents
from a **file supplied by the user at runtime**. It does not generate,
derive, guess or contain keys. Its purpose is to let the guest kernel's
OTP driver complete initialisation during emulation.

If you do not have a key file, the device simply returns an error, in the
same way the real hardware would to a caller without access.

## Intent

This is research into how the PS5 system software boots, so that it can be
studied and instrumented on ordinary hardware. It is not a circumvention
tool: it does not defeat content protection, does not enable installation
of unsigned software on a retail console, and has no mechanism for doing
so.

## Credits

- Kernel memory image: `terrafirma2021/ps5-13.60-kernel-dump`
- `bls_header` / `bls_entry` structure cross-check: `zecoxao/ps5-pup-decrypt`
- Hypervisor bug background: `PS5Dev/Byepervisor-Reborn`, `soniciso1/ps5-hv-writeups`
- QEMU, upon which the device models are built
