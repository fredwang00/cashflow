# Household catch-up and a smaller monthly routine

Reviewed September 23, 2026. The active cards were confirmed as Robinhood Gold Card, Amex Gold, Chase Prime Visa, BofA cards, and Target. Robinhood brokerage is outside this workflow.

## Catch up in this order

First open the issuer apps and verify current balances, due dates, AutoPay funding accounts, and recent payment results. The local ledger records an Amex late fee on June 21 and interest on June 26. Recorded avoidable charges = late fee + interest = $29.00 + $94.87 = **$123.87**. This is historical evidence, not proof of a current unpaid balance or current AutoPay settings. Amex describes its statement-balance and other AutoPay options in its [payment guide](https://www.americanexpress.com/en-us/resources/how-to-make-a-payment/).

Then obtain these exports. Dates below are the latest observed transactions in the local database, not verified statement coverage.

| Priority | Source | Latest observed | Suggested catch-up export | Reason |
|---|---|---|---|---|
| 1 | BofA checking, every household checking account | Expenses June 11; payroll May 29 | All 2026 if available; at least May 1–today | Restore income, mortgage, utilities and direct debits before interpreting surplus |
| 2 | Robinhood Gold Card | July 10 | All 2026 / all transactions | Main spending card; recover refunds omitted by the old parser |
| 2 | Amex Gold | July 8 | All 2026 | Main spending, fees, refunds; reconcile the historical imported payment |
| 3 | BofA credit cards, each account | June 10, combined bucket | All 2026; at least June 1–today | One combined freshness date can hide a missing card |
| 3 | Chase Prime Visa | June 11 | All 2026 | Restore Amazon/general spending and previously omitted refunds |
| 4 | Target credit card | March 11 | March 1–today, or all 2026 | Confirmed active despite the oldest main-card snapshot |
| 5 | Apple, Wells Fargo, Capital One, Citi | Various older dates | Check each for activity/fees first; export any gaps | Catch residual subscriptions, annual fees, travel refunds and unused-card activity |

Robinhood's [Gold Card guide](https://robinhood.com/us/en/support/articles/robinhood-gold-card-get-started/) gives the route: Menu → Documents → Export transaction history. Select the desired timeframe; the emailed download link is valid for seven days. BofA's [card FAQ](https://www.bankofamerica.com/credit-cards/credit-card-payments-statements-faq/) confirms downloadable transaction history. Chase's [spending tools page](https://www.chase.com/personal/financial-tools/build/spending-budget) describes desktop CSV downloads. Export availability and date limits should be checked in the actual account.

Download CSVs, not PDFs, for supported card/checking imports. Keep original files in a dated folder. Preserve account distinctions in filenames even though parsing now uses CSV headers. Chase Freedom is now supported when its filename contains `freedom`; other Chase CSVs map to Prime Visa. BofA accounts are aggregated in the database; keep a separate checklist of every underlying account exported.

Run against a backup copy first for this catch-up. The changes intentionally leave historical records untouched. In particular, review the existing Amex payment and checking duplicate links described in [the audit](2026-09-23-audit.md). Reimport can add missing refunds; it will not remove old payments or undo old links. If an import reports a conflicting source ID, reconcile that record rather than editing the export until it passes.

After reconciliation, the normal command sequence is:

```bash
cashflow ingest --files ~/cashflow/inbox
cashflow freshness
cashflow status
cashflow review
cashflow dashboard
```

`cashflow ingest --auto` is a shortcut for the same local inbox. It does not log into banks or poll email. Rules run on new imports. If `CASHFLOW_LLM_URL` is configured, unmatched transactions may be sent to that endpoint; leave it unset for a local rules/manual workflow.

Validate one closed month against statements before trusting the annual surplus: net card spending = purchases + fees − merchant credits/refunds − recorded reimbursements. Card payments are transfers, not extra spending. For example, $100 purchase − $25 refund − $20 reimbursement = $55 household cost, regardless of the card payment amount. Validate reimbursements against actual receipts too; approved expense reports alone do not prove cash was received.

Defer Amazon item enrichment and PayPal unless there is a concrete question they answer. The current database has 84 Amazon items and zero links, so this is presently extra work without dashboard benefit. Card exports already capture card-funded spending; PayPal balance-funded spending needs separate attention because the PayPal parser is not a complete ledger.

## Reduce the recurring work

1. **Make payment reliability independent of this dashboard.** If full payment is affordable, use issuer statement-balance AutoPay from one funded checking account, plus payment-failure and low-balance alerts. Verify enrollment and the first successful debit in each issuer app. If carrying a balance, prioritize a payoff plan over reward optimization. The dashboard does not know current balances or guarantee payments.
2. **Choose one default everyday card.** Robinhood can be the default if it remains your preferred card. Keep Prime tied to Amazon and Target tied to Target. Keep Amex only if its benefits you actually use justify the annual fee and extra account maintenance. Move recurring charges from redundant BofA/legacy cards to the default where practical.
3. **Review legacy annual-fee cards first.** Capital One Venture/Wendy and Wells Fargo are candidates to inspect, based on previously observed fees and limited recent imports—not automatic cancellation recommendations. Check current account status, product-change options, rewards, pending refunds and subscriptions. Compare annual net value = rewards actually redeemed + benefits actually used − annual fee − additional costs. Do not count face-value credits you would not otherwise use. A no-fee product change may simplify costs while retaining an account, if offered.
4. **Do not indiscriminately close every old no-fee card.** You can stop using one, remove stored payment details, and keep issuer alerts. Closing reduces available credit and can increase utilization; assess this before an upcoming credit application. Unused open accounts still need statement monitoring. See the [CFPB's closing-card guidance](https://www.consumerfinance.gov/ask-cfpb/does-it-hurt-my-credit-to-close-a-credit-card-en-1231/).
5. **Use one monthly close, with a narrow definition of done.** Export the active accounts through the last closed month, import once, verify payroll and major fixed bills, investigate large surprises, and resolve only material categorization issues. Label the month complete only after every account on the checklist is covered. Category perfection and item-level Amazon history are optional.

## Small automation worth doing next

The useful automation boundary is after downloading, where there are no bank logins or MFA challenges. Header detection, local inbox import, source-ID deduplication and import timestamps now work. A future small wrapper could create a consistent SQLite backup, import the inbox, and print a short exception report. It should stop on parser errors and identity conflicts, and distinguish a successfully read file from verified account/date coverage.

Next most valuable product improvements would be explicit per-account coverage dates and active/occasional/retired states. `MAX(transaction.date)` cannot distinguish inactivity from missing data, and the current BofA bucket cannot represent each card's coverage. These changes need an account-identity design before migrating history.

A reminder for the monthly close is simpler than automated banking login. Browser download orchestration is still only a proposal. Start with the reduced card set and a reliable manual export routine; evaluate a financial aggregator only if manual downloading remains the bottleneck and its coverage is demonstrated for all main accounts, especially Robinhood Gold Card. No recurring task, account connection, card cancellation, or bank setting was changed during this review.
