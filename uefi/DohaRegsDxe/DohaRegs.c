/*
 * Diagnostic: what ClockDxe changes in the display hardware the doha's ABL left on. Built twice:
 *   DohaRegsBefore.inf, loaded before ClockDxe, reads the registers into RAM;
 *   DohaRegsAfter.inf (REGS_AFTER), loaded after it, reads them again and prints both on the screen, where a
 *   DohaSaveDxe right after keeps them on the eMMC.
 *
 * Reads only. Offsets from Linux, drivers/clk/qcom/dispcc-sm6125.c and gcc-sm6125.c. The display clock
 * controller is read only while its bus clock (gcc_disp_ahb_clk) is on, and the display core (MDSS) only while
 * its power domain and its bus clock are on: an access to a block without its clock can hang the bus.
 */
#include <Uefi.h>
#include <Library/DebugLib.h>

#ifndef REGS_AFTER
#define REGS_AFTER  0
#endif

#define GCC       0x01400000UL
#define DISPCC    0x05F00000UL
#define MDSS      0x05E00000UL
#define STORE     0x5BAFE000UL       /* in the "DBI Dump" RAM region, next to the shim's header */
#define MAGIC     0x52454753U        /* "REGS" */
#define SKIPPED   0xDEAD0000U

#define CLK_OFF   (1U << 31)         /* branch clock: halted */
#define PWR_ON    (1U << 31)         /* GDSC: powered */

typedef struct {
  CONST CHAR8  *Name;
  UINTN        Address;
  UINT8        Needs;                /* 0 always, 1 the display bus clock, 2 also the MDSS power domain */
} REG;

STATIC CONST REG  mRegs[] = {
  { "gcc_disp_ahb_cbcr",     GCC + 0x1700c,    0 },
  { "gcc_disp_hf_axi_cbcr",  GCC + 0x17020,    0 },
  { "gcc_disp_xo_cbcr",      GCC + 0x1702c,    0 },
  { "gcc_disp_throttle",     GCC + 0x17064,    0 },
  { "gcc_vote_79004",        GCC + 0x79004,    0 },
  { "gcc_vote_7900c",        GCC + 0x7900c,    0 },
  { "mdss_gdscr",            DISPCC + 0x3000,  1 },
  { "dcc_pll0_mode",         DISPCC + 0x0000,  1 },
  { "dcc_mdss_ahb_cbcr",     DISPCC + 0x2044,  1 },
  { "dcc_mdp_cbcr",          DISPCC + 0x2008,  1 },
  { "dcc_byte0_cbcr",        DISPCC + 0x2024,  1 },
  { "dcc_byte0_intf_cbcr",   DISPCC + 0x2028,  1 },
  { "dcc_pclk0_cbcr",        DISPCC + 0x2004,  1 },
  { "dcc_esc0_cbcr",         DISPCC + 0x202c,  1 },
  { "dcc_vsync_cbcr",        DISPCC + 0x2020,  1 },
  { "dcc_non_gdsc_ahb_cbcr", DISPCC + 0x4004,  1 },
  { "dcc_xo_cbcr",           DISPCC + 0x604c,  1 },
  { "dcc_mdp_rcgr",          DISPCC + 0x2074,  1 },
  { "dcc_byte0_rcgr",        DISPCC + 0x20bc,  1 },
  { "dcc_pclk0_rcgr",        DISPCC + 0x205c,  1 },
  { "dcc_esc0_rcgr",         DISPCC + 0x20d8,  1 },
  { "mdss_hw_version",       MDSS + 0x0000,    2 },
  { "mdp_vig0_src0_addr",    MDSS + 0x5014,    2 },
  { "mdp_vig0_src_size",     MDSS + 0x5000,    2 },
};

#define COUNT  ARRAY_SIZE (mRegs)

STATIC
UINT32
Rd (
  IN UINTN  Address
  )
{
  return *(volatile UINT32 *)Address;
}

STATIC
VOID
ReadAll (
  OUT UINT32  *Values
  )
{
  BOOLEAN  Bus, Core;
  UINTN    Index;

  /*
   * gcc_disp_ahb_clk is gated by hardware when idle, so its halt bit can read 1 while it runs: what counts is that
   * it is enabled (bit 0). Linux keeps it on as critical.
   */
  Bus  = (Rd (GCC + 0x1700c) & 1) != 0;
  Core = Bus && (Rd (DISPCC + 0x3000) & PWR_ON) && ((Rd (DISPCC + 0x2044) & CLK_OFF) == 0);
  for (Index = 0; Index < COUNT; Index++) {
    if (((mRegs[Index].Needs == 1) && !Bus) || ((mRegs[Index].Needs == 2) && !Core)) {
      Values[Index] = SKIPPED;
    } else {
      Values[Index] = Rd (mRegs[Index].Address);
    }
  }
}

EFI_STATUS
EFIAPI
DohaRegsEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  volatile UINT32  *Store = (volatile UINT32 *)STORE;
  UINT32           Now[COUNT];
  UINTN            Index;

  ReadAll (Now);
  if (!REGS_AFTER) {
    for (Index = 0; Index < COUNT; Index++) {
      Store[1 + Index] = Now[Index];
    }

    Store[0] = MAGIC;
    DEBUG ((DEBUG_ERROR, "DohaRegs: %u registers read before\n", (UINT32)COUNT));
    return EFI_SUCCESS;
  }

  DEBUG ((DEBUG_ERROR, "DohaRegs: before / after (DEAD0000 = not read: block without its clock)\n"));
  for (Index = 0; Index < COUNT; Index++) {
    DEBUG ((DEBUG_ERROR, "DohaRegs: %-22a %08x %08x%a\n", mRegs[Index].Name,
            (Store[0] == MAGIC) ? Store[1 + Index] : 0xFFFFFFFF, Now[Index],
            ((Store[0] == MAGIC) && (Store[1 + Index] != Now[Index])) ? "  <<" : ""));
  }

  Store[0] = 0;
  return EFI_SUCCESS;
}
