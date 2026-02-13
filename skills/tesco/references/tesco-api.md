# Tesco Browser API Reference

JavaScript snippets for use with `browser(action="act", request={kind: "evaluate", fn: "..."})`.

All snippets run in the Tesco groceries page context. Requires `browser.evaluateEnabled=true`.

## Extract CSRF Token

```javascript
() => {
  const el = document.querySelector('html');
  return el ? el.dataset.csrfToken : null;
}
```

If null, try the meta tag fallback:

```javascript
() => {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.getAttribute('content') : null;
}
```

Store the token for subsequent API calls in the same session.

## Search for a Product

```javascript
(query, csrf) => {
  return fetch('/groceries/en-GB/resources', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-csrf-token': csrf
    },
    body: JSON.stringify({
      resources: [{
        type: 'search',
        params: { query: { 'query-small': query }, page: { number: 1, size: 10 } }
      }]
    })
  })
  .then(r => r.json())
  .then(data => {
    const results = data?.search?.data?.results?.productItems || [];
    return results.slice(0, 5).map(item => ({
      id: item.product?.id,
      title: item.product?.title,
      price: item.product?.price,
      unitPrice: item.product?.unitPrice,
      imageUrl: item.product?.defaultImageUrl,
      isAvailable: item.product?.isAvailable
    }));
  });
}
```

Call with template:

```javascript
() => {
  const csrf = document.querySelector('html')?.dataset?.csrfToken;
  return fetch('/groceries/en-GB/resources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-csrf-token': csrf },
    body: JSON.stringify({
      resources: [{ type: 'search', params: { query: { 'query-small': 'SEARCH_TERM' }, page: { number: 1, size: 10 } } }]
    })
  }).then(r => r.json()).then(data => {
    const items = data?.search?.data?.results?.productItems || [];
    return items.slice(0, 5).map(i => ({
      id: i.product?.id,
      title: i.product?.title,
      price: i.product?.price,
      unitPrice: i.product?.unitPrice,
      available: i.product?.isAvailable
    }));
  });
}
```

Replace `SEARCH_TERM` with the actual query.

## Add Item to Trolley

```javascript
() => {
  const csrf = document.querySelector('html')?.dataset?.csrfToken;
  return fetch('/groceries/en-GB/trolley/items?_method=PUT', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-csrf-token': csrf },
    body: JSON.stringify({
      items: [{
        id: 'PRODUCT_ID',
        newValue: QUANTITY,
        oldValue: 0,
        newUnitChoice: 'pcs',
        oldUnitChoice: 'pcs'
      }]
    })
  }).then(r => r.json()).then(data => ({
    success: !data.error,
    trolleyTotal: data?.trolley?.total,
    itemCount: data?.trolley?.itemCount,
    error: data?.error?.message
  }));
}
```

Replace `PRODUCT_ID` with the product ID from search and `QUANTITY` with the number of units.

For weight-based items (meat, veg), use `newUnitChoice: 'kg'` and set value in kg.

## Get Trolley Contents

```javascript
() => {
  const csrf = document.querySelector('html')?.dataset?.csrfToken;
  return fetch('/groceries/en-GB/resources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-csrf-token': csrf },
    body: JSON.stringify({
      resources: [{ type: 'trolley', params: {} }]
    })
  }).then(r => r.json()).then(data => {
    const trolley = data?.trolley?.data;
    return {
      total: trolley?.total,
      itemCount: trolley?.itemCount,
      items: (trolley?.items || []).map(i => ({
        id: i.id,
        title: i.title,
        price: i.price,
        quantity: i.quantity
      }))
    };
  });
}
```

## DOM Automation: Search & Add (PRIMARY METHOD)

The BFF API CSRF tokens may not be available from browser evaluate on the VM. Use DOM automation as the primary method.

### Search

Navigate to the search URL:

```
https://www.tesco.com/groceries/en-GB/search?query={encodeURIComponent(item)}
```

Then snapshot the page. Products appear as `<li>` elements containing:
- Product title: `<a>` link with href containing `/products/`
- Price: element with `data-auto="price-value"`
- Add button: `<button>` with `data-auto="ddsweb-quantity-controls-add-button"` (text = "Add")
- Remove button (after adding): `data-auto="ddsweb-quantity-controls-remove-button"`
- Quantity display (after adding): `data-auto="trolley-product-quantity"`

### Add to Basket

Click the "Add" button ref from the snapshot. After clicking, snapshot again and verify the button changed to show quantity controls with a Remove button.

### Item Selection Strategy

- Skip "Sponsored" items (they appear first but are ads)
- Prefer Tesco own-brand for staples
- Match quantity/weight to what the recipe needs
- If the first non-sponsored result is a good match, use it

### JavaScript Click Fallback

If the browser `act` click doesn't trigger, use evaluate:

```javascript
() => {
    const lis = document.querySelectorAll('li');
    const productLis = Array.from(lis).filter(li =>
        li.querySelector('[data-auto="ddsweb-quantity-controls-add-button"]')
    );
    // Skip sponsored
    const chosen = productLis.find(li => !li.innerText.includes('Sponsored')) || productLis[0];
    if (!chosen) return {error: 'No products'};
    const link = chosen.querySelector('a[href*="/products/"]');
    const addBtn = chosen.querySelector('[data-auto="ddsweb-quantity-controls-add-button"]');
    addBtn.click();
    return {name: link?.textContent?.trim(), clicked: true};
}
```

## DOM Fallback: Trolley Page

Navigate to `https://www.tesco.com/groceries/en-GB/trolley` and snapshot to see basket contents.

## Session Check

To verify the user is still logged in:

```javascript
() => {
  return fetch('/groceries/en-GB/resources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resources: [{ type: 'user', params: {} }] })
  }).then(r => r.json()).then(data => ({
    loggedIn: !!data?.user?.data?.uid,
    name: data?.user?.data?.firstName,
    email: data?.user?.data?.email
  }));
}
```

If `loggedIn` is false, redirect to the Login Flow.

## API Notes

- All API calls go through the same domain (relative URLs) so CORS is not an issue
- CSRF token changes per page load; re-extract after navigation
- Rate limiting: space requests ~500ms apart to avoid 429s
- Product IDs are numeric strings (e.g. `"252261477"`)
- Prices are returned as floats in GBP (e.g. `1.45`)
- Some items are "Clubcard price" - the `price` field shows the Clubcard price if logged in
