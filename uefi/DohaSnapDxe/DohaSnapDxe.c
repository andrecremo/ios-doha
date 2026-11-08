/*
 * Diagnostic: a light watcher. It starts one more core, which waits SNAP_SECONDS without touching memory, copies
 * the framebuffer and the log buffer to RAM once, then asks for a reboot. For the shim (shim.c, show_saved).
 *
 * The busy watcher of DohaSaveDxe, which copies the screen all the time, made the firmware's DisplayDxe finish
 * three times in four; a parked core did not, three times in three. This one stays out of the way until the
 * copy, so that the boot fails as without it, and keeps the screen of the failure: written by the boot core's
 * exception handler, if that is what happens. The header says 2000 + the seconds it waited.
 */
#include <Uefi.h>
#include <Library/DebugLib.h>

#define PSCI_CPU_ON   0xC4000003
#define SNAP_CORE     0x103
#define SNAP_LENGTH   0x200

__attribute__((naked))
STATIC
VOID
Snap (
  VOID
  )
{
  __asm__ (
    "   mrs   x19, cntpct_el0            \n"
    "   movz  x20, #0xF800               \n"   // 19.2 MHz
    "   movk  x20, #0x124, lsl #16       \n"
    "   mov   x21, #6                    \n"   // SNAP_SECONDS
    "   mul   x21, x21, x20              \n"
    "1: yield                            \n"
    "   mrs   x6, cntpct_el0             \n"
    "   sub   x6, x6, x19                \n"
    "   cmp   x6, x21                    \n"
    "   b.lo  1b                         \n"
    "   movz  x1, #0x5C00, lsl #16       \n"   // framebuffer
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
    "   movz  x5, #0xF000                \n"   // header
    "   movk  x5, #0x5BAF, lsl #16       \n"
    "   movz  x7, #0x4F44                \n"   // "DOHALOG1"
    "   movk  x7, #0x4148, lsl #16       \n"
    "   movk  x7, #0x4F4C, lsl #32       \n"
    "   movk  x7, #0x3147, lsl #48       \n"
    "   mov   x22, #2006                 \n"
    "   str   x22, [x5, #8]              \n"
    "   str   x7, [x5]                   \n"
    "   dsb   sy                         \n"
    "5: movz  x0, #0x0009                \n"   // PSCI SYSTEM_RESET
    "   movk  x0, #0x8400, lsl #16       \n"
    "   smc   #0                         \n"
    "   b     5b                         \n"
    );
}

EFI_STATUS
EFIAPI
DohaSnapEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINTN  Address;

  /* The core starts with its caches off: its code has to be in RAM, not only in this core's cache. */
  for (Address = (UINTN)Snap & ~(UINTN)63; Address < (UINTN)Snap + SNAP_LENGTH; Address += 64) {
    __asm__ volatile ("dc civac, %0" : : "r" (Address) : "memory");
  }

  __asm__ volatile ("dsb sy" : : : "memory");

  {
    register UINT64  X0 __asm__ ("x0") = PSCI_CPU_ON;
    register UINT64  X1 __asm__ ("x1") = SNAP_CORE;
    register UINT64  X2 __asm__ ("x2") = (UINT64)(UINTN)Snap;
    register UINT64  X3 __asm__ ("x3") = 0;

    __asm__ volatile (
      "smc #0"
      : "+r" (X0), "+r" (X1), "+r" (X2), "+r" (X3)
      :
      : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory"
      );
    DEBUG ((DEBUG_ERROR, "DohaSnap: core %x started, %lx\n", SNAP_CORE, X0));
  }

  return EFI_SUCCESS;
}
