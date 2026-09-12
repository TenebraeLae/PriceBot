(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  const state = {
    q: "",
    page: 1,
    category: "",
    debounce: 0,
    abort: null,
    cartOpen: false,
  };

  const els = {
    search: document.getElementById("search"),
    hint: document.getElementById("hint"),
    cards: document.getElementById("cards"),
    cats: document.getElementById("categories"),
    pager: document.getElementById("pager"),
    pageLabel: document.getElementById("page-label"),
    prev: document.getElementById("prev-page"),
    next: document.getElementById("next-page"),
    cartToggle: document.getElementById("cart-toggle"),
    cartClose: document.getElementById("cart-close"),
    cartTray: document.getElementById("cart-tray"),
    cartItems: document.getElementById("cart-items"),
    cartCount: document.getElementById("cart-count"),
    cartTotal: document.getElementById("cart-total"),
    checkout: document.getElementById("checkout"),
    checkoutHint: document.getElementById("checkout-hint"),
    promo: document.getElementById("promo-code"),
    ordersToggle: document.getElementById("orders-toggle"),
    ordersSheet: document.getElementById("orders-sheet"),
    ordersList: document.getElementById("orders-list"),
    ordersClose: document.getElementById("orders-close"),
    paySheet: document.getElementById("pay-sheet"),
    payNumber: document.getElementById("pay-number"),
    paySum: document.getElementById("pay-sum"),
    payQr: document.getElementById("pay-qr"),
    payClose: document.getElementById("pay-close"),
  };

  function headers() {
    return {
      "X-Telegram-Init-Data": (tg && tg.initData) || "",
      Accept: "application/json",
    };
  }

  async function api(path, options) {
    if (state.abort && options && options.signal == null && path.startsWith("/api/v1/search")) {
      state.abort.abort();
    }
    const ctrl = new AbortController();
    if (path.startsWith("/api/v1/search")) {
      state.abort = ctrl;
    }
    const res = await fetch(path, {
      ...options,
      headers: { ...headers(), ...(options && options.headers) },
      signal: (options && options.signal) || ctrl.signal,
    });
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (!res.ok) {
      const detail = body && body.detail;
      let msg = typeof detail === "string" ? detail : "Запрос не выполнен";
      if (res.status === 401) {
        msg = "Откройте витрину через кнопку меню в боте.";
      }
      throw new Error(msg);
    }
    return body;
  }

  function photoSrc(url) {
    if (!url) return null;
    if (/^https?:\/\//i.test(url)) return url;
    return `/media/${String(url).replace(/^\/+/, "")}`;
  }

  function money(value) {
    return `${value} ₽`;
  }

  function stockLabel(item) {
    if (item.stock == null || item.stock === "") return "";
    const numeric = Number(item.stock);
    const qty = Number.isFinite(numeric) ? String(numeric) : String(item.stock);
    return item.unit ? `остаток ${qty} ${item.unit}` : `остаток ${qty}`;
  }

  function renderCategories(items, active) {
    els.cats.replaceChildren();
    for (const item of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "chip" + (item.name === active ? " is-on" : "");
      btn.textContent = item.name;
      btn.addEventListener("click", () => {
        state.category = state.category === item.name ? "" : item.name;
        state.q = state.category;
        els.search.value = state.category;
        state.page = 1;
        loadSearch();
        renderCategories(items, state.category);
      });
      els.cats.append(btn);
    }
  }

  function qtyInput(sku, stock) {
    const wrap = document.createElement("div");
    wrap.className = "step";
    const minus = document.createElement("button");
    minus.type = "button";
    minus.textContent = "−";
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.step = "1";
    input.value = "1";
    input.setAttribute("aria-label", "Количество");
    const plus = document.createElement("button");
    plus.type = "button";
    plus.textContent = "+";
    const add = document.createElement("button");
    add.type = "button";
    add.className = "add";
    add.textContent = "В корзину";
    const bump = (delta) => {
      const next = Math.max(1, Number(input.value || 1) + delta);
      input.value = String(next);
    };
    minus.addEventListener("click", () => bump(-1));
    plus.addEventListener("click", () => bump(1));
    add.addEventListener("click", async () => {
      add.disabled = true;
      try {
        await api("/api/v1/cart/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sku, qty: input.value, price: "0" }),
        }).then(renderCart);
      } catch (err) {
        els.hint.textContent = err.message;
        els.hint.classList.add("err");
      } finally {
        add.disabled = false;
      }
    });
    if (Number(stock) <= 0) {
      add.disabled = true;
    }
    wrap.append(minus, input, plus, add);
    return wrap;
  }

  function renderCards(items) {
    els.cards.replaceChildren();
    for (const item of items) {
      const card = document.createElement("article");
      card.className = "card";
      const src = photoSrc(item.photo_url);
      const media = src
        ? Object.assign(document.createElement("img"), {
            className: "photo",
            src,
            alt: item.name,
          })
        : Object.assign(document.createElement("div"), {
            className: "photo-fallback",
            textContent: "нет фото",
          });
      const body = document.createElement("div");
      const sku = document.createElement("p");
      sku.className = "sku";
      sku.textContent = item.sku;
      const name = document.createElement("h2");
      name.className = "name";
      name.textContent = item.name;
      const meta = document.createElement("p");
      meta.className = "meta";
      meta.textContent = [item.category, item.description].filter(Boolean).join(" · ");
      const priceRow = document.createElement("div");
      priceRow.className = "price-row";
      const price = document.createElement("span");
      price.className = "price";
      price.textContent = money(item.price);
      const avail = document.createElement("span");
      avail.className = "avail" + (item.availability === "нет" ? " out" : "");
      avail.textContent = item.availability;
      const stock = document.createElement("span");
      stock.className = "stock" + (item.availability === "нет" ? " out" : "");
      stock.textContent = stockLabel(item);
      priceRow.append(price, avail);
      if (stock.textContent) {
        priceRow.append(stock);
      }
      body.append(sku, name, meta, priceRow, qtyInput(item.sku, item.stock));
      card.append(media, body);
      els.cards.append(card);
    }
  }

  function renderPager(page, pageSize, total) {
    const pages = pageSize > 0 ? Math.ceil(total / pageSize) : 0;
    if (pages <= 1) {
      els.pager.hidden = true;
      return;
    }
    els.pager.hidden = false;
    els.pageLabel.textContent = `стр. ${page} из ${pages}`;
    els.prev.disabled = page <= 1;
    els.next.disabled = page >= pages;
  }

  function renderCart(cart) {
    const items = (cart && cart.items) || [];
    els.cartCount.textContent = String(items.length);
    els.cartTotal.textContent = money((cart && cart.total) || "0");
    els.cartItems.replaceChildren();
    for (const line of items) {
      const li = document.createElement("li");
      const title = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = line.name;
      const meta = document.createElement("div");
      meta.className = "sku";
      meta.textContent = `${line.sku} · ${line.qty} ${line.unit}`;
      title.append(name, meta);
      const right = document.createElement("div");
      right.className = "line-total";
      right.textContent = money(line.line_total);
      const row = document.createElement("div");
      row.className = "step";
      const minus = document.createElement("button");
      minus.type = "button";
      minus.textContent = "−";
      const plus = document.createElement("button");
      plus.type = "button";
      plus.textContent = "+";
      const drop = document.createElement("button");
      drop.type = "button";
      drop.textContent = "Убрать";
      minus.addEventListener("click", () => changeQty(line.sku, Number(line.qty) - 1));
      plus.addEventListener("click", () => changeQty(line.sku, Number(line.qty) + 1));
      drop.addEventListener("click", () => changeQty(line.sku, 0));
      row.append(minus, plus, drop);
      li.append(title, right, row);
      els.cartItems.append(li);
    }
    if (els.checkout) {
      els.checkout.disabled = items.length === 0;
    }
  }

  function showPay(order) {
    els.payNumber.textContent = order.number;
    els.paySum.textContent = money(order.amount || order.total);
    if (order.qr_png_base64) {
      els.payQr.src = `data:image/png;base64,${order.qr_png_base64}`;
      els.payQr.hidden = false;
    } else {
      els.payQr.removeAttribute("src");
      els.payQr.hidden = true;
    }
    els.paySheet.hidden = false;
    els.ordersSheet.hidden = true;
  }

  async function checkoutCart() {
    if (!els.checkout || els.checkout.disabled) return;
    els.checkout.disabled = true;
    els.checkoutHint.textContent = "";
    els.checkoutHint.classList.remove("err");
    try {
      const promo = (els.promo && els.promo.value.trim()) || "";
      const order = await api("/api/v1/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ telegram_id: 0, price: "0", promo_code: promo || null }),
      });
      renderCart({ items: [], total: "0" });
      showPay(order);
      setCartOpen(false);
    } catch (err) {
      els.checkoutHint.textContent = err.message;
      els.checkoutHint.classList.add("err");
      els.checkout.disabled = false;
    }
  }

  async function loadOrders() {
    els.ordersList.replaceChildren();
    try {
      const page = await api("/api/v1/orders");
      const items = (page && page.items) || [];
      if (!items.length) {
        const empty = document.createElement("li");
        empty.textContent = "Заказов пока нет.";
        els.ordersList.append(empty);
        return;
      }
      for (const order of items) {
        const li = document.createElement("li");
        const title = document.createElement("strong");
        title.textContent = order.number;
        const meta = document.createElement("div");
        meta.className = "sku";
        meta.textContent = `${order.total} ₽ · ${order.status_label}`;
        li.append(title, meta);
        if (order.status === "awaiting_payment") {
          const again = document.createElement("button");
          again.type = "button";
          again.className = "reopen";
          again.textContent = "Показать QR";
          again.addEventListener("click", async () => {
            try {
              showPay(await api(`/api/v1/orders/${encodeURIComponent(order.number)}`));
            } catch (err) {
              els.hint.textContent = err.message;
              els.hint.classList.add("err");
            }
          });
          li.append(again);
        }
        els.ordersList.append(li);
      }
    } catch (err) {
      const fail = document.createElement("li");
      fail.textContent = err.message;
      els.ordersList.append(fail);
    }
  }

  async function changeQty(sku, qty) {
    try {
      if (qty <= 0) {
        renderCart(await api(`/api/v1/cart/items/${encodeURIComponent(sku)}`, { method: "DELETE" }));
        return;
      }
      renderCart(
        await api(`/api/v1/cart/items/${encodeURIComponent(sku)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sku, qty: String(qty), price: "0" }),
        }),
      );
    } catch (err) {
      els.hint.textContent = err.message;
      els.hint.classList.add("err");
    }
  }

  async function loadSearch() {
    els.hint.classList.remove("err");
    const params = new URLSearchParams({ q: state.q, page: String(state.page) });
    try {
      const page = await api(`/api/v1/search?${params}`);
      if (page.reason === "empty_query") {
        els.hint.textContent = page.hint || "Введите запрос";
        renderCards([]);
        renderPager(1, page.page_size, 0);
        if (page.category_hints && page.category_hints.length && !els.cats.children.length) {
          renderCategories(
            page.category_hints.map((name) => ({ name })),
            state.category,
          );
        }
        return;
      }
      if (page.reason === "user_blocked") {
        els.hint.textContent = page.hint || "Поиск недоступен";
        renderCards([]);
        return;
      }
      if (page.reason === "query_too_long") {
        els.hint.textContent = "Запрос слишком длинный";
        renderCards([]);
        return;
      }
      els.hint.textContent = page.total ? `${page.total} поз.` : "Ничего не найдено";
      renderCards(page.items || []);
      renderPager(page.page, page.page_size, page.total);
    } catch (err) {
      if (err.name === "AbortError") return;
      els.hint.textContent = err.message;
      els.hint.classList.add("err");
    }
  }

  async function boot() {
    try {
      const cats = await api("/api/v1/categories");
      renderCategories(cats.items || [], state.category);
    } catch (err) {
      els.hint.textContent = err.message;
      els.hint.classList.add("err");
    }
    try {
      renderCart(await api("/api/v1/cart"));
    } catch {
      renderCart({ items: [], total: "0" });
    }
    await loadSearch();
  }

  els.search.addEventListener("input", () => {
    window.clearTimeout(state.debounce);
    state.debounce = window.setTimeout(() => {
      state.q = els.search.value;
      state.page = 1;
      if (state.category && state.q !== state.category) {
        state.category = "";
        [...els.cats.children].forEach((node) => node.classList.remove("is-on"));
      }
      loadSearch();
    }, 300);
  });

  els.prev.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadSearch();
    }
  });
  els.next.addEventListener("click", () => {
    state.page += 1;
    loadSearch();
  });

  function setCartOpen(open) {
    state.cartOpen = open;
    els.cartTray.hidden = !open;
    els.cartToggle.setAttribute("aria-expanded", open ? "true" : "false");
  }

  els.cartToggle.addEventListener("click", () => setCartOpen(!state.cartOpen));
  els.cartClose.addEventListener("click", () => setCartOpen(false));
  if (els.checkout) {
    els.checkout.addEventListener("click", checkoutCart);
  }
  if (els.payClose) {
    els.payClose.addEventListener("click", () => {
      els.paySheet.hidden = true;
    });
  }
  if (els.ordersToggle) {
    els.ordersToggle.addEventListener("click", async () => {
      els.ordersSheet.hidden = !els.ordersSheet.hidden;
      if (!els.ordersSheet.hidden) {
        els.paySheet.hidden = true;
        await loadOrders();
      }
    });
  }
  if (els.ordersClose) {
    els.ordersClose.addEventListener("click", () => {
      els.ordersSheet.hidden = true;
    });
  }

  window.addEventListener("resize", () => {
    if (tg && tg.expand) tg.expand();
  });

  boot();
})();
