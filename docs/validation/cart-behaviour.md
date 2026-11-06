# Cart behaviour validation

Fill this in on the Mac with your own Swiggy account. Plan section 7.4 lists the tests and 7.5 the decision.
Never paste tokens, phone numbers or OTPs here. Do not check out or pay from the app while testing.

- Date: TODO
- Tester: TODO
- Commit SHA (`git rev-parse --short HEAD`): TODO
- Address ID (`DEFAULT_ADDRESS_ID` in `.env`): TODO

**Rule: keep the Swiggy app closed, except where a test says to open it.** Opening the app may change the cart.

## Before you start

Save your starting cart so you can restore it at the end. Read it with:

```bash
uv run --directory agent python -c "
import asyncio, httpx
from chat2cart.cli import build_swiggy_client
from chat2cart.swiggy.cart import read_cart
with httpx.Client(timeout=30) as http:
    cart = asyncio.run(read_cart(build_swiggy_client(http)))
print(cart.model_dump_json(indent=2, by_alias=True))
"
```

Starting cart (paste the output, with no personal details): TODO

To write a list, replace the `ITEMS` line with the lines you want, as `(spinId, skuId, quantity)`. Get the IDs from `chat2cart prototype "<item>" --dry-run` or from the read above. The write **replaces the entire cart** with exactly this list.

```bash
uv run --directory agent python -c "
import asyncio, httpx
from chat2cart.cli import build_swiggy_client
from chat2cart.config import ENV_FILE, load_settings
from chat2cart.swiggy.cart import CartItem, write_cart
ITEMS = [('SPIN_A', 'SKU_A', 1)]
address_id = load_settings(ENV_FILE).default_address_id
lines = [CartItem(spin_id=s, sku_id=k, name='', quantity=q) for s, k, q in ITEMS]
with httpx.Client(timeout=30) as http:
    result = asyncio.run(write_cart(build_swiggy_client(http), lines, address_id))
print(result.model_dump_json(indent=2, by_alias=True))
"
```

Pick two cheap in-stock items, **A** and **B**, and note their IDs:

- Item A: TODO
- Item B: TODO

## CB-1 Write A, then write A and B

Steps: write `[A]`, read the cart, write `[A, B]`, read the cart.

Expected: the cart holds both A and B.

- Result: pass / fail: TODO
- Observed: TODO

## CB-2 Write only B

Steps: write `[B]`, read the cart.

Expected: A disappears. This proves full replacement.

- Result: pass / fail: TODO
- Observed: TODO

## CB-3 Hand-added item survives the merge

Steps: open the Swiggy app, add item C by hand, close the app. Read the cart. Then do a merge write: the cart from the read plus item B, as the agent would.

Expected: C is still in the cart after the merge.

- Result: pass / fail: TODO
- Observed: TODO

## CB-4 Same item sent twice

Steps: write `[A x1]`, then write `[A x1]` again, read the cart.

Expected: the quantity of A is 1, not 2. (`chat2cart prototype` adds one to an existing line by design; this test is about `write_cart` itself.)

- Result: pass / fail: TODO
- Observed: TODO

## CB-5 Quantity above the limit

Steps: write item A with quantity 99, read the cart.

Expected: the write result lists A under `reducedQuantityItems`, with the requested and the allowed quantity.

- Result: pass / fail: TODO
- Observed: TODO

## CB-6 Read-back matches the phone app

Steps: after each of CB-1 to CB-5, compare `get_cart` output with the Swiggy app (open the app only for this comparison, and close it after).

Expected: the same items and quantities in both.

- Result: pass / fail: TODO
- Observed: TODO

## CB-7 Opening the app between two updates

Steps: write `[A]`. Open the Swiggy app, look at the cart, close it. Read the cart. Write `[A, B]`. Read the cart.

Expected: the earlier changes survive opening the app.

- Result: pass / fail: TODO
- Observed: TODO

## CB-8 Same product under two names

Steps: `chat2cart prototype "<name one>" --dry-run`, then `chat2cart prototype "<name two>" --dry-run` for the same product (for example "milk" and "toned milk").

Expected: both searches return the same spinId and skuId for it.

- Result: pass / fail: TODO
- Observed: TODO

## Restore your starting cart

Write the starting cart back with a full write. Done: yes / no: TODO

## Answers

- Does update_cart replace the whole cart? TODO
- Do hand-added items survive? TODO
- Does opening the app revert changes? TODO

## Decision (plan 7.5)

Choose one: keep read-merge-write (the default) / use the 7.5 alternative (send only new items, keep the read-back check).

- Decision: TODO
- Reason: TODO

If the design changes, open an issue against P31.
