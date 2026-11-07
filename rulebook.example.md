# Chat2Cart rule book

Copy this file to `rulebook.md` (the path in `CHAT2CART_RULEBOOK_PATH`) and edit it. The app reads
it again whenever it changes, so there is no need to restart.

Each item has a `## Item name` heading followed by `- key: value` lines. Every key is optional.
Lines that are not `##` headings or `- key: value` bullets, like this paragraph and the table, are
notes and are ignored. A bullet before the first heading is an error.

Keys:

| Key | Meaning |
| --- | --- |
| `aliases` | Other names for the item, comma-separated. Hindi and Hinglish names go here (`ande`, `doodh`). A message that says "ande" uses the Eggs entry. |
| `brand` | Preferred brands, comma-separated, in order of preference. |
| `default_quantity` | How many packs to order when the message gives no quantity (a whole number). With a `size`, it is a number of packs of that size: `size: 30 pcs` and `default_quantity: 1` is one tray of 30. |
| `min_quantity` | The least number of packs to order when the default is used (a whole number). |
| `size` | The pack size to look for, like `500 g`, `2 kg`, `1 l` or `30 pcs`. |
| `substitute` | What to do when the item is out of stock: `never` (the default), `same_brand` (another size or pack of the same brand) or `any`. |

A mistake in the file is reported with its line number and the app will not start until it is fixed.

## Eggs

- aliases: egg, ande, anda
- brand: Farm Fresh, Country Eggs
- default_quantity: 1
- min_quantity: 1
- size: 30 pcs
- substitute: same_brand

## Milk

- aliases: doodh
- brand: Amul
- default_quantity: 2
- size: 500 ml
- substitute: never

## Atta

- aliases: wheat flour, gehu ka atta
- brand: Aashirvaad
- default_quantity: 1
- size: 5 kg
- substitute: same_brand

## Onions

- aliases: pyaaz, pyaz
- default_quantity: 2
- size: 1 kg
- substitute: any
