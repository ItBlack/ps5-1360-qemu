/*
 * Emulation du controleur ICC (Internal Communication Controller) de l'APU PS5.
 *
 * Le noyau PS5 dialogue avec un controleur qui arbitre les echanges entre
 * l'APU et les autres blocs (SMU, GPU, ...). Sans lui, le noyau boucle :
 *
 *   ICC:handshake failed
 *   Try to recover ICC status
 *   ICC: sow:00, sor:00, emw:00, emr:00
 *   panic: ICC: not recovered
 *
 * Protocole observe (desassemblage + trace des registres) :
 *
 *   base+0x0014  bit 0x01 : reponse prete au polling
 *   base+0x0014  bit 0x40 : acquittement du handshake
 *   base+0x07f0  sow  : status of write
 *   base+0x07f4  sor  : status of read, compteur vivant
 *   base+0x0800  fenetre de message (0x20 octets)
 *   base+0x0ff0  emw  : error mask write
 *   base+0x0ff4  emr  : error mask read
 *
 * Le noyau pose sow puis relit sor : ce dernier doit avancer a chaque acces,
 * sinon le noyau conclut que le controleur ne repond pas.
 *
 * Instanciation : -device ps5-icc,addr=0x800000
 */

#include "qemu/osdep.h"
#include "qemu/log.h"
#include "qemu/module.h"
#include "hw/qdev-properties.h"
#include "hw/sysbus.h"
#include "exec/address-spaces.h"
#include "migration/vmstate.h"

#define TYPE_PS5_ICC "ps5-icc"
OBJECT_DECLARE_SIMPLE_TYPE(PS5ICCState, PS5_ICC)

#define ICC_MMIO_SIZE 0x1000

#define ICC_OFF_STATUS   0x0014
#define ICC_OFF_SOW      0x07f0
#define ICC_OFF_SOR      0x07f4
#define ICC_OFF_MSG      0x0800
#define ICC_OFF_EMW      0x0ff0
#define ICC_OFF_EMR      0x0ff4

#define ICC_MSG_SIZE     0x20

struct PS5ICCState {
    DeviceState parent_obj;
    MemoryRegion mmio;
    uint64_t addr;
    uint32_t status;
    uint16_t sow;
    uint16_t sor;
    uint16_t emw;
    uint16_t emr;
    uint8_t  msg[ICC_MSG_SIZE];
};

static void icc_update_status(PS5ICCState *s)
{
    s->status = 0x41;
}

static uint64_t icc_read(void *opaque, hwaddr addr, unsigned size)
{
    PS5ICCState *s = PS5_ICC(opaque);
    uint64_t r = 0;

    fprintf(stderr, "ICC_R off=%#x size=%u\n", (unsigned)addr, size);

    if (addr + size > ICC_MMIO_SIZE) {
        return 0;
    }

    /* Le noyau attend un message precis : source 0x07, destination 0x40,
     * code 0x4001, valeur 0x0373. On le presente dans la fenetre de message.
     */
    if (addr >= ICC_OFF_MSG && addr < ICC_OFF_MSG + ICC_MSG_SIZE && s->msg[0] == 0) {
        /* message attendu par le noyau : 07-4001 0373
         * layout deduit de la file interne (dword 0x40010a42 = src 0x0a, dst 0x40, code 0x4001)
         */
        s->msg[0] = 0x07;           /* source      */
        s->msg[1] = 0x40;           /* destination */
        s->msg[2] = 0x01;           /* code 0x4001 */
        s->msg[3] = 0x40;
        s->msg[4] = 0x73;           /* valeur 0x0373 */
        s->msg[5] = 0x03;
    }

    if (addr == ICC_OFF_STATUS || (addr & ~3) == ICC_OFF_STATUS) {
        icc_update_status(s);
        r = s->status;
    } else if ((addr & ~1) == ICC_OFF_SOW) {
        r = s->sow;
    } else if ((addr & ~1) == ICC_OFF_SOR) {
        s->sor++;
        if (!s->sor) {
            s->sor = 1;
        }
        r = s->sor;
    } else if ((addr & ~1) == ICC_OFF_EMW) {
        r = s->emw;
    } else if ((addr & ~1) == ICC_OFF_EMR) {
        r = s->emr;
    } else if (addr >= ICC_OFF_MSG && addr < ICC_OFF_MSG + ICC_MSG_SIZE) {
        memcpy(&r, &s->msg[addr - ICC_OFF_MSG], size);
    }

    return r;
}

static void icc_write(void *opaque, hwaddr addr, uint64_t val, unsigned size)
{
    PS5ICCState *s = PS5_ICC(opaque);

    fprintf(stderr, "ICC_W off=%#x val=%#llx size=%u\n", (unsigned)addr,
            (unsigned long long)val, size);

    if (addr + size > ICC_MMIO_SIZE) {
        return;
    }

    if ((addr & ~3) == ICC_OFF_STATUS) {
        s->status = val & 0xffff;
    } else if ((addr & ~1) == ICC_OFF_SOW) {
        s->sow = val & 0xffff;
        if (s->sow) {
            s->sor |= 1;
            s->status |= 0x41;
        }
    } else if ((addr & ~1) == ICC_OFF_SOR) {
        s->sor = val & 0xffff;
    } else if ((addr & ~1) == ICC_OFF_EMW) {
        s->emw = val & 0xffff;
    } else if ((addr & ~1) == ICC_OFF_EMR) {
        s->emr = val & 0xffff;
    } else if (addr >= ICC_OFF_MSG && addr < ICC_OFF_MSG + ICC_MSG_SIZE) {
        memcpy(&s->msg[addr - ICC_OFF_MSG], &val, size);
    }
}

static const MemoryRegionOps icc_ops = {
    .read = icc_read,
    .write = icc_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
    .impl  = { .min_access_size = 1, .max_access_size = 4 },
};

static void ps5_icc_reset(DeviceState *dev)
{
    PS5ICCState *s = PS5_ICC(dev);

    s->sow = 0;
    s->sor = 1;
    s->emw = 0;
    s->emr = 0;
    memset(s->msg, 0, sizeof(s->msg));
    icc_update_status(s);
}

static void ps5_icc_realize(DeviceState *dev, Error **errp)
{
    PS5ICCState *s = PS5_ICC(dev);

    memory_region_init_io(&s->mmio, OBJECT(s), &icc_ops, s,
                          TYPE_PS5_ICC, ICC_MMIO_SIZE);
    memory_region_add_subregion(get_system_memory(), s->addr, &s->mmio);
    ps5_icc_reset(dev);

    qemu_log_mask(LOG_GUEST_ERROR, "ps5-icc: mapped at %#" PRIx64 "\n", s->addr);
}

static Property ps5_icc_properties[] = {
    DEFINE_PROP_UINT64("addr", PS5ICCState, addr, 0x800000),
};

static void ps5_icc_class_init(ObjectClass *klass, void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = ps5_icc_realize;
    dc->reset = ps5_icc_reset;
    dc->desc = "PS5 APU Internal Communication Controller";
    dc->user_creatable = true;
    device_class_set_props(dc, ps5_icc_properties);
    set_bit(DEVICE_CATEGORY_MISC, dc->categories);
}

static const TypeInfo ps5_icc_info = {
    .name = TYPE_PS5_ICC,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(PS5ICCState),
    .class_init = ps5_icc_class_init,
};

static void ps5_icc_register_types(void)
{
    type_register_static(&ps5_icc_info);
}

type_init(ps5_icc_register_types)
