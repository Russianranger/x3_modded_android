# Box64 regression for X3AP.exe's start-up check (first Thor run, Nov 2026):
#   66 0F 01 E0   smsw ax        <- X3AP.exe at 0x4F9975: "test al,4" (CR0.EM) then FXSAVE probing
# Unpatched Box64 2f130fab stops with "Unimplemented 32bits Opcode (00 01 74 5D) 66 0F 01 E0".
# Exit status 0 = pass; 1..5 names the failing check. Build: as + ld (x86-64), run under box64.
    .intel_syntax noprefix
    .globl _start
    .text
_start:
    # 1: register form with operand-size prefix keeps the upper bits of EAX
    mov     eax, 0xAAAA5555
    .byte   0x66, 0x0F, 0x01, 0xE0          # smsw ax
    mov     edi, 1
    cmp     eax, 0xAAAA0011
    jne     fail
    # 2: CR0.EM (bit 2) must read clear, or X3 assumes an emulated FPU
    mov     edi, 2
    test    al, 4
    jnz     fail
    # 3: memory form with prefix stores exactly 16 bits
    lea     rbx, [rip + word_slot]
    mov     dword ptr [rbx], 0xBBBBCCCC
    .byte   0x66, 0x0F, 0x01, 0x23          # smsw word ptr [rbx]
    mov     edi, 3
    cmp     dword ptr [rbx], 0xBBBB0011
    jne     fail
    # 4: another register (ecx) through the same group-7 path
    mov     ecx, 0x12345678
    .byte   0x66, 0x0F, 0x01, 0xE1          # smsw cx
    mov     edi, 4
    cmp     ecx, 0x12340011
    jne     fail
    # 5: the unprefixed form Box64 already had still works
    xor     edx, edx
    .byte   0x0F, 0x01, 0xE2                # smsw edx
    mov     edi, 5
    cmp     dx, 0x0011
    jne     fail
    xor     edi, edi
fail:
    mov     eax, 60                         # exit(edi)
    syscall

    .data
word_slot:
    .long   0
