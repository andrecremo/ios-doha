/*
 * Diagnostic for a boot with the screen off. A timer on the boot core is no use for this: an abort stops it, and an
 * abort is what there is to see. So the last core is the watcher: it runs on its own, MMU off, and once a second
 * it copies to RAM the framebuffer (the log of the modules built from source is drawn there even with the image
 * off) and the firmware's log buffer. At 25 s it asks for a reboot: stop the boot before BDS with DOHA_HALT_AFTER,
 * since BDS gives up and powers off sooner, and a power off loses the RAM. The copies go to the "DBI Dump" region,
 * which a normal boot does not use, for the shim (shim.c, show_saved) to show after the reboot.
 *
 * Reads only the two buffers, writes only that region of RAM.
 *
 *   0x5C000000, 0x964A00 bytes (1080 x 2280 x 4)  ->  0x5B100000
 *   0x5FFF7000, 0x8000 bytes                      ->  0x5BA80000
 *   header at 0x5BAFF000: "DOHALOG1", then the seconds
 */
#include <Uefi.h>
#include <Library/DebugLib.h>

#define PSCI_CPU_ON   0xC4000003
#define WATCH_CORE    0x103
#define WATCH_LENGTH  0x200     /* what to clean from the cache: the code below is shorter */

/* All registers and no stack, and every access aligned: with the MMU off, memory is Device memory. */
__attribute__((naked))
STATIC
VOID
Watcher (
  VOID
  )
{
  __asm__ (
    "   mrs   x19, cntpct_el0            \n"
    "   movz  x20, #0xF800               \n"   // 19.2 MHz
    "   movk  x20, #0x124, lsl #16       \n"
    "   movz  x5, #0xF000                \n"   // header
    "   movk  x5, #0x5BAF, lsl #16       \n"
    "   movz  x7, #0x4F44                \n"   // "DOHALOG1"
    "   movk  x7, #0x4148, lsl #16       \n"
    "   movk  x7, #0x4F4C, lsl #32       \n"
    "   movk  x7, #0x3147, lsl #48       \n"
    "1: movz  x1, #0x5C00, lsl #16       \n"   // framebuffer
    "   movz  x2, #0x5B10, lsl #16       \n"
    "   movz  x3, #0x9280                \n"
    "   movk  x3, #0x25, lsl #16         \n"
    "2: ldr   w4, [x1], #4               \n"
    "   str   w4, [x2], #4               \n"
    "   subs  x3, x3, #1                 \n"
    "   b.ne  2b                         \n"
    "   movz  x1, #0x7000                \n"   // log buffer
    "   movk  x1, #0x5FFF, lsl #16       \n"
    "   movz  x2, #0x5BA8, lsl #16       \n"
    "   movz  x3, #0x2000                \n"
    "3: ldr   w4, [x1], #4               \n"
    "   str   w4, [x2], #4               \n"
    "   subs  x3, x3, #1                 \n"
    "   b.ne  3b                         \n"
    "   mrs   x6, cntpct_el0             \n"
    "   sub   x6, x6, x19                \n"
    "   udiv  x21, x6, x20               \n"
    "   str   x21, [x5, #8]              \n"
    "   str   x7, [x5]                   \n"
    "   dsb   sy                         \n"
    "   cmp   x21, #25                   \n"
    "   b.hs  5f                         \n"
    "4: yield                            \n"
    "   mrs   x6, cntpct_el0             \n"
    "   sub   x6, x6, x19                \n"
    "   udiv  x6, x6, x20                \n"
    "   cmp   x6, x21                    \n"
    "   b.ls  4b                         \n"
    "   b     1b                         \n"
    "5: movz  x0, #0x0009                \n"   // PSCI SYSTEM_RESET
    "   movk  x0, #0x8400, lsl #16       \n"
    "   smc   #0                         \n"
    "   b     5b                         \n"
    );
}

EFI_STATUS
EFIAPI
DohaLogEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINTN  Address;

  /* The watcher starts with its caches off: its code has to be in RAM, not only in this core's cache. */
  for (Address = (UINTN)Watcher & ~(UINTN)63; Address < (UINTN)Watcher + WATCH_LENGTH; Address += 64) {
    __asm__ volatile ("dc civac, %0" : : "r" (Address) : "memory");
  }

  __asm__ volatile ("dsb sy" : : : "memory");

  {
    register UINT64  X0 __asm__ ("x0") = PSCI_CPU_ON;
    register UINT64  X1 __asm__ ("x1") = WATCH_CORE;
    register UINT64  X2 __asm__ ("x2") = (UINT64)(UINTN)Watcher;
    register UINT64  X3 __asm__ ("x3") = 0;

    __asm__ volatile (
      "smc #0"
      : "+r" (X0), "+r" (X1), "+r" (X2), "+r" (X3)
      :
      : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory"
      );
    DEBUG ((DEBUG_ERROR, "DohaLog: watcher %lx\n", X0));
  }

  return EFI_SUCCESS;
}
