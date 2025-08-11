# src/routes/proxy.py
from flask import Blueprint, request, jsonify
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI  # keep if used elsewhere

proxy_bp = Blueprint('proxy', __name__)

def _shop_from_request():
    # Accept ?shop=..., ?shop_domain=..., or proxy header
    return (
        request.args.get('shop')
        or request.args.get('shop_domain')
        or request.headers.get('X-Shopify-Shop-Domain')
    )

def verify_proxy_request():
    # Minimal check; add HMAC later if you want
    return bool(_shop_from_request())

# ---------- Lightweight proxy verification while we integrate ----------
def verify_proxy_request(params):
    # App Proxy always includes ?shop=...; keep simple during dev
    return 'shop' in params


# ========================= WIDGET: /apps/wishlist/wishlist.js =========================
@proxy_bp.route('/proxy/wishlist.js', methods=['GET'])
def wishlist_js():
    """
    JavaScript widget served via Shopify App Proxy.
    Storefront loads:  /apps/wishlist/wishlist.js?shop=xxxx
    Shopify forwards to: <your app url>/apps/wishlist/proxy/wishlist.js?shop=xxxx
    """
    if not verify_proxy_request():
        return "Unauthorized", 401

    shop = _shop_from_request() or ''

    JS = r"""
(function () {
  // --- Config (read any pre-set global, then publish) -----------------
  var PRE = (window.WISHLIST_CONFIG || {});
  var CANDIDATE_ID =
      PRE.customerId
   || (typeof window.__CUSTOMER_ID__ !== "undefined" ? window.__CUSTOMER_ID__ : null)
   || ((window.Shopify && window.Shopify.customer) ? window.Shopify.customer.id : null);

  var WISHLIST_CONFIG = {
    shop: PRE.shop || "__SHOP__",
    apiEndpoint: PRE.apiEndpoint || "/apps/wishlist",  // storefront base
    customerId: CANDIDATE_ID,
    isLoggedIn: !!CANDIDATE_ID
  };
  window.WISHLIST_CONFIG = WISHLIST_CONFIG; // make global for theme overrides
  console.log("[wishlist] boot config:", WISHLIST_CONFIG);

  // Initialize after DOM ready to allow theme override to run too
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initWishlist);
  } else {
    setTimeout(initWishlist, 0);
  }

  function initWishlist() {
    // Re-sync from Shopify globals if available
    if (window.Shopify && window.Shopify.customer) {
      WISHLIST_CONFIG.customerId = window.Shopify.customer.id;
      WISHLIST_CONFIG.isLoggedIn = true;
    }
    // Guard
    if (!WISHLIST_CONFIG.shop) {
      console.warn("[wishlist] missing shop");
    }

    addWishlistButtons();
    updateWishlistCount();
  }

  // ---------- Button injection (PDP forms) ----------
  function addWishlistButtons() {
    var productForms = document.querySelectorAll('form[action*="/cart/add"]');
    productForms.forEach(function (form) {
      if (form.querySelector(".wishlist-btn")) return; // avoid duplicates
      var variantId = getVariantId(form);
      if (!variantId) return;
      var btn = createWishlistButton(variantId);
      var addToCartBtn = form.querySelector('button[type="submit"], .btn-cart, .add-to-cart');
      if (addToCartBtn && addToCartBtn.parentNode) {
        addToCartBtn.parentNode.insertBefore(btn, addToCartBtn.nextSibling);
      } else {
        form.appendChild(btn);
      }
      // Pre-check
      checkWishlistStatus(variantId, btn);
    });
  }

  function getVariantId(el) {
    var idInput = el.querySelector('input[name="id"]');
    return idInput && idInput.value ? idInput.value : null; // PDP: this is VARIANT id
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
      customer_id: String(WISHLIST_CONFIG.customerId),   // << REQUIRED
      shop_domain: WISHLIST_CONFIG.shop,
      variant_id: String(variantId)
    };

    button.disabled = true;
    button.textContent = isIn ? "Removing..." : "Adding...";

    fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
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

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.success) {
          var inList = (data.wishlist || []).some(function (it) {
            // accept either field coming back
            return String(it.variant_id || it.product_id) === String(variantId);
          });
          updateButtonState(button, inList);
        }
      })
      .catch(function (e) {
        console.warn("check status failed:", e);
      });
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

    fetch(url)
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

  // Expose a tiny API
  window.WishlistWidget = window.WishlistWidget || {};
  window.WishlistWidget.updateCount = updateWishlistCount;
  window.WishlistWidget.refreshButtons = addWishlistButtons;
})();
"""
    js_code = JS.replace("__SHOP__", shop)
    return js_code, 200, {"Content-Type": "application/javascript"}


# ========================= API via App Proxy =========================
@proxy_bp.route('/proxy/wishlist', methods=['GET', 'POST', 'DELETE'])
def proxy_wishlist():
    """
    Storefront calls /apps/wishlist/wishlist (GET/POST/DELETE)
    App proxy forwards to this route.
    """
    if not verify_proxy_request():
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    shop = _shop_from_request()
    if not shop:
        return jsonify({'success': False, 'error': 'Missing shop'}), 400

    # Ensure shop settings exist (token etc.)
    shop_settings = WishlistSettings.query.filter_by(shop_domain=shop).first()
    if not shop_settings:
        return jsonify({'success': False, 'error': 'Shop not configured'}), 400

    try:
        if request.method == 'GET':
            return get_wishlist_proxy(shop)
        elif request.method == 'POST':
            return add_to_wishlist_proxy(shop)
        elif request.method == 'DELETE':
            return remove_from_wishlist_proxy(shop)
    except Exception as e:
        return jsonify({'success': False, 'error': f'unhandled: {str(e)}'}), 500


def get_wishlist_proxy(shop):
    customer_id = request.args.get('customer_id')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400

    try:
        items = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        ).all()
        return jsonify({'success': True, 'wishlist': [i.to_dict() for i in items]})
    except Exception as e:
        return jsonify({'success': False, 'error': f'get_failed: {str(e)}'}), 500


def add_to_wishlist_proxy(shop):
    data = request.get_json(silent=True) or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    if not customer_id or not (product_id or variant_id):
        return jsonify({'success': False, 'error': 'customer_id and product_id or variant_id are required'}), 400

    try:
        # Prevent duplicates (match by whichever identifiers were provided)
        q = Wishlist.query.filter_by(customer_id=str(customer_id), shop_domain=shop)
        if product_id:
            q = q.filter_by(product_id=str(product_id))
        if variant_id:
            q = q.filter_by(variant_id=str(variant_id))
        existing = q.first()
        if existing:
            return jsonify({'success': False, 'error': 'Item already in wishlist'}), 409

        item = Wishlist(
            customer_id=str(customer_id),
            shop_domain=shop,
            product_id=str(product_id) if product_id else None,
            variant_id=str(variant_id) if variant_id else None
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Item added to wishlist'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'add_failed: {str(e)}'}), 500


def remove_from_wishlist_proxy(shop):
    data = request.get_json(silent=True) or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    if not customer_id or not (product_id or variant_id):
        return jsonify({'success': False, 'error': 'customer_id and product_id or variant_id are required'}), 400

    try:
        q = Wishlist.query.filter_by(customer_id=str(customer_id), shop_domain=shop)
        if product_id:
            q = q.filter_by(product_id=str(product_id))
        if variant_id:
            q = q.filter_by(variant_id=str(variant_id))
        item = q.first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found'}), 404

        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Item removed from wishlist'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'remove_failed: {str(e)}'}), 500


@proxy_bp.route('/proxy/wishlist/count', methods=['GET'])
def proxy_wishlist_count():
    if not verify_proxy_request():
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    shop = _shop_from_request()
    customer_id = request.args.get('customer_id')
    if not shop or not customer_id:
        return jsonify({'success': False, 'error': 'shop and customer_id are required'}), 400

    try:
        count = Wishlist.query.filter_by(
            customer_id=str(customer_id),
            shop_domain=shop
        ).count()
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'error': f'count_failed: {str(e)}'}), 500


@proxy_bp.route('/proxy', methods=['GET'])
def shopify_proxy_root():
    return jsonify({"success": True, "wishlist": []})
