# Chat2Cart - Implementation Plan

Last reviewed on 3 November 2026 against Swiggy's Builders Club documentation, the Swiggy MCP GitHub README, Baileys release notes and WhatsApp's linked-device rules. Anything still unconfirmed is marked **To test** or **Open**. Sources are listed in section 18.

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [WhatsApp Integration with Baileys](#3-whatsapp-integration-with-baileys)
4. [Swiggy Instamart MCP Integration](#4-swiggy-instamart-mcp-integration)
5. [Strict Rule: No Automatic Orders](#5-strict-rule-no-automatic-orders)
6. [Ordering Window and Scheduling](#6-ordering-window-and-scheduling)
7. [Validation: Cart Behaviour Across Multiple Messages](#7-validation-cart-behaviour-across-multiple-messages)
8. [Message Handling and Rule Book](#8-message-handling-and-rule-book)
9. [Notifications and Failure Handling](#9-notifications-and-failure-handling)
10. [Hosting and Deployment](#10-hosting-and-deployment)
11. [Setup and Onboarding](#11-setup-and-onboarding)
12. [Development Workflow and Testing (Proposed)](#12-development-workflow-and-testing-proposed)
13. [Swiggy Builders Club Application Text](#13-swiggy-builders-club-application-text)
14. [Risks and Constraints](#14-risks-and-constraints)
15. [Alternatives Considered](#15-alternatives-considered)
16. [Backlog](#16-backlog)
17. [Next Steps](#17-next-steps)
18. [Sources](#18-sources)
19. [Revision History](#19-revision-history)

## 1. Overview

Chat2Cart turns a WhatsApp message from one specific sender into a ready Swiggy Instamart cart, with no human interaction up to the cart stage. The user then reviews the cart and pays manually in the Swiggy app.

### 1.1 Purpose

- Read incoming WhatsApp messages from one specific sender only, using a personal WhatsApp number.
- No business account or business number is available, so everything must work with the personal number.
- Extract the list of items to order from each message. Messages are expected to contain full product names. Anything unclear is handled by the rule book (section 8).

### 1.2 End Goal

- Build the Instamart cart automatically from the message text.
- Stop at the cart. The agent never places the order or starts a payment (section 5).
- Proposed: tell the user what was added and what was skipped, so the cart can be checked before paying (section 9).

### 1.3 Name

- The application is called **Chat2Cart**: an agent that turns WhatsApp messages into a ready Instamart cart.

### 1.4 Milestone 0: Swiggy Prototype and Login Validation

This is the first implementation step. Nothing else is built until a small prototype proves that the Swiggy Instamart MCP server works from localhost with our own account.

**Why a prototype first**

- Swiggy's developer quickstart says development on http://localhost needs no approval and is free. Approval is only needed for production endpoints.
- Apps register themselves automatically through dynamic client registration, so there is no client ID to apply for.
- Swiggy's GitHub README already lists http://localhost/callback and http://127.0.0.1/callback as allowed OAuth redirect addresses.
- Redirect addresses are matched exactly, so a custom port may be rejected. The CLI may need to use http://localhost/callback on the default port. **To test.**
- The quickstart also mentions a staging endpoint for development. We must confirm the prototype acts on the real account and real cart. **To test.**
- Some developers reported a not-whitelisted gate at sign-in for their own redirect addresses, so the login must be tested for real.

**What the prototype must prove**

1. The Swiggy OAuth login completes from a local command line tool, with the phone number and OTP entered on Swiggy's own page.
2. The access token can be refreshed without logging in again.
3. The saved delivery addresses can be read, and one can be chosen as the default.
4. A product can be searched by name and returns usable variant IDs (spinId and skuId).
5. An item can be added to the cart, and the cart can be read back.
6. The cart built through MCP appears in the Swiggy phone app.
7. The prototype calls only allowlisted tools, never checkout, payment or confirm order (section 4.3).

**What each outcome means**

- **Everything works:** no application is needed. Continue with the cart validation in section 7.
- **Login is blocked, or only staging data is available:** apply to the Swiggy Builders Club using the text in section 13, with the GitHub link and a demo.
- **Swiggy declines or the cart cannot be built:** fall back to Swiggy's personal-use path, which connects the Instamart MCP server directly inside an AI assistant such as Claude, and revisit the design.

**Open questions for Swiggy, only if the login is blocked**

- Does a personal, single-user, local-only app qualify?
- Is a localhost redirect with a custom port accepted, or must it match http://localhost/callback exactly?

## 2. Architecture

The system runs end to end on the user's own Mac. A Node.js process listens to WhatsApp, and an agent built with LangChain or LangGraph talks to the Swiggy Instamart MCP server.

### 2.1 Pipeline

1. **Receive:** Baileys delivers each new WhatsApp message to the Node app.
2. **Filter:** keep only text messages in the direct chat with the chosen sender. Ignore the user's own messages, groups, status updates and repeats (section 3.4).
3. **Classify:** decide whether the message is an order request or a general message. General messages stop here (section 8.1).
4. **Schedule:** between 7:00 and 22:30 India Standard Time the request continues. Outside that window it is queued until 7:00 (section 6).
5. **Extract:** turn the message text into a structured list of items and quantities.
6. **Resolve:** apply the rule book, search each item on Instamart, and pick one product variant per item. Unclear items are skipped (section 8).
7. **Build cart:** read the current cart, merge the new items, remove duplicates, write the cart back, and read it again to verify (section 7).
8. **Report:** proposed summary of what was added, what was skipped and why, and the cart total (section 9).

### 2.2 Technology Choices

- **WhatsApp access:** Baileys, a Node.js library, linked to the personal number. Requires Node.js 20 or later.
- **Agent framework:** LangGraph for the order pipeline, with LangChain for the language model calls. Swiggy is called through the official MCP Python SDK from code, never handed to the model as tools.
- **Languages (decided 3 Nov 2026):** the WhatsApp listener is TypeScript on Node.js 20, in `listener/`. The agent and everything else is Python 3.12, in `agent/`. The listener hands each accepted message to the agent through the shared SQLite database.
- **Language model:** used only for intent classification, item extraction and product matching. Provider and model are not chosen yet. **Open.**
- **Grocery backend:** the official Swiggy Instamart MCP server at mcp.swiggy.com/im.
- **Storage:** a local SQLite file shared by both processes, for incoming messages, WhatsApp connection state, the request queue and run history.
- **Rule book:** a markdown file holding brand, size and quantity preferences (section 8.2).
- **Safety layer:** plain code, not the language model, enforces the tool allowlist (section 4.3).

## 3. WhatsApp Integration with Baileys

Baileys is the library we use to read WhatsApp messages from the personal number.

### 3.1 Why Baileys

- **Works with a personal number.** The official WhatsApp Business Cloud API needs a business number and cannot see personal chats, so it is ruled out. Baileys links to a personal account as an extra device, using a QR code or pairing code.
- **Actively maintained.** The project lives under the WhiskeySockets organization on GitHub and is community maintained. Version 7 is still a release candidate, with 7.0.0-rc14 the latest, and 6.7.x is the stable line.
- **Push-based.** The app is notified the moment a message arrives, which suits always-on automation. An MCP server is pull-based, which suits ad-hoc questions instead.
- **No per-message cost.** It runs locally with no usage fees.

### 3.2 What We Use It For

- Listening for incoming messages on the personal WhatsApp number.
- Filtering to messages from one specific sender only.
- Passing order requests on to the agent.
- Possibly sending the cart summary, depending on the decision in section 9.1.

### 3.3 How It Runs

Baileys links to the personal number as an extra device, using a QR code or an 8-character pairing code. It then pushes each incoming message to our Node app. See section 10 for where it runs.

The project pins one exact Baileys version. Version 7 handles WhatsApp's newer contact IDs better but is still a release candidate. **Open:** start on the 7.0.0 release candidate or on stable 6.7.x.

### 3.4 Message Filtering Rules

- **Sender identity:** WhatsApp increasingly identifies contacts by a privacy ID ending in @lid, instead of the phone number. Filtering by phone number alone can silently miss messages. The filter must accept both the sender's phone-number ID and their @lid ID, using the mapping Baileys provides. **To test** with the real sender.
- **Direct chat only:** only messages in the one-to-one chat with the sender count. Group messages, status updates and broadcasts are ignored, even from the same person.
- **Ignore own messages:** messages the user sends in that chat are marked as from me and ignored.
- **Text only in version 1:** voice notes, images, documents and stickers are ignored and logged (backlog, section 16).
- **Process once:** each message ID is stored after processing, so a message redelivered after a reconnect is not processed twice.
- **Edited or deleted messages:** ignored in version 1 (backlog, section 16).

### 3.5 Session Limits

- WhatsApp logs out all linked devices if the main phone is not used for more than 14 days.
- A linked device that is inactive for 30 days is also disconnected.
- After a logout, the CLI WhatsApp login must be run again (section 11.2), and the user is alerted (section 9.2).

## 4. Swiggy Instamart MCP Integration

Swiggy provides an official Instamart MCP server that our agent connects to. The facts below were rechecked against Swiggy's Builders Club documentation on 3 November 2026.

### 4.1 Capabilities and Access

- **Official server.** Swiggy launched MCP servers for Food, Instamart and Dineout on 27 January 2026. The Instamart server now offers 20 tools for search, cart, payment, ordering and tracking.
- **Own app is allowed for development.** The Builders Club, launched in April 2026, opens the MCP servers to developers. Building on localhost needs no approval. Applying is only needed to go live in production (section 1.4).
- **Payments now include UPI.** Since July 2026, checkout supports UPI as well as cash on delivery, through a set of payment tools. This does not change our rule: the agent never checks out or pays (section 5).
- **Cart sync caveat.** Developers reported that the MCP cart and the phone app cart sometimes did not match (issue 131), and that MCP cart changes could disappear after the Swiggy app was opened (issue 141). **To test** in section 7.
- **Keep the Swiggy app closed.** Swiggy's README advises not opening the app while MCP is in use, to avoid session conflicts. Open it only after the cart summary arrives.
- **Mitigation.** After building the cart, the agent reads it back with get\_cart and reports it, so the user can compare it with the phone app before paying.

### 4.2 Order History and Preferences

- **get\_orders** returns orders from the last 15 days only, 10 by default and up to about 20. It includes items, status, bill details and, when available, the store name.
- **get\_order\_details** returns full details for one order.
- **your\_go\_to\_items** returns frequently or recently ordered items for the chosen delivery address. It can help match the user's usual brand or pack size.
- Some users reported get\_orders returning stale or missing recent orders (issue 36). **To test.**
- The earlier open question about which store an order came from is partly answered: get\_orders can include a store name. **To test** whether it is filled in for our orders.

### 4.3 Tool Allowlist

Plain code checks every tool call against this list before sending it. Any tool not marked Allowed is blocked, including tools Swiggy adds later.

| Tool | Status | Reason |
| --- | --- | --- |
| get\_addresses | Allowed | Read saved addresses and pick the default |
| search\_products | Allowed | Find each item and its variants |
| your\_go\_to\_items | Allowed | Match the user's usual products |
| get\_cart | Allowed | Read the cart before and after changes |
| update\_cart | Allowed | Write the merged cart |
| get\_orders | Allowed | Read recent order history |
| get\_order\_details | Allowed | Read details of one past order |
| checkout | Blocked | Places the order |
| get\_payment\_options | Blocked | Starts the payment flow |
| check\_payment\_status | Blocked | Part of the payment flow |
| confirm\_order | Blocked | Completes a paid order |
| clear\_cart | Blocked | Would wipe items the user added |
| apply\_coupon, list\_coupons | Blocked | Coupons are the user's choice at payment |
| create\_address, delete\_address, recommend\_address | Blocked | Addresses are managed in the Swiggy app |
| track\_order, get\_delivery\_status, report\_error | Blocked | Not needed in version 1 |

### 4.4 Limits, Errors and Retries

- **Minimum order:** Instamart has a ₹99 minimum order. A smaller cart is still built, and the summary flags it.
- **Serviceability:** an address outside the service area returns an error. The run stops and the user is told.
- **Out of stock or capped quantity:** update\_cart can drop out-of-stock items or reduce a quantity, and it reports both. These are reported as skipped or reduced, not retried.
- **Rate limits:** Swiggy has no metered quota but returns HTTP 429 with a Retry-After header when busy. The app waits as told.
- **Retries:** timeouts and server errors are retried with exponential backoff, from 0.5 to 8 seconds, at most 5 times. Business errors, such as out of stock, are not retried.
- **Tokens:** the access token lasts 5 days and can be refreshed. Each refresh lasts 30 days, and the session ends after 30 days without use (section 11.3).

### 4.5 Note on Conflicting Sources

Swiggy's GitHub README still says third-party app development is not permitted and that ordering is cash on delivery only. The newer Builders Club documentation says the opposite on both points. This plan follows the Builders Club documentation, and Milestone 0 confirms it in practice.

## 5. Strict Rule: No Automatic Orders

### 5.1 The Rule

The agent must never place an order or start a payment, whether cash on delivery or UPI. It only builds the cart. The user reviews the cart and pays manually in the Swiggy app.

### 5.2 Why It Matters

- Checkout can now take UPI payments as well as cash on delivery, so one wrong call could start a real payment.
- Swiggy's README warns that orders placed through MCP cannot be cancelled.
- Swiggy's docs say checkout is not safe to repeat: retrying after an error can create a second order.

### 5.3 How It Is Enforced

- The tool allowlist in section 4.3 is checked in plain code before every call. The agent's instructions alone are not trusted.
- Unknown or new tools are blocked by default.
- An automated test fails the build if checkout, any payment tool or confirm order can be called (section 12.3).
- This rule applies at all times, including requests held overnight and released at 7:00.

## 6. Ordering Window and Scheduling

### 6.1 Window

Orders are only processed between 7:00 and 22:30 India Standard Time. Messages that arrive outside this window are held and processed at 7:00 the next morning.

### 6.2 Scheduling and Batching Rules

- **Time zone:** the app always uses India Standard Time (Asia/Kolkata), not the Mac's system time zone.
- **Inside the window:** the request goes straight to the agent.
- **Outside the window:** the request is stored in the SQLite queue, so it survives a restart. A scheduler releases the queue at 7:00.
- **Batching:** all requests queued overnight are merged into one batch and built as a single cart.
- **No repeated items:** item names are normalised (lowercase, trimmed) and combined before the agent runs. After product search, items are deduplicated again by the Instamart variant ID.
- **One cart job at a time:** cart updates run one after another through a single worker, so two jobs never read and write the cart at the same time.
- **Missed release:** if the Mac was asleep or the app was down at 7:00, the queue is released as soon as the app is running again inside the window.

### 6.3 Open Decisions

- Settled: duplicate items are removed, and a quantity in the message wins over the rule book default. See section 8.4.
- Open: during the day, whether each message updates the cart immediately or the app waits a few minutes to collect several messages first.
- **To test:** whether Instamart serves the delivery address across the whole 7:00 to 22:30 window.

## 7. Validation: Cart Behaviour Across Multiple Messages

### 7.1 Purpose

We must confirm what the Instamart MCP server does when a new request arrives while an earlier cart is still unpaid. The design below is the default, but it stays a validation item until the tests pass.

### 7.2 What We Know So Far

- Swiggy's tool reference now states that update\_cart replaces the entire cart. This settles the earlier conflict between developer reports.
- update\_cart takes variant IDs (spinId and skuId) from search\_products, a quantity per item, and the delivery address ID.
- It reports items it removed as out of stock and items whose quantity it reduced.
- The cart is stored on Swiggy's side and does not reset by itself.
- Developers reported that MCP cart changes can disappear after the Swiggy app is opened (issue 141). Not yet verified by us.

### 7.3 Default Design

Because update\_cart replaces the whole cart, the agent must never send only the new items. Every update follows these steps:

1. Read the current cart with get\_cart.
2. Add the new items to the existing ones, keeping every item already in the cart, including items the user added by hand.
3. Remove duplicates by variant ID.
4. Write the full merged list with update\_cart.
5. Read the cart again and compare it with what was intended. Report any difference.

### 7.4 Tests to Run

1. Build a cart with item A, then update with A and B. Check the cart holds both.
2. Update with only item B. Confirm A disappears, which proves full replacement.
3. Add an item by hand in the Swiggy app, close the app, then run the agent. Confirm the hand-added item survives the merge.
4. Send the same item twice. Check the quantity is not doubled.
5. Request a quantity above Swiggy's limit. Check the reduced-quantity report.
6. Read the cart after each step and compare it with the phone app.
7. Open the Swiggy app between two updates and check whether earlier changes survive.
8. Search the same product under two different names and check whether both resolve to the same variant ID.

### 7.5 Decision After Testing

If the tests confirm full replacement, keep the default design. If update\_cart turns out to merge, the agent can send only new items, but the read-back check stays.

## 8. Message Handling and Rule Book

This section covers how messages are classified, how ambiguity is handled, and how quantities and variants are set.

### 8.1 Intent Classification

- Every incoming message from the chosen sender is first classified: is it a request to order items, or a general message?
- Order requests continue to item extraction and the agent.
- General messages are ignored. Nothing is touched on Swiggy.
- Mixed messages, such as an order plus an unrelated question, should have the items extracted and the rest ignored. This is a suggestion, not yet confirmed.
- Open: when the classifier is unsure, whether the app stays silent or asks the user whether to treat the message as an order.

### 8.2 Rule Book

A markdown file, associated with the LangChain application, holds the user's ordering rules. It can be edited without changing code.

- Preferred brands for each item.
- Default and minimum quantities. For example, eggs are usually ordered as 30.
- Default sizes and pack types, so the right product variant can be chosen.
- Substitution rules, for example never substitute, or only substitute within the same brand.

### 8.3 Ambiguity and Missing Items

- If the rule book gives no clear answer for an item, the agent makes no decision and does not add the item to the cart.
- The default is: when in doubt, leave it out.
- Proposed: skipped items are listed in the cart summary with the reason, so they can be added by hand (section 9.1).

### 8.4 Quantities and Duplicates

- Duplicate items are removed. The same product never appears twice in the cart.
- A quantity stated in the message wins. The rule book default applies only when the message gives no quantity.
- Suggested, not yet confirmed: if the same item appears twice in a batch without numbers, it counts as one line with a single quantity, not the default added twice.
- Swiggy may cap the quantity of an item. A capped quantity is reported, not retried.

### 8.5 Product Variants and Units

- A search returns products with variants, such as different pack sizes. The agent must pick exactly one variant per item.
- The rule book's default size decides the variant. If several variants fit and the rule book does not decide, the item is skipped.
- Quantities given as weight or volume, such as 2 kg onions, are converted to a pack count only when the conversion is exact. Otherwise the item is skipped.

### 8.6 Message Text Is Untrusted

- The message text goes to a language model, so it could contain instructions that try to change the agent's behaviour.
- The model only returns a structured item list. Which Swiggy tools are called, and in what order, is decided by code.
- The allowlist in section 4.3 stays in force whatever the message says.

## 9. Notifications and Failure Handling

### 9.1 Cart Summary Channel

The proposed summary after each run lists items added, items skipped with the reason, reduced quantities, and the cart total. How it is delivered is **Open**, because sending WhatsApp messages conflicts with the read-only approach in section 14.1.

| Option | Benefit | Drawback |
| --- | --- | --- |
| WhatsApp message to the user's own Message yourself chat | Arrives where the request came from | Automated sending adds some ban risk, even at low volume |
| Mac notification | No WhatsApp risk, simple | Only seen when at the Mac |
| Email or a separate chat app such as Telegram | Reaches the phone with no WhatsApp risk | One more account and setup step |
| Local log only | Simplest | The user must check the log |

An alert about a WhatsApp logout cannot be sent through WhatsApp, so at least one non-WhatsApp channel is needed for alerts.

### 9.2 Failure Scenarios

| Situation | What the app does |
| --- | --- |
| Swiggy access token expired | Refresh it automatically and continue |
| Swiggy refresh fails or session ended | Keep the request queued and alert the user to run the Swiggy login again |
| WhatsApp logged out | Alert the user through a non-WhatsApp channel to run the WhatsApp login again |
| Address not serviceable | Stop the run, keep the request queued, and alert the user |
| Item out of stock or not found | Skip it and list it in the summary |
| Swiggy timeout or server error | Retry with backoff up to 5 times, then keep the request queued and alert the user |
| Language model unavailable | Keep the request queued and retry later |
| Mac asleep or app stopped | Messages sent meanwhile may be missed (backlog, section 16). Queued requests resume on restart |
| Cart read-back does not match | Report the difference in the summary |

### 9.3 Activity Log

- Every message, decision, tool call and result is written to a local log with a timestamp.
- Tokens, OTPs and session keys are never written to the log.
- The log shows what the agent did for each request and helps debug failed runs.

## 10. Hosting and Deployment

### 10.1 Current Decision

- The application runs on the user's own Mac for now. Cloud deployment is skipped and can be revisited later.
- The Mac stays on 24/7. A process manager such as pm2 restarts the app after a crash or reboot, and the Mac's sleep settings are turned off.
- The main phone must use WhatsApp at least once every 14 days, or the linked session is logged out (section 3.5).

### 10.2 Cloud Option for Later

- AWS Lightsail costs 5 dollars a month for its smallest plan with a public IPv4 address. Its 3.50 dollar plan is IPv6-only, which may not reach every service we need.
- Hetzner raised its shared plan prices in August 2026. A third-party comparison puts its 2 vCPU, 4 GB plan at €5.99 a month. Recheck before choosing.
- DigitalOcean and Linode start at around 4 to 6 dollars a month. Not rechecked in this review.
- The smallest plans have only 512 MB of memory, which may be tight for Node.js plus an agent. Plan for 1 to 2 GB.
- Language model usage is billed separately and depends on message volume.
- A data centre IP address may look more suspicious to WhatsApp than a home connection, which slightly raises the ban risk.

## 11. Setup and Onboarding

This section is the basis for the README, so someone can run Chat2Cart on their own machine. Setup is done through a command line tool (CLI), not a web interface.

### 11.1 Why a CLI

- Neither login needs the user to type a password or OTP into our app. Both happen on the official WhatsApp and Swiggy screens.
- A CLI is the least work for a single-user local tool.
- A web interface would need its own local server to secure. It can be added later on top of the CLI if a friendlier setup is wanted.

### 11.2 WhatsApp Login

Baileys links to the personal number as an extra device. There is no password or OTP. The user picks one of two ways:

1. **QR code:** the CLI shows a QR code in the terminal. On the phone, open WhatsApp, go to Linked Devices, choose Link a Device, and scan it.
2. **Pairing code:** the user enters their phone number in the CLI, with the country code and no plus sign. The CLI shows an 8-character code. On the phone, open Linked Devices, choose Link a Device, then Link with phone number instead, and type the code.

After linking, the session is saved locally, so the login is needed only once. If the session expires or is logged out from the phone, the CLI login is run again (section 3.5).

### 11.3 Swiggy Instamart Login

Swiggy uses OAuth 2.1 with PKCE, so the user's credentials are never typed into our app.

1. The app registers itself with Swiggy automatically through dynamic client registration. No client ID or secret is needed.
2. The CLI opens a Swiggy login link in the browser.
3. The user enters their phone number and the OTP on Swiggy's own page.
4. Swiggy redirects back to http://localhost/callback, and the app exchanges the code for an access token and a refresh token.
5. The CLI lists the saved delivery addresses, and the user picks the default address for orders.

Token rules:

- The access token lasts 5 days. The app refreshes it automatically before it expires.
- Each refresh returns a new refresh token, valid for 30 days. Only the latest one is kept.
- The session ends after 30 days without use. The CLI Swiggy login is then run again.
- Tokens are stored in the macOS Keychain, not in plain files.

Development on localhost needs no approval from Swiggy (section 1.4). Approval is only needed to move to production endpoints.

### 11.4 Configuration

- **Environment file:** holds only non-secret settings, such as the allowed sender's phone number, the ordering window, the time zone and the default address ID.
- **Secrets:** the Swiggy tokens and the language model API key are stored in the macOS Keychain, never in the environment file or the repository.
- **Local session folder:** holds the WhatsApp session. It must be excluded from GitHub through the ignore file.
- **Rule book file:** the markdown rule book from section 8.2.
- **Example files:** the repository includes an example environment file and an example rule book with placeholder values.

### 11.5 Setup Steps for the README

1. Install Node.js 20 or later, and clone the repository.
2. Install the dependencies.
3. Copy the example environment file and fill in the allowed sender's number and the ordering window.
4. Copy the example rule book and add brand, size and quantity preferences.
5. Add the language model API key to the Keychain through the CLI.
6. Run the CLI WhatsApp login and link the phone.
7. Run the CLI Swiggy login, approve it in the browser, and choose the default address.
8. Start the application with the process manager. Keep the Swiggy app closed while it runs.

### 11.6 Security Notes

- Never commit the session folder, tokens, API keys or the environment file.
- Anyone with the session folder can read the linked WhatsApp account, so it should be kept private on the machine.
- The linked device can be removed at any time from the phone under Linked Devices.
- The CLI should offer a logout command that ends the Swiggy session through Swiggy's logout endpoint.

## 12. Development Workflow and Testing (Proposed)

The goal is for development to run automatically on a GitHub repository: user stories sit on a prioritised board, and Claude implements them one at a time. This section records the proposal. Nothing here is decided yet.

### 12.1 Story Board

- User stories are GitHub Issues in the project repository, ordered on a GitHub Projects board by priority and sequence.
- Each story has acceptance criteria and gets a ready label once it is fully written.
- Stories are written from this document, starting with Milestone 0.

### 12.2 Automated Implementation

- The official Claude Code GitHub Action runs Claude inside GitHub Actions. It can turn an issue into a branch, code changes and a pull request.
- Given a prompt, it can run on any GitHub event, such as a label or a schedule, without an @claude mention.
- Setup: run /install-github-app from Claude Code, or install the Claude GitHub App and add a secret by hand. The secret is either a Claude API key or a Claude subscription token.
- A CLAUDE.md file in the repository holds the project rules, including the strict rule in section 5.
- Picking the next issue in board order is not built in. It needs a prompt or skill that reads the board.
- Proposed flow per story: pick the next ready issue, create a branch, implement, run the tests, open a pull request, merge when checks pass, then move to the next story.
- CI must run on Claude's pull requests. GitHub does not trigger workflows for commits pushed with the default token, so the action should push as the Claude GitHub App.
- Costs: GitHub Actions minutes, plus API usage or the Claude subscription.
- **Open:** whether merges happen automatically or after the user's review. Changes to the tool allowlist should always get human review.

### 12.3 Validation at Each Step

- **Automated tests in CI:** unit tests with a mocked Swiggy MCP server and sample WhatsApp messages. CI cannot log in to WhatsApp or Swiggy, because both need a phone.
- **Allowlist test:** a required check that fails if any blocked tool can be called.
- **Dry-run mode:** runs the full pipeline on the Mac but only searches, without calling update\_cart.
- **End-to-end checks on the Mac:** real logins and real carts are tested on the Mac after each merge that touches WhatsApp or Swiggy code.

## 13. Swiggy Builders Club Application Text

This is ready-to-paste text for the Builders Club application at mcp.swiggy.com/builders/access. It is only needed if Milestone 0 shows that local development is blocked, or if the app later moves to production. Use the developer track, which is for solo developers, indie hackers and side projects. Swiggy's quickstart says the form asks for the integration name and organization, OAuth redirect URIs, the servers to be called, expected volume and use case, and a demo video link. Replace every item in square brackets before submitting.

### 13.1 Project Name and One-Line Summary

**Chat2Cart.** A personal assistant that turns a WhatsApp message into a ready Swiggy Instamart cart, which the user then reviews and pays for manually in the Swiggy app.

### 13.2 Use Case Description

Chat2Cart is a single-user personal automation. When one trusted contact sends me a WhatsApp message listing grocery items, the app extracts the product names, searches for each one on Instamart using the official MCP server, and builds a cart on my own account. It then reads the cart back and sends me a summary so I can check it.

The app never places an order. Checkout and payment tools are blocked in code through an allowlist, and I review the cart and pay myself in the Swiggy app. Orders requested outside 7:00 to 22:30 India Standard Time are held and the cart is built the next morning.

### 13.3 Who Will Use It

- One user: myself, on my own Swiggy account.
- The app is not offered to the public and does not collect other people's Swiggy accounts.
- &#91;If the code will be published on GitHub for others to run themselves, add: Others can run their own copy locally with their own account. No central service holds anyone's credentials.\]

### 13.4 Swiggy Tools Needed

Instamart MCP server only:

- get\_addresses, to use my saved delivery address.
- search\_products, to find each item by name.
- get\_cart and update\_cart, to build and verify the cart.
- get\_orders, get\_order\_details and your\_go\_to\_items, to match my usual products and brands.

The app will not call checkout, get\_payment\_options, check\_payment\_status, confirm\_order or clear\_cart.

### 13.5 Security and Data Handling

- Sign-in uses Swiggy's own OAuth login with PKCE. My phone number and OTP are entered only on Swiggy's page, never in the app.
- Tokens are stored in the macOS Keychain on my machine, refreshed as documented, never committed to source control, and not shared.
- The app runs on my own computer. It has no public web server and no central database.
- Request volume is very low: a few searches and cart updates per message, well under \[100\] requests a day.
- No scraping, reverse engineering or shared credentials.

### 13.6 Technical Stack

Node.js for receiving messages, a LangChain or LangGraph agent for orchestration, the official Swiggy Instamart MCP server over OAuth, and a local SQLite file for queuing messages received outside the ordering window.

### 13.7 OAuth Redirect URL

http://localhost/callback, which Swiggy's GitHub README already lists as allowed. \[If a port number is needed, give the exact address, for example http://localhost:PORT/callback.\]

### 13.8 Applicant Details

- Name: Amit Bisht
- Email: \[your email\]
- GitHub or website: \[repository link, if any\]
- Track: Developer

### 13.9 Demo

&#91;A short screen recording showing a WhatsApp message turning into an Instamart cart, ending at the cart without placing an order. Record this once the prototype works. Swiggy says a demo video speeds up review.\]

### 13.10 Questions to Ask Swiggy

- Does a personal, single-user, local-only app qualify for approval?
- Does localhost development act on the live account cart, or on staging data?

## 14. Risks and Constraints

### 14.1 WhatsApp Risks

- Baileys is unofficial and goes against WhatsApp's terms of service, so the number could be banned.
- To keep risk low, the app sends no automated replies and no bulk messages. A cart summary sent through WhatsApp would be the only exception, and that is still an open decision (section 9.1).
- Sender filtering can miss messages because of WhatsApp's @lid contact IDs (section 3.4).
- The linked session is logged out if the main phone is not used for 14 days (section 3.5).
- Baileys version 7 is still a release candidate, so updates may break things. The version is pinned.

### 14.2 Swiggy Risks

- The MCP cart may not match the phone app cart, or may revert after the app is opened (section 7).
- Swiggy's README and its Builders Club documentation disagree on access and payments (section 4.5). Swiggy could tighten access later.
- update\_cart replaces the whole cart, so a bug in the merge step could delete items the user added.
- A checkout call would place an order that cannot be cancelled through MCP. The allowlist prevents this (section 5).

### 14.3 Privacy and AI Risks

- Message text from the sender is sent to the language model provider.
- Message text could try to steer the agent. Structured output and the allowlist limit the damage (section 8.6).

## 15. Alternatives Considered

- **WhatsApp Business Cloud API:** official and stable, but needs a business number and does not cover personal chats.
- **whatsapp-web.js:** a similar unofficial approach using a hidden browser session, so heavier than Baileys.
- **lharries whatsapp-mcp:** popular, with about 6,700 stars, but built on the Go library whatsmeow and with about 165 open pull requests waiting. Maintained forks exist, such as verygoodplugins and whatsapp-mcp-extended. It could be added later if we want Claude to analyse stored messages.
- **Swiggy personal-use path:** connect the Instamart MCP server directly inside an AI assistant such as Claude. No approval is needed, but nothing is automated. This is the fallback if Milestone 0 fails.

## 16. Backlog

Items deliberately postponed. They are not part of the first version.

- **Offline and missed messages:** what happens when the Mac is off or the app crashes while messages arrive. Baileys may fetch some missed messages after reconnecting, but not reliably. Possible approach: send a notice when the app comes back online so missed requests can be resent.
- **Voice notes and images:** read orders sent as voice notes or as photos of a list.
- **Edited and deleted messages:** decide whether an edit updates a request and whether a deletion cancels it.
- **Web setup page:** a small local web interface on top of the CLI.
- **Cloud deployment:** move from the Mac to a small cloud server (section 10.2).

Moved out of the backlog: a cart that already holds unrelated items is now handled by the merge design in section 7.3, because update\_cart replaces the whole cart.

## 17. Next Steps

1. **Milestone 0, do this first:** build a small prototype that logs in to the Swiggy Instamart MCP server from localhost, picks an address, searches a product, builds a cart and reads it back. Do not start the other steps until it works. If login is blocked, apply to the Builders Club (section 13).
2. Run the cart validation tests in section 7 with the prototype.
3. Decide the open items: Baileys version, language model provider, summary channel, and daytime batching.
4. Set up the GitHub repository, the story board and the Claude Code automation (section 12), and write the user stories from this document.
5. Build the WhatsApp listener with the sender filter, including @lid handling, and test it with the real sender.
6. Define the extraction output and the first version of the rule book.
7. Build the LangGraph agent with the allowlist, the merge design and the read-back check.
8. Add the queue, the 7:00 release and the failure handling in section 9.

## 18. Sources

Checked on 3 November 2026.

- [Swiggy Builders Club home](https://mcp.swiggy.com/builders/)
- [Swiggy developer quickstart](https://mcp.swiggy.com/builders/docs/start/developer/)
- [Swiggy authentication guide](https://mcp.swiggy.com/builders/docs/start/authenticate/)
- [Instamart tool reference](https://mcp.swiggy.com/builders/docs/reference/instamart/)
- [update\_cart reference](https://mcp.swiggy.com/builders/docs/reference/instamart/update_cart/)
- [get\_orders reference](https://mcp.swiggy.com/builders/docs/reference/instamart/get_orders/)
- [Swiggy error codes](https://mcp.swiggy.com/builders/docs/reference/errors/)
- [Order groceries recipe](https://mcp.swiggy.com/builders/docs/build/recipes/order-groceries/)
- [UPI payments announcement, July 2026](https://mcp.swiggy.com/builders/blog/2026-07-10-mcp-payments-upi/)
- [Swiggy MCP GitHub README](https://github.com/Swiggy/swiggy-mcp-server-manifest)
- [Swiggy issue 131, cart divergence](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/131)
- [Swiggy issue 141, cart changes lost after opening the app](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/141)
- [Swiggy issue 36, stale order history](https://github.com/Swiggy/swiggy-mcp-server-manifest/issues/36)
- [Baileys 7.0.0 release candidate notes](https://newreleases.io/project/npm/baileys/release/7.0.0-rc10)
- [Baileys @lid mapping guide](https://github.com/WhiskeySockets/Baileys/issues/2414)
- [WhatsApp linked device logout rules](https://gulfnews.com/lifestyle/your-whatsapp-could-still-be-linked-to-a-device-you-dont-use-or-dont-own-heres-how-to-check-1.500694345)
- [lharries whatsapp-mcp](https://github.com/lharries/whatsapp-mcp)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
- [AWS Lightsail pricing](https://aws.amazon.com/lightsail/pricing)

## 19. Revision History

| Date | Change |
| --- | --- |
| 3 Nov 2026 | Full review against current sources. UPI payments, full cart replacement, approval-free localhost development and token lifetimes confirmed. Added the tool allowlist, @lid sender handling, session limits, variant rules, failure handling, development workflow and sources. Fixed contradictions about approval and WhatsApp replies. |
