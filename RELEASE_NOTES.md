# FreeAgent 0.1.2

- The extension installs from the Flow Steward catalog and from a release archive again.
  The extension descriptor now takes its operations, OAuth providers and OAuth callback
  from the extension manifest, so the install check finds everything it references.
- A test checks every file the host validates on its own for undeclared OAuth callbacks.

No change to operations, connections or settings: existing workflows keep working.
