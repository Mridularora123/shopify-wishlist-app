# src/routes/proxy.py
from flask import Blueprint, request, jsonify
from sqlalchemy.exc import IntegrityError
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI

proxy_bp = Blueprint('proxy', __name__)

# ─────────────────────────────
# Helpers
# ─────────────────────────────

def _json_body():
    return request.get_json(silent=True) or {}

def _shop_from_request():
    """
    Accept the shop from anywhere Shopify/the theme might send it:
    - ?shop=…  (Shopify App Proxy default)
    - X-Shopify-Shop-Domain header
    - ?shop_domain=…
    - JSON body { "shop_domain": … }
    """
    return (
        request.args.get('shop')
        or request.headers.get('X-Shopify-Shop-Domain')
        or request.args.get('shop_domain')
        or _json_body().get('shop_domain')
    )

def _json_error(msg, code=400, extra=None):
    payload = {'success': False, 'error': msg}
    if extra:
        payload['detail'] = extra
    return jsonify(payload), code

def verify_proxy_request():
    # Keep permissive during integration; tighten with HMAC later.
    return True

def _get_shop_settings(shop):
    if not shop:
        return None
    return WishlistSettings.query.filter_by(shop_domain=shop).first()

def _resolve_product_id(shop, variant_id):
    """
    Try to resolve a product_id from a variant_id using ShopifyAPI.
    If we can't (no token or method not available), return None.
    """
    if not (shop and variant_id):
        return None
    settings = _get_shop_settings(shop)
    if not settings or not getattr(settings, "access_token", None):
        return None
    try:
        api = ShopifyAPI(shop, settings.access_token)
        # Your ShopifyAPI class may expose get_variant() or a generic request.
        # First try a dedicated method if it exists:
        if hasattr(api, "get_variant"):
            v = api.get_variant(str(variant_id))
        else:
            # Fallback: most wrappers expose a low-level GET
            # Expected Shopify REST path: /admin/api/2023-10/variants/{id}.json
            v = api.get(f"variants/{variant_id}")  # adjust if your wrapper uses full path
        if not v:
            return None
        # Normalize payload shape (either {"variant": {...}} or {...})
        variant_obj = v.get("variant", v)
        pid = variant_obj.get("product_id")
        return str(pid) if pid else None
    except Exception:
        # Don’t kill the flow; just fail open and return None.
        return None


# ─────────────────────────────
# Widget JS (served via proxy) — NEVER block
# /apps/wishlist/wishlist.js  → proxy →  /proxy/wishlist.js
# ─────────────────────────────

@proxy_bp.route('/proxy/wishlist.js', methods=['GET'])
def wishlist_js():
    # Do NOT 401 here; let the widget bootstrap from theme globals.
    JS = r"""
(function () {
  // --- Config (take any preset, then publish) -------------------------
  var PRE = (window.WISHLIST_CONFIG || {});
  var CANDIDATE_ID =
      PRE.customerId
   || (typeof window.__CUSTOMER_ID__ !== "undefined" ? window.__CUSTOMER_ID__ : null)
   || ((window.Shopify && window.Shopify.customer) ? window.Shopify.customer.id : null);

  var WISHLIST_CONFIG = {
    shop: PRE.shop || (window.Shopify && window.Shopify.shop ? window.Shopify.shop : ""),
    apiEndpoint: PRE.apiEndpoint || "/apps/wishlist",   // storefront base (Shopify proxies to /proxy/*)
    customerId: CANDIDATE_ID,
    isLoggedIn: !!CANDIDATE_ID
  };
  window.WISHLIST_CONFIG = WISHLIST_CONFIG;
  console.log("[wishlist] boot config:", WISHLIST_CONFIG);

  // Init after DOM ready (let theme overrides run first)
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initWishlist);
  } else {
    setTimeout(initWishlist, 0);
  }

  function initWishlist() {
    if (window.Shopify && window.Shopify.customer) {
      WISHLIST_CONFIG.customerId = window.Shopify.customer.id;
      WISHLIST_CONFIG.isLoggedIn = true;
    }
    addWishlistButtons();
    updateWishlistCount();
  }

  // ---------- Button injection (Dawn PDP) ----------
  function addWishlistButtons() {
    var productForms = document.querySelectorAll('product-form form[action*="/cart/add"], form[action*="/cart/add"]');
    if (!productForms.length) {
      setTimeout(addWishlistButtons, 500); // sections load async; retry once
      return;
    }
    productForms.forEach(function (form) {
      if (form.querySelector(".wishlist-btn")) return; // avoid duplicates
      var variantId = getVariantId(form);
      if (!variantId) return;
      var btn = createWishlistButton(variantId);
      var atc = form.querySelector('button[type="submit"], .btn-cart, .add-to-cart');
      if (atc && atc.parentNode) {
        atc.parentNode.insertBefore(btn, atc.nextSibling);
      } else {
        form.appendChild(btn);
      }
      checkWishlistStatus(variantId, btn);
    });
  }

  function getVariantId(el) {
    var idInput = el.querySelector('input[name="id"]');
    return idInput && idInput.value ? idInput.value : null; // PDP: variant id
  }

  function createWishlistButton(variantId) {
    var b = document.createElement("button");
    b.className = "wishlist-btn";
    b.type = "button";
    b.dataset.variantId = String(variantId);
    b.textContent = "♡ Add to Wishlist";
    b.style.cssText = "background:none;border:1px solid #ccc;padding:8px 12px;cursor:pointer;margin:6px 0;border-radius:4px;font-size:14px;";
    b.addEventListener("click", function (e) {
      e.preventDefault();
      toggleWishlist(variantId, b);
    });
    return b;
  }

  // ---------- API actions ----------
  function toggleWishlist(variantId, button) {
    if (!WISHLIST_CONFIG.isLoggedIn || !WISHLIST_CONFIG.customerId) {
      alert("Please log in to use the wishlist feature.");
      return;
    }
    var isIn = button.classList.contains("in-wishlist");
    var method = isIn ? "DELETE" : "POST";
    var url = WISHLIST_CONFIG.apiEndpoint + "/wishlist";

    var payload = {
      customer_id: String(WISHLIST_CONFIG.customerId),
      shop_domain: WISHLIST_CONFIG.shop,
      variant_id: String(variantId)
    };

    button.disabled = true;
    button.textContent = isIn ? "Removing..." : "Adding...";

    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload)
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data && data.success) {
        updateButtonState(button, !isIn);
        updateWishlistCount();
      } else {
        alert("Error: " + ((data && data.error) || "Unknown error"));
      }
    })
    .catch(function (e) {
      console.error("Wishlist error:", e);
      alert("Error updating wishlist");
    })
    .finally(function () { button.disabled = false; });
  }

  function checkWishlistStatus(variantId, button) {
    if (!WISHLIST_CONFIG.isLoggedIn) return;
    var url = WISHLIST_CONFIG.apiEndpoint + "/wishlist"
      + "?customer_id=" + encodeURIComponent(WISHLIST_CONFIG.customerId)
      + "&shop_domain=" + encodeURIComponent(WISHLIST_CONFIG.shop);

    fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.success) {
          var inList = (data.wishlist || []).some(function (it) {
            return String(it.variant_id || it.product_id) === String(variantId);
          });
          updateButtonState(button, inList);
        }
      })
      .catch(function (e) { console.warn("check status failed:", e); });
  }

  function updateButtonState(button, inWishlist) {
    if (inWishlist) {
      button.classList.add("in-wishlist");
      button.textContent = "♥ In Wishlist";
      button.style.backgroundColor = "#ff6b6b";
      button.style.color = "#fff";
      button.style.borderColor = "#ff6b6b";
    } else {
      button.classList.remove("in-wishlist");
      button.textContent = "♡ Add to Wishlist";
      button.style.backgroundColor = "transparent";
      button.style.color = "#333";
      button.style.borderColor = "#ccc";
    }
  }

  function updateWishlistCount() {
    if (!WISHLIST_CONFIG.isLoggedIn) return;
    var url = WISHLIST_CONFIG.apiEndpoint + "/wishlist/count"
      + "?customer_id=" + encodeURIComponent(WISHLIST_CONFIG.customerId)
      + "&shop_domain=" + encodeURIComponent(WISHLIST_CONFIG.shop);

    fetch(url, { headers: { "Accept": "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.success) {
          document.querySelectorAll(".wishlist-count").forEach(function (el) {
            el.textContent = data.count;
          });
        }
      })
      .catch(function (e) { console.warn("count failed:", e); });
  }

  // Small public API
  window.WishlistWidget = window.WishlistWidget || {};
  window.WishlistWidget.updateCount = updateWishlistCount;
  window.WishlistWidget.refreshButtons = addWishlistButtons;
})();
"""
    return JS, 200, {
        'Content-Type': 'application/javascript',
        'Cache-Control': 'no-store',
    }


# ─────────────────────────────
# Proxy endpoints (Shopify forwards /apps/wishlist/* here)
# ─────────────────────────────

@proxy_bp.route('/proxy/wishlist', methods=['GET', 'POST', 'DELETE'])
def proxy_wishlist():
    if not verify_proxy_request():
        return _json_error('Unauthorized', 401)

    try:
        shop = _shop_from_request()
        if not shop:
            return _json_error('missing shop', 400)

        # Ensure the shop is configured (needed for enrichment & variant->product resolution)
        shop_settings = _get_shop_settings(shop)
        if not shop_settings:
            # We still allow basic reads/writes without enrichment,
            # but variant->product resolution will be unavailable.
            pass

        if request.method == 'GET':
            return _get_wishlist(shop)
        elif request.method == 'POST':
            return _add_to_wishlist(shop)
        elif request.method == 'DELETE':
            return _remove_from_wishlist(shop)

        return _json_error('unsupported method', 405)

    except Exception as e:
        # Always JSON, never HTML error pages
        return _json_error(f'unhandled: {str(e)}', 500)


@proxy_bp.route('/proxy/wishlist/count', methods=['GET'])
def proxy_wishlist_count():
    if not verify_proxy_request():
        return _json_error('Unauthorized', 401)
    try:
        shop = _shop_from_request()
        customer_id = request.args.get('customer_id') or _json_body().get('customer_id')
        if not shop or not customer_id:
            return _json_error('shop and customer_id are required', 400)

        count = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        ).count()

        return jsonify({'success': True, 'count': count})

    except Exception as e:
        return _json_error(f'count_failed: {str(e)}', 500)


@proxy_bp.route('/proxy', methods=['GET'])
def shopify_proxy_root():
    return jsonify({"success": True, "wishlist": []})


# ─────────────────────────────
# Internal handlers (called by proxy routes above)
# ─────────────────────────────

def _get_wishlist(shop):
    customer_id = request.args.get('customer_id') or _json_body().get('customer_id')
    if not customer_id:
        return _json_error('customer_id is required', 400)

    try:
        wishlist_items = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        ).all()

        # Optional enrichment with product data
        enriched = []
        settings = _get_shop_settings(shop)
        api = None
        if settings and getattr(settings, "access_token", None):
            try:
                api = ShopifyAPI(shop, settings.access_token)
            except Exception:
                api = None

        for item in wishlist_items:
            d = item.to_dict()
            if api and d.get('product_id'):
                try:
                    p = api.get_product(d['product_id'])
                    if p:
                        d['product'] = p
                except Exception:
                    pass
            enriched.append(d)

        return jsonify({'success': True, 'wishlist': enriched})

    except Exception as e:
        return _json_error(f'get_failed: {str(e)}', 500)


def _add_to_wishlist(shop):
    data = _json_body() or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    if not customer_id or not (product_id or variant_id):
        return _json_error('customer_id and product_id or variant_id are required', 400)

    # If only variant_id came in, try to resolve product_id
    if not product_id and variant_id:
        resolved = _resolve_product_id(shop, variant_id)
        if resolved:
            product_id = resolved

    try:
        # Prevent duplicates (match on actual stored values, including NULLs)
        q = Wishlist.query.filter_by(customer_id=str(customer_id), shop_domain=shop)
        if product_id:
            q = q.filter_by(product_id=str(product_id))
        else:
            q = q.filter_by(product_id=None)
        if variant_id:
            q = q.filter_by(variant_id=str(variant_id))
        else:
            q = q.filter_by(variant_id=None)

        existing = q.first()
        if existing:
            return _json_error('Item already in wishlist', 409)

        item = Wishlist(
            customer_id=str(customer_id),
            shop_domain=shop,
            product_id=str(product_id) if product_id else None,
            variant_id=str(variant_id) if variant_id else None
        )
        db.session.add(item)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Item added to wishlist', 'item': item.to_dict()})

    except IntegrityError as ie:
        db.session.rollback()
        # If your table has NOT NULL on product_id, tell the caller explicitly:
        return _json_error('db_integrity_failed: product_id may be required in your schema', 500, extra=str(ie))
    except Exception as e:
        db.session.rollback()
        return _json_error(f'add_failed: {str(e)}', 500)


def _remove_from_wishlist(shop):
    data = _json_body() or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    if not customer_id or not (product_id or variant_id):
        return _json_error('customer_id and product_id or variant_id are required', 400)

    try:
        q = Wishlist.query.filter_by(customer_id=str(customer_id), shop_domain=shop)
        if product_id:
            q = q.filter_by(product_id=str(product_id))
        else:
            q = q.filter_by(product_id=None)
        if variant_id:
            q = q.filter_by(variant_id=str(variant_id))
        else:
            q = q.filter_by(variant_id=None)

        item = q.first()
        if not item:
            return _json_error('Item not found', 404)

        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Item removed from wishlist'})

    except Exception as e:
        db.session.rollback()
        return _json_error(f'remove_failed: {str(e)}', 500)
