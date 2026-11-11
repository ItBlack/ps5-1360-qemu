/*
 * ps5_otpctrl.c — controleur OTP pour l'emulation PS5
 *
 * Le noyau Prospero expose un device "sbl/otpctrl" (code a
 * 0xffffffff9ee44200..0xffffffff9ee44767 dans le dump 13.60) et ses
 * fonctions otpctrl_init / otpctrl_ioctl_nolock. Sans lui, la chaine
 * sbl_sm_service echoue et rien de ce qui depend des cles ne demarre.
 *
 * Ce device ne FABRIQUE aucune cle. Il fournit un controleur OTP qui
 * repond, alimente par un fichier de cles fourni par l'utilisateur.
 * C'est un mecanisme, pas un contournement : le contenu des fuses
 * appartient a la console qui le possede.
 *
 * Modele de registres (compatible avec ce que le noyau attend) :
 *   0x00  CONTROL    W : 1=lire, 2=ecrire (provoque un transfert)
 *   0x04  ADDRESS    RW: offset dans la banque OTP
 *   0x08  STATUS     R : bit0 PRET, bit1 ERREUR, bit2 ECRITURE_OK
 *   0x0C  DATA       RW: banque de donnees (acces indirect)
 *   0x10  SIZE       R : taille de la banque en octets
 *
 * Alimentation des cles :
 *   -otpkeys <fichier>   fichier binaire (format "OTPK" ci-dessous)
 *   ou variable d'environnement PS5_OTP_KEYS
 *
 * Format du fichier (little endian) :
 *   magic  "OTPK"   4 octets
 *   version u32     = 1
 *   count  u32      nombre d'entrees
 *   puis pour chaque entree :
 *       offset u32, size u32, data[size]
 */
#include "qemu/osdep.h"
#include "hw/isa/isa.h"
#include "hw/qdev-properties.h"
#include "qemu/module.h"
#include "qemu/log.h"
#include "qemu/error-report.h"
#include "migration/vmstate.h"
#include "qom/object.h"

#define TYPE_PS5_OTPCTRL "ps5-otpctrl"
OBJECT_DECLARE_SIMPLE_TYPE(PS5OtpCtrlState, PS5_OTPCTRL)

#define OTP_BANK_SIZE      0x10000u

/* compteur d'acces : sert a prouver si le noyau touche le device */
static unsigned ps5_otp_access_log;
/*
 * Le noyau accede au bloc OTP par des offsets 0x105xx (vus dans le dump :
 * 0x1054c, 0x10550...). Ce sont des offsets DANS le bloc, pas des ports.
 * L'espace de ports x86 s'arrete a 0xFFFF : la base doit donc etre un port
 * 16 bits valide, et les registres sont adresses relativement. La base
 * reelle reste a confirmer sur materiel ; 0x0500 est libre et non conflictuel.
 */
#define OTP_BLOCK_SIZE     0x400
      /* 4 Kio de banque OTP */
#define OTP_REG_CONTROL    0x00
#define OTP_REG_ADDRESS    0x04
#define OTP_REG_STATUS     0x08
#define OTP_REG_DATA       0x0C
#define OTP_REG_SIZE       0x10

#define OTP_STATUS_READY   0x01
#define OTP_STATUS_ERROR   0x02
#define OTP_STATUS_WROTE   0x04

#define OTP_CMD_READ       1
#define OTP_CMD_WRITE      2

struct PS5OtpCtrlState {
    ISADevice parent_obj;

    MemoryRegion io;
    uint32_t control;
    uint32_t address;
    uint32_t status;
    uint32_t data;

    uint8_t bank[OTP_BANK_SIZE];
    bool have_keys;
    char *keys_path;
    uint32_t iobase;
};

/* ------------------------------------------------------------------ keys */

typedef struct {
    uint32_t magic;      /* 'OTPK' */
    uint32_t version;
    uint32_t count;
} OtpKeysHeader;

static bool otp_load_keys(PS5OtpCtrlState *s, const char *path, Error **errp)
{
    g_autofree char *blob = NULL;
    gsize len = 0;
    GError *gerr = NULL;

    if (!path || !*path) {
        return false;
    }

    if (!g_file_get_contents(path, &blob, &len, &gerr)) {
        warn_report("ps5-otpctrl: cannot read keys '%s': %s",
                    path, gerr ? gerr->message : "unknown");
        g_clear_error(&gerr);
        return false;
    }

    if (len < sizeof(OtpKeysHeader)) {
        warn_report("ps5-otpctrl: keys file too short");
        return false;
    }

    OtpKeysHeader hdr;
    memcpy(&hdr, blob, sizeof(hdr));

    if (hdr.magic != 0x4B50544F) {          /* 'OTPK' little endian */
        warn_report("ps5-otpctrl: bad keys magic (expected 'OTPK')");
        return false;
    }
    if (hdr.version != 1) {
        warn_report("ps5-otpctrl: unsupported keys version %u", hdr.version);
        return false;
    }

    gsize pos = sizeof(hdr);
    uint32_t loaded = 0;

    for (uint32_t i = 0; i < hdr.count; i++) {
        if (pos + 8 > len) {
            warn_report("ps5-otpctrl: truncated entry %u", i);
            break;
        }
        uint32_t off, sz;
        memcpy(&off, blob + pos, 4);
        memcpy(&sz, blob + pos + 4, 4);
        pos += 8;

        if (pos + sz > len) {
            warn_report("ps5-otpctrl: truncated data for entry %u", i);
            break;
        }
        if ((uint64_t)off + sz > OTP_BANK_SIZE) {
            warn_report("ps5-otpctrl: entry %u out of bank (off=%#x size=%u)",
                        i, off, sz);
            pos += sz;
            continue;
        }
        memcpy(s->bank + off, blob + pos, sz);
        pos += sz;
        loaded++;
    }

    if (loaded) {
        s->have_keys = true;
        info_report("ps5-otpctrl: %u key region(s) loaded from %s",
                    loaded, path);
    }
    return s->have_keys;
}

/* ------------------------------------------------------------- registers */

static uint64_t otp_read(void *opaque, hwaddr addr, unsigned size)
{
    PS5OtpCtrlState *s = opaque;
    uint64_t r = 0;

    switch (addr & ~3u) {
    case OTP_REG_CONTROL:
        r = s->control;
        break;
    case OTP_REG_ADDRESS:
        r = s->address;
        break;
    case OTP_REG_STATUS:
        /*
         * PRET toujours positionne : le noyau sonde ce bit en boucle au
         * demarrage et bloque indefiniment s'il ne le voit jamais.
         */
        r = s->status | OTP_STATUS_READY;
        if (!s->have_keys) {
            /*
             * Sans banque fournie on annonce ERROR : le noyau prend la
             * branche "pas de cles" au lieu d'utiliser des zeros.
             */
            r |= OTP_STATUS_ERROR;
        }
        break;
    case OTP_REG_DATA:
        r = s->data;
        break;
    case OTP_REG_SIZE:
        r = OTP_BANK_SIZE;
        break;
    default:
        r = 0;
        break;
    }

    if (ps5_otp_access_log < 20) {
        fprintf(stderr, "PS5OTP: read  reg %#" HWADDR_PRIx " -> %#" PRIx64 "\n", addr, r);
        fflush(stderr);
        ps5_otp_access_log++;
    }
    return r;
}

static void otp_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    PS5OtpCtrlState *s = opaque;

    if (ps5_otp_access_log < 20) {
        fprintf(stderr, "PS5OTP: write reg %#" HWADDR_PRIx " = %#" PRIx64 "\n", addr, val);
        fflush(stderr);
        ps5_otp_access_log++;
    }

    switch (addr & ~3u) {
    case OTP_REG_CONTROL:
        s->control = val;
        s->status = 0;

        if ((val & 0xff) == OTP_CMD_READ) {
            if (s->address < OTP_BANK_SIZE) {
                s->data = s->bank[s->address];
                s->status = OTP_STATUS_READY;
            } else {
                s->data = 0;
                s->status = OTP_STATUS_ERROR;
            }
        } else if ((val & 0xff) == OTP_CMD_WRITE) {
            if (s->address < OTP_BANK_SIZE) {
                s->bank[s->address] = s->data & 0xff;
                s->status = OTP_STATUS_READY | OTP_STATUS_WROTE;
            } else {
                s->status = OTP_STATUS_ERROR;
            }
        } else if (val != 0) {
            s->status = OTP_STATUS_ERROR;
        }
        break;

    case OTP_REG_ADDRESS:
        s->address = val & (OTP_BANK_SIZE - 1);
        break;

    case OTP_REG_DATA:
        s->data = val;
        break;

    case OTP_REG_STATUS:
        break;              /* lecture seule */

    default:
        break;
    }
}

static const MemoryRegionOps otp_ops = {
    .read = otp_read,
    .write = otp_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 1,
        .max_access_size = 4,
    },
};

/* ---------------------------------------------------------------- realize */

static void ps5_otpctrl_realize(DeviceState *dev, Error **errp)
{
    PS5OtpCtrlState *s = PS5_OTPCTRL(dev);
    const char *env = getenv("PS5_OTP_KEYS");
    const char *path = s->keys_path ? s->keys_path : env;

    s->status = OTP_STATUS_READY;
    s->address = 0;
    s->control = 0;
    s->data = 0;
    memset(s->bank, 0, sizeof(s->bank));

    if (path && *path) {
        otp_load_keys(s, path, errp);
    } else {
        warn_report("ps5-otpctrl: no keys file (use -otpkeys or PS5_OTP_KEYS); "
                    "device will report ERROR until keys are provided");
    }

    memory_region_init_io(&s->io, OBJECT(dev), &otp_ops, s,
                          TYPE_PS5_OTPCTRL, OTP_BLOCK_SIZE);
    isa_register_ioport(&s->parent_obj, &s->io, s->iobase);
}

static Property ps5_otpctrl_props[] = {
    DEFINE_PROP_UINT32("iobase", PS5OtpCtrlState, iobase, 0x0500),
    DEFINE_PROP_STRING("keys", PS5OtpCtrlState, keys_path),
};

static void ps5_otpctrl_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = ps5_otpctrl_realize;
    device_class_set_props(dc, ps5_otpctrl_props);
    dc->user_creatable = true;
    set_bit(DEVICE_CATEGORY_MISC, dc->categories);
}

static const TypeInfo ps5_otpctrl_info = {
    .name = TYPE_PS5_OTPCTRL,
    .parent = TYPE_ISA_DEVICE,
    .instance_size = sizeof(PS5OtpCtrlState),
    .class_init = ps5_otpctrl_class_init,
};

static void ps5_otpctrl_register_types(void)
{
    type_register_static(&ps5_otpctrl_info);
}

type_init(ps5_otpctrl_register_types)
