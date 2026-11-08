/*
 * Diagnostic: stops the boot at a chosen place in the load order and counts time on the screen, with the
 * timer and interrupts running as they would for any driver. If the phone resets anyway, the reset does
 * not come from the modules after this one.
 *
 * After RESET_SECONDS it asks the secure world to reboot, which also works with the screen off: a reboot
 * at that time means the CPU and the timer were still alive.
 */
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>

#define STEP_SECONDS       5
#define RESET_SECONDS      30
#define PSCI_SYSTEM_RESET  0x84000009

/* What the shim (shim.c, show_saved) shows after the reboot, in the "DBI Dump" region. */
#define FB_BASE      0x5C000000UL
#define FB_SIZE      (1080UL * 2280 * 4)
#define LOG_BASE     0x5FFF7000UL
#define LOG_SIZE     0x8000UL
#define SAVE_FB      0x5B100000UL
#define SAVE_LOG     0x5BA80000UL
#define SAVE_HEADER  0x5BAFF000UL
#define SAVE_MAGIC   0x31474F4C41484F44ULL     /* "DOHALOG1" */

STATIC
VOID
Copy (
  IN UINTN  To,
  IN UINTN  From,
  IN UINTN  Size
  )
{
  volatile UINT32  *Dst = (volatile UINT32 *)To;
  volatile UINT32  *Src = (volatile UINT32 *)From;
  UINTN            Index;

  for (Index = 0; Index < Size / 4; Index++) {
    Dst[Index] = Src[Index];
  }
}

/*
 * The screen and the log buffer go to RAM at the start and at every step, so that a reset from elsewhere still
 * leaves the last copy; the header says how many seconds the stop had counted.
 */
STATIC
VOID
Save (
  IN UINT32  Seconds
  )
{
  volatile UINT64  *Header = (volatile UINT64 *)SAVE_HEADER;

  Copy (SAVE_FB, FB_BASE, FB_SIZE);
  Copy (SAVE_LOG, LOG_BASE, LOG_SIZE);
  Header[1] = Seconds;
  Header[0] = SAVE_MAGIC;
}

EFI_STATUS
EFIAPI
DohaHaltEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINT32  Seconds = 0;

  DEBUG ((DEBUG_ERROR, "DohaHalt: stopped on purpose\n"));
  Save (Seconds);
  for ( ; ; ) {
    gBS->Stall (STEP_SECONDS * 1000000);
    Seconds += STEP_SECONDS;
    DEBUG ((DEBUG_ERROR, "DohaHalt: %u s\n", Seconds));
    Save (Seconds);
    if (Seconds == RESET_SECONDS) {
      register UINT64  X0 __asm__ ("x0") = PSCI_SYSTEM_RESET;

      __asm__ volatile ("smc #0" : "+r" (X0) : : "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
      DEBUG ((DEBUG_ERROR, "DohaHalt: PSCI reset returned %lx\n", X0));
    }
  }
}
