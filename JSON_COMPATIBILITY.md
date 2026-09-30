# JSON compatibility policy

`msxdbg exec --json` emits one JSON object per command. The top-level
`schema_version` is currently `1`.

Within a schema version:

- existing field names and meanings remain stable;
- new optional fields may be added;
- consumers must ignore unknown fields;
- enum strings, error codes, numeric addresses, and lowercase hexadecimal byte
  strings retain their documented representation;
- an unavailable value is never silently encoded as zero;
- removal, renaming, type changes, or semantic changes require a new schema
  version.

Every envelope contains `schema_version`, `command_index`, `command`, `ok`,
`data`, `warnings`, and `error`. Successful results have `error: null`; failures
have `data: null`. Diagnostics outside command envelopes go to stderr so stdout
remains valid JSON Lines.

Package semantic versioning and JSON schema versioning are independent. A
package major release does not by itself change the schema, and a future schema
may be introduced alongside an older one during a documented transition.

