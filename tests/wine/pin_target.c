/*
 * Test program for x3pin.exe, run under Wine in CI. It does what X3AP.exe does while loading:
 * acquire and release a CryptoAPI context over and over, and reports whether rsaenh.dll,
 * crypt32.dll and bcrypt.dll stay loaded afterwards.
 *
 *   pin_target.exe --expect-unpinned        (run directly: the DLLs must unload again)
 *   x3pin.exe pin_target.exe --expect-pinned "two words"   (they must stay; args must arrive)
 *   x3pin.exe pin_target.exe --exit7        (x3pin must return 7)
 *
 * It pumps messages first so x3pin's WaitForInputIdle returns, then waits up to 8 s for the
 * pinned DLLs to appear before testing. Exit code 0 = expectation met.
 */
#include <windows.h>
#include <wincrypt.h>
#include <stdio.h>
#include <string.h>

static int loaded(void)
{
    return GetModuleHandleW(L"rsaenh.dll") && GetModuleHandleW(L"crypt32.dll") && GetModuleHandleW(L"bcrypt.dll");
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command_line, int show)
{
    int expect_pinned = strstr(command_line, "--expect-pinned") != NULL, i, result;
    DWORD start = GetTickCount(), elapsed;
    HCRYPTPROV provider;
    MSG msg;
    (void)instance; (void)previous; (void)show;

    if (strstr(command_line, "--exit7")) return 7;   /* exit-code passthrough check */
    if (expect_pinned && !strstr(command_line, "\"two words\"")) {
        fprintf(stderr, "pin_target: arguments not passed through: [%s]\n", command_line);
        return 3;
    }
    while (GetTickCount() - start < 8000 && !(expect_pinned && loaded())) {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        MsgWaitForMultipleObjects(0, NULL, FALSE, 50, QS_ALLINPUT);
        if (!expect_pinned && GetTickCount() - start > 1000) break;
    }
    start = GetTickCount();
    for (i = 0; i < 40; i++) {
        if (!CryptAcquireContextW(&provider, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)) {
            fprintf(stderr, "pin_target: CryptAcquireContext failed (%lu)\n", GetLastError());
            return 4;
        }
        CryptReleaseContext(provider, 0);
    }
    elapsed = GetTickCount() - start;
    result = loaded();
    fprintf(stderr, "pin_target: 40 acquire/release cycles in %lu ms; crypto DLLs %s afterwards\n",
            elapsed, result ? "still loaded" : "unloaded");
    return result == expect_pinned ? 0 : 1;
}
