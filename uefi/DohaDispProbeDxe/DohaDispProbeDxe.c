/*
 * Diagnostic for the screen going dark once ClockDxe loads: reads the display clocks, then switches them on
 * through the firmware's own clock driver, in stages 5 s apart, and reboots. It touches no register itself
 * and no regulator. Nothing is kept: the phone reboots into its normal state.
 *
 * The log goes to the framebuffer even with the image off. If a stage brings the image back, the moment it
 * does names the stage and the whole log shows. If none does, the time of the reboot tells what was read:
 *
 *   15 s  no clock protocol
 *   40 s  every clock read was on already, so the clocks are not what is missing
 *   60 s  some clock read was off
 */
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>

#define PSCI_SYSTEM_RESET  0x84000009
#define STAGE_SECONDS      5

typedef struct _DOHA_CLOCK DOHA_CLOCK;
typedef EFI_STATUS (EFIAPI *DOHA_GET_ID)(DOHA_CLOCK *This, CONST CHAR8 *Name, UINTN *Id);
typedef EFI_STATUS (EFIAPI *DOHA_BY_ID)(DOHA_CLOCK *This, UINTN Id);
typedef EFI_STATUS (EFIAPI *DOHA_QUERY)(DOHA_CLOCK *This, UINTN Id, BOOLEAN *Answer);

/* The entries of Qualcomm's clock protocol, in order, up to the power domains. */
struct _DOHA_CLOCK {
  UINT64         Version;
  DOHA_GET_ID    GetClockId;
  DOHA_BY_ID     EnableClock;
  DOHA_BY_ID     DisableClock;
  DOHA_QUERY     IsClockEnabled;
  DOHA_QUERY     IsClockOn;
  VOID           *SetClockFreqHz;
  VOID           *GetClockFreqHz;
  VOID           *CalcClockFreqHz;
  VOID           *SelectExternalSource;
  DOHA_GET_ID    GetPowerDomainId;
  DOHA_BY_ID     EnablePowerDomain;
};

STATIC EFI_GUID  mClockGuid = {
  0x241afae6, 0x885f, 0x4f6c, { 0xa7, 0xea, 0xc2, 0x8e, 0xab, 0x79, 0xc3, 0xe5 }
};

STATIC CONST CHAR8  *mBuses[] = {
  "gcc_disp_ahb_clk",            "gcc_disp_hf_axi_clk",  "gcc_disp_xo_clk",
  "disp_cc_mdss_non_gdsc_ahb_clk", "disp_cc_mdss_ahb_clk",
};
STATIC CONST CHAR8  *mMdp[] = {
  "disp_cc_mdss_mdp_clk",        "disp_cc_mdss_mdp_lut_clk", "disp_cc_mdss_vsync_clk",
};
STATIC CONST CHAR8  *mDsi[] = {
  "disp_cc_mdss_byte0_clk",      "disp_cc_mdss_byte0_intf_clk", "disp_cc_mdss_pclk0_clk",
  "disp_cc_mdss_esc0_clk",
};

STATIC
VOID
Reboot (
  IN UINT32  Seconds
  )
{
  register UINT64  X0 __asm__ ("x0");

  gBS->Stall (Seconds * 1000000);
  DEBUG ((DEBUG_ERROR, "DohaDisp: reboot\n"));
  X0 = PSCI_SYSTEM_RESET;
  __asm__ volatile ("smc #0" : "+r" (X0) : : "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
  DEBUG ((DEBUG_ERROR, "DohaDisp: PSCI reset returned %lx\n", X0));
  for ( ; ; ) {
    gBS->Stall (1000000);
  }
}

/* Returns how many of the clocks read as off. */
STATIC
UINTN
Read (
  IN DOHA_CLOCK         *Clock,
  IN CONST CHAR8 *CONST *Names,
  IN UINTN              Count
  )
{
  UINTN       Off = 0;
  UINTN       Index;
  UINTN       Id;
  BOOLEAN     Enabled;
  BOOLEAN     On;
  EFI_STATUS  Status;

  for (Index = 0; Index < Count; Index++) {
    Enabled = FALSE;
    On      = FALSE;
    Status  = Clock->GetClockId (Clock, Names[Index], &Id);
    if (EFI_ERROR (Status)) {
      DEBUG ((DEBUG_ERROR, "DohaDisp: %a: no id, %r\n", Names[Index], Status));
      continue;
    }

    Clock->IsClockEnabled (Clock, Id, &Enabled);
    Clock->IsClockOn (Clock, Id, &On);
    DEBUG ((DEBUG_ERROR, "DohaDisp: %a enabled %d on %d\n", Names[Index], Enabled, On));
    if (!On) {
      Off++;
    }
  }

  return Off;
}

STATIC
VOID
Enable (
  IN DOHA_CLOCK         *Clock,
  IN CONST CHAR8 *CONST *Names,
  IN UINTN              Count
  )
{
  UINTN       Index;
  UINTN       Id;
  EFI_STATUS  Status;

  for (Index = 0; Index < Count; Index++) {
    Status = Clock->GetClockId (Clock, Names[Index], &Id);
    if (!EFI_ERROR (Status)) {
      Status = Clock->EnableClock (Clock, Id);
    }

    DEBUG ((DEBUG_ERROR, "DohaDisp: enable %a: %r\n", Names[Index], Status));
  }
}

EFI_STATUS
EFIAPI
DohaDispProbeEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  DOHA_CLOCK  *Clock;
  EFI_STATUS  Status;
  UINTN       Id;
  UINTN       Off;

  DEBUG ((DEBUG_ERROR, "DohaDisp: start\n"));
  Status = gBS->LocateProtocol (&mClockGuid, NULL, (VOID **)&Clock);
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_ERROR, "DohaDisp: no clock protocol, %r\n", Status));
    Reboot (15);
  }

  DEBUG ((DEBUG_ERROR, "DohaDisp: clock protocol version %lx\n", Clock->Version));
  Off  = Read (Clock, mBuses, ARRAY_SIZE (mBuses));
  Off += Read (Clock, mMdp, ARRAY_SIZE (mMdp));
  Off += Read (Clock, mDsi, ARRAY_SIZE (mDsi));
  DEBUG ((DEBUG_ERROR, "DohaDisp: %d clocks off\n", (UINT32)Off));

  gBS->Stall (STAGE_SECONDS * 1000000);
  DEBUG ((DEBUG_ERROR, "DohaDisp: stage 1, power domain\n"));
  Status = Clock->GetPowerDomainId (Clock, "mdss_core_gdsc", &Id);
  if (!EFI_ERROR (Status)) {
    Status = Clock->EnablePowerDomain (Clock, Id);
  }

  DEBUG ((DEBUG_ERROR, "DohaDisp: mdss_core_gdsc: %r\n", Status));

  gBS->Stall (STAGE_SECONDS * 1000000);
  DEBUG ((DEBUG_ERROR, "DohaDisp: stage 2, buses\n"));
  Enable (Clock, mBuses, ARRAY_SIZE (mBuses));

  gBS->Stall (STAGE_SECONDS * 1000000);
  DEBUG ((DEBUG_ERROR, "DohaDisp: stage 3, MDP\n"));
  Enable (Clock, mMdp, ARRAY_SIZE (mMdp));

  gBS->Stall (STAGE_SECONDS * 1000000);
  DEBUG ((DEBUG_ERROR, "DohaDisp: stage 4, DSI\n"));
  Enable (Clock, mDsi, ARRAY_SIZE (mDsi));

  /* 20 s went by in the stages. */
  Reboot ((Off != 0) ? 40 : 20);
  return EFI_SUCCESS;
}
