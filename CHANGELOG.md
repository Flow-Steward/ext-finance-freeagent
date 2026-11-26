# Changelog

## 0.1.2

- The extension installs from the Flow Steward catalog and from a release archive again.
  The extension descriptor now takes its operations, OAuth providers and OAuth callback
  from the extension manifest, so the install check finds everything it references.
- A test checks every file the host validates on its own for undeclared OAuth callbacks.

## 0.1.1

First Marketplace release.

- 166 operations over the FreeAgent company API v2: sales, purchases, banking, accounting,
  reports, tax and payroll records.
- Production and sandbox companies, each with its own OAuth provider and connection type.
- Invoice, estimate and credit note PDFs as artifacts; receipts and bank statement files from
  artifacts.
- Test Run suppresses every change and email; per-connection switches for create, update,
  delete and email.
