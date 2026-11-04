/*
 * Userspace program on doha, installed as /sbin/launchd on a test volume. It needs a
 * kernel with writes enabled on that volume (boot-arg emmcwrite=).
 *
 * Each boot it remounts the root read-write, reads /doha-count, checks that /doha-data
 * still holds what the previous boot wrote, rewrites both, ticks for 15 s, remounts the
 * root read-only, which marks the volume clean, and exits. A reboot in between proves
 * the data reached the flash. /doha-data is 2 MiB, larger than the driver's 1 MiB bounce
 * buffer. init exiting panics the kernel, and the panic prints the exit status:
 *   status 42        everything passed
 *   status 58..70    the failing step (printed on the console with its errno)
 *   status 100+errno could not open the console
 *
 * tools/mkinit.py wraps __text into a static Mach-O: everything here is PC-relative,
 * with no relocations and no writable data; the stack is the only writable memory.
 *
 * Raw XNU syscalls: number in x16, svc #0x80, carry set on error.
 * Registers: x19 console, x22 count file, x23 previous count, x24 data file,
 * x25 block, x26 word index, x28 current step.
 */
#define SYS_exit	1
#define SYS_read	3
#define SYS_write	4
#define SYS_open	5
#define SYS_close	6
#define SYS_getpid	20
#define SYS_sync	36
#define SYS_select	93
#define SYS_fsync	95
#define SYS_mount	167
#define SYS_lseek	199
#define MNT_RDONLY	0x00000001
#define MNT_UPDATE	0x00010000
#define O_RDONLY	0
#define O_RDWR		2
#define O_RDWR_CREAT	0x202
#define O_WRONLY_CREAT_TRUNC 0x601
#define MODE_644	0x1a4
#define BUF_SIZE	16384
#define BUF_WORDS	(BUF_SIZE / 8)
#define BLOCKS		128
#define RECORD_SIZE	14
#define PREFIX_SIZE	11
#define TICKS		3
#define STATUS_DONE	42
#define STATUS_NO_CONSOLE 100

	.macro put_text from, to
	adr	x1, \from
	adr	x2, \to
	sub	x2, x2, x1
	bl	put
	.endm

	.macro syscall number
	mov	x16, #\number
	svc	#0x80
	.endm

	.text
	.globl	_start
	.p2align 2
_start:
	/* sp points at argc and may be misaligned. [sp] is for digits, [sp + 16] the buffer. */
	mov	x9, sp
	and	x9, x9, #~15
	sub	x9, x9, #4, lsl #12		/* BUF_SIZE */
	sub	x9, x9, #32
	mov	sp, x9

	adr	x0, console_path
	mov	x1, #O_RDWR
	mov	x2, #0
	syscall	SYS_open
	b.cc	console_open
	add	x0, x0, #STATUS_NO_CONSOLE
	b	exit

console_open:
	mov	x19, x0
	put_text hello, hello_pid
	syscall	SYS_getpid
	bl	put_number
	put_text hello_pid, mounted_text

	/*
	 * mount -uw /. The data is what mount_hfs passes: the device path, then struct
	 * hfs_mount_args with every field VNOVAL (-1), meaning "leave as it is". The HFS
	 * update path asserts that this pointer is not NULL.
	 */
	mov	x28, #58
	mov	x2, #MNT_UPDATE
	bl	remount
	b.cs	fail
	put_text mounted_text, previous_text

	/* The count of the previous boot; an empty file means there was none. */
	mov	x28, #60
	adr	x0, count_path
	mov	x1, #O_RDWR_CREAT
	mov	x2, #MODE_644
	syscall	SYS_open
	b.cs	fail
	mov	x22, x0

	mov	x28, #61
	mov	x0, x22
	add	x1, sp, #16
	mov	x2, #RECORD_SIZE
	syscall	SYS_read
	b.cs	fail
	mov	x23, #0
	cbz	x0, have_count

	mov	x28, #62
	cmp	x0, #RECORD_SIZE
	b.ne	fail_value
	adr	x9, record
	add	x10, sp, #16
	mov	x11, #0
check_prefix:
	ldrb	w12, [x9, x11]
	ldrb	w13, [x10, x11]
	cmp	w12, w13
	b.ne	fail_value
	add	x11, x11, #1
	cmp	x11, #PREFIX_SIZE
	b.lo	check_prefix
	ldrb	w12, [x10, #PREFIX_SIZE]
	ldrb	w13, [x10, #PREFIX_SIZE + 1]
	sub	w12, w12, #'0'
	sub	w13, w13, #'0'
	cmp	w12, #9
	b.hi	fail_value
	cmp	w13, #9
	b.hi	fail_value
	mov	w9, #10
	mul	w12, w12, w9
	add	w23, w12, w13

have_count:
	put_text previous_text, data_ok_text
	mov	x0, x23
	bl	put_number
	put_text newline, newline_end
	cbz	x23, write_new

	/* What the previous boot wrote must still be there. */
	mov	x28, #63
	adr	x0, data_path
	mov	x1, #O_RDONLY
	mov	x2, #0
	syscall	SYS_open
	b.cs	fail
	mov	x24, x0
	mov	x25, #0
	mov	x26, #0
check_block:
	mov	x28, #64
	mov	x0, x24
	add	x1, sp, #16
	mov	x2, #BUF_SIZE
	syscall	SYS_read
	b.cs	fail
	mov	x28, #65
	mov	x9, #BUF_SIZE
	cmp	x0, x9
	b.ne	fail_value
	add	x10, sp, #16
	mov	x11, #BUF_WORDS
check_word:
	orr	x12, x26, x23, lsl #32
	ldr	x13, [x10], #8
	cmp	x12, x13
	b.ne	fail_value
	add	x26, x26, #1
	subs	x11, x11, #1
	b.ne	check_word
	add	x25, x25, #1
	cmp	x25, #BLOCKS
	b.lo	check_block
	mov	x0, x24
	syscall	SYS_close
	put_text data_ok_text, wrote_text

write_new:
	add	x23, x23, #1

	mov	x28, #66
	adr	x0, data_path
	mov	x1, #O_WRONLY_CREAT_TRUNC
	mov	x2, #MODE_644
	syscall	SYS_open
	b.cs	fail
	mov	x24, x0
	mov	x25, #0
	mov	x26, #0
write_block:
	add	x10, sp, #16
	mov	x11, #BUF_WORDS
fill_word:
	orr	x12, x26, x23, lsl #32
	str	x12, [x10], #8
	add	x26, x26, #1
	subs	x11, x11, #1
	b.ne	fill_word
	mov	x28, #67
	mov	x0, x24
	add	x1, sp, #16
	mov	x2, #BUF_SIZE
	syscall	SYS_write
	b.cs	fail
	mov	x9, #BUF_SIZE
	cmp	x0, x9
	b.ne	fail_value
	add	x25, x25, #1
	cmp	x25, #BLOCKS
	b.lo	write_block
	mov	x28, #68
	mov	x0, x24
	syscall	SYS_fsync
	b.cs	fail
	mov	x0, x24
	syscall	SYS_close

	/* The record, built on the stack, over the old one. */
	adr	x9, record
	add	x10, sp, #16
	mov	x11, #0
copy_record:
	ldrb	w12, [x9, x11]
	strb	w12, [x10, x11]
	add	x11, x11, #1
	cmp	x11, #RECORD_SIZE
	b.lo	copy_record
	mov	x9, #10
	udiv	x11, x23, x9
	msub	x12, x11, x9, x23
	add	w11, w11, #'0'
	add	w12, w12, #'0'
	strb	w11, [x10, #PREFIX_SIZE]
	strb	w12, [x10, #PREFIX_SIZE + 1]

	mov	x28, #69
	mov	x0, x22
	mov	x1, #0
	mov	x2, #0
	syscall	SYS_lseek
	b.cs	fail
	mov	x0, x22
	add	x1, sp, #16
	mov	x2, #RECORD_SIZE
	syscall	SYS_write
	b.cs	fail
	mov	x0, x22
	syscall	SYS_fsync
	b.cs	fail
	mov	x0, x22
	syscall	SYS_close
	syscall	SYS_sync

	put_text wrote_text, tick_text
	mov	x0, x23
	bl	put_number
	put_text newline, newline_end

	mov	x20, #1
tick:
	mov	x0, #0
	mov	x1, #0
	mov	x2, #0
	mov	x3, #0
	adr	x4, five_seconds
	syscall	SYS_select
	put_text tick_text, newline
	mov	x0, x20
	bl	put_number
	put_text newline, newline_end
	add	x20, x20, #1
	cmp	x20, #TICKS
	b.ls	tick

	/* mount -ur /: flushes everything and marks the volume clean. */
	mov	x28, #70
	mov	x2, #MNT_UPDATE
	orr	x2, x2, #MNT_RDONLY
	bl	remount
	b.cs	fail

	put_text bye, bye_end
	mov	x0, #STATUS_DONE
exit:
	syscall	SYS_exit
1:	b	1b

fail_value:
	mov	x0, #0
fail:
	mov	x27, x0
	put_text failed_text, errno_text
	mov	x0, x28
	bl	put_number
	put_text errno_text, record
	mov	x0, x27
	bl	put_number
	put_text newline, newline_end
	mov	x0, x28
	b	exit

/* mount("hfs", "/", x2, args); leaves the carry flag from the syscall. Leaf, keeps lr. */
remount:
	add	x3, sp, #16
	mov	x9, #-1
	stp	x9, x9, [x3]
	stp	x9, x9, [x3, #16]
	stp	x9, x9, [x3, #32]
	stp	x9, x9, [x3, #48]
	adr	x9, device_path
	str	x9, [x3]
	adr	x0, hfs_name
	adr	x1, root_path
	mov	x16, #SYS_mount
	svc	#0x80
	ret

/* write(console, x1, x2); leaf, keeps lr */
put:
	mov	x0, x19
	mov	x16, #SYS_write
	svc	#0x80
	ret

/* Writes x0 (below 100) in decimal. */
put_number:
	mov	x21, lr
	mov	x9, #10
	udiv	x10, x0, x9
	msub	x11, x10, x9, x0
	add	x10, x10, #'0'
	add	x11, x11, #'0'
	strb	w10, [sp]
	strb	w11, [sp, #1]
	mov	x1, sp
	mov	x2, #2
	bl	put
	mov	lr, x21
	ret

	.p2align 3
five_seconds:
	.quad	5		/* tv_sec */
	.quad	0		/* tv_usec and padding */
console_path:
	.asciz	"/dev/console"
device_path:
	.asciz	"/dev/emmcroot0"
hfs_name:
	.asciz	"hfs"
root_path:
	.asciz	"/"
count_path:
	.asciz	"/doha-count"
data_path:
	.asciz	"/doha-data"
hello:
	.ascii	"\n*** DOHA userspace: init running, PID "
hello_pid:
	.ascii	" ***\n"
mounted_text:
	.ascii	"DOHA init: root is read-write\n"
previous_text:
	.ascii	"DOHA init: previous count "
data_ok_text:
	.ascii	"DOHA init: 2 MiB from the previous boot ok\n"
wrote_text:
	.ascii	"DOHA init: wrote count "
tick_text:
	.ascii	"DOHA init: tick "
newline:
	.ascii	"\n"
newline_end:
bye:
	.ascii	"DOHA init: exiting with status 42\n"
bye_end:
failed_text:
	.ascii	"DOHA init: FAILED step "
errno_text:
	.ascii	" errno "
record:
	.ascii	"DOHA-COUNT 00\n"
