/*
 * Keeps the screen ABL left on alive after ClockDxe. On the doha, once ClockDxe has loaded, the display's AXI
 * clock (gcc_disp_hf_axi_clk) halts though still enabled: its bus, the real-time multimedia NoC, is an RPM
 * resource ClockDxe creates as /clk/mmrt, and with no client asking for it the RPM turns it off, so the display
 * can no longer read the framebuffer. The firmware's own DisplayDxe asks for it first; this does the same,
 * through the NPA protocol of NpaDxe, with the same request (a required client, 240000 kHz).
 *
 * The protocol entries, read from the firmware's DisplayDxe: 0x10 creates a client
 * (resource, client name, type, value, data, &handle), 0x28 issues a scalar request (handle, state).
 */
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>

#define NPA_CLIENT_REQUIRED  0x40
#define MMRT_KHZ             240000

typedef VOID  *NPA_CLIENT;
typedef EFI_STATUS (EFIAPI *NPA_CREATE)(CONST CHAR8 *Resource, CONST CHAR8 *Client, UINT32 Type, UINT32 Value,
                                         VOID *Data, NPA_CLIENT *Handle);
typedef VOID (EFIAPI *NPA_ISSUE)(NPA_CLIENT Handle, UINT32 State);

STATIC EFI_GUID  mNpaGuid = {
  0x79d6c870, 0x725e, 0x489e, { 0xa0, 0xa1, 0x27, 0xe7, 0xa5, 0xd0, 0xcb, 0x35 }
};

EFI_STATUS
EFIAPI
DohaMmrtEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  UINT8       *Npa;
  NPA_CLIENT  Client = NULL;
  EFI_STATUS  Status;

  Status = gBS->LocateProtocol (&mNpaGuid, NULL, (VOID **)&Npa);
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_ERROR, "DohaMmrt: no NPA protocol, %r\n", Status));
    return EFI_SUCCESS;
  }

  Status = (*(NPA_CREATE *)(Npa + 0x10))("/clk/mmrt", "DOHA_DISPLAY_KEEP", NPA_CLIENT_REQUIRED, 0, NULL, &Client);
  if (EFI_ERROR (Status) || (Client == NULL)) {
    DEBUG ((DEBUG_ERROR, "DohaMmrt: no client for /clk/mmrt, %r\n", Status));
    return EFI_SUCCESS;
  }

  (*(NPA_ISSUE *)(Npa + 0x28))(Client, MMRT_KHZ);
  DEBUG ((DEBUG_ERROR, "DohaMmrt: /clk/mmrt requested at %u kHz\n", MMRT_KHZ));
  return EFI_SUCCESS;
}
