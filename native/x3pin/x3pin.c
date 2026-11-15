/*
 * x3pin.exe: start a program and keep Wine's CryptoAPI DLLs loaded in it for its whole life.
 *
 * Why: while loading a game X3AP.exe opens and closes a CryptoAPI context for every script it
 * checks (1,467 times for one LxXRM new game on the AYN Thor). Each close lets rsaenh.dll,
 * crypt32.dll and bcrypt.dll unload, and each open loads them again together with their
 * emulated Unix libraries (crypt32.so, bcrypt.so, wrapped GnuTLS) under Box64: about 130 ms per
 * cycle, 208 s for that load. One extra reference per DLL stops the churn.
 *
 * How: CreateProcess the command line we were given, wait until the program is idle at its
 * first window (X3's launcher dialog), then run LoadLibraryW("<dll>") in it through
 * CreateRemoteThread for each DLL. Nothing else in the program is touched; if pinning fails
 * the program just runs as it would have. Waits for the program and returns its exit code.
 *
 * Usage: x3pin.exe PROGRAM [ARGUMENTS...]    (diagnostics go to stderr, prefixed "x3pin:")
 * Build: i686-w64-mingw32-gcc -municode -O2 -s -o x3pin.exe x3pin.c -lpsapi
 */
#include <windows.h>
#include <psapi.h>
#include <stdio.h>
#include <wchar.h>

static const wchar_t *const pin_dlls[] = { L"bcrypt.dll", L"crypt32.dll", L"rsaenh.dll" };

/* Our command line minus our own program name, respecting the quoting CreateProcess uses. */
static wchar_t *rest_of_command_line(void)
{
    wchar_t *p = GetCommandLineW();
    if (*p == L'"') { p++; while (*p && *p != L'"') p++; if (*p) p++; }
    else while (*p && *p != L' ' && *p != L'\t') p++;
    while (*p == L' ' || *p == L'\t') p++;
    return p;
}

/* kernel32 base in the target; WoW64 Wine normally maps it at the same address, but check. */
static BYTE *remote_kernel32(HANDLE process)
{
    HMODULE modules[512];
    DWORD needed = 0, i;
    wchar_t name[MAX_PATH];
    if (!EnumProcessModulesEx(process, modules, sizeof(modules), &needed, LIST_MODULES_32BIT)) return NULL;
    for (i = 0; i < needed / sizeof(HMODULE) && i < 512; i++)
        if (GetModuleBaseNameW(process, modules[i], name, MAX_PATH) && !_wcsicmp(name, L"kernel32.dll"))
            return (BYTE *)modules[i];
    return NULL;
}

static int pin(HANDLE process, DWORD pid)
{
    BYTE *local_k32 = (BYTE *)GetModuleHandleW(L"kernel32.dll");
    BYTE *local_load = (BYTE *)GetProcAddress((HMODULE)local_k32, "LoadLibraryW");
    BYTE *target_k32 = remote_kernel32(process);
    LPTHREAD_START_ROUTINE load;
    int pinned = 0;
    size_t i;

    if (!local_load) return 0;
    if (!target_k32) { fprintf(stderr, "x3pin: kernel32 not found in pid %lu (error %lu), assuming same base\n", pid, GetLastError()); target_k32 = local_k32; }
    load = (LPTHREAD_START_ROUTINE)(target_k32 + (local_load - local_k32));

    for (i = 0; i < sizeof(pin_dlls) / sizeof(pin_dlls[0]); i++) {
        SIZE_T bytes = (wcslen(pin_dlls[i]) + 1) * sizeof(wchar_t);
        void *name = VirtualAllocEx(process, NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        HANDLE thread;
        DWORD module = 0;
        if (!name || !WriteProcessMemory(process, name, pin_dlls[i], bytes, NULL)) {
            fprintf(stderr, "x3pin: cannot write into pid %lu (error %lu)\n", pid, GetLastError());
            if (name) VirtualFreeEx(process, name, 0, MEM_RELEASE);
            break;
        }
        thread = CreateRemoteThread(process, NULL, 0, load, name, 0, NULL);
        if (!thread) { fprintf(stderr, "x3pin: CreateRemoteThread failed (error %lu)\n", GetLastError()); VirtualFreeEx(process, name, 0, MEM_RELEASE); break; }
        if (WaitForSingleObject(thread, 30000) == WAIT_OBJECT_0) GetExitCodeThread(thread, &module);
        CloseHandle(thread);
        VirtualFreeEx(process, name, 0, MEM_RELEASE);
        if (module) pinned++;
        fprintf(stderr, "x3pin: %ls %s in pid %lu\n", pin_dlls[i], module ? "pinned" : "NOT pinned", pid);
    }
    return pinned;
}

int wmain(void)
{
    wchar_t *command = rest_of_command_line();
    STARTUPINFOW startup = { sizeof(startup) };
    PROCESS_INFORMATION child;
    DWORD idle, code = 1;
    int pinned;

    if (!*command) { fwprintf(stderr, L"usage: x3pin.exe PROGRAM [ARGUMENTS...]\n"); return 2; }
    command = _wcsdup(command);   /* CreateProcessW may write to its command line */
    if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &child)) {
        fprintf(stderr, "x3pin: cannot start %ls (error %lu)\n", command, GetLastError());
        return 1;
    }
    idle = WaitForInputIdle(child.hProcess, 60000);
    if (WaitForSingleObject(child.hProcess, 0) == WAIT_TIMEOUT) {
        pinned = pin(child.hProcess, child.dwProcessId);
        fprintf(stderr, "x3pin: %d of %u DLLs pinned (%s)\n", pinned, (unsigned)(sizeof(pin_dlls) / sizeof(pin_dlls[0])),
                idle == 0 ? "program idle" : idle == WAIT_TIMEOUT ? "idle wait timed out" : "idle wait failed");
    }
    WaitForSingleObject(child.hProcess, INFINITE);
    GetExitCodeProcess(child.hProcess, &code);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    return (int)code;
}
