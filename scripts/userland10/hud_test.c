/*
 * hud_test: what is going on in a running iOS, said on the panel over the picture (the Keys line, through the
 * kernel's kern.redwood_note), for a phone whose log nobody can read. Each line also goes to the standard output.
 * One line every 4 s, the last staying. Run as root (the launchd job com.redwood.demo, rc.jobs.dohasafari).
 *
 * usage: hud_test STEP...
 *   ps PATTERN        the processes whose executable's name contains PATTERN: "name pid", as many as fit
 *   crashes           how many crash reports there are, then the newest six: the process and the exception
 *   serve PORT        the whole log (every line said, every line of a probe) to whoever connects to PORT over TCP,
 *                     from its first line on, while this program runs; lines stay 1 s on the panel instead of 4
 *   probe PROGRAM     run PROGRAM ("ok ..."/"FAIL ..." a line each): its FAILs, a count every 10, how it ended
 *   env NAME=VALUE    an environment variable for the programs started after it (probe)
 *   say TEXT          TEXT itself
 *   wait SECONDS
 */
#include <dirent.h>
#include <signal.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/types.h>
#include <unistd.h>

#define LINE 56

#include <netinet/in.h>
#include <pthread.h>
#include <sys/socket.h>

/*
 * The log, for the network (serve PORT): every line said or read from a probe, kept in one growing buffer; whoever
 * connects to PORT over TCP gets it from its first byte and then each new line as it comes. Read-only: nothing that
 * comes from the other side is read at all.
 */
static char *log_text;
static size_t log_length, log_room;
static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t log_grew = PTHREAD_COND_INITIALIZER;
static int serving;
static unsigned pause_s = 4;            /* how long a line stays on the panel before the next (1 while serving) */

static void
log_line(const char *text)
{
	size_t n = strlen(text);

	pthread_mutex_lock(&log_lock);
	if (log_text == NULL && (log_text = malloc(16u << 20)) != NULL) {
		log_room = 16u << 20;           /* (once, and never moved: a client sends from it without the lock) */
	}
	if (log_length + n + 2 <= log_room) {
		memcpy(log_text + log_length, text, n);
		log_text[log_length + n] = '\n';
		log_length += n + 1;
		pthread_cond_broadcast(&log_grew);
	}
	pthread_mutex_unlock(&log_lock);
}

static void *
log_client(void *arg)
{
	int s = (int)(intptr_t)arg;
	size_t sent = 0;

	signal(SIGPIPE, SIG_IGN);
	for (;;) {
		size_t have;

		pthread_mutex_lock(&log_lock);
		while (sent == log_length) {
			pthread_cond_wait(&log_grew, &log_lock);
		}
		have = log_length;
		pthread_mutex_unlock(&log_lock);
		while (sent < have) {
			ssize_t n = send(s, log_text + sent, have - sent, 0);

			if (n <= 0) {
				close(s);
				return NULL;
			}
			sent += (size_t)n;
		}
	}
}

static void *
log_server(void *arg)
{
	int port = (int)(intptr_t)arg, l = socket(AF_INET, SOCK_STREAM, 0), one = 1;
	struct sockaddr_in a;

	memset(&a, 0, sizeof(a));
	a.sin_family = AF_INET;
	a.sin_port = htons((uint16_t)port);
	a.sin_addr.s_addr = htonl(INADDR_ANY);
	setsockopt(l, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
	if (l < 0 || bind(l, (struct sockaddr *)&a, sizeof(a)) != 0 || listen(l, 4) != 0) {
		log_line("hud_test: serve: the port could not be opened");
		return NULL;
	}
	for (;;) {
		int c = accept(l, NULL, NULL);
		pthread_t t;

		if (c >= 0 && pthread_create(&t, NULL, log_client, (void *)(intptr_t)c) == 0) {
			pthread_detach(t);
		} else if (c >= 0) {
			close(c);
		}
	}
}

static void
say(const char *format, ...)
{
	char line[256], logged[280];
	va_list list;

	va_start(list, format);
	vsnprintf(line, sizeof(line), format, list);
	va_end(list);
	printf("hud_test: %s\n", line);
	fflush(stdout);
	snprintf(logged, sizeof(logged), "hud_test: %s", line);
	log_line(logged);
	sysctlbyname("kern.redwood_note", NULL, NULL, line, strlen(line) < LINE ? strlen(line) : LINE);
	sleep(pause_s);
}

/* the executable's file name of a process (KERN_PROCARGS2: argc, then the path), or its 16-character p_comm */
static void
process_name(pid_t pid, const char *comm, char *name, size_t size)
{
	int mib[3] = { CTL_KERN, KERN_PROCARGS2, pid };
	static char args[16384];
	size_t length = sizeof(args);

	strlcpy(name, comm, size);
	if (sysctl(mib, 3, args, &length, NULL, 0) == 0 && length > sizeof(int)) {
		const char *path = args + sizeof(int), *base;

		if (memchr(path, 0, length - sizeof(int)) != NULL && path[0] != 0) {
			base = strrchr(path, '/');
			strlcpy(name, base != NULL ? base + 1 : path, size);
		}
	}
}

static void
ps(const char *pattern)
{
	int mib[4] = { CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0 };
	struct kinfo_proc *procs;
	size_t length = 0;
	char line[256] = "", one[96], name[96];
	unsigned found = 0;

	if (sysctl(mib, 4, NULL, &length, NULL, 0) != 0 || (procs = malloc(length + 16 * sizeof(*procs))) == NULL) {
		say("ps %s: no list of processes", pattern);
		return;
	}
	length += 16 * sizeof(*procs);
	if (sysctl(mib, 4, procs, &length, NULL, 0) != 0) {
		free(procs);
		say("ps %s: no list of processes", pattern);
		return;
	}
	for (size_t i = 0; i < length / sizeof(*procs); i++) {
		pid_t pid = procs[i].kp_proc.p_pid;
		const char *shown;

		process_name(pid, procs[i].kp_proc.p_comm, name, sizeof(name));
		if (strcasestr(name, pattern) == NULL) {
			continue;
		}
		/* (com.apple.WebKit.WebContent: the part after the last dot is what tells them apart) */
		shown = strncmp(name, "com.apple.", 10) == 0 && strrchr(name, '.') != NULL ? strrchr(name, '.') + 1 : name;
		snprintf(one, sizeof(one), "%s%s %d", found ? ", " : "", shown, pid);
		if (strlen(line) + strlen(one) > LINE - 8 && line[0] != 0) {
			say("%s: %s", pattern, line);
			snprintf(one, sizeof(one), "%s %d", shown, pid);
			line[0] = 0;
		}
		strlcat(line, one, sizeof(line));
		found++;
	}
	free(procs);
	if (found == 0) {
		say("%s: NO process", pattern);
	} else {
		say("%s: %s", pattern, line);
	}
}

struct report {
	char name[128];
	time_t when;
};

static int
newest_first(const void *a, const void *b)
{
	const struct report *x = a, *y = b;

	return x->when < y->when ? 1 : x->when > y->when ? -1 : 0;
}

/* the exception of a report: "exception" : {"type":"EXC_..."} in an .ips, "Exception Type:" in an older one */
static void
exception_of(const char *path, char *what, size_t size)
{
	FILE *f = fopen(path, "r");
	static char text[65536];
	size_t n;
	const char *at;

	strlcpy(what, "?", size);
	if (f == NULL) {
		strlcpy(what, "unreadable", size);
		return;
	}
	n = fread(text, 1, sizeof(text) - 1, f);
	fclose(f);
	text[n] = 0;
	if ((at = strstr(text, "\"exception\"")) != NULL && (at = strstr(at, "\"type\"")) != NULL &&
	    (at = strchr(at + 6, '"')) != NULL) {
		size_t k = 0;

		for (at++; at[k] != 0 && at[k] != '"' && k < size - 1; k++) {
			what[k] = at[k];
		}
		what[k] = 0;
	} else if ((at = strstr(text, "Exception Type:")) != NULL) {
		size_t k = 0;

		for (at += 15; *at == ' '; at++) {
		}
		for (; at[k] != 0 && at[k] != '\n' && at[k] != ' ' && k < size - 1; k++) {
			what[k] = at[k];
		}
		what[k] = 0;
	} else if (strstr(text, "\"bug_type\":\"298\"") != NULL || strstr(text, "\"bug_type\":\"409\"") != NULL) {
		strlcpy(what, "hang/jetsam", size);
	}
}

static void
crashes(void)
{
	static const char *const places[] = { "/private/var/mobile/Library/Logs/CrashReporter",
		"/private/var/mobile/Library/Logs/CrashReporter/Retired", "/private/var/root/Library/Logs/CrashReporter" };
	static struct report reports[512];
	unsigned count = 0;

	for (unsigned p = 0; p < sizeof(places) / sizeof(places[0]); p++) {
		DIR *d = opendir(places[p]);
		struct dirent *e;

		while (d != NULL && (e = readdir(d)) != NULL && count < sizeof(reports) / sizeof(reports[0])) {
			char path[512];
			struct stat st;

			if (e->d_name[0] == '.') {
				continue;
			}
			snprintf(path, sizeof(path), "%s/%s", places[p], e->d_name);
			if (stat(path, &st) != 0 || !S_ISREG(st.st_mode)) {
				continue;
			}
			strlcpy(reports[count].name, path, sizeof(reports[count].name));
			reports[count].when = st.st_mtime;
			count++;
		}
		if (d != NULL) {
			closedir(d);
		}
	}
	say("crash reports: %u", count);
	qsort(reports, count, sizeof(reports[0]), newest_first);
	for (unsigned i = 0; i < count && i < 6; i++) {
		char what[64], process[96];
		const char *base = strrchr(reports[i].name, '/') + 1, *dash = strchr(base, '-');
		size_t k = dash != NULL ? (size_t)(dash - base) : strlen(base);

		if (k >= sizeof(process)) {
			k = sizeof(process) - 1;
		}
		memcpy(process, base, k);
		process[k] = 0;
		exception_of(reports[i].name, what, sizeof(what));
		say("%s: %s", strncmp(process, "com.apple.", 10) == 0 && strrchr(process, '.') ? strrchr(process, '.') + 1 :
		    process, what);
	}
}

/*
 * A test program that says "ok ..." / "FAIL ..." a line each (hakios-metal-probe): run with its output read here, every
 * FAIL line shown, a running count every 10 checks, and at the end the counts and how it ended (exit status or signal)
 */
#include <signal.h>
#include <sys/wait.h>

static void
probe(const char *program)
{
	int fds[2], status = 0;
	pid_t child;
	FILE *in;
	char line[512], last[512] = "";
	unsigned ok = 0, failed = 0, lines = 0;

	if (pipe(fds) != 0 || (child = fork()) < 0) {
		say("probe: cannot start %s", program);
		return;
	}
	if (child == 0) {
		dup2(fds[1], STDOUT_FILENO);
		dup2(fds[1], STDERR_FILENO);
		close(fds[0]);
		close(fds[1]);
		execl(program, program, (char *)NULL);
		_exit(127);
	}
	close(fds[1]);
	in = fdopen(fds[0], "r");
	say("probe: %s started", strrchr(program, '/') ? strrchr(program, '/') + 1 : program);
	while (in != NULL && fgets(line, sizeof(line), in) != NULL) {
		size_t n = strlen(line);
		const char *text = line;

		if (n > 0 && line[n - 1] == '\n') {
			line[--n] = 0;
		}
		printf("%s\n", line);                   /* (everything, to the standard output, for a log) */
		log_line(line);                         /* (and to whoever reads the network's log: serve PORT) */
		lines++;
		if (strncmp(text, "probe: ", 7) == 0) {
			text += 7;
		}
		strlcpy(last, text, sizeof(last));
		if (strstr(text, "FAIL") != NULL) {
			failed++;
			say("F%u %s", failed, text);
		} else if (strncmp(text, "ok", 2) == 0) {
			if (++ok % 10 == 0) {
				say("probe: %u ok, %u FAIL so far", ok, failed);
			}
		}
	}
	if (in != NULL) {
		fclose(in);
	}
	waitpid(child, &status, 0);
	say("last: %s", last);
	if (WIFSIGNALED(status)) {
		say("probe: KILLED by signal %d after %u ok, %u FAIL", WTERMSIG(status), ok, failed);
	} else {
		say("probe: done, exit %d: %u ok, %u FAIL (%u lines)", WEXITSTATUS(status), ok, failed, lines);
	}
}

int
main(int argc, char **argv)
{
	setvbuf(stdout, NULL, _IOLBF, 0);
	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "ps") == 0 && i + 1 < argc) {
			ps(argv[++i]);
		} else if (strcmp(argv[i], "crashes") == 0) {
			crashes();
		} else if (strcmp(argv[i], "serve") == 0 && i + 1 < argc) {
			pthread_t t;
			int port = atoi(argv[++i]);

			if (!serving && pthread_create(&t, NULL, log_server, (void *)(intptr_t)port) == 0) {
				pthread_detach(t);
				serving = 1;
				pause_s = 1;
				say("log on TCP port %d", port);
			}
		} else if (strcmp(argv[i], "probe") == 0 && i + 1 < argc) {
			probe(argv[++i]);
		} else if (strcmp(argv[i], "env") == 0 && i + 1 < argc && strchr(argv[i + 1], '=') != NULL) {
			char *pair = argv[++i], *eq = strchr(pair, '=');

			*eq = 0;
			setenv(pair, eq + 1, 1);        /* (for the programs a probe step starts) */
			say("env %s=%s", pair, eq + 1);
			*eq = '=';
		} else if (strcmp(argv[i], "say") == 0 && i + 1 < argc) {
			say("%s", argv[++i]);
		} else if (strcmp(argv[i], "wait") == 0 && i + 1 < argc) {
			sleep((unsigned)atoi(argv[++i]));
		} else {
			fprintf(stderr, "hud_test: bad step \"%s\"\n", argv[i]);
			return 1;
		}
	}
	return 0;
}
