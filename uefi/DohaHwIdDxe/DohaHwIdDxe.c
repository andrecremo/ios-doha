/*
 * Stands in for two Motorola protocols, which the firmware's DisplayDxe asserts without, so that MotHwIdDxe,
 * MotUtagsDxe and the storage modules behind them stay out of the image: this one lives in memory and writes nothing.
 *
 * Hwid. DisplayDxe calls two entries, at 0x18 (a product name, or NULL: it then skips the device tree entry it was
 * matching) and at 0x28 (a number compared with a board revision). Every entry answers 0, which is NULL for the
 * first. What the second number should be is not known yet.
 *
 * Utags. DisplayDxe reaches entries 0x10, 0x18 and 0x20 through wrappers that return a size, 0 until the entry says
 * otherwise, and 0xA8, which says whether a tag exists. Every entry answers EFI_NOT_FOUND and touches nothing: no
 * tag exists, so "BootCycleCount" and "logfs" are taken as not defined and "bare_board" as not set.
 */
#include <Uefi.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>

#define HWID_ENTRIES  16
#define UTAG_ENTRIES  32

STATIC EFI_GUID  mHwIdGuid = {
  0x6634b0ee, 0x0d71, 0x40f4, { 0x59, 0x44, 0x48, 0x7a, 0xd0, 0x29, 0x61, 0x9e }
};
STATIC EFI_GUID  mUtagsGuid = {
  0xfeb30e8d, 0x06ed, 0x4c9a, { 0x8d, 0x35, 0xa8, 0xe5, 0x2a, 0x34, 0x6f, 0x3f }
};

STATIC
UINT64
EFIAPI
Nothing (
  VOID
  )
{
  return 0;
}

STATIC
EFI_STATUS
EFIAPI
NotFound (
  VOID
  )
{
  return EFI_NOT_FOUND;
}

STATIC struct {
  UINT64    Revision;
  VOID      *Entry[HWID_ENTRIES];
} mHwId;

STATIC struct {
  UINT64    Revision;
  VOID      *Entry[UTAG_ENTRIES];
} mUtags;

EFI_STATUS
EFIAPI
DohaHwIdEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  EFI_HANDLE  Handle = NULL;
  EFI_STATUS  Status;
  UINTN       Index;

  mHwId.Revision = 0x10000;   // what MotHwIdDxe has
  for (Index = 0; Index < HWID_ENTRIES; Index++) {
    mHwId.Entry[Index] = (VOID *)Nothing;
  }

  mUtags.Revision = 0x10000;
  for (Index = 0; Index < UTAG_ENTRIES; Index++) {
    mUtags.Entry[Index] = (VOID *)NotFound;
  }

  Status = gBS->InstallMultipleProtocolInterfaces (&Handle, &mHwIdGuid, &mHwId, &mUtagsGuid, &mUtags, NULL);
  DEBUG ((DEBUG_ERROR, "DohaHwId: %r\n", Status));
  return Status;
}
