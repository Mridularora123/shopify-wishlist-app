# src/routes/proxy.py
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import HTTPException
from src.models.wishlist import db, Wishlist, WishlistSettings
from src.utils.shopify_api import ShopifyAPI

proxy_bp = Blueprint('proxy', __name__)

# ─────────────────────────────
# Global JSON error handling (for this blueprint)
# ─────────────────────────────

@proxy_bp.app_errorhandler(Exception)
def _proxy_json_errors(e):
    """Ensure ALL errors from this blueprint are JSON (no HTML pages)."""
    try:
        if isinstance(e, HTTPException):
            return jsonify({'success': False, 'error': e.description}), e.code
        current_app.logger.exception("Unhandled proxy error:", exc_info=e)
        return jsonify({'success': False, 'error': 'server_error', 'detail': str(e)}), 500
    except Exception:
        # Absolute last resort
        return jsonify({'success': False, 'error': 'server_error'}), 500

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

def verify_proxy_request():
    # Keep permissive during integration; tighten with HMAC later.
    return True

def _get_shop_settings(shop):
    if not shop:
        return None
    return WishlistSettings.query.filter_by(shop_domain=shop).first()

def _resolve_product_id(shop, variant_id):
    """
    Try to resolve product_id from variant_id using ShopifyAPI.
    If not possible, return None (and we’ll still proceed).
    """
    if not (shop and variant_id):
        return None
    settings = _get_shop_settings(shop)
    if not settings or not getattr(settings, "access_token", None):
        return None
    try:
        api = ShopifyAPI(shop, settings.access_token)
        # Prefer a dedicated method if your wrapper has it:
        if hasattr(api, "get_variant"):
            v = api.get_variant(str(variant_id))
        else:
            # Generic fallback; adjust to your wrapper’s style if needed
            v = api.get(f"variants/{variant_id}")
        if not v:
            return None
        variant_obj = v.get("variant", v)
        pid = variant_obj.get("product_id")
        return str(pid) if pid else None
    except Exception:
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
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    shop = _shop_from_request()
    if not shop:
        return jsonify({'success': False, 'error': 'missing shop'}), 400

    if request.method == 'GET':
        return _get_wishlist(shop)
    elif request.method == 'POST':
        return _add_to_wishlist(shop)
    elif request.method == 'DELETE':
        return _remove_from_wishlist(shop)

    return jsonify({'success': False, 'error': 'unsupported method'}), 405


@proxy_bp.route('/proxy/wishlist/count', methods=['GET'])
def proxy_wishlist_count():
    if not verify_proxy_request():
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    shop = _shop_from_request()
    customer_id = request.args.get('customer_id') or _json_body().get('customer_id')
    if not shop or not customer_id:
        return jsonify({'success': False, 'error': 'shop and customer_id are required'}), 400

    count = Wishlist.query.filter_by(
        customer_id=str(customer_id),
        shop_domain=shop
    ).count()

    return jsonify({'success': True, 'count': count})


@proxy_bp.route('/proxy', methods=['GET'])
def shopify_proxy_root():
    return jsonify({"success": True, "wishlist": []})

# ─────────────────────────────
# Internal handlers
# ─────────────────────────────

def _get_wishlist(shop):
    customer_id = request.args.get('customer_id') or _json_body().get('customer_id')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400

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

def _add_to_wishlist(shop):
    data = _json_body() or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    if not customer_id or not (product_id or variant_id):
        return jsonify({'success': False, 'error': 'customer_id and product_id or variant_id are required'}), 400

    # If only variant_id came in, try to resolve product_id
    if not product_id and variant_id:
        resolved = _resolve_product_id(shop, variant_id)
        if resolved:
            product_id = resolved

    try:
        # Prevent duplicates (match on actual stored values, including NULLs)
        q = Wishlist.query.filter_by(customer_id=str(customer_id), shop_domain=shop)
        q = q.filter_by(product_id=str(product_id)) if product_id else q.filter_by(product_id=None)
        q = q.filter_by(variant_id=str(variant_id)) if variant_id else q.filter_by(variant_id=None)
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
        return jsonify({'success': True, 'message': 'Item added to wishlist', 'item': item.to_dict()})

    except IntegrityError as ie:
        db.session.rollback()
        return jsonify({'success': False, 'error': 'db_integrity_failed', 'detail': str(ie)}), 500
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'add_failed: {str(e)}'}), 500

def _remove_from_wishlist(shop):
    data = _json_body() or request.form or {}
    customer_id = data.get('customer_id')
    product_id  = data.get('product_id')
    variant_id  = data.get('variant_id')

    if not customer_id or not (product_id or variant_id):
        return jsonify({'success': False, 'error': 'customer_id and product_id or variant_id are required'}), 400

    try:
        q = Wishlist.query.filter_by(customer_id=str(customer_id), shop_domain=shop)
        q = q.filter_by(product_id=str(product_id)) if product_id else q.filter_by(product_id=None)
        q = q.filter_by(variant_id=str(variant_id)) if variant_id else q.filter_by(variant_id=None)

        item = q.first()
        if not item:
            return jsonify({'success': False, 'error': 'Item not found'}), 404

        db.session.delete(item)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Item removed from wishlist'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': f'remove_failed: {str(e)}'}), 500
