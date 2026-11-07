# Cart behaviour validation

Fill this in on the Mac with your own Swiggy account. Plan section 7.4 lists the tests and 7.5 the decision.
Never paste tokens, phone numbers or OTPs here. Do not check out or pay from the app while testing.

- Date: 2026-11-06
- Tester: Amit Bisht
- Commit SHA (`git rev-parse --short HEAD`): be4ee21
- Address ID (`DEFAULT_ADDRESS_ID` in `.env`): 348541496__ARuWZwRlf-Yci0ucxTuKhK

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

Starting cart (paste the output, with no personal details):

```json
{"items": [{"spinId": "WQUDSRI028", "skuId": "L04WSPHD6I", "itemName": "Maiva Life Almond Milk Vanilla Pack of 4", "quantity": 1}], "cartTotalAmount": "212"}
```

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

- Item A: Amul Taaza Tetra, 200 ml, Rs 17 (`31VQRTD5DH`, `8ZAP7YU7SJ`)
- Item B: Amul Lactose Free Milk, 250 ml, Rs 26 (`B2PVP4JKO7`, `FFKMZK5VS4`)

## CB-1 Write A, then write A and B

Steps: write `[A]`, read the cart, write `[A, B]`, read the cart.

Expected: the cart holds both A and B.

- Result: pass / fail: pass
- Observed: after `[A]` the cart held only A x 1 (total 89), and the earlier Maiva item was gone. After `[A, B]` it held A x 1 and B x 1 (total 115). `removedOutOfStockItems` and `reducedQuantityItems` were empty both times.

## CB-2 Write only B

Steps: write `[B]`, read the cart.

Expected: A disappears. This proves full replacement.

- Result: pass / fail: pass
- Observed: after writing `[B]` the cart held only B x 1 (total 98); A was gone. Writes replace the whole cart.

## CB-3 Hand-added item survives the merge

Steps: open the Swiggy app, add item C by hand, close the app. Read the cart. Then do a merge write: the cart from the read plus item B, as the agent would.

Expected: C is still in the cart after the merge.

- Result: pass / fail: pass
- Observed: first run (store later became unserviceable): after the popcorn was added by hand the cart showed only the popcorn, so B was gone; unexplained. A merge write then kept the popcorn (C x 1, A x 1). Clean re-run: server cart B x 1, the app showed B only, then onion 1 kg was added by hand in the app and the app showed B and onion. A read showed B x 1 and Onion x 1 (total 171). A merge write (that cart plus A) gave B, Onion and A, each x 1 (total 164). The hand-added onion survived our write.

## CB-4 Same item sent twice

Steps: write `[A x1]`, then write `[A x1]` again, read the cart.

Expected: the quantity of A is 1, not 2. (`chat2cart prototype` adds one to an existing line by design; this test is about `write_cart` itself.)

- Result: pass / fail: pass
- Observed: writing `[A x1]` twice in a row left A x 1 (total 99) both times. `write_cart` sets the quantity; it does not add to it.

## CB-5 Quantity above the limit

Steps: write item A with quantity 99, read the cart.

Expected: the write result lists A under `reducedQuantityItems`, with the requested and the allowed quantity.

- Result: pass / fail: pass for Swiggy, fail for our parser (see below)
- Observed: writing A x 99 capped the cart at A x 20 (total 353). Swiggy's `reducedQuantityItems` entry has `spinId`, `itemName`, `requestedQuantity: 99`, `cappedQuantity: 20` and `reason: "Only 20 unit(s) of this item can be added per order."`. It has no `skuId` and no `quantity`, so `write_cart` raised "answer was not in the expected format" even though the cart was updated. The `CartWriteResult` model in `swiggy/cart.py` needs a follow-up fix (out of scope here).

## CB-6 Read-back matches the phone app

Steps: after each of CB-1 to CB-5, compare `get_cart` output with the Swiggy app (open the app only for this comparison, and close it after).

Expected: the same items and quantities in both.

- Result: pass / fail: pass for the one clean comparison; unclear for the earlier case
- Observed: with the server cart at A x 1 (total 89), the app showed Amul Taaza Tetra only. Not compared after each of CB-1 to CB-5 (the app stays closed during writes). Earlier, after the hand-added popcorn in CB-3, the app showed only the popcorn while the server cart also held A after the merge write; it is unclear whether that was before or after the write.

## CB-7 Opening the app between two updates

Steps: write `[A]`. Open the Swiggy app, look at the cart, close it. Read the cart. Write `[A, B]`. Read the cart.

Expected: the earlier changes survive opening the app.

- Result: pass / fail: pass
- Observed: wrote `[A]`, opened the app (it showed A), closed it, then read the cart: A x 1 (total 89), unchanged. Writing `[A, B]` afterwards gave A x 1 and B x 1 (total 115). Merely opening the app did not revert anything.

## CB-8 Same product under two names

Steps: `chat2cart prototype "<name one>" --dry-run`, then `chat2cart prototype "<name two>" --dry-run` for the same product (for example "milk" and "toned milk").

Expected: both searches return the same spinId and skuId for it.

- Result: pass / fail: pass
- Observed: searching "milk" and "amul taaza tetra" both returned Amul Taaza Tetra, 200 ml, with spinId `31VQRTD5DH` and skuId `8ZAP7YU7SJ`.

## Restore your starting cart

Write the starting cart back with a full write. Done: yes / no: yes

Restored Maiva Life Almond Milk Vanilla Pack of 4 x 1 (total 212), matching the starting cart. An earlier attempt failed while Swiggy reported the store as unserviceable; the retry worked once the store was open again.

## Answers

- Does update_cart replace the whole cart? Yes. Writing `[B]` removed A (CB-2), and the first write removed the Maiva item that was already there (CB-1). A write sets quantities rather than adding to them (CB-4).
- Do hand-added items survive? Yes, if the write includes them: merge writes built from a fresh read kept the popcorn and the onion added by hand (CB-3, twice). One earlier add in the app showed the cart without B; the clean re-run did not repeat that, so it stays unexplained.
- Does opening the app revert changes? No: opening and viewing the cart left it unchanged (CB-7), and in the clean CB-3 re-run an add inside the app kept the existing item. The one earlier case where B vanished after an in-app add is unexplained.

## Decision (plan 7.5)

Choose one: keep read-merge-write (the default) / use the 7.5 alternative (send only new items, keep the read-back check).

- Decision: keep read-merge-write (the default).
- Reason: `update_cart` replaces the whole cart, so the agent must send the full list, existing lines included. Built from a fresh read, that kept a hand-added item, and opening the app did not revert anything. Read right before each write to shrink the window in which an add made inside the app could be overwritten. Findings for the design: Swiggy caps a line at 20 per order and reports it as `cappedQuantity` (not `quantity`, no `skuId`), which `CartWriteResult` cannot parse today; and Swiggy can refuse reads and writes with "address not serviceable" when the store is closed. The merge design does not change, so no P31 issue is needed; the parser fix is a separate issue against `swiggy/cart.py` (P12).

If the design changes, open an issue against P31.
