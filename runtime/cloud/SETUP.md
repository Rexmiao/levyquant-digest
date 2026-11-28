# LevyQuant Cloud Digest: Public Code, Encrypted State

**English** | [简体中文](https://github.com/Rexmiao/levyquant-digest/blob/main/README.zh-CN.md)

Runs on GitHub-hosted runners, the Gemini API free tier and Gmail SMTP. Your local machine can stay off while it runs. The personal public repository is **Rexmiao/levyquant-digest**. The real sender address, recipient lists, passwords and state key are all set through GitHub Secrets and are never placed in the public code.

## 1. Confirm the deployment target

Code is deployed through the existing GitHub connection to the personal **Public** repository [Rexmiao/levyquant-digest](https://github.com/Rexmiao/levyquant-digest). After deploying, confirm that `.github/workflows/daily-digest.yml` exists on the default branch. This process does not require a new GitHub CLI login, a new PAT or any organization access.

If you need to upload the fallback bundle by hand, use `outputs/levyquant-cloud-deploy.zip`, regenerated and reviewed under the public scheme, and place its files at the repository root. Do not upload the whole local project, the n8n database, OAuth tokens, private email, logs, local subscriber files or plaintext delivery records.

**Workflow logs, Summaries, files and commit history in a public repository are visible to anyone.** The Summary shows only non-sensitive run metadata, never full drafts, real addresses, recipient lists or keys. Logs must not print these either. HTML-escaped body text is still public content and is not a form of encryption. [GitHub log access](https://docs.github.com/en/rest/actions/workflow-runs)

## 2. Confirm free-tier settings

In [Google AI Studio Projects](https://aistudio.google.com/projects), find the project that owns the API key you plan to use, check its **Billing Tier**, and confirm it is still **Free** with no paid billing enabled or linked. Use only keys from a confirmed free project, and do not enable paid billing for this digest.

The code pins the model, limits calls and never falls back to a paid model, **but it cannot tell from an API key alone whether a Google project is billed**. You must verify this in AI Studio before setting `GEMINI_FREE_TIER_CONFIRMED=true`. The free tier is limited by model, region and quota. When the quota runs out the job is allowed to stop; it never upgrades automatically. [Google billing](https://aistudio.google.com/docs/billing), [model pricing](https://aistudio.google.com/docs/pricing)

Standard GitHub-hosted runner minutes are free for public repositories; larger runners and other paid features follow separate rules. In [GitHub personal Billing](https://github.com/settings/billing) → **Budgets and alerts**, set a **$0 additional-spend budget** for Actions and enable **Stop usage when budget limit is reached**. An alert alone does not stop overage, and repository variables do not control GitHub or Google billing. [Actions usage](https://docs.github.com/en/actions/concepts/billing-and-usage), [budgets](https://docs.github.com/en/billing/how-tos/set-up-budgets)

## 3. Set six Secrets and two Variables

Open the repository's **Settings → Secrets and variables → Actions**. On the **Secrets** tab, click **New repository secret** for each of the following and enter the value yourself:

| Name | Value |
| --- | --- |
| `GEMINI_API_KEY` | The Gemini API key from the free project confirmed in step 2 |
| `SMTP_USERNAME` | The confirmed Gmail sender address; do not write the real address into public config |
| `SMTP_APP_PASSWORD` | A Google app password for that sender account |
| `DIGEST_RECIPIENTS` | The current regular subscriber list as a JSON array or comma-separated addresses; change only this one when replacing the external list later |
| `DIGEST_INTERNAL_RECIPIENTS` | The fixed internal recipient list as a JSON array or comma-separated addresses; always kept, independent of the regular list |
| `STATE_ENCRYPTION_KEY` | A separately generated 32-byte random key, URL-safe Base64 encoded |

Each list lives in its own Secret and real addresses never go into public config. Format example, with placeholder addresses only:

```json
["you@example.com","another@example.com"]
```

Both accept this JSON array form as well as `you@example.com,another@example.com`. A real `send` merges the two lists, de-duplicates case-insensitively and delivers one message per person; at most 100 unique addresses after merging.

The fixed internal list is required for real sends. If `DIGEST_INTERNAL_RECIPIENTS` is missing, empty or invalid, the whole run stops before any network call so internal recipients are never skipped. The regular `DIGEST_RECIPIENTS` must also be valid and non-empty. When you replace the external list later, change only `DIGEST_RECIPIENTS` and keep the internal Secret, so internal recipients do not disappear with the external list. Never copy real lists into public code, Issues, logs or Summaries.

`preview`, `preview-email` and `smtp-test` do not depend on either list. The latter two test deliveries go only to the `SMTP_USERNAME` mailbox and never pull in the internal or external lists.

Generate the state key separately from the API key and mail password. You can run the command below in your own terminal; copy its output only into `STATE_ENCRYPTION_KEY` and keep it privately. Do not paste it into chat or commit it.

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Switch to the **Variables** tab and add:

| Name | Initial value |
| --- | --- |
| `DIGEST_ENABLED` | `false` |
| `GEMINI_FREE_TIER_CONFIRMED` | `true` only after you have actually confirmed step 2; otherwise keep `false` |

Only you enter passwords and keys, directly into GitHub Secrets, never in chat. The cloud job does not read passwords stored in the local n8n. [Using GitHub Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)

## 4. Verify previews and connectivity, then enable daily sends

In **Actions → LevyQuant Daily Digest → Run workflow**, choose the default branch and set `run_mode`:

1. **`preview`**: builds the day's draft without sending email. The public Summary shows only non-sensitive results and counts, not the full text; do not use public logs to read drafts.
2. **`smtp-test`**: sends a single connectivity test only to the `SMTP_USERNAME` sender mailbox. Check the inbox and spam folder to confirm cloud SMTP works; a successful local connection does not prove the cloud path.
3. **Optional `preview-email`**: use only if the deployed version's dropdown offers this mode. When you choose it manually, it sends the day's draft to the `SMTP_USERNAME` mailbox for a private check of layout, sources and languages; nothing goes to subscribers. If the option is absent, do not assume the feature is live; check the text with a local preview first.
4. After the cloud checks, change the repository Variable **`DIGEST_ENABLED` to `true`**. The daily schedule targets **07:00 America/New_York local time**, follows daylight saving automatically and delivers one by one to the merged internal and regular lists.

Manual `send` mode really delivers the day's edition to the merged internal and regular lists, subject to the same enable switch, key and delivery-record checks. To pause the digest, set `DIGEST_ENABLED` back to `false`. There is no need to click Run workflow every day.

## Hugging Face public subscription portal

The deployable bundle and configuration are described in `runtime/huggingface/README.md`. HF provides the public preview, email-confirmed subscription, unsubscribe and a server-authenticated `/admin`; Gmail SMTP and the 07:00 New York schedule still run on GitHub.

Once the Space address is ready, add `DIGEST_PUBLIC_BASE_URL=https://<owner>-<space>.hf.space` to this repository's Variables. After confirming that HF and this repository use the same state key and public address and that the confirmation-mail workflow is deployed, set `SUBSCRIPTIONS_ENABLED` to `true` on both sides. This switch controls public sign-up and confirmation emails; existing unsubscribes and admin deactivations are still filtered at every daily send.

Once enabled, the regular list is merged with confirmed public subscribers, unsubscribed external addresses are excluded, and the fixed internal list is always kept. Public sign-up only queues a confirmation email; an address joins the public list only after the confirm button in that email is clicked. Confirmation emails run on GitHub, with an hourly queue recovery. A successful submission does not mean the email actually arrived.

### Unsubscribe and delivery dashboard

Real digests to anyone outside the fixed internal list keep the footer unsubscribe link and add `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers plus a dedicated unsubscribe POST endpoint. Opening the page with GET never changes subscription state, so mail scanners cannot trigger it. Whether Gmail or other providers show a top-of-message unsubscribe button is up to them. There is currently no evidence that Gmail's automatic DKIM signature covers these two `List-*` headers, so RFC 8058 signature compliance or button display is not claimed.

Once a regular address unsubscribes or is deactivated in the admin, it is filtered even if it is still in the original `DIGEST_RECIPIENTS` and even if public sign-up is switched off; eligibility is re-checked right before each recipient is sent. Mail already handed to SMTP cannot be recalled, and the very short race between the check and the submission cannot guarantee a recall either. The fixed internal list is kept separately, carries no public unsubscribe link and is not removed by public unsubscribes or admin deactivation; only an explicit owner change to the internal configuration removes it.

The private admin delivery dashboard distinguishes `send`, `preview`, `preview-email` and `smtp-test`. Only real digests show per-recipient submission counts: accepted, rejected, uncertain, reserved, pending, skipped due to unsubscribe, internal count and accepted already present in this run. Accepted means only that SMTP accepted the message, not that it reached the inbox. For older digests without a complete headcount snapshot, unknown totals, internal counts and unprocessed counts are shown as unknown rather than guessed from existing hash records; older GitHub runs without a mode marker are not described as sent emails.

The CLI writes metadata for the latest 50 safe runs to `reports/delivery-activity.json` in the existing encrypted state, merging run records with CAS, and never includes addresses, body text, URLs, codes or keys. HF private previews do not write this CLI activity record; the admin combines the last 7 days of real digest state with GitHub runs. A failed report write never triggers a duplicate delivery. This feature reuses existing credentials and CPU Basic and needs no new Secret, permission, hardware or state migration.

### Administrator email-code sign-in

After the email sign-in feature is deployed, an administrator enters an allow-listed address at `/admin` and then the 6-digit code from the email. The code is valid for 10 minutes from the request and works only once; do not forward or share it. Public subscriptions never grant admin rights, and admin addresses are not written to public config or logs. The allow list is maintained through a dedicated admin endpoint protected by the original `SPACE_ADMIN_TOKEN` recovery credential; ordinary sign-in sessions cannot change it.

Code emails share the fixed `subscription-mail.yml` and the existing SMTP Secrets with subscription confirmation emails. `SUBSCRIPTIONS_ENABLED` controls only the confirmation queue; codes for allow-listed administrators are processed independently and need no new Secret, extra permission or hardware. HF holds no mail password and never sends mail over SMTP directly. GitHub queuing may be delayed; expired codes are not resent, so request a new one on the page.

A successful email code or recovery credential creates a one-hour administrator session. The browser restores the sign-in through a Secure, HttpOnly cookie, and a page refresh keeps the original session expiry. Signing out revokes the server-side session and clears the cookie. The recovery credential is used only for verification. Persistent records of codes, requests and sessions reuse the existing encrypted state; the worker delivers only after a successful reservation and never resends automatically when the outcome is uncertain or the process is interrupted.

Open `/admin` directly in its own browser tab on the Space's own address. The session cookie is `SameSite=Strict`, so when the console is embedded in another page, such as the huggingface.co Space page, the browser does not keep the sign-in after a refresh. In that case the console shows a notice with a button to open it in a new tab. The cookie policy is intentionally not relaxed for embedding.

To sign in to the admin on a custom domain attached to the Space (for example `https://daily.levyquant.ai`), add the Space variable `DIGEST_ADMIN_ORIGINS` with that exact origin: `https://`, lowercase host, no trailing slash or port; separate up to five origins with commas. The canonical `DIGEST_PUBLIC_BASE_URL` stays trusted, and any malformed entry trusts no extra origin. Sessions are per host, so signing in on one address does not sign in on the other. Emailed links keep using `DIGEST_PUBLIC_BASE_URL`.

### Shared Moomoo search keywords

After deploying the version with source settings, change and save Moomoo keywords in the HF private admin at `/admin`. The setting is written to `settings/moomoo.json` on the existing `delivery-state` branch and encrypted with the original `STATE_ENCRYPTION_KEY`; neither HF's temporary disk nor browser storage keeps this persistent setting. The GitHub daily digest and newly generated HF previews read the same setting; `config/friend-sources.json` only supplies default keywords before anything has been saved.

Saving keywords does not generate a preview or send email. An official edition already generated and frozen for the day keeps its text and delivery records; the update applies to later collection and new previews and never rewrites or resends an edition already sent that day. Moomoo still provides only headlines, source times and links, which must not be expanded into text that was never obtained. This setting reuses the existing GitHub token and encrypted state and needs no new Secret, permission or hardware; HF stays on CPU Basic.

### Encrypted state and recovery

The delivery-state branch stores only **AES-GCM ciphertext**. The decryption key comes from `STATE_ENCRYPTION_KEY` and is never committed to that branch. Recipients, delivery records and any state that must persist are never published in plaintext.

If the key is missing or wrong, or state integrity verification fails, delivery must stop and the existing ciphertext must be kept for recovery; a decryption failure must never be treated as a first run or empty history. Do not casually delete or rebuild the state branch or change the key. Rotating the key requires a controlled migration that decrypts with the old key; replacing the Secret alone is not enough.

If a run reports an uncertain delivery outcome, check the sent mail first and then deal with state; do not re-run repeatedly to resend. SMTP acceptance does not guarantee inbox delivery, and a fixed Message-ID is not a Gmail de-duplication guarantee.

## Operating limits

- **Timing**: The main job starts at 07:00 New York local time every day, with fallback checks at 07:20 and 08:10. A completed digest skips sending. If the day's edition is missing, a fallback job generates and sends it; after a partial delivery failure, the day's frozen edition is used to resend only mail that can be safely retried. Accepted or uncertain mail is never resent. All three triggers use GitHub Actions, so an outage on that platform can affect all of them at once. Workflows must be on the default branch, and scheduled workflows in a public repository may be disabled automatically after 60 days without activity. [Schedule docs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- **Content**: Each new bilingual edition puts the full English text first in one email, followed by an item-by-item matching Simplified Chinese text, with full sections, focused on macro, U.S. equities and quantitative research; general news includes only major events. The default `config/friend-sources.json` has 21 sources: official sources such as the Fed, BLS, SEC, arXiv and NVIDIA; public feeds from CNBC, WSJ, SCMP, Digitimes, Leiphone and ifanr; and 5 podcasts recommended by a friend. Moomoo's official News Search additionally searches NVIDIA, Microsoft and Federal Reserve by default and selects up to 6 candidates by time, keeping only the headline, an explicit source time and the original link. Media items use only the headline and excerpt from the feed and podcasts use only episode descriptions, with no audio download; this is not complete market coverage. Licensed Reuters content, the Finnhub calendar, real-time quotes, consensus estimates and authorized X, Xueqiu or WeChat official accounts are not connected yet. Missing content is omitted and the model is not allowed to make it up.
- **Deployment status**: Code published, Secrets saved, model callable, cloud SMTP working and the daily schedule enabled are separate stages. Confirm completion from the repository's current code, run results and actual email, not from the existence of a fallback bundle or a successful local test.

## New email copy

Newly generated digests use an English subject in the form `LevyQuant Morning Briefing — November 26, 2026`. The confirmation email explains that the address came from the subscription page, what the digest covers and that it is sent around 7 a.m. New York time, and keeps the 48-hour deadline and the second confirmation step on the web page. The new digest footer explains why each person receives it: a confirmed public subscription, the original authorized list or internal archiving. Regular recipients get a clear `Unsubscribe from LevyQuant` link; the fixed internal list gets no unsubscribe link.

The Coverage notice keeps only a short scope statement, reading limits for the material actually cited in that edition and notes about collection, truncation or editorial removal that actually happened. The list of unconnected services above remains the full deployment boundary; the shorter footer does not relax any source, number or date verification. The new copy applies only to newly generated digests and confirmation emails sent afterward. Subjects, text and accepted delivery records of older frozen digests stay as they were and are not resent because of the copy change. Changing the copy cannot guarantee inbox placement.

## Bilingual email format

Each new digest provides the full English text first in one email, followed by a complete matching Simplified Chinese translation. Both parts present items, source links and verified numbers and dates in the same order. The website's language setting is independent of this layout order.

Translation uses the existing model on the confirmed free tier, with at most two translation attempts per new edition. A bilingual edition must pass translation validation before it can be sent. Times with an explicit time zone are shown as `America/New_York` dates with an EST/EDT marker; date-only material keeps its original precision.

Same-day retries keep using that edition's frozen text and delivery records.

## Public archive

The homepage's "Archive" link leads to `/archive`, where you can pick a month, search the full text within that month, open an edition by date and share `/archive?date=YYYY-MM-DD`. The interface keeps the English/Chinese switch, lists 10 editions per page, and edition text stays in its original language.

A new digest is added automatically once the mail server accepts it; editions an administrator explicitly publishes are added too. The archive keeps the first public version for each date, so a later revision or real email on the same day may differ from it. Private previews are never published automatically. The public API returns only non-personalized titles, dates and text; delivery records, subscription data and recipient-specific links stay in the encrypted admin state.

An authenticated administrator backfills history with `POST /api/admin/archive/backfill`, up to 31 dates per batch, with a cursor returned for the next batch. It verifies existing official editions against real acceptance records and may include the latest published edition; it does not regenerate or send email and does not rewrite the original frozen editions. Archive snapshots and the date index reuse the existing encrypted storage and CAS, and a failed write can be retried to complete the index. There is currently no automatic archive deletion rule.
