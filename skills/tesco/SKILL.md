---
name: tesco
description: "Meal prep and Tesco grocery shopping via browser automation. Plan weekly meals, extract ingredients from recipes or URLs, consolidate shopping lists (deduplicate pantry staples), and add items to a Tesco.com basket. Supports multiple users with separate Tesco accounts. Triggers: meal prep, plan meals, tesco shop, add to tesco, grocery list, weekly meals, tesco login, connect my tesco."
metadata: {"openclaw": {"emoji": "🛒", "requires": {"bins": ["python3"]}}}
---

# Tesco Meal Prep & Shopping

Plan weekly meals and shop the consolidated ingredient list on Tesco.com via browser automation. Stops at the basket (never checkout).

## References

- `references/tesco-api.md` - JavaScript snippets for Tesco search/add-to-trolley API calls via browser evaluate, plus DOM fallback patterns.

## Entry Point: What Does the User Want?

When triggered, figure out which mode the user wants. Ask if it's not obvious:

> What are we doing today?
> 1. **Meal plan** - plan meals for the week and shop the ingredients
> 2. **Quick shop** - add specific items to your Tesco basket

**"Meal plan"** → go to Meal Prep Flow.
**"Quick shop"** / "add X to basket" / explicit item list → go to Shopping Flow.
**"Show basket"** → go to Basket View.

If the user's message already makes it clear (e.g. "plan meals for the week" or "add milk to my basket"), skip the question and go straight to the right flow.

## Browser Setup Before ANY Tesco Navigation

Always follow these steps before visiting any Tesco page.

### Step 1: Start the browser profile

```
browser(action="start", profile="tesco-ruzin")
```

Use `tesco-ruzin` as the default profile. Use `tesco-gf` for the girlfriend's account.

### Step 2: Open Tesco in a new tab

Use the `open` action (not `navigate`) to open Tesco in a new tab:

```
browser(action="open", targetUrl="https://www.tesco.com/groceries/en-GB/", profile="tesco-ruzin")
```

### Step 3: Wait and verify the page loaded

Wait 3 seconds, then snapshot to verify the page loaded (title should NOT be "Access Denied"):

```
browser(action="snapshot", profile="tesco-ruzin")
```

If you see "Access Denied", stop the browser, wait 5 seconds, and retry from Step 1.

## Multi-User Browser Profiles

Each user gets an isolated browser profile so Tesco sessions (cookies, login) persist independently.

Profile naming: `tesco-{username}` (e.g. `tesco-ruzin`, `tesco-gf`).

Profile data lives at `~/.openclaw/browser/tesco-{username}/user-data/`.

Route to the correct profile based on the Telegram sender's name or username. Default to `tesco-ruzin` if the sender is Ruzin or ambiguous.

## Login Flow

**IMPORTANT:** When the user says "connect my tesco", "log into tesco", or any login-related request, you MUST use the VNC Login method below. Do NOT use the `browser()` tool for login — Akamai Bot Manager blocks automated logins from cloud server IPs. The `browser()` tool is only for shopping AFTER login.

### Method 1: VNC Login (PRIMARY - always use this for login)

Opens a real Chrome browser on the server inside a virtual display and shares it with the user via noVNC. The user logs in like a normal human — Akamai sees genuine interaction. Use the `exec()` tool (not `browser()`) to run the VNC login script.

1. Determine the profile name from the sender (e.g. `tesco-ruzin`, `tesco-gf`).

2. Start the VNC session:
   ```
   exec(command="python3 ~/.openclaw/workspace/skills/tesco/scripts/tesco-vnc-login.py start tesco-{username}", timeout=30)
   ```

3. Parse the JSON response and extract the `url` field.

4. Send the user a message with the clickable URL:
   > To connect your Tesco account, open this link and log in:
   >
   > [Login here]({url})
   >
   > You'll see a Chrome browser with Tesco open — just sign in normally. I'll detect when you're done.

5. Poll every 15 seconds until login is detected or 30 minutes elapse:
   ```
   exec(command="python3 ~/.openclaw/workspace/skills/tesco/scripts/tesco-vnc-login.py status tesco-{username}", timeout=10)
   ```

6. When `logged_in: true`:
   ```
   exec(command="python3 ~/.openclaw/workspace/skills/tesco/scripts/tesco-vnc-login.py stop tesco-{username}", timeout=10)
   ```
   Confirm to the user:
   > You're connected! I can now shop on Tesco for you.

7. If 30 minutes pass without login: stop the VNC session and tell the user it timed out. Offer to try again.

### Method 2: Cookie Login (FALLBACK - only if VNC login fails or user prefers)

The user logs in on their own device and shares session cookies. More technical but works without VNC.

1. Ask the user to log in on their phone or computer:
   > To connect your Tesco account, I need your session cookies:
   > 1. Open **https://www.tesco.com** on your phone/computer and sign in
   > 2. In Chrome: press **F12** > **Application** tab > **Cookies** > **www.tesco.com**
   > 3. Copy ALL cookie names and values (or just copy the **Cookie** header from any request in the Network tab)
   > 4. Paste the cookie string here

2. Once the user provides cookies, inject them using the helper script:
   ```
   exec(command="python3 /home/ubuntu/tesco_cookie_login.py 18801 '<cookie_string>'", timeout=30)
   ```
   Replace `<cookie_string>` with the user's pasted cookies (format: `name1=value1; name2=value2; ...`).

3. Follow Browser Setup steps and verify login by snapshotting the homepage. Look for the user's name or "My account" instead of "Sign in".

4. If verification fails, ask the user to re-copy cookies (they may have expired or been incomplete).

Session cookies persist in the profile. Re-login only if session expires (detected by redirect to login page during shopping).

---

## Meal Prep Flow

This is the full conversational flow for planning meals and shopping the ingredients.

### Step 1: Gather preferences

Ask the user in a natural, casual way. You need to know:

- **How many meals/days?** (e.g. "5 dinners for the week")
- **How many people?** (default 2 if user is Ruzin - him + girlfriend)
- **Any preferences?** (healthy, quick, cuisine type, dietary restrictions)
- **Any recipes they already have?** (URLs or specific dishes)

Example opening:

> How many meals are we planning? And any preferences - healthy, quick, specific cuisine? Also let me know if you have any recipe links you want to include.

Don't ask all questions in a giant list. Keep it conversational. If they say "5 meals, healthy, me and my gf", you have everything you need - move on.

### Step 2: Suggest meals (the back-and-forth)

Search the web for recipes matching their preferences. Present **5 meals** (or however many they asked for) in a compact format:

> Here's what I'm thinking for the week:
>
> 1. **Lemon Herb Salmon** with roasted veg (30 min)
> 2. **Chicken Stir Fry** with noodles (20 min)
> 3. **Mediterranean Pasta** with olives & feta (25 min)
> 4. **Thai Green Curry** with rice (35 min)
> 5. **Stuffed Peppers** with quinoa & black beans (40 min)
>
> Want to swap any? Or send me a recipe link and I'll slot it in.

**Then iterate.** The user might say:
- "swap 3 for a risotto" → search for a risotto recipe, replace it, show updated list
- "add this: [URL]" → fetch the URL, extract the recipe, slot it in
- "looks good" / "go for it" → move to Step 3

Keep going back and forth until the user approves the full list. Don't rush - this is the collaborative part.

**For recipe URLs:** use `web_fetch` to extract the page. Parse out the recipe name, servings, and ingredient list. Show the user what you extracted and confirm.

**For suggestions:** use `web_search` to find highly-rated recipes. Prefer recipes from BBC Good Food, Mob Kitchen, Jamie Oliver, or Delicious Magazine (they have clean ingredient lists).

### Step 3: Extract all ingredients

Once the meal plan is agreed, extract a structured ingredient list from each recipe. For each recipe, you need:

```json
{
  "recipe": "Lemon Herb Salmon",
  "ingredients": [
    {"qty": 2, "unit": "fillets", "item": "salmon"},
    {"qty": 1, "unit": "pcs", "item": "lemon"},
    {"qty": 200, "unit": "g", "item": "green beans"},
    {"qty": 1, "unit": "tbsp", "item": "olive oil"},
    {"qty": 2, "unit": "cloves", "item": "garlic"}
  ]
}
```

Build this JSON for ALL recipes, then write it to a temp file.

### Step 4: Consolidate & deduplicate

Run the consolidation script to merge duplicates and separate pantry staples:

```bash
exec(command="echo '<JSON_ARRAY>' | python3 ~/.openclaw/workspace/skills/tesco/scripts/tesco-shop.py consolidate", timeout=15)
```

The script will:
- **Sum quantities** across recipes (2 recipes each need 1 onion = 2 onions)
- **Deduplicate pantry staples** (salt, olive oil, pepper = buy once, not per recipe)
- **Normalize units** (kg/g, l/ml)
- **Return** a split list: `shopping_list` (things to buy) + `pantry_staples` (things you probably have)

### Step 5: Present the shopping list for approval

Show the user the consolidated list clearly, split into shopping items and pantry staples:

> Here's your shopping list for 5 meals (2 people):
>
> **To buy (12 items):**
> - 2x salmon fillets
> - 500g chicken breast
> - 300g pasta
> - 2x peppers
> - 200g feta
> - 1x tin chopped tomatoes
> - 200g green beans
> - 1x bunch spring onions
> - 400ml coconut milk
> - 1x pack rice noodles
> - 250g quinoa
> - 1x tin black beans
>
> **Pantry staples (probably already have):**
> - Olive oil
> - Salt & pepper
> - Garlic (4 cloves total)
> - Soy sauce
>
> Want me to add the pantry staples too, or just the main items?
> Say **"shop it"** when you're happy with the list.

**Wait for explicit confirmation** before touching the basket. The user might:
- Remove items ("skip the quinoa, we have some")
- Add items ("add eggs too")
- Include/exclude pantry staples
- Say "shop it" / "go" / "add to basket" → move to Step 6

### Step 6: Shop the list on Tesco

Once confirmed, run the Shopping Flow (below) for every item on the approved list.

**During shopping, give progress updates** every 3-4 items:

> Adding to basket... (4/12)
> + Tesco Salmon Fillets 2 Pack - £4.50
> + Tesco Chicken Breast Fillets 300g - £3.25
> + Tesco Fusilli Pasta 500g - £0.70
> + Tesco Mixed Peppers 3 Pack - £1.50

When done, show the final report:

> Done! Added 11/12 items to your Tesco basket.
>
> + Salmon Fillets 2 Pack - £4.50
> + Chicken Breast 300g - £3.25
> + Fusilli Pasta 500g - £0.70
> + Mixed Peppers 3 Pack - £1.50
> + Tesco Greek Feta 200g - £1.75
> + Chopped Tomatoes 400g - £0.40
> + Green Beans 200g - £1.00
> + Spring Onions Bunch - £0.50
> + Coconut Milk 400ml - £1.10
> + Rice Noodles 250g - £1.50
> + Black Beans 400g - £0.60
>
> Could not find: quinoa (want me to try a different search?)
>
> Estimated total: ~£16.80
> Review your basket: https://www.tesco.com/groceries/en-GB/trolley

---

## Shopping Flow (Adding Items to Basket)

This is the core flow for adding items. Use this for "quick shop" requests or when the Meal Prep Flow reaches Step 6.

### Prerequisites

- User must be logged into Tesco (check by navigating to trolley page; if redirected to login, run Login Flow first)
- Always follow the Browser Setup steps first (start, open tab, verify)

### Method 1: DOM automation (primary method)

For each item:

1. Navigate to the search page:
   ```
   browser(action="navigate", targetUrl="https://www.tesco.com/groceries/en-GB/search?query=semi%20skimmed%20milk", profile="tesco-ruzin")
   ```
2. Snapshot the results:
   ```
   browser(action="snapshot", profile="tesco-ruzin")
   ```
3. Look for the best product match in the snapshot results. Products have:
   - `data-auto="ddsweb-quantity-controls-add-button"` on the Add button
   - `data-auto="price-value"` on the price
   - Product links with href containing `/products/`
4. **Skip Sponsored items** - they appear first but are ads. Pick the first non-sponsored result that matches.
5. Click "Add" on the best match:
   ```
   browser(action="act", request={kind: "click", ref: "<add-button-ref>"}, profile="tesco-ruzin")
   ```
6. Snapshot to confirm it was added (button should now show quantity or "Remove")

### Method 2: Browser evaluate API (faster, use if DOM fails)

See `references/tesco-api.md` for full JavaScript snippets.

Steps per item:
1. Extract CSRF token via evaluate
2. Search for the item via Tesco BFF API (evaluate)
3. Pick the best match (first result or closest name match)
4. Add to trolley via PUT API (evaluate)
5. Record result: item name, price, product ID

### Batch shopping flow

1. Follow Browser Setup (start, open tab, verify)
2. For each item in the list: search + add using Method 1 or 2
3. Track successes and failures
4. **Send progress updates** to the user every 3-4 items (don't wait until the end)
5. After all items: navigate to trolley page:
   ```
   browser(action="navigate", targetUrl="https://www.tesco.com/groceries/en-GB/trolley", profile="tesco-ruzin")
   ```
6. Snapshot the trolley and report to user with item names, prices, total, and the basket link
7. For failed items: ask user for substitution or skip

### Item matching strategy

When multiple search results appear:
- **Skip Sponsored results** (they are ads, not necessarily the best match)
- Prefer Tesco own-brand for staples (cheaper)
- Match quantity/weight to what's needed
- Prefer fresh over frozen unless user specifies
- If ambiguous, pick the first reasonable non-sponsored match rather than asking

### Basket View

When the user asks to see their basket:

1. Navigate to `https://www.tesco.com/groceries/en-GB/trolley`
2. Snapshot the page
3. Report: item count, estimated total, any unavailable items, and the link

---

## Safety Rules

- **Never checkout.** Stop at the basket. User reviews and pays manually.
- **Always confirm** the shopping list before adding anything to the basket.
- **Never store passwords.** Credentials are entered live via the login flow and stored only as session cookies in the browser profile.
- **Item not found:** Ask user for substitution. Never skip silently.
- **One shop at a time.** Don't run concurrent shopping sessions for different users.
- **Progress updates:** Always keep the user informed during long shopping runs.

## Quick Commands

| User says | Action |
|-----------|--------|
| "connect my tesco" | Run Login Flow (VNC) |
| "log into tesco" | Run Login Flow |
| "plan meals for the week" | Meal Prep Flow from Step 1 |
| "meal plan" / "meal prep" | Meal Prep Flow from Step 1 |
| "add milk to my tesco basket" | Single-item Shopping Flow |
| "shop this list: X, Y, Z" | Multi-item Shopping Flow with given list |
| "show my tesco basket" | Basket View |
| "what's in my basket" | Basket View |
