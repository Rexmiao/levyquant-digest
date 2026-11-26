---
title: LevyQuant Digest
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Macro, U.S. equities and quantitative research
---

# LevyQuant Digest

Public news preview, confirmed email subscriptions, unsubscribe controls, and a private owner administration page. The digest focuses on macroeconomics, U.S. equities, and quantitative research. Its main text is English, with original Chinese titles retained when relevant.

This package is prepared for deployment. The Hugging Face owner and Space name have not yet been selected, and no live launch URL has been verified. Replace the placeholders below with the actual Space values when deploying; the README itself is not evidence that a service is live.

## Architecture

- **Hugging Face Docker Space, CPU Basic** serves the public landing page and `/admin`, accepts subscription requests, and performs authorized owner preview generation over HTTPS.
- **GitHub Actions** keeps the daily schedule at **07:00 America/New_York** and sends both digest and confirmation emails through Gmail SMTP.
- **GitHub-backed encrypted state** holds subscription and delivery information. The Space's temporary disk is not the durable state store.
- The latest owner-published preview is intentionally public. It is separate from private subscriber records and management responses.

Select **CPU Basic** when creating the Space. That hardware tier is free; no GPU, dedicated Inference Endpoint, or additional paid hardware is required. Existing Pro membership is sufficient for this setup without purchasing hardware. Free hardware may sleep when idle, so the first visit can require a wake-up. Daily email scheduling remains on GitHub independently of the Space's running state.

HF Spaces restrict outbound networking; this design does not send SMTP from the Space. Do not add a mailbox password to HF. Model and GitHub requests use HTTPS, while GitHub Actions performs SMTP delivery. [Space networking](https://huggingface.co/docs/hub/spaces-overview#networking), [hardware](https://huggingface.co/docs/hub/spaces-gpus)

## Deploy the allowlisted package

Create a **Docker** Space under your own HF account, select **CPU Basic**, and upload the contents of the reviewed `levyquant-huggingface-deploy.zip` to the Space repository root. The package maps this README and the Dockerfile to root `README.md` and `Dockerfile`; preserve the remaining directory structure.

The app listens on port **7860** and runs as UID **1000** with Python 3.12. It can display the public landing page before credentials are configured; subscription and administrative operations remain locked until their required configuration is valid. A landing page loading does not prove signup, confirmation, or email delivery works.

No GitHub CLI or organization access is needed. For the Space's server-side GitHub access, create a **fine-grained personal access token** owned by the personal account that owns `Rexmiao/levyquant-digest`. Choose **Only select repositories**, select only that repository, and grant **Contents: Read and write** and **Actions: Read and write**. Do not grant unrelated repositories or organization permissions.

## Hugging Face Settings

Add these values in the Space's **Settings → Variables and secrets**, using **Secrets** for the first table. Never paste secret values into a chat, public source file, build argument, URL, or browser console log.

| Secret | Value |
| --- | --- |
| `GITHUB_TOKEN` | The fine-grained token limited to the one personal digest repository |
| `STATE_ENCRYPTION_KEY` | The **same existing key** already used by the GitHub workflow; do not generate a replacement |
| `SPACE_ADMIN_TOKEN` | The existing independent administrator recovery credential, at least 32 URL-safe characters |
| `GEMINI_API_KEY` | A key for the owner's verified Gemini Free-tier project |

The existing state key is URL-safe Base64 encoding of 32 random bytes. Copy its original value from your secure backup into HF Secrets. If you cannot recover it, keep protected operations locked and recover the original key; changing the key does not decrypt existing state. Missing keys, wrong keys, or state authentication failures must block operations rather than erase or reset the state.

To create the **new, independent admin password** in your own terminal:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy that output only into `SPACE_ADMIN_TOKEN` and save it privately. This command is for the admin password, **not** for replacing `STATE_ENCRYPTION_KEY`.

| Variable | Value |
| --- | --- |
| `GEMINI_FREE_TIER_CONFIRMED` | `true` only after the owner verifies the key's Google project is still Free and has no paid billing enabled |
| `SUBSCRIPTIONS_ENABLED` | Controls public subscription requests and confirmation mail; administrator sign-in codes are independent |
| `DIGEST_PUBLIC_BASE_URL` | `https://<owner>-<space>.hf.space`, using the Space's actual direct application URL |

`GITHUB_REPOSITORY` defaults to the fixed personal repository `Rexmiao/levyquant-digest` and need not be supplied. A different explicit repository is rejected. GitHub Secrets and HF Secrets are separate stores; configuring one does not configure the other.

No `SMTP_APP_PASSWORD`, `SMTP_USERNAME`, or private recipient list is required in HF Secrets. Subscriber addresses are entered by their owners through the application and stored in authenticated encrypted state, not in public source files.

## GitHub mail worker and daily delivery

Keep the existing GitHub email and model configuration. In that same digest repository:

- Add **Secret `DIGEST_INTERNAL_RECIPIENTS`** for the owner's confirmed fixed internal address list. Use the existing ordinary **`DIGEST_RECIPIENTS`** Secret for the existing ordinary list; do not remove it. JSON arrays and comma-separated addresses are supported. Documentation examples use placeholders only: `["internal@example.com"]` and `["reader@example.com"]`.
- Add **Variable `DIGEST_PUBLIC_BASE_URL`** with the same direct HF application URL.
- Add **Variable `SUBSCRIPTIONS_ENABLED`**, initially `false`. After the subscription modules and confirmation worker have been published to the default branch and tested, enable the GitHub switch and the HF switch together.

The daily workflow combines the configured ordinary list, the fixed internal list, and confirmed active public subscriptions, then removes duplicates. Fixed internal recipients remain protected when the public subscription list changes. Keep daily delivery under the existing `DIGEST_ENABLED` switch.

Pending public requests do not receive the daily digest. GitHub Actions sends the confirmation email; the recipient opens the confirmation link and explicitly confirms before becoming active. A link visit alone does not complete consent. Subscription emails include an unsubscribe route. Public unsubscribe controls apply to public subscriptions; fixed internal recipients are maintained separately by the owner.

Ordinary-recipient digest messages include a footer unsubscribe link plus `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers backed by a dedicated POST endpoint. GET requests only display a confirmation page, so link scanners do not change subscriptions. Provider presentation remains outside the app's control: Gmail's automatic DKIM signature has not been verified to cover both `List-*` headers, so these headers and endpoint alone do not establish RFC 8058 signature compliance or guarantee a top-of-message unsubscribe button.

Opt-outs and owner suppressions continue to block ordinary recipients retained in `DIGEST_RECIPIENTS`, even when public signup is disabled. Eligibility is checked again before each recipient submission. A message already submitted to SMTP cannot be recalled, and the small interval between the final check and submission cannot provide a recall guarantee. Fixed internal recipients remain protected and receive no public unsubscribe control; only an explicit owner change to their separate configuration removes them.

The same fixed `subscription-mail.yml` also sends queued administrator sign-in codes using the existing SMTP secrets. Only subscription confirmations depend on `SUBSCRIPTIONS_ENABLED`; allowlisted administrator codes remain available independently. The worker requires no new secret, permission or hardware, and HF still does not hold SMTP credentials. Its manual dispatch has no email, code, token or private URL inputs. Both queues reserve messages durably before SMTP, and uncertain or interrupted submissions are not automatically replayed.

## Public use and owner administration

Visitors can read the currently published preview, request a subscription, confirm it, and unsubscribe. Anonymous requests cannot invoke the model, generate a new digest, or trigger a manual daily mailing. A generic request receipt is not proof that a confirmation email has arrived.

The **中文 / EN** control switches the public and administrator interface, including subscription messages. Only that language preference is saved in browser storage; form entries and administrator credentials are not persisted by the switch. Published briefing content keeps its original language, identified beside the preview.

The administrator opens **`/admin`**, requests a code for an address on the private administrator allowlist, and enters the emailed six-digit code. The code expires **10 minutes after the request** and is single-use. Do not forward or share it. A public subscription does not grant administrator access, and unknown addresses receive no administrator code. The allowlist is managed only through the dedicated recovery-credential interface; ordinary sign-in sessions cannot change it.

Successful verification issues a random **one-hour Bearer session**. The UI keeps it only in memory, never in URLs, localStorage or sessionStorage. Language switching preserves it; reloading requires signing in again. Explicit sign-out revokes the server-side session. Every protected management API validates `Authorization: Bearer ...` on the server. The original `SPACE_ADMIN_TOKEN` remains available through a collapsed recovery entry and is never emailed. Durable allowlist, login and session records use the existing encrypted state; session tokens are stored there only as hashes.

Administrator requests trigger the existing GitHub mail worker. GitHub scheduling can delay delivery; the worker skips expired requests rather than sending stale codes. If a code expires before arrival, request a new code on the page. Knowing `/admin` alone grants no access.

### Delivery activity

The private dashboard separates formal `send` editions from `preview`, self-only `preview-email`, and `smtp-test` runs. Formal-edition counts reflect recorded SMTP outcomes, including accepted, rejected, uncertain, reserved, pending, skipped opt-outs, internal recipients and previously accepted submissions. SMTP acceptance does not prove inbox arrival. Legacy editions without a complete audience snapshot retain unknown totals, internal counts and pending counts rather than inventing them from recipient hashes. Historical GitHub runs without a known mode are not labeled as sent mail.

The CLI records at most 50 credential-free activity rows in the existing encrypted `reports/delivery-activity.json`, merging concurrent runs with CAS. Email addresses, message bodies, URLs, codes and credentials are excluded. HF preview generation does not write CLI activity reports. The dashboard combines these rows with the last seven days of real edition receipts and GitHub run status. No new secret, repository permission, hardware, state migration or key replacement is needed; keep CPU Basic. A report failure does not justify resending an already accepted message.

After configuration, the owner generates a real preview from the live sources, lets the existing schema and evidence checks validate it, then publishes the approved preview. Before a preview is published, the landing page must clearly indicate that a current real preview is unavailable; demo copy is not a live news edition. Do not bypass evidence failures by changing model providers or publishing an unchecked draft.

### Shared Moomoo keywords

After deploying the source-settings feature, edit and save Moomoo search keywords in `/admin`. They are stored at `settings/moomoo.json` on the existing `delivery-state` branch, encrypted with the existing `STATE_ENCRYPTION_KEY`. GitHub daily delivery and newly generated HF previews read the same saved configuration. `config/friend-sources.json` supplies initial defaults only when no saved settings exist; the Space's temporary disk and browser storage are not the durable settings store.

Saving keywords does not generate a preview or send email. A formal edition already frozen for the current New York date retains its original body and delivery records; changed keywords apply to new collection and previews, without rewriting or resending an already sent edition. Moomoo remains headline-and-link coverage, without inferred article detail. The feature uses the existing GitHub token and encrypted state: no additional secret, repository permission, paid hardware or GPU is required. Keep the Space on CPU Basic.

## Validate before calling it live

1. Confirm the Docker build succeeds and the public landing page loads at the actual HF URL. With credentials absent, protected operations must remain locked.
2. Configure the original encryption key and restricted GitHub token. Use the recovery credential to configure only the intended administrator allowlist, then test email-code sign-in, single-use/expired-code rejection and explicit sign-out. Verify protected actions reject missing or incorrect sessions, recovery credentials and state keys without exposing them.
3. Configure the same public base URL on both services. Test a subscription using an address you control, receive a confirmation through GitHub, explicitly confirm, and verify the active state without exposing addresses in logs.
4. Verify unsubscribe, then verify an inactive subscription is excluded from subsequent public-list delivery. Keep the configured fixed internal recipients unchanged.
5. Generate, validate, and publish a real preview from the private owner page. Check that public responses contain the intended published content only.

Email acceptance, inbox delivery, subscription confirmation, and a scheduled production run are separate checks. SMTP uncertainty must not cause automatic duplicate delivery. The 07:00 schedule is a target trigger time; GitHub scheduling and model generation do not guarantee exact inbox arrival.

The default `config/friend-sources.json` has 20 feeds plus Moomoo's official News Search: six official macro, research, SEC and company sources; nine publisher feeds from CNBC, WSJ, SCMP, Digitimes, Leiphone and Ifanr; and the reference newsletter's five podcasts. Moomoo search is a bounded, unauthenticated public HTTPS request for headlines, source timestamps and explicit original-source links. It requires no OpenD, trading account, new secret or extra runtime. Its linked articles and images are not downloaded, and headline-only items cannot be expanded into inferred summaries. Publisher coverage uses feed headlines and excerpts; podcast coverage uses episode descriptions without downloading audio. Reuters licensed content, Finnhub calendars, live quotes, consensus estimates and authenticated X/Xueqiu/WeChat access remain unconnected. This is selected coverage, not a complete market newswire or economic calendar. Free API quotas can stop generation. The code cannot independently prove that a Google project remains on its free billing tier.

The package does not create a Space, purchase resources, configure secrets, or send an email. Complete and verify these deployment steps before describing the service as launched.

Newly generated editions use the subject `LevyQuant Morning Briefing — November 26, 2026`. Confirmation messages explain why the address received the message, what the briefing covers, its approximate New York delivery time, and the unchanged two-step confirmation and 48-hour expiry. New personalized footers distinguish confirmed subscriptions, previously authorized recipients and fixed operator archive copies; ordinary recipients see `Unsubscribe from LevyQuant`.

Coverage notes are concise and describe only the material actually cited plus genuine availability, shortening or validation omissions. The detailed service limitations above still apply; source, numeric and date checks are unchanged. This copy upgrade never rewrites frozen editions or replays accepted deliveries. Clearer copy does not guarantee inbox placement.
