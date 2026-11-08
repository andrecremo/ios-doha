/*
 * Experiment: starts one more core and parks it, doing nothing. On the doha, the firmware's DisplayDxe hung with
 * the boot core alone (interrupts off for good), and twice in three boots it lit the panel with a second core
 * running a watcher. This tells whether a second core alone is enough: the parked core touches no memory, waits
 * in WFE and never comes back.
 */
#include <Uefi.h>
#include <Library/DebugLib.h>

#define PSCI_CPU_ON   0xC4000003
#define PARK_CORE     0x103
#define PARK_LENGTH   0x40

__attribute__((naked))
STATIC
VOID
Park (
  VOID
  )
{
  __asm__ (
    "1: wfe      \n"
    "   b    1b  \n"
    );
}

EFI_STATUS
EFIAPI
DohaParkEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINTN  Address;

  /* The parked core starts with its caches off: its two instructions have to be in RAM. */
  for (Address = (UINTN)Park & ~(UINTN)63; Address < (UINTN)Park + PARK_LENGTH; Address += 64) {
    __asm__ volatile ("dc civac, %0" : : "r" (Address) : "memory");
  }

  __asm__ volatile ("dsb sy" : : : "memory");

  {
    register UINT64  X0 __asm__ ("x0") = PSCI_CPU_ON;
    register UINT64  X1 __asm__ ("x1") = PARK_CORE;
    register UINT64  X2 __asm__ ("x2") = (UINT64)(UINTN)Park;
    register UINT64  X3 __asm__ ("x3") = 0;

    __asm__ volatile (
      "smc #0"
      : "+r" (X0), "+r" (X1), "+r" (X2), "+r" (X3)
      :
      : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory"
      );
    DEBUG ((DEBUG_ERROR, "DohaPark: core %x started, %lx\n", PARK_CORE, X0));
  }

  return EFI_SUCCESS;
}
