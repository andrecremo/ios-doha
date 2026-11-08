/*
 * Diagnostic: keeps the screen of a boot that resets or hangs on the eMMC, where a reset of any kind leaves it.
 * It writes the framebuffer (where the log is drawn even with the image off) and the firmware's log buffer to
 * system_b, 128 MiB into the partition, once when it loads and then every 5 s from a timer, at most 12 times.
 * tools/readsave.py reads it back from Android and makes a PNG of the screen.
 *
 * Why not the microSD card: this firmware exposes only the eMMC (its user area and two boot partitions), measured
 * with this driver on the phone.
 *
 * system_b is the B slot's system partition, which this phone does not boot (slot A is active), already used for
 * the XNU write tests. Before writing anything the driver requires all of these, or it writes nothing:
 *   - a whole disk of exactly EMMC_BLOCKS sectors of 512 bytes (the eMMC user area, measured on this phone);
 *   - in its GPT, an entry named system_b whose first and last LBA are the ones measured on this phone;
 *   - the area to write inside that entry.
 *
 *   sector 0      header: "DOHADSK1", seconds, count, fb size, log size, width, height, stride, counter at load
 *   sector 1...   the framebuffer, 1080 x 2280 x 4, padded to a sector
 *   then          the log buffer, 0x8000 bytes
 */
#include <Uefi.h>
#include <Protocol/BlockIo.h>
#include <Library/DebugLib.h>
#include <Library/UefiBootServicesTableLib.h>

/*
 * DohaSaveConfig.h, written by mkdohapkg.py from DOHA_SAVE_ONCE: SAVE_ONCE 1 keeps only the write at load, with no
 * timer and no watcher core.
 */
#include "DohaSaveConfig.h"

#define EMMC_BLOCKS  122142720ULL
#define PART_FIRST   11599872ULL
#define PART_LAST    17924095ULL
#define SAVE_LBA     (PART_FIRST + 262144ULL)    /* 128 MiB into the partition */
#define SECTOR       512

#define FB_BASE      0x5C000000UL
#define FB_W         1080
#define FB_H         2280
#define FB_STRIDE    (FB_W * 4)
#define FB_SIZE      (FB_STRIDE * FB_H)
#define FB_PADDED    ((FB_SIZE + SECTOR - 1) / SECTOR * SECTOR)
#define LOG_BASE     0x5FFF7000UL
#define LOG_SIZE     0x8000UL
#define SAVE_SIZE    (SECTOR + FB_PADDED + LOG_SIZE)
#define SAVE_SECTORS (SAVE_SIZE / SECTOR)
#define SAVE_MAGIC   0x314B534441484F44ULL      /* "DOHADSK1" */

#define STEP_SECONDS  5
#define MAX_WRITES    12

/*
 * A second timer, at TPL_NOTIFY, copies the same buffers to RAM every second, for the shim (shim.c, show_saved):
 * it still runs when the module after this one holds TPL_CALLBACK, which stops the timer that writes the eMMC.
 * If neither runs, interrupts are off.
 */
#define RAM_FB       0x5B100000UL
#define RAM_LOG      0x5BA80000UL
#define RAM_HEADER   0x5BAFF000UL
#define RAM_MAGIC    0x31474F4C41484F44ULL      /* "DOHALOG1" */

STATIC UINT32     mRamSeconds;
STATIC EFI_EVENT  mRamEvent;

/*
 * When interrupts are off for good on the boot core (no timer runs, which the doha showed once the module after this
 * one starts), only another core can still see the screen. The last core is started as a watcher: MMU off, all
 * registers and no stack, every access aligned. Once a second it copies the framebuffer and the log buffer to the
 * same RAM area, and writes 1000 + its seconds in the header, so the shim tells its copies from the ones above. At
 * 20 s it asks for a reboot. If nothing else resets the phone first.
 */
#define PSCI_CPU_ON    0xC4000003
#define WATCH_CORE     0x103
#define WATCH_LENGTH   0x200

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
    "   add   x22, x21, #1000            \n"
    "   str   x22, [x5, #8]              \n"
    "   str   x7, [x5]                   \n"
    "   dsb   sy                         \n"
    "   cmp   x21, #20                   \n"
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

STATIC
VOID
StartWatcher (
  VOID
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
    DEBUG ((DEBUG_ERROR, "DohaSave: watcher %lx\n", X0));
  }
}

STATIC EFI_BLOCK_IO_PROTOCOL  *mDisk;
STATIC UINT8                  *mBuffer;
STATIC UINT32                 mSeconds;
STATIC UINT32                 mCount;
STATIC UINT64                 mStamp;
STATIC EFI_EVENT              mEvent;

STATIC
VOID
Copy (
  IN UINT8        *To,
  IN CONST UINT8  *From,
  IN UINTN        Size
  )
{
  volatile UINT32  *Src = (volatile UINT32 *)From;
  UINT32           *Dst = (UINT32 *)To;
  UINTN            Index;

  for (Index = 0; Index < Size / 4; Index++) {
    Dst[Index] = Src[Index];
  }
}

STATIC
BOOLEAN
SameName (
  IN CONST UINT16  *Entry
  )
{
  STATIC CONST CHAR16  Name[] = L"system_b";
  UINTN                Index;

  for (Index = 0; Index < ARRAY_SIZE (Name); Index++) {
    if (Entry[Index] != Name[Index]) {
      return FALSE;
    }
  }

  return TRUE;
}

/* TRUE only if this disk's GPT has system_b exactly where it was measured. */
STATIC
BOOLEAN
HasOurPartition (
  IN EFI_BLOCK_IO_PROTOCOL  *Disk
  )
{
  UINT8       Header[SECTOR];
  UINT8       *Entries;
  UINT64      EntryLba;
  UINT32      Number, Size, Index;
  UINTN       Bytes;
  EFI_STATUS  Status;
  BOOLEAN     Found = FALSE;

  Status = Disk->ReadBlocks (Disk, Disk->Media->MediaId, 1, SECTOR, Header);
  if (EFI_ERROR (Status) || (*(UINT64 *)Header != 0x5452415020494645ULL)) {     /* "EFI PART" */
    DEBUG ((DEBUG_ERROR, "DohaSave: no GPT, %r\n", Status));
    return FALSE;
  }

  EntryLba = *(UINT64 *)(Header + 72);
  Number   = *(UINT32 *)(Header + 80);
  Size     = *(UINT32 *)(Header + 84);
  if ((Size < 128) || (Number == 0) || (Number > 256)) {
    return FALSE;
  }

  Bytes = ((UINTN)Number * Size + SECTOR - 1) / SECTOR * SECTOR;
  if (EFI_ERROR (gBS->AllocatePool (EfiBootServicesData, Bytes, (VOID **)&Entries))) {
    return FALSE;
  }

  Status = Disk->ReadBlocks (Disk, Disk->Media->MediaId, EntryLba, Bytes, Entries);
  for (Index = 0; !EFI_ERROR (Status) && Index < Number; Index++) {
    UINT8  *Entry = Entries + (UINTN)Index * Size;

    if (SameName ((UINT16 *)(Entry + 56))) {
      Found = (*(UINT64 *)(Entry + 32) == PART_FIRST) && (*(UINT64 *)(Entry + 40) == PART_LAST);
      DEBUG ((DEBUG_ERROR, "DohaSave: system_b %lu..%lu %a\n", *(UINT64 *)(Entry + 32), *(UINT64 *)(Entry + 40),
              Found ? "matches" : "DOES NOT MATCH"));
      break;
    }
  }

  gBS->FreePool (Entries);
  return Found;
}

STATIC
VOID
Store (
  VOID
  )
{
  UINT64      *Header = (UINT64 *)mBuffer;
  EFI_STATUS  Status;
  UINTN       Index;

  for (Index = 0; Index < SECTOR / 8; Index++) {
    Header[Index] = 0;
  }

  mCount++;
  Header[1] = mSeconds;
  Header[2] = mCount;
  Header[3] = FB_SIZE;
  Header[4] = LOG_SIZE;
  Header[5] = FB_W;
  Header[6] = FB_H;
  Header[7] = FB_STRIDE;
  Header[8] = mStamp;
  Copy (mBuffer + SECTOR, (UINT8 *)FB_BASE, FB_SIZE);
  Copy (mBuffer + SECTOR + FB_PADDED, (UINT8 *)LOG_BASE, LOG_SIZE);
  Header[0] = SAVE_MAGIC;

  Status = mDisk->WriteBlocks (mDisk, mDisk->Media->MediaId, SAVE_LBA, SAVE_SIZE, mBuffer);
  if (!EFI_ERROR (Status)) {
    Status = mDisk->FlushBlocks (mDisk);
  }

  DEBUG ((DEBUG_ERROR, "DohaSave: %u s written, %r\n", mSeconds, Status));
}

STATIC
VOID
EFIAPI
RamTick (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  volatile UINT64  *Header = (volatile UINT64 *)RAM_HEADER;
  volatile UINT32  *Dst;
  volatile UINT32  *Src;
  UINTN            Index;

  Dst = (volatile UINT32 *)RAM_FB;
  Src = (volatile UINT32 *)FB_BASE;
  for (Index = 0; Index < FB_SIZE / 4; Index++) {
    Dst[Index] = Src[Index];
  }

  Dst = (volatile UINT32 *)RAM_LOG;
  Src = (volatile UINT32 *)LOG_BASE;
  for (Index = 0; Index < LOG_SIZE / 4; Index++) {
    Dst[Index] = Src[Index];
  }

  Header[1] = mRamSeconds++;
  Header[0] = RAM_MAGIC;
}

STATIC
VOID
EFIAPI
Tick (
  IN EFI_EVENT  Event,
  IN VOID       *Context
  )
{
  mSeconds += STEP_SECONDS;
  Store ();
  if (mCount >= MAX_WRITES) {
    gBS->SetTimer (mEvent, TimerCancel, 0);
  }
}

EFI_STATUS
EFIAPI
DohaSaveEntry (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE  *SystemTable
  )
{
  EFI_HANDLE             *Handles;
  UINTN                  Count, Index;
  EFI_BLOCK_IO_PROTOCOL  *Disk;
  EFI_STATUS             Status;

  Status = gBS->LocateHandleBuffer (ByProtocol, &gEfiBlockIoProtocolGuid, NULL, &Count, &Handles);
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_ERROR, "DohaSave: no block device, %r\n", Status));
    return EFI_SUCCESS;
  }

  for (Index = 0; Index < Count && mDisk == NULL; Index++) {
    if (EFI_ERROR (gBS->HandleProtocol (Handles[Index], &gEfiBlockIoProtocolGuid, (VOID **)&Disk))) {
      continue;
    }

    if (Disk->Media->LogicalPartition || !Disk->Media->MediaPresent || (Disk->Media->BlockSize != SECTOR) ||
        (Disk->Media->LastBlock + 1 != EMMC_BLOCKS))
    {
      continue;
    }

    if (HasOurPartition (Disk)) {
      mDisk = Disk;
    }
  }

  gBS->FreePool (Handles);
  if ((mDisk == NULL) || (SAVE_LBA + SAVE_SECTORS - 1 > PART_LAST)) {
    DEBUG ((DEBUG_ERROR, "DohaSave: system_b not found where it should be: nothing written\n"));
    return EFI_SUCCESS;
  }

  if (EFI_ERROR (gBS->AllocatePool (EfiBootServicesData, SAVE_SIZE, (VOID **)&mBuffer))) {
    return EFI_SUCCESS;
  }

  __asm__ volatile ("mrs %0, cntpct_el0" : "=r" (mStamp));
  Store ();
  if (SAVE_ONCE) {
    return EFI_SUCCESS;
  }

  /* SECONDS 0 in the shim: only this copy; more: the TPL_NOTIFY timer ran that many times after it. */
  RamTick (NULL, NULL);
  Status = gBS->CreateEvent (EVT_TIMER | EVT_NOTIFY_SIGNAL, TPL_NOTIFY, RamTick, NULL, &mRamEvent);
  if (!EFI_ERROR (Status)) {
    Status = gBS->SetTimer (mRamEvent, TimerPeriodic, 10000000ULL);
  }

  DEBUG ((DEBUG_ERROR, "DohaSave: RAM timer %r\n", Status));
  StartWatcher ();

  /* TPL_CALLBACK: the highest level the block driver may be called at. */
  Status = gBS->CreateEvent (EVT_TIMER | EVT_NOTIFY_SIGNAL, TPL_CALLBACK, Tick, NULL, &mEvent);
  if (!EFI_ERROR (Status)) {
    Status = gBS->SetTimer (mEvent, TimerPeriodic, STEP_SECONDS * 10000000ULL);
  }

  DEBUG ((DEBUG_ERROR, "DohaSave: timer %r\n", Status));
  return EFI_SUCCESS;
}
