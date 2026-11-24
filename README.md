# FreeAgent extension for Flow Steward

Connects Flow Steward workflows to [FreeAgent](https://www.freeagent.com/), the accounting
system for UK small businesses, through the public FreeAgent API v2.

> **Early release.** Live FreeAgent testing is pending. Use a sandbox company to evaluate
> the integration.

- Extension id: `flowsteward.freeagent`
- 166 operations over the company API: contacts, projects, tasks, timeslips, notes, invoices,
  recurring invoices, estimates, credit notes and reconciliations, price list, bills, expenses
  with receipts, stock, capital assets, hire purchases, bank accounts, feeds, transactions,
  statement upload (rows or OFX/QIF/CSV file), explanations and their attachments, categories,
  journal sets, properties, users, profit and loss, balance sheet, trial balance, ledger
  transactions, cashflow, VAT returns, corporation tax, final accounts, EC VAT MOSS rates,
  sales tax periods and payroll records.
- Native Python, standard library plus the Flow Steward extension SDK. No extra packages.

## Connecting

1. Sign in at <https://dev.freeagent.com/>, open **My Apps** and create an app.
2. Add the callback URL that Flow Steward shows in the project OAuth setup as the app's
   redirect URI, exactly as shown.
3. In Flow Steward, save the app's OAuth identifier and OAuth secret for the provider:
   - **FreeAgent** for real books, used by the connection type **FreeAgent company**;
   - **FreeAgent sandbox** for a test company from
     <https://signup.sandbox.freeagent.com/signup>, used by **FreeAgent sandbox company**.
     Finish the sandbox company's setup steps in the FreeAgent web app first.
4. Create a connection and approve access in FreeAgent. Flow Steward reads the company back
   (`verify_company`) and shows its name.

FreeAgent has no OAuth scopes: the connection can do what the approving FreeAgent user can do.
Flow Steward requires one declared scope for an authorization-code provider, so the connection
types declare `freeagent`; FreeAgent ignores the `scope` parameter.
Reports, tax and payroll need the access level "Tax, Accounting and Users" or Full Access.

Each connection has four switches, all on by default: `allow_create`, `allow_update`,
`allow_delete` and `allow_email`. Test Run suppresses every change and email.

## How the operations behave

- **Records are URLs.** FreeAgent references records by URL
  (`https://api.freeagent.com/v2/contacts/123`). Inputs such as `contact`, `project` or
  `bank_account` take either the URL or the bare id. `id` inputs take either as well.
  The extension refuses a sandbox URL on a production connection and the reverse.
- **`data` is the native object without its wrapper.** For `create_invoice` send the invoice
  fields; `{"invoice": {...}}` is accepted too.
- **Lists** return `data`, `page`, `next_page` and `total_count`. `all_pages: true` follows
  FreeAgent's `Link` header for up to 50 pages of 100 rows.
- **Payments.** FreeAgent has no payment endpoint: record an invoice payment with
  `create_bank_transaction_explanation` and `paid_invoice`, a bill payment with `paid_bill`,
  a transfer with `transfer_bank_account`.
- **Files.** `get_invoice_pdf`, `get_estimate_pdf` and `get_credit_note_pdf` write a PDF
  artifact. `create_bill`, `update_bill`, `create_expense` and `update_expense` take an optional
  receipt artifact (PNG, JPEG, GIF or PDF, up to 5 MB).
  `add_bank_transaction_explanation_attachment` attaches one receipt to an explanation;
  `upload_bank_statement_file` imports an OFX, QIF or CSV file.
- **Filing transitions only record a status.** `transition_vat_return`,
  `transition_corporation_tax_return` and `transition_final_accounts_report` do not submit
  anything to HMRC or Companies House. Payment transitions move no money.
- **API version.** Every request sends `X-Api-Version: 2026-09-01`, so bank explanations use
  the multi-attachment model that FreeAgent makes the default on 1 December 2026.

## Limits and errors

- FreeAgent allows 120 requests per minute and 3600 per hour per user. A read refused with a
  short `Retry-After` (10 s or less) is retried once; otherwise the step fails with
  `rate_limited` and `retryable: true`.
- Validation errors carry FreeAgent's own messages (`provider_validation`).
- A write that fails after it was sent (timeout, HTTP 5xx) is reported as
  `timeout_unknown`: check FreeAgent before running it again. FreeAgent has no idempotency keys.

## Not covered

- The FreeAgent Practice (accountancy) API.
- GoCardless direct debit requests, payroll submissions and anything that moves money.
- Downloading attachment files: `get_attachment` returns metadata with FreeAgent's short-lived
  `content_src` link.

## Development

```bash
python3 scripts/generate_contracts.py
```

regenerates every manifest under `contracts/`, `ui/`, `artifacts/`, `extension.yaml` and
`extension-descriptor.yaml` from `freeagent/catalog.py`. Never edit those files by hand;
`tests/test_contracts.py` fails when they drift.

Run the checks from a Flow Steward Core checkout:

```bash
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root "$PWD"
```

FreeAgent is a trademark of FreeAgent Central Ltd. This independent integration is not
endorsed by FreeAgent.
