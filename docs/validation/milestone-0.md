# Milestone 0 validation

Fill this in on the Mac with your own Swiggy account. Plan section 1.4 explains why each check matters.
Never paste tokens, phone numbers or OTPs here. Do not check out or pay from the app while testing.

- Date: 2026-11-06
- Tester: Amit Bisht
- Commit SHA (`git rev-parse --short HEAD`): 198dccd (checks run on code from ba199d4, which includes #13)
- Baileys version: n/a (the listener adds Baileys in P17)
- Python version (`uv run --directory agent python --version`): 3.12.11

Prerequisite: `make install`, then store the LLM key if the commands ask for it.

## M0-1 Login from localhost

Command: `chat2cart login swiggy`

Expected: the browser opens Swiggy's page, you enter the phone number and OTP there, and the command ends with a success message.

- Was login blocked by a redirect allowlist? yes / no: no
- Result: pass / fail: pass
- Notes: Swiggy accepted `http://localhost/callback`. macOS only lets an unprivileged process bind port 80 on the wildcard address, so the callback server listens on 0.0.0.0 (fixed in story #6).

## M0-2 Token refresh

Command (prints only whether the stored tokens changed, never the tokens):

```bash
uv run --directory agent python -c "
from chat2cart.cli import build_secret_store
from chat2cart.secrets import SWIGGY_TOKENS
from chat2cart.swiggy.tokens import TokenManager
import httpx
store = build_secret_store()
before = store.get(SWIGGY_TOKENS)
with httpx.Client(timeout=30) as http:
    TokenManager(store, http).refresh()
print('new refresh token stored:', store.get(SWIGGY_TOKENS) != before)
"
```

Expected: `new refresh token stored: True`.

- Result: pass / fail: pass
- Notes: printed `new refresh token stored: True`; the new access token expires in about 30 days.

## M0-3 Address listing

Command: `chat2cart swiggy address`

Expected: your saved addresses are listed, you pick one, and `.env` gets the default address ID.

- Result: pass / fail: pass
- Notes: all saved addresses were listed across two pages and the chosen ID was saved to `.env`. Needed a parser fix for Swiggy's real response (story #10).

## M0-4 Product search

Command: `chat2cart prototype "<item>" --dry-run`

Expected: variants are listed with name, pack size, price and stock, and the cart is not changed.

- Item searched: milk, eggs
- Result: pass / fail: pass
- Notes: variants listed with pack size, price and stock; cart unchanged in the dry run. Only the first page of results is shown (follow-up).

## M0-5 Add to cart

Command: `chat2cart prototype "<item>"`

Expected: choose a variant, then the cart is printed with that item in it.

- Result: pass / fail: pass
- Notes: existing items were kept, the chosen item was added, and the read-back showed items and total. Swiggy may add free items itself (P15).

## M0-6 Cart appears in the Swiggy phone app

Open the Swiggy app on your phone after M0-5.

- Appeared? yes / no: yes
- Minutes taken: about 0.5 (roughly 30 seconds)
- Result: pass / fail: pass
- Notes: the cart showed up in the app. Once it reverted to its earlier state about a minute after a write, unexplained (P15).

## M0-7 Live cart or staging data

Does localhost development act on your real account and real cart, or on staging data?

- Real cart / staging: real cart
- Result: pass / fail: pass
- Notes: items added by the CLI appeared in the real Swiggy app cart.

## M0-8 Only allowlisted tools are called

Plan section 1.4 check 7. Checkout, payment and order tools must never be called.

Command: `make check` (allowlist and call-order tests), plus one live `chat2cart prototype "<item>"` run.

Expected: only tools in `ALLOWED_TOOLS` (`agent/src/chat2cart/swiggy/allowlist.py`) are used, and no order is started.

- Result: pass / fail: pass
- Notes: `SwiggyClient` rejects any tool outside the allowlist, tests check the call order, and no order was created in the app during the live runs. No live call trace was captured.

## Outcome

Choose one: continue / apply to the Builders Club / fall back to the personal-use path.

- Outcome: continue
- Reason: login was not blocked, tokens refresh, addresses, search and add-to-cart work on the real account and cart, and the cart reaches the phone app in about 30 seconds. No Builders Club application or fallback is needed. Cart behaviour questions (free items, a cart that once reverted) go to P15.

If M0-1 was blocked, use the application text in plan section 13 (`docs/plan.md`).
Any failure becomes a new issue.
