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
| `SPACE_ADMIN_TOKEN` | An independently generated URL-safe random administrator password, at least 32 characters |
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
| `SUBSCRIPTIONS_ENABLED` | Start with `false`; set `true` only after the GitHub confirmation worker and its matching switch are configured |
| `DIGEST_PUBLIC_BASE_URL` | `https://<owner>-<space>.hf.space`, using the Space's actual direct application URL |

`GITHUB_REPOSITORY` defaults to the fixed personal repository `Rexmiao/levyquant-digest` and need not be supplied. A different explicit repository is rejected. GitHub Secrets and HF Secrets are separate stores; configuring one does not configure the other.

No `SMTP_APP_PASSWORD`, `SMTP_USERNAME`, or private recipient list is required in HF Secrets. Subscriber addresses are entered by their owners through the application and stored in authenticated encrypted state, not in public source files.

## GitHub confirmation worker and daily delivery

Keep the existing GitHub email and model configuration. In that same digest repository:

- Add **Secret `DIGEST_INTERNAL_RECIPIENTS`** for the owner's confirmed fixed internal address list. Use the existing ordinary **`DIGEST_RECIPIENTS`** Secret for the existing ordinary list; do not remove it. JSON arrays and comma-separated addresses are supported. Documentation examples use placeholders only: `["internal@example.com"]` and `["reader@example.com"]`.
- Add **Variable `DIGEST_PUBLIC_BASE_URL`** with the same direct HF application URL.
- Add **Variable `SUBSCRIPTIONS_ENABLED`**, initially `false`. After the subscription modules and confirmation worker have been published to the default branch and tested, enable the GitHub switch and the HF switch together.

The daily workflow combines the configured ordinary list, the fixed internal list, and confirmed active public subscriptions, then removes duplicates. Fixed internal recipients remain protected when the public subscription list changes. Keep daily delivery under the existing `DIGEST_ENABLED` switch.

Pending public requests do not receive the daily digest. GitHub Actions sends the confirmation email; the recipient opens the confirmation link and explicitly confirms before becoming active. A link visit alone does not complete consent. Subscription emails include an unsubscribe route. Public unsubscribe controls apply to public subscriptions; fixed internal recipients are maintained separately by the owner.

## Public use and owner administration

Visitors can read the currently published preview, request a subscription, confirm it, and unsubscribe. Anonymous requests cannot invoke the model, generate a new digest, or trigger a manual daily mailing. A generic request receipt is not proof that a confirmation email has arrived.

The owner opens **`/admin`** and supplies `SPACE_ADMIN_TOKEN`. Every protected management API validates this token on the server through **`Authorization: Bearer ...`**. The `/admin` path itself is not an authentication mechanism; no administrative capability is granted just by knowing the URL. Tokens are not passed as URL query parameters.

After configuration, the owner generates a real preview from the live sources, lets the existing schema and evidence checks validate it, then publishes the approved preview. Before a preview is published, the landing page must clearly indicate that a current real preview is unavailable; demo copy is not a live news edition. Do not bypass evidence failures by changing model providers or publishing an unchecked draft.

## Validate before calling it live

1. Confirm the Docker build succeeds and the public landing page loads at the actual HF URL. With credentials absent, protected operations must remain locked.
2. Configure the original encryption key and restricted GitHub token. Verify protected actions reject missing or incorrect admin tokens and state keys.
3. Configure the same public base URL on both services. Test a subscription using an address you control, receive a confirmation through GitHub, explicitly confirm, and verify the active state without exposing addresses in logs.
4. Verify unsubscribe, then verify an inactive subscription is excluded from subsequent public-list delivery. Keep the configured fixed internal recipients unchanged.
5. Generate, validate, and publish a real preview from the private owner page. Check that public responses contain the intended published content only.

Email acceptance, inbox delivery, subscription confirmation, and a scheduled production run are separate checks. SMTP uncertainty must not cause automatic duplicate delivery. The 07:00 schedule is a target trigger time; GitHub scheduling and model generation do not guarantee exact inbox arrival.

The initial feeds cover official macro releases, research, SEC events, and a few company sources. They are not complete market news, real-time quotes, consensus estimates, or a full economic calendar. Free API quotas can stop generation. The code cannot independently prove that a Google project remains on its free billing tier.

The package does not create a Space, purchase resources, configure secrets, or send an email. Complete and verify these deployment steps before describing the service as launched.
