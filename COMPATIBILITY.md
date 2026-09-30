# Compatibility

## Supported matrix

| Component | Supported | Validation |
| --- | --- | --- |
| Python | 3.10–3.14 | Offline CI matrix |
| openMSX | 21.0 | Read-only and explicitly opted-in live scenarios |
| SDCC/SDLD | 4.6.0 | Real CDB/ADB fixtures plus synthetic MAP/LST coverage |

Other openMSX and SDCC versions may work, but are not release-qualified until
their behavior is captured by fixtures or an opt-in live run. Unsupported or
unproven records degrade to structured diagnostics; they are not guessed.

openMSX extensions such as conditional breakpoints, watchpoints, mapping
conditions, block reads, and persistent transport are enabled only after
read-only capability probes. Lack of an extension must not disable offline
resolution.

SDCC type layouts are accepted only when the CDB or a configured header proves
them. Bitfields, unions, and target-program function calls remain unsupported.

