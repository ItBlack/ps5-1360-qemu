/*
 * ps5_ec.c — ACPI Embedded Controller pour l'émulation PS5
 *
 * Le noyau Orbis (FreeBSD 11) attache son pilote acpi_ec via ACPI.
 * QEMU x86 n'expose pas de EC : on en fournit un minimal mais conforme
 * au protocole ACPI EC (ports 0x62 data / 0x66 status+command).
 *
 * But : faire disparaître "cannot find EC device" et permettre à
 * acpi_ec_acpi de s'attacher.
 */
#include "qemu/osdep.h"
#include "hw/isa/isa.h"
#include "hw/qdev-properties.h"
#include "qom/object.h"
#include "qemu/module.h"
#include "qemu/log.h"
#include "migration/vmstate.h"

#define TYPE_PS5_EC "ps5-ec"
OBJECT_DECLARE_SIMPLE_TYPE(PS5ECState, PS5_EC)

#define EC_DATA   0x62
#define EC_SC     0x66

/* bits du registre de statut (EC_SC) */
#define EC_STAT_OBF 0x01  /* output buffer full  : donnee dispo en 0x62  */
#define EC_STAT_IBF 0x02  /* input buffer full   : hote a ecrit, non lu  */

/* commandes ACPI EC */
#define EC_CMD_READ    0x80
#define EC_CMD_WRITE   0x81
#define EC_CMD_QUERY   0x84

/* machine a etats du protocole */
typedef enum {
    EC_ST_IDLE = 0,
    EC_ST_RD_ADDR,    /* apres 0x80 : attend l'adresse */
    EC_ST_WR_ADDR,    /* apres 0x81 : attend l'adresse */
    EC_ST_WR_DATA,    /* attend la valeur a ecrire     */
} ECPhase;

struct PS5ECState {
    ISADevice parent_obj;

    MemoryRegion io;
    uint8_t status;     /* OBF / IBF */
    uint8_t outbuf;     /* octet que l'hote va lire en 0x62 */
    uint8_t cmd;
    uint8_t addr;       /* adresse EC courante */
    ECPhase phase;

    /* espace d'adressage EC interne (256 octets, comme la vraie puce) */
    uint8_t ram[256];
};

/*
 * Lecture par l'hote du registre de statut.
 * On expose OBF quand une donnee attend, IBF toujours a 0 car on
 * consomme immediatement ce que l'hote ecrit (pas de latence reelle).
 */
static uint64_t ec_ioport_read(void *opaque, hwaddr addr, unsigned size)
{
    PS5ECState *s = opaque;

    if (addr == EC_SC) {
        return s->status;
    }
    if (addr == EC_DATA) {
        uint8_t v = s->outbuf;
        s->status &= ~EC_STAT_OBF;   /* la donnee est consommee */
        s->outbuf = 0xFF;
        return v;
    }
    return 0xFF;
}

static void ec_ioport_write(void *opaque, hwaddr addr, uint64_t val,
                            unsigned size)
{
    PS5ECState *s = opaque;
    uint8_t v = val & 0xFF;

    if (addr == EC_SC) {
        s->cmd = v;
        switch (v) {
        case EC_CMD_READ:
            s->phase = EC_ST_RD_ADDR;
            break;
        case EC_CMD_WRITE:
            s->phase = EC_ST_WR_ADDR;
            break;
        case EC_CMD_QUERY:
            /* pas d'evenement en attente : on renvoie 0 (pas de query) */
            s->outbuf = 0x00;
            s->status |= EC_STAT_OBF;
            s->phase = EC_ST_IDLE;
            break;
        default:
            s->phase = EC_ST_IDLE;
            break;
        }
        return;
    }

    if (addr == EC_DATA) {
        switch (s->phase) {
        case EC_ST_RD_ADDR:
            s->addr = v;
            s->outbuf = s->ram[v];
            s->status |= EC_STAT_OBF;
            s->phase = EC_ST_IDLE;
            break;
        case EC_ST_WR_ADDR:
            s->addr = v;
            s->phase = EC_ST_WR_DATA;
            break;
        case EC_ST_WR_DATA:
            s->ram[s->addr] = v;
            s->phase = EC_ST_IDLE;
            break;
        default:
            break;
        }
        return;
    }
}

static const MemoryRegionOps ec_ops = {
    .read  = ec_ioport_read,
    .write = ec_ioport_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 1 },
    .impl  = { .min_access_size = 1, .max_access_size = 1 },
};

static void ps5_ec_realize(DeviceState *dev, Error **errp)
{
    PS5ECState *s = PS5_EC(dev);
    ISADevice *isa = ISA_DEVICE(dev);

    isa_register_ioport(isa, &s->io, EC_DATA);  /* couvre 0x62 et 0x66 */

    /*
     * Valeurs d'init plausibles : une vraie EC PS5 remonte l'etat
     * d'alimentation secteur. On met des valeurs neutres mais non nulles
     * pour que le pilote ne caille pas sur un bus muet.
     */
    memset(s->ram, 0, sizeof(s->ram));
    s->ram[0x00] = 0x00;
    s->status = 0x00;
    s->outbuf = 0xFF;
    s->phase  = EC_ST_IDLE;
}

static void ps5_ec_init(Object *obj)
{
    PS5ECState *s = PS5_EC(obj);

    memory_region_init_io(&s->io, obj, &ec_ops, s, "ps5-ec", 8);
}

static const VMStateDescription vmstate_ps5_ec = {
    .name = "ps5-ec",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT8(status, PS5ECState),
        VMSTATE_UINT8(outbuf, PS5ECState),
        VMSTATE_UINT8(cmd,    PS5ECState),
        VMSTATE_UINT8(addr,   PS5ECState),
        VMSTATE_UINT8_ARRAY(ram, PS5ECState, 256),
        VMSTATE_END_OF_LIST()
    },
};

static void ps5_ec_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize  = ps5_ec_realize;
    dc->vmsd     = &vmstate_ps5_ec;
    set_bit(DEVICE_CATEGORY_MISC, dc->categories);
    /* instanciable par -device ps5-ec, comme ps5-icc */
    dc->user_creatable = true;
}

static const TypeInfo ps5_ec_info = {
    .name          = TYPE_PS5_EC,
    .parent        = TYPE_ISA_DEVICE,
    .instance_size = sizeof(PS5ECState),
    .instance_init = ps5_ec_init,
    .class_init    = ps5_ec_class_init,
};

static void ps5_ec_register_types(void)
{
    type_register_static(&ps5_ec_info);
}

type_init(ps5_ec_register_types)
