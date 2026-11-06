# Milestone 0 validation

Fill this in on the Mac with your own Swiggy account. Plan section 1.4 explains why each check matters.
Never paste tokens, phone numbers or OTPs here. Do not check out or pay from the app while testing.

- Date: TODO
- Tester: TODO
- Commit SHA (`git rev-parse --short HEAD`): TODO
- Baileys version (`listener/package.json`): TODO
- Python version (`uv run --directory agent python --version`): TODO

Prerequisite: `make install`, then store the LLM key if the commands ask for it.

## M0-1 Login from localhost

Command: `chat2cart login swiggy`

Expected: the browser opens Swiggy's page, you enter the phone number and OTP there, and the command ends with a success message.

- Was login blocked by a redirect allowlist? yes / no: TODO
- Result: pass / fail: TODO
- Notes: TODO

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

- Result: pass / fail: TODO
- Notes: TODO

## M0-3 Address listing

Command: `chat2cart swiggy address`

Expected: your saved addresses are listed, you pick one, and `.env` gets the default address ID.

- Result: pass / fail: TODO
- Notes: TODO

## M0-4 Product search

Command: `chat2cart prototype "<item>" --dry-run`

Expected: variants are listed with name, pack size, price and stock, and the cart is not changed.

- Item searched: TODO
- Result: pass / fail: TODO
- Notes: TODO

## M0-5 Add to cart

Command: `chat2cart prototype "<item>"`

Expected: choose a variant, then the cart is printed with that item in it.

- Result: pass / fail: TODO
- Notes: TODO

## M0-6 Cart appears in the Swiggy phone app

Open the Swiggy app on your phone after M0-5.

- Appeared? yes / no: TODO
- Minutes taken: TODO
- Result: pass / fail: TODO
- Notes: TODO

## M0-7 Live cart or staging data

Does localhost development act on your real account and real cart, or on staging data?

- Real cart / staging: TODO
- Result: pass / fail: TODO
- Notes: TODO

## Outcome

Choose one: continue / apply to the Builders Club / fall back to the personal-use path.

- Outcome: TODO
- Reason: TODO

If M0-1 was blocked, use the application text in plan section 13 (`docs/plan.md`).
Any failure becomes a new issue.
