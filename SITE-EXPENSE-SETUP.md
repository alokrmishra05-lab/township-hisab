# Site Expense + Evidence — Setup

This is an isolated approval-based expense module. The original 15 ledger transactions and encrypted static main totals remain unchanged.

## New capabilities
- Staff and partners can sign in individually and submit site expenses.
- Fields: date, amount, category, description, payer, payment method, bill number, notes.
- Upload up to five JPEG, PNG, WEBP, PDF, DOC or DOCX files (10 MB each).
- Submitters can correct their own pending entries and append evidence.
- Only an active admin can approve/reject. Approval requires at least one evidence record.
- Evidence lives in a private Storage bucket; 60-second signed links are generated for authorized members.
- Approved entries cannot be edited by the app or deleted via the supplied RLS policies.

## Set up before merging
1. Create a separate secure Supabase project (do not reuse a study-app database).
2. Review and run the SQL from supabase/site-expenses.sql in Supabase SQL Editor.
3. In Authentication, disable public signups and create/invite each trusted account separately.
4. Find actual Authentication User UUIDs, then insert entries into public.site_expense_members with fields user_id, display_name and role (admin, partner or assistant). Assign admin only to a trusted owner.
5. In site/expenses-config.js set your actual Supabase project URL and PUBLIC publishable/anon key. Never publish any service_role/secret keys.
6. Test on an isolated branch: staff submission, PDF/photo upload, admin approval/rejection, signed private evidence opening, anonymous API access denied, editing approved records denied.
7. Only after setup and testing, merge the PR. GitHub Pages deployment cannot by itself provision Supabase. The existing Android APK is not automatically rebuilt on this change.

## Accounting warning
Approved site expenses appear only within the new Site Expense module. They DO NOT automatically increase the legacy ledger investment/expense totals or change the three-way settlement. That requires a separately reviewed reconciliation and a duplication-safe posting mechanism. A payer identified as project fund or site cash must not be credited to an individual partner without fund reconciliation.

## Upload limitation
An interrupted evidence upload may leave an incomplete pending expense, and can leave a private orphan Storage object. Retry through 'एंट्री सुधारें'. The account and evidence need a secure admin recovery/backup workflow before any production reliance.

## QA checklist (NOT YET EXECUTED)
- Anonymous queries are rejected.
- Assistant can submit but not approve.
- Assistant cannot edit other user's pending entries.
- Approved entries cannot be edited.
- Private file cannot be read without member authorization.
- Admin cannot approve missing-evidence entry.
- Admin can approve complete evidence entry.
- Existing main ledger and APK continue working.
