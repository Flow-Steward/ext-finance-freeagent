"""The closed FreeAgent v2 operation catalog shared by the runtime and the contract generator.

Every operation names one fixed HTTP method and path template. Workflow input can only
fill declared path parameters (validated identifiers), declared query parameters and the
request body object; it can never choose a host, a path or a header.
"""

from __future__ import annotations

from dataclasses import dataclass

API_VERSION = "2026-09-01"
"""Pinned X-Api-Version: bank explanations already use the multi-attachment model that
becomes FreeAgent's default on 2026-12-01, so the extension does not change behaviour then."""

READ = "read"
CREATE = "create"
UPDATE = "update"
DELETE = "delete"
EMAIL = "email"
WRITE_EFFECTS = frozenset({CREATE, UPDATE, DELETE, EMAIL})


@dataclass(frozen=True)
class Param:
    """One workflow input that lands in the path or the query string."""

    name: str
    kind: str  # text | slug | integer | boolean | date | datetime | enum | resource | id | ...
    required: bool = False
    location: str = "query"
    choices: tuple[str, ...] = ()
    resource: str = ""
    minimum: int = 0
    maximum: int = 0
    help: str = ""


@dataclass(frozen=True)
class Operation:
    name: str
    title: str
    group: str
    method: str
    path: str
    effect: str
    description: str
    params: tuple[Param, ...] = ()
    response_root: str = ""
    body_root: str = ""
    body: str = ""  # "" | data | email | statement | estimate_item
    paged: bool = False
    special: str = ""  # pdf | statement_file | explanation_attachment | inline_attachment
    reread_path: str = ""


ID = Param("id", "id", True, "path", help="Numeric FreeAgent id or the resource URL.")
PAGE = Param("page", "integer", minimum=1, maximum=100000, help="Page number, starting at 1.")
PER_PAGE = Param("per_page", "integer", minimum=1, maximum=100, help="Rows per page (max 100).")
ALL_PAGES = Param(
    "all_pages",
    "boolean",
    help="Fetch every page (up to 50 pages of 100 rows). next_page is set when more remain.",
)
UPDATED_SINCE = Param(
    "updated_since", "datetime", help="Only records changed after this ISO 8601 timestamp."
)
FROM_DATE = Param("from_date", "date", help="YYYY-MM-DD.")
TO_DATE = Param("to_date", "date", help="YYYY-MM-DD.")
PERIOD_ENDS_ON = Param("period_ends_on", "date", True, "path", help="Period end date YYYY-MM-DD.")
PAGING = (PAGE, PER_PAGE, ALL_PAGES)


def view(*values: str) -> Param:
    return Param("view", "slug", help="FreeAgent view filter, e.g. " + ", ".join(values) + ".")


def sort(*fields: str) -> Param:
    return Param(
        "sort",
        "slug",
        help="Sort field: " + ", ".join(fields) + ". Prefix with - for descending order.",
    )


def ref(name: str, resource: str, required: bool = False) -> Param:
    return Param(
        name,
        "resource",
        required,
        resource=resource,
        help=f"FreeAgent {resource} URL or numeric id.",
    )


def flag(name: str, text: str) -> Param:
    return Param(name, "boolean", help=text)


def transition(*values: str) -> Param:
    return Param("transition", "enum", True, "path", choices=values)


OPERATIONS_LIST: list[Operation] = []


def add(*operations: Operation) -> None:
    OPERATIONS_LIST.extend(operations)


def crud(
    plural: str,
    singular: str,
    group: str,
    label: str,
    *,
    list_params: tuple[Param, ...] = (),
    get_params: tuple[Param, ...] = (),
    create_params: tuple[Param, ...] = (),
    path: str = "",
    actions: str = "lgcud",
    create_note: str = "",
    special: str = "",
) -> None:
    base = "/" + (path or plural)
    item = base + "/{id}"
    if "l" in actions:
        add(
            Operation(
                "list_" + plural,
                "List " + label + "s",
                group,
                "GET",
                base,
                READ,
                f"List FreeAgent {label}s, one page at a time or all pages.",
                list_params + PAGING,
                response_root=plural,
                paged=True,
            )
        )
    if "g" in actions:
        add(
            Operation(
                "get_" + singular,
                "Get " + label,
                group,
                "GET",
                item,
                READ,
                f"Read one FreeAgent {label}.",
                (ID, *get_params),
                response_root=singular,
            )
        )
    if "c" in actions:
        add(
            Operation(
                "create_" + singular,
                "Create " + label,
                group,
                "POST",
                base,
                CREATE,
                f"Create a FreeAgent {label}. data holds the native {singular} fields; "
                "reference other records by their FreeAgent URL. " + create_note,
                create_params,
                response_root=singular,
                body_root=singular,
                body="data",
                special=special,
            )
        )
    if "u" in actions:
        add(
            Operation(
                "update_" + singular,
                "Update " + label,
                group,
                "PUT",
                item,
                UPDATE,
                f"Update a FreeAgent {label}. data holds only the fields to change.",
                (ID,),
                response_root=singular,
                body_root=singular,
                body="data",
                special=special,
                reread_path=item,
            )
        )
    if "d" in actions:
        add(
            Operation(
                "delete_" + singular,
                "Delete " + label,
                group,
                "DELETE",
                item,
                DELETE,
                f"Delete a FreeAgent {label}. FreeAgent refuses deletion of records in use.",
                (ID,),
            )
        )


def pdf(plural: str, singular: str, group: str, label: str) -> None:
    add(
        Operation(
            f"get_{singular}_pdf",
            f"Get {label} PDF",
            group,
            "GET",
            f"/{plural}/{{id}}/pdf",
            READ,
            f"Render a FreeAgent {label} as a PDF artifact.",
            (ID,),
            special="pdf",
        )
    )


def send_email(plural: str, singular: str, group: str, label: str) -> None:
    add(
        Operation(
            f"send_{singular}_email",
            f"Email {label}",
            group,
            "POST",
            f"/{plural}/{{id}}/send_email",
            EMAIL,
            f"Email a FreeAgent {label} to the customer. email holds to, from, subject and body, "
            'or {"use_template": true}. from must belong to a FreeAgent user.',
            (ID,),
            body_root=singular,
            body="email",
        )
    )


# Company and users -------------------------------------------------------------------------
add(
    Operation(
        "get_company",
        "Get company",
        "company",
        "GET",
        "/company",
        READ,
        "Read the connected FreeAgent company: name, type, currency, VAT registration.",
        response_root="company",
    ),
    Operation(
        "list_business_categories",
        "List business categories",
        "company",
        "GET",
        "/company/business_categories",
        READ,
        "List the business categories FreeAgent offers for a company.",
    ),
    Operation(
        "get_tax_timeline",
        "Get tax timeline",
        "company",
        "GET",
        "/company/tax_timeline",
        READ,
        "List upcoming tax and filing deadlines for the company.",
    ),
    Operation(
        "get_current_user",
        "Get current user",
        "users",
        "GET",
        "/users/me",
        READ,
        "Read the FreeAgent user who authorised this connection.",
        response_root="user",
    ),
)
crud(
    "users",
    "user",
    "users",
    "user",
    list_params=(view("all", "staff", "active_staff", "advisors", "active_advisors"),),
)

# Contacts, projects, tasks, timeslips, notes -------------------------------------------------
crud(
    "contacts",
    "contact",
    "contacts",
    "contact",
    list_params=(
        view(
            "active",
            "all",
            "clients",
            "suppliers",
            "active_projects",
            "completed_projects",
            "hidden",
        ),
        sort("name", "created_at", "updated_at"),
        UPDATED_SINCE,
    ),
    create_note="Needs organisation_name, or first_name and last_name.",
)
crud(
    "projects",
    "project",
    "projects",
    "project",
    list_params=(
        view("active", "completed", "cancelled", "hidden"),
        sort("name", "contact_name", "created_at", "updated_at"),
        ref("contact", "contacts"),
        flag("nested", "Include nested task details."),
    ),
    create_note="Needs contact, name, currency and budget_units.",
)
crud(
    "tasks",
    "task",
    "projects",
    "task",
    list_params=(
        view("all", "active", "completed", "hidden"),
        sort("name", "project", "billing_rate", "created_at", "updated_at"),
        ref("project", "projects"),
        UPDATED_SINCE,
    ),
    create_params=(ref("project", "projects", True),),
    create_note="Needs name; the project is a separate input.",
)
crud(
    "timeslips",
    "timeslip",
    "projects",
    "timeslip",
    list_params=(
        view("all", "unbilled", "running"),
        FROM_DATE,
        TO_DATE,
        UPDATED_SINCE,
        ref("user", "users"),
        ref("task", "tasks"),
        ref("project", "projects"),
        flag("nested", "Include nested user, task and project."),
    ),
    create_note="Needs task, user, project, dated_on and hours (decimal, 1.5 = 1h30).",
)
add(
    Operation(
        "start_timeslip_timer",
        "Start timeslip timer",
        "projects",
        "POST",
        "/timeslips/{id}/timer",
        UPDATE,
        "Start the running timer on a FreeAgent timeslip.",
        (ID,),
        response_root="timeslip",
    ),
    Operation(
        "stop_timeslip_timer",
        "Stop timeslip timer",
        "projects",
        "DELETE",
        "/timeslips/{id}/timer",
        UPDATE,
        "Stop the running timer on a FreeAgent timeslip.",
        (ID,),
        response_root="timeslip",
    ),
)
crud(
    "notes",
    "note",
    "contacts",
    "note",
    list_params=(ref("contact", "contacts"), ref("project", "projects")),
    create_params=(ref("contact", "contacts"), ref("project", "projects")),
    create_note="Needs note (text). Give exactly one of contact or project.",
)

# Sales ---------------------------------------------------------------------------------------
crud(
    "invoices",
    "invoice",
    "sales",
    "invoice",
    list_params=(
        view(
            "all",
            "recent_open_or_overdue",
            "open",
            "overdue",
            "open_or_overdue",
            "draft",
            "paid",
            "scheduled_to_email",
            "thank_you_emails",
            "reminder_emails",
            "last_3_months",
        ),
        sort("created_at", "updated_at"),
        UPDATED_SINCE,
        ref("contact", "contacts"),
        ref("project", "projects"),
        flag("nested_invoice_items", "Include invoice_items in every row."),
    ),
    create_note="Invoices are created as Draft. Needs contact, dated_on, payment_terms_in_days "
    "and invoice_items (description, quantity, price, item_type).",
)
pdf("invoices", "invoice", "sales", "invoice")
send_email("invoices", "invoice", "sales", "invoice")
add(
    Operation(
        "transition_invoice",
        "Change invoice status",
        "sales",
        "PUT",
        "/invoices/{id}/transitions/{transition}",
        UPDATE,
        "Mark an invoice as sent, scheduled, draft or cancelled, or convert it to a credit note.",
        (
            ID,
            transition(
                "mark_as_sent",
                "mark_as_scheduled",
                "mark_as_draft",
                "mark_as_cancelled",
                "convert_to_credit_note",
            ),
        ),
        reread_path="/invoices/{id}",
        response_root="invoice",
    ),
    Operation(
        "duplicate_invoice",
        "Duplicate invoice",
        "sales",
        "POST",
        "/invoices/{id}/duplicate",
        CREATE,
        "Create a new draft invoice copied from an existing one.",
        (ID,),
        response_root="invoice",
    ),
    Operation(
        "get_invoice_timeline",
        "Get invoice timeline",
        "sales",
        "GET",
        "/invoices/timeline",
        READ,
        "Read the invoicing timeline (sent, paid and overdue events).",
    ),
)
crud(
    "recurring_invoices",
    "recurring_invoice",
    "sales",
    "recurring invoice",
    list_params=(view("draft", "active", "inactive"), ref("contact", "contacts")),
    actions="lg",
)
crud(
    "estimates",
    "estimate",
    "sales",
    "estimate",
    list_params=(
        view("all", "recent", "draft", "non_draft", "sent", "approved", "rejected", "invoiced"),
        FROM_DATE,
        TO_DATE,
        UPDATED_SINCE,
        ref("contact", "contacts"),
        ref("project", "projects"),
        ref("invoice", "invoices"),
        flag("nested_estimate_items", "Include estimate_items in every row."),
    ),
    create_note="Needs status, estimate_type (Estimate, Quote or Proposal), contact, reference "
    "and dated_on.",
)
pdf("estimates", "estimate", "sales", "estimate")
send_email("estimates", "estimate", "sales", "estimate")
add(
    Operation(
        "duplicate_estimate",
        "Duplicate estimate",
        "sales",
        "POST",
        "/estimates/{id}/duplicate",
        CREATE,
        "Create a new draft estimate copied from an existing one.",
        (ID,),
        response_root="estimate",
    ),
    Operation(
        "create_estimate_item",
        "Add estimate item",
        "sales",
        "POST",
        "/estimate_items",
        CREATE,
        "Add one line item to an existing estimate. data holds the estimate_item fields.",
        (ref("estimate", "estimates", True),),
        response_root="estimate_item",
        body_root="estimate_item",
        body="estimate_item",
    ),
    Operation(
        "update_estimate_item",
        "Update estimate item",
        "sales",
        "PUT",
        "/estimate_items/{id}",
        UPDATE,
        "Change one estimate line item.",
        (ID,),
        response_root="estimate_item",
        body_root="estimate_item",
        body="data",
    ),
    Operation(
        "delete_estimate_item",
        "Delete estimate item",
        "sales",
        "DELETE",
        "/estimate_items/{id}",
        DELETE,
        "Remove one estimate line item.",
        (ID,),
    ),
)
crud(
    "credit_notes",
    "credit_note",
    "sales",
    "credit note",
    list_params=(
        view(
            "all",
            "recent_open_or_overdue",
            "open",
            "overdue",
            "open_or_overdue",
            "draft",
            "refunded",
        ),
        sort("created_at", "updated_at"),
        UPDATED_SINCE,
        ref("contact", "contacts"),
        ref("project", "projects"),
        flag("nested_credit_note_items", "Include credit_note_items in every row."),
    ),
    create_note="Created as Draft. Needs contact, dated_on, payment_terms_in_days and "
    "credit_note_items.",
)
pdf("credit_notes", "credit_note", "sales", "credit note")
send_email("credit_notes", "credit_note", "sales", "credit note")
add(
    Operation(
        "transition_credit_note",
        "Change credit note status",
        "sales",
        "PUT",
        "/credit_notes/{id}/transitions/{transition}",
        UPDATE,
        "Mark a credit note as sent or back to draft.",
        (ID, transition("mark_as_sent", "mark_as_draft")),
        reread_path="/credit_notes/{id}",
        response_root="credit_note",
    )
)
crud(
    "credit_note_reconciliations",
    "credit_note_reconciliation",
    "sales",
    "credit note reconciliation",
    list_params=(UPDATED_SINCE, FROM_DATE, TO_DATE),
    create_note="Allocates a credit note to an invoice. Needs invoice, credit_note and currency.",
)
crud(
    "price_list_items",
    "price_list_item",
    "sales",
    "price list item",
    list_params=(sort("created_at", "code", "updated_at"),),
    create_note="Needs code, quantity, item_type and description.",
)

# Purchases -----------------------------------------------------------------------------------
crud(
    "bills",
    "bill",
    "purchases",
    "bill",
    list_params=(
        view(
            "all", "open", "overdue", "open_or_overdue", "paid", "recurring", "hire_purchase", "cis"
        ),
        FROM_DATE,
        TO_DATE,
        UPDATED_SINCE,
        ref("contact", "contacts"),
        ref("project", "projects"),
        flag("nested_bill_items", "Include bill_items in every row."),
    ),
    create_note="Needs contact, reference, dated_on, due_on and bill_items (category, "
    "total_value). An optional attachment artifact is sent as the bill's receipt.",
    special="inline_attachment",
)
crud(
    "expenses",
    "expense",
    "purchases",
    "expense",
    list_params=(
        view("recent", "recurring"),
        FROM_DATE,
        TO_DATE,
        UPDATED_SINCE,
        ref("project", "projects"),
    ),
    create_note="Needs user, category (URL, or Mileage), dated_on, description and gross_value "
    "(negative for money spent). An optional attachment artifact is sent as the receipt.",
    special="inline_attachment",
)
add(
    Operation(
        "get_mileage_settings",
        "Get mileage settings",
        "purchases",
        "GET",
        "/expenses/mileage_settings",
        READ,
        "Read mileage rates and engine settings used for mileage expenses.",
    )
)
crud(
    "stock_items",
    "stock_item",
    "purchases",
    "stock item",
    list_params=(sort("created_at", "description", "updated_at"),),
    actions="lg",
)
crud(
    "capital_assets",
    "capital_asset",
    "purchases",
    "capital asset",
    list_params=(
        view("all", "disposed", "disposable"),
        flag("include_history", "Include asset history."),
    ),
    get_params=(flag("include_history", "Include asset history."),),
    actions="lg",
)
crud(
    "capital_asset_types",
    "capital_asset_type",
    "purchases",
    "capital asset type",
    create_note="Needs name.",
)
crud("hire_purchases", "hire_purchase", "purchases", "hire purchase", actions="lg")

# Banking -------------------------------------------------------------------------------------
crud(
    "bank_accounts",
    "bank_account",
    "banking",
    "bank account",
    list_params=(view("standard_bank_accounts", "credit_card_accounts", "paypal_accounts"),),
    create_note="Needs name and opening_balance; type is StandardBankAccount, CreditCardAccount "
    "or EcommerceAccount.",
)
crud("bank_feeds", "bank_feed", "banking", "bank feed", actions="lg")
crud(
    "bank_transactions",
    "bank_transaction",
    "banking",
    "bank transaction",
    list_params=(
        ref("bank_account", "bank_accounts", True),
        view("all", "unexplained", "explained", "manual", "imported", "marked_for_review"),
        FROM_DATE,
        TO_DATE,
        UPDATED_SINCE,
        flag("last_uploaded", "Only transactions from the last statement upload."),
    ),
    actions="lgd",
)
add(
    Operation(
        "upload_bank_statement",
        "Upload bank statement rows",
        "banking",
        "POST",
        "/bank_transactions/statement",
        CREATE,
        "Import statement rows into a bank account. statement is an array of objects with "
        "dated_on, amount (negative for money out), description, optional fitid and "
        "transaction_type. FreeAgent de-duplicates on date, amount and description; upload a "
        "whole day at once. Success means received: list the account to confirm the import.",
        (ref("bank_account", "bank_accounts", True),),
        body="statement",
    ),
    Operation(
        "upload_bank_statement_file",
        "Upload bank statement file",
        "banking",
        "POST",
        "/bank_transactions/statement",
        CREATE,
        "Import an OFX (recommended), QIF or CSV statement file artifact into a bank account.",
        (
            ref("bank_account", "bank_accounts", True),
            Param(
                "file_name",
                "file_name",
                True,
                help="Statement file name ending .ofx, .qif or .csv.",
            ),
        ),
        special="statement_file",
    ),
)
crud(
    "bank_transaction_explanations",
    "bank_transaction_explanation",
    "banking",
    "bank transaction explanation",
    list_params=(ref("bank_account", "bank_accounts", True), FROM_DATE, TO_DATE, UPDATED_SINCE),
    create_note="Needs bank_transaction or bank_account, dated_on and gross_value. Set "
    "paid_invoice to record an invoice payment, paid_bill for a bill payment, "
    "transfer_bank_account for a transfer, otherwise category.",
)
add(
    Operation(
        "list_bank_transaction_explanation_attachments",
        "List explanation attachments",
        "banking",
        "GET",
        "/bank_transaction_explanations/{id}/attachments",
        READ,
        "List the receipts attached to a bank transaction explanation.",
        (ID,),
        response_root="attachments",
    ),
    Operation(
        "add_bank_transaction_explanation_attachment",
        "Attach receipt to explanation",
        "banking",
        "POST",
        "/bank_transaction_explanations/{id}/attachments",
        CREATE,
        "Attach one file artifact (PNG, JPEG, GIF or PDF, max 5 MB) to a bank transaction "
        "explanation. FreeAgent keeps up to 50 per explanation.",
        (
            ID,
            Param("file_name", "file_name", True, help="File name shown in FreeAgent."),
            Param("content_type", "attachment_type", True, help="MIME type of the file."),
            Param("description", "text", help="Optional description."),
        ),
        response_root="attachments",
        special="explanation_attachment",
    ),
    Operation(
        "update_bank_transaction_explanation_attachments",
        "Update explanation attachments",
        "banking",
        "PUT",
        "/bank_transaction_explanations/{id}/attachments",
        UPDATE,
        "Change or remove attachments in one call. data is "
        '{"attachments": [{"url": ..., "description": ...} or {"url": ..., "_destroy": "true"}]}.',
        (ID,),
        response_root="attachments",
        body="data",
    ),
    Operation(
        "delete_bank_transaction_explanation_attachments",
        "Remove all explanation attachments",
        "banking",
        "DELETE",
        "/bank_transaction_explanations/{id}/attachments",
        DELETE,
        "Remove every attachment from a bank transaction explanation.",
        (ID,),
        response_root="attachments",
    ),
    Operation(
        "get_attachment",
        "Get attachment",
        "banking",
        "GET",
        "/attachments/{id}",
        READ,
        "Read attachment metadata, including a short-lived content_src download URL.",
        (ID,),
        response_root="attachment",
    ),
    Operation(
        "delete_attachment",
        "Delete attachment",
        "banking",
        "DELETE",
        "/attachments/{id}",
        DELETE,
        "Delete one attachment.",
        (ID,),
    ),
)

# Accounting ----------------------------------------------------------------------------------
NOMINAL_CODE = Param(
    "nominal_code", "nominal_code", True, "path", help="Nominal code, e.g. 250 or 750-1."
)
add(
    Operation(
        "list_categories",
        "List categories",
        "accounting",
        "GET",
        "/categories",
        READ,
        "List the chart of accounts grouped by income, cost of sales, admin expenses and "
        "general categories.",
        (flag("sub_accounts", "Include sub-account categories."),),
    ),
    Operation(
        "get_category",
        "Get category",
        "accounting",
        "GET",
        "/categories/{nominal_code}",
        READ,
        "Read one accounting category by nominal code.",
        (NOMINAL_CODE,),
    ),
    Operation(
        "create_category",
        "Create category",
        "accounting",
        "POST",
        "/categories",
        CREATE,
        "Create an accounting category. data needs description, nominal_code and "
        "category_group (income, cost_of_sales, admin_expenses, current_assets, liabilities, "
        "equities).",
        response_root="category",
        body_root="category",
        body="data",
    ),
    Operation(
        "update_category",
        "Update category",
        "accounting",
        "PUT",
        "/categories/{nominal_code}",
        UPDATE,
        "Update a user-created category that has no items.",
        (NOMINAL_CODE,),
        response_root="category",
        body_root="category",
        body="data",
    ),
    Operation(
        "delete_category",
        "Delete category",
        "accounting",
        "DELETE",
        "/categories/{nominal_code}",
        DELETE,
        "Delete a user-created category that has no items.",
        (NOMINAL_CODE,),
    ),
)
crud(
    "journal_sets",
    "journal_set",
    "accounting",
    "journal set",
    list_params=(
        FROM_DATE,
        TO_DATE,
        UPDATED_SINCE,
        Param("tag", "text", help="Only sets with this tag."),
    ),
    create_note="Needs description, dated_on and journal_entries (category, debit_value; credits "
    "negative). Entries must balance.",
)
add(
    Operation(
        "get_journal_set_opening_balances",
        "Get opening balances journal",
        "accounting",
        "GET",
        "/journal_sets/opening_balances",
        READ,
        "Read the opening balances journal set.",
        response_root="journal_set",
    ),
    Operation(
        "get_profit_and_loss",
        "Get profit and loss",
        "reports",
        "GET",
        "/accounting/profit_and_loss/summary",
        READ,
        "Profit and loss summary for a date range (max 12 months) or an accounting period.",
        (
            FROM_DATE,
            TO_DATE,
            Param("accounting_period", "accounting_period", help="Accounting year, e.g. 2025/26."),
        ),
        response_root="profit_and_loss_summary",
    ),
    Operation(
        "get_balance_sheet",
        "Get balance sheet",
        "reports",
        "GET",
        "/accounting/balance_sheet",
        READ,
        "Balance sheet as at a date (default today).",
        (Param("as_at_date", "date", help="YYYY-MM-DD."),),
        response_root="balance_sheet",
    ),
    Operation(
        "get_balance_sheet_opening_balances",
        "Get opening balance sheet",
        "reports",
        "GET",
        "/accounting/balance_sheet/opening_balances",
        READ,
        "Opening balances of the balance sheet.",
    ),
    Operation(
        "get_trial_balance",
        "Get trial balance",
        "reports",
        "GET",
        "/accounting/trial_balance/summary",
        READ,
        "Trial balance per category for a date range. Use display_nominal_code in output.",
        (FROM_DATE, TO_DATE),
        response_root="trial_balance_summary",
    ),
    Operation(
        "get_trial_balance_opening_balances",
        "Get opening trial balance",
        "reports",
        "GET",
        "/accounting/trial_balance/summary/opening_balances",
        READ,
        "Opening balances of the trial balance.",
    ),
    Operation(
        "list_accounting_transactions",
        "List ledger transactions",
        "reports",
        "GET",
        "/accounting/transactions",
        READ,
        "General ledger lines (debit_value, credits negative) for a date range, optionally for "
        "one nominal code. Default range is the current accounting year.",
        (
            FROM_DATE,
            TO_DATE,
            Param("nominal_code", "nominal_code", help="Only lines for this nominal code."),
            *PAGING,
        ),
        response_root="transactions",
        paged=True,
    ),
    Operation(
        "get_accounting_transaction",
        "Get ledger transaction",
        "reports",
        "GET",
        "/accounting/transactions/{id}",
        READ,
        "Read one general ledger line.",
        (ID,),
        response_root="transaction",
    ),
    Operation(
        "get_cashflow",
        "Get cashflow",
        "reports",
        "GET",
        "/cashflow",
        READ,
        "Monthly money in, money out and balance between two dates.",
        (
            Param("from_date", "date", True, help="YYYY-MM-DD."),
            Param("to_date", "date", True, help="YYYY-MM-DD."),
        ),
        response_root="cashflow",
    ),
)

# Tax -----------------------------------------------------------------------------------------
add(
    Operation(
        "list_vat_returns",
        "List VAT returns",
        "tax",
        "GET",
        "/vat_returns",
        READ,
        "List VAT returns with filing and payment status.",
        response_root="vat_returns",
    ),
    Operation(
        "get_vat_return",
        "Get VAT return",
        "tax",
        "GET",
        "/vat_returns/{period_ends_on}",
        READ,
        "Read one VAT return, including boxes 1-9.",
        (PERIOD_ENDS_ON,),
        response_root="vat_return",
    ),
    Operation(
        "transition_vat_return",
        "Mark VAT return filed",
        "tax",
        "PUT",
        "/vat_returns/{period_ends_on}/{transition}",
        UPDATE,
        "Record that a VAT return was filed outside FreeAgent, or undo that. This does not "
        "submit anything to HMRC. Needs Full Access.",
        (PERIOD_ENDS_ON, transition("mark_as_filed", "mark_as_unfiled")),
        reread_path="/vat_returns/{period_ends_on}",
        response_root="vat_return",
    ),
    Operation(
        "transition_vat_return_payment",
        "Mark VAT payment paid",
        "tax",
        "PUT",
        "/vat_returns/{period_ends_on}/payments/{payment_date}/{transition}",
        UPDATE,
        "Mark a VAT payment as paid or unpaid. This moves no money.",
        (
            PERIOD_ENDS_ON,
            Param("payment_date", "date", True, "path", help="Payment due date YYYY-MM-DD."),
            transition("mark_as_paid", "mark_as_unpaid"),
        ),
        reread_path="/vat_returns/{period_ends_on}",
        response_root="vat_return",
    ),
    Operation(
        "list_corporation_tax_returns",
        "List corporation tax returns",
        "tax",
        "GET",
        "/corporation_tax_returns",
        READ,
        "List corporation tax returns with filing and payment status.",
        response_root="corporation_tax_returns",
    ),
    Operation(
        "get_corporation_tax_return",
        "Get corporation tax return",
        "tax",
        "GET",
        "/corporation_tax_returns/{period_ends_on}",
        READ,
        "Read one corporation tax return.",
        (PERIOD_ENDS_ON,),
        response_root="corporation_tax_return",
    ),
    Operation(
        "transition_corporation_tax_return",
        "Mark corporation tax return",
        "tax",
        "PUT",
        "/corporation_tax_returns/{period_ends_on}/{transition}",
        UPDATE,
        "Mark a corporation tax return filed, unfiled, paid or unpaid. Nothing is sent to HMRC.",
        (
            PERIOD_ENDS_ON,
            transition("mark_as_filed", "mark_as_unfiled", "mark_as_paid", "mark_as_unpaid"),
        ),
        reread_path="/corporation_tax_returns/{period_ends_on}",
        response_root="corporation_tax_return",
    ),
    Operation(
        "list_final_accounts_reports",
        "List final accounts",
        "tax",
        "GET",
        "/final_accounts_reports",
        READ,
        "List final accounts reports with filing status.",
        response_root="final_accounts_reports",
    ),
    Operation(
        "get_final_accounts_report",
        "Get final accounts",
        "tax",
        "GET",
        "/final_accounts_reports/{period_ends_on}",
        READ,
        "Read one final accounts report.",
        (PERIOD_ENDS_ON,),
        response_root="final_accounts_report",
    ),
    Operation(
        "transition_final_accounts_report",
        "Mark final accounts filed",
        "tax",
        "PUT",
        "/final_accounts_reports/{period_ends_on}/{transition}",
        UPDATE,
        "Mark final accounts filed or unfiled. Nothing is sent to Companies House.",
        (PERIOD_ENDS_ON, transition("mark_as_filed", "mark_as_unfiled")),
        reread_path="/final_accounts_reports/{period_ends_on}",
        response_root="final_accounts_report",
    ),
    Operation(
        "get_ec_moss_sales_tax_rates",
        "Get EU VAT MOSS rates",
        "tax",
        "GET",
        "/ec_moss/sales_tax_rates",
        READ,
        "VAT rates of one EU country on a date, for EC VAT MOSS sales.",
        (
            Param("country", "text", True, help="EU member country name, e.g. Austria."),
            Param("date", "date", True, help="YYYY-MM-DD."),
        ),
        response_root="sales_tax_rates",
    ),
)
crud(
    "sales_tax_periods",
    "sales_tax_period",
    "tax",
    "sales tax period",
    create_note="US and Universal companies only. Needs sales_tax_name, "
    "sales_tax_registration_status, sales_tax_is_value_added and effective_date.",
)

# Payroll and properties ----------------------------------------------------------------------
YEAR = Param(
    "year",
    "integer",
    True,
    "path",
    minimum=2000,
    maximum=2100,
    help="Tax year end, e.g. 2026 for 2025/26.",
)
add(
    Operation(
        "get_payroll_year",
        "Get payroll year",
        "payroll",
        "GET",
        "/payroll/{year}",
        READ,
        "Payroll periods and payments of one UK tax year.",
        (YEAR,),
    ),
    Operation(
        "get_payroll_period",
        "Get payroll period",
        "payroll",
        "GET",
        "/payroll/{year}/{period}",
        READ,
        "One payroll period with its payslips.",
        (
            YEAR,
            Param("period", "integer", True, "path", minimum=0, maximum=11, help="Period 0-11."),
        ),
        response_root="period",
    ),
    Operation(
        "transition_payroll_payment",
        "Mark payroll payment paid",
        "payroll",
        "PUT",
        "/payroll/{year}/payments/{payment_date}/{transition}",
        UPDATE,
        "Mark a payroll (PAYE/NI) payment as paid or unpaid. This moves no money.",
        (
            YEAR,
            Param("payment_date", "date", True, "path", help="Payment date YYYY-MM-DD."),
            transition("mark_as_paid", "mark_as_unpaid"),
        ),
    ),
    Operation(
        "list_payroll_profiles",
        "List payroll profiles",
        "payroll",
        "GET",
        "/payroll_profiles/{year}",
        READ,
        "Employee payroll profiles of one tax year.",
        (YEAR, ref("user", "users")),
        response_root="profiles",
    ),
)
crud(
    "properties",
    "property",
    "accounting",
    "property",
    create_note="Unincorporated landlords only. Needs address1.",
)

OPERATIONS: dict[str, Operation] = {op.name: op for op in OPERATIONS_LIST}
if len(OPERATIONS) != len(OPERATIONS_LIST):  # pragma: no cover - catalog authoring guard
    raise RuntimeError("Duplicate FreeAgent operation name")

ATTACHMENT_OPERATIONS = frozenset(
    op.name
    for op in OPERATIONS_LIST
    if op.special in ("inline_attachment", "explanation_attachment", "statement_file")
)
PDF_OPERATIONS = frozenset(op.name for op in OPERATIONS_LIST if op.special == "pdf")
